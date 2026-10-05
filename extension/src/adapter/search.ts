// Same-tab search state machine. Drives the site's own search UI (input fill
// via native setter + InputEvent, Enter to submit) and waits for observed
// results — never a fixed sleep, never a location.href navigation (that would
// reload the player). One search in flight; a newer query supersedes the old.
//
// All selectors come from selectors.ts and are UNVERIFIED until Phase 0.
import { PLAYER_PAGE, RADIO, SEARCH } from "./selectors";
import { isEnabledControl, isVisibleControl } from "./dom";
import { cleanId, cleanText, isFiniteSeconds } from "../shared/sanitize";
import type {
  SearchResultRow,
  SearchSongsResult,
} from "../protocol/types";

export const SEARCH_RESULT_CAP = 30;
// How often to re-check the results while the player page closes. The change
// arrives through CSS on a layout attribute, so there is no single mutation
// to wait for.
const REVEAL_POLL_MS = 50;

export type SearchOutcome =
  | { ok: true; result: SearchSongsResult }
  | { ok: false; error: { code: "stale_result" | "timeout" | "internal_error"; message: string } };

interface ResolvedRow {
  element: Element;
  title: string;
  artists: string[];
  durationSeconds: number | null;
  kind: SearchResultRow["kind"];
  artworkId: string | null;
  supported: boolean;
  radioSupported: boolean;
}

type RowResolution = { ok: true; row: Element } | { ok: false; error: string };
type RadioFailure = {
  ok: false;
  error: string;
  code: "stale_result" | "unsupported_operation" | "timeout" | "user_interaction_required";
};
type RadioPreparation =
  | { ok: true; playlistId: string; activate: () => RowResolution }
  | RadioFailure;

interface EntryIdentity {
  title: string;
  artists: string[];
  kind: SearchResultRow["kind"];
}

export class SearchTimeoutError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SearchTimeoutError";
  }
}

export class SearchStaleError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SearchStaleError";
  }
}

function queryAll(doc: ParentNode, selectors: string[]): Element[] {
  const out: Element[] = [];
  for (const sel of selectors) {
    try {
      out.push(...doc.querySelectorAll(sel));
    } catch {
      // Skip malformed candidate selectors rather than failing the query.
    }
  }
  return [...new Set(out)];
}

function queryFirst(doc: ParentNode, selectors: string[]): Element | null {
  for (const sel of selectors) {
    try {
      const el = doc.querySelector(sel);
      if (el) return el;
    } catch {
      // keep looking
    }
  }
  return null;
}

// Framework-controlled inputs (Polymer/React-style) ignore programmatic
// .value sets unless the change goes through the native setter + a real
// InputEvent. This is the single most likely Phase 0 failure mode.
export function fillControlledInput(input: HTMLInputElement, value: string): void {
  const proto = Object.getPrototypeOf(input) as object;
  const descriptor =
    Object.getOwnPropertyDescriptor(proto, "value") ??
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
  if (descriptor?.set) {
    descriptor.set.call(input, value);
  } else {
    input.value = value;
  }
  input.dispatchEvent(
    new InputEvent("input", {
      bubbles: true,
      cancelable: true,
      inputType: "insertText",
      data: value,
    }),
  );
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

export function submitEnter(input: HTMLElement): void {
  for (const type of ["keydown", "keypress", "keyup"] as const) {
    input.dispatchEvent(
      new KeyboardEvent(type, {
        key: "Enter",
        code: "Enter",
        keyCode: 13,
        which: 13,
        bubbles: true,
        cancelable: true,
      }),
    );
  }
}

function parseDuration(text: string): number | null {
  const m = /(\d+):(\d{2})(?::(\d{2}))?/.exec(text);
  if (!m) return null;
  const h = m[3] ? Number(m[1]) : 0;
  const min = m[3] ? Number(m[2]) : Number(m[1]);
  const sec = m[3] ? Number(m[3]) : Number(m[2]);
  const v = h * 3600 + min * 60 + sec;
  return isFiniteSeconds(v);
}

export class SiteSearch {
  private readonly doc: Document;
  private epoch = 0;
  private teardownCurrent: (() => void) | null = null;
  private entries = new Map<string, EntryIdentity>();
  private radioAvailable = false;
  private cancelRadio: (() => void) | null = null;

  constructor(doc: Document = document) {
    this.doc = doc;
  }

  get currentEpoch(): number {
    return this.epoch;
  }

  get canStartRadio(): boolean {
    return this.radioAvailable;
  }

  cancelCurrent(reason = "superseded by a newer query"): void {
    this.teardownCurrent?.();
    this.teardownCurrent = null;
    this.entries.clear();
    this.radioAvailable = false;
    this.cancelRadio?.();
    this.cancelRadio = null;
    void reason;
  }

  search(query: string, deadlineMs: number): {
    token: string;
    promise: Promise<SearchSongsResult>;
  } {
    this.cancelCurrent();
    const epoch = ++this.epoch;
    const token = `s${epoch.toString(36)}-${Math.random().toString(36).slice(2, 10)}`;

    const promise = new Promise<SearchSongsResult>((resolve, reject) => {
      const input = queryFirst(this.doc, SEARCH.input);
      if (!(input instanceof HTMLInputElement)) {
        reject(
          new SearchTimeoutError("search input not found (selector set unverified)"),
        );
        return;
      }

      let settled = false;
      const fail = (err: Error) => {
        if (settled) return;
        settled = true;
        observer.disconnect();
        clearTimeout(timer);
        reject(err);
      };
      const succeed = () => {
        if (settled) return;
        settled = true;
        observer.disconnect();
        clearTimeout(timer);
        resolve(this.scan(epoch, token));
      };

      const timer = setTimeout(() => {
        fail(new SearchTimeoutError("results did not appear before the deadline"));
      }, deadlineMs);

      // Guard: only accept results that arrive via a DOM change AFTER submit,
      // so a previous query's leftovers are never reported as fresh.
      let sawMutation = false;
      const observer = new MutationObserver((mutations) => {
        if (epoch !== this.epoch) {
          fail(new SearchStaleError("search superseded"));
          return;
        }
        for (const m of mutations) {
          if (m.addedNodes.length > 0 || m.type === "characterData") {
            sawMutation = true;
          }
        }
        if (sawMutation) succeed();
      });

      const observeRoots = (): boolean => {
        const root =
          queryFirst(this.doc, SEARCH.resultsRoot) ?? this.doc.body;
        if (!root) return false;
        observer.observe(root, {
          childList: true,
          subtree: true,
          characterData: true,
        });
        return true;
      };

      fillControlledInput(input, query);
      submitEnter(input);
      if (!observeRoots()) {
        fail(new SearchTimeoutError("no observable results root found"));
        return;
      }
      // The input itself re-rendering (suggest dropdown) counts as motion;
      // scan immediately too in case results were already synchronous.
      queueMicrotask(() => {
        if (!settled && sawMutation) succeed();
      });

      this.teardownCurrent = () => {
        if (!settled) {
          settled = true;
          observer.disconnect();
          clearTimeout(timer);
          reject(new SearchStaleError("search superseded"));
        }
      };
    });

    return { token, promise };
  }

  private scan(epoch: number, token: string): SearchSongsResult {
    if (epoch !== this.epoch) {
      throw new SearchStaleError("search superseded before scan");
    }
    const rows = this.resultRows();
    this.entries.clear();
    const results: SearchResultRow[] = [];
    for (const [i, el] of rows.entries()) {
      if (results.length >= SEARCH_RESULT_CAP) break;
      const resolved = this.resolveRow(el);
      if (!resolved) continue;
      const resultId = `${token}/${i.toString(36)}`;
      this.entries.set(resultId, {
        title: resolved.title,
        artists: resolved.artists,
        kind: resolved.kind,
      });
      results.push({
        resultId,
        kind: resolved.kind,
        title: resolved.title,
        artists: resolved.artists,
        album: null,
        durationSeconds: resolved.durationSeconds,
        supported: resolved.supported,
        radioSupported: resolved.radioSupported,
        artworkId: resolved.artworkId,
      });
    }
    this.radioAvailable = results.some((row) => row.radioSupported);
    // complete=false while the page may be virtualized or paginated — we only
    // claim completeness when the row count is comfortably under the cap.
    return {
      searchToken: token,
      complete: rows.length < SEARCH_RESULT_CAP,
      results,
    };
  }

  private resolveRow(el: Element): ResolvedRow | null {
    const titleEl = queryFirst(el, SEARCH.rowTitle);
    const title = cleanText(titleEl?.textContent);
    if (!title) return null;

    const subEl = queryFirst(el, SEARCH.rowSubtitle);
    const subText = cleanText(subEl?.textContent);
    const artists = subText
      .split(/[•·-]/)
      .map((s) => cleanText(s))
      .filter(Boolean)
      .slice(0, 4);

    const durationSeconds = parseDuration(subText || el.textContent || "");
    const playable = queryFirst(el, SEARCH.rowPlayButton) !== null;
    const kind: SearchResultRow["kind"] =
      durationSeconds !== null || playable ? "song" : "other";
    const thumb = queryFirst(el, SEARCH.rowThumbnail);
    const artworkId =
      thumb instanceof HTMLImageElement && thumb.src
        ? cleanId(thumb.src.slice(-64))
        : null;
    const menu = queryFirst(el, SEARCH.rowActionMenu);

    return {
      element: el,
      title,
      artists,
      durationSeconds,
      kind,
      artworkId,
      supported: kind === "song" && playable,
      radioSupported: kind === "song" && menu instanceof HTMLElement && isEnabledControl(menu),
    };
  }

  private resultRows(): Element[] {
    const root = queryFirst(this.doc, SEARCH.resultsRoot);
    return root ? queryAll(root, SEARCH.resultRow) : [];
  }

  // Re-resolve a previously returned result by verified identity (never by a
  // stale row index), then activate its play control.
  playResult(
    searchToken: string,
    resultId: string,
  ): { ok: true } | { ok: false; error: string } {
    const resolved = this.resolveResult(searchToken, resultId);
    if (!resolved.ok) return resolved;

    const play = queryFirst(resolved.row, SEARCH.rowPlayButton);
    if (play instanceof HTMLElement || play instanceof SVGElement) {
      (play as HTMLElement).click();
      return { ok: true };
    }
    return { ok: false, error: "result has no playable control" };
  }

  private resolveResult(searchToken: string, resultId: string): RowResolution {
    const identity = this.entries.get(resultId);
    if (!identity || !resultId.startsWith(`${searchToken}/`)) {
      return { ok: false, error: "stale_result" };
    }
    const rows = this.resultRows();
    const matches: Element[] = [];
    for (const el of rows) {
      const resolved = this.resolveRow(el);
      if (
        resolved &&
        resolved.title === identity.title &&
        resolved.kind === identity.kind &&
        (identity.artists.length === 0 ||
          resolved.artists.join(" ") === identity.artists.join(" "))
      ) {
        matches.push(el);
      }
    }
    if (matches.length !== 1) return { ok: false, error: "Result is missing or ambiguous; search again" };

    return { ok: true, row: matches[0]! };
  }

  async prepareRadio(searchToken: string, resultId: string, deadlineMs: number): Promise<RadioPreparation> {
    const startedAt = Date.now();
    const resolved = this.resolveResult(searchToken, resultId);
    if (!resolved.ok) return { ...resolved, code: "stale_result" };

    const revealed = await this.revealResults(resolved.row, deadlineMs);
    if (!revealed.ok) return revealed;
    const current = this.resolveResult(searchToken, resultId);
    if (!current.ok || current.row !== resolved.row) {
      return { ok: false, code: "stale_result", error: "Search result changed while closing the player page" };
    }
    const remainingMs = Math.max(0, deadlineMs - (Date.now() - startedAt));

    const menu = queryFirst(resolved.row, SEARCH.rowActionMenu);
    if (!menu || !isVisibleControl(menu) || !isEnabledControl(menu)) {
      return { ok: false, code: "unsupported_operation", error: "No available action menu for this result" };
    }
    if ([...this.doc.querySelectorAll(RADIO.popup)].some(isVisibleControl)) {
      return { ok: false, code: "user_interaction_required", error: "Close the open YouTube Music menu, then try Start mix again" };
    }

    return new Promise((resolve) => {
      const freshPopups = new Set<Element>();
      let settled = false;
      let sawFreshMenu = false;
      const finish = (result: RadioPreparation) => {
        if (settled) return;
        settled = true;
        observer.disconnect();
        clearTimeout(timer);
        this.cancelRadio = null;
        resolve(result);
      };
      const check = (mutations: MutationRecord[]) => {
        const current = this.resolveResult(searchToken, resultId);
        if (!current.ok || current.row !== resolved.row) {
          finish({ ok: false, code: "stale_result", error: "Search result changed while opening its menu" });
          return;
        }
        const popups = [...this.doc.querySelectorAll(RADIO.popup)];
        for (const popup of popups) {
          const refreshed = mutations.some((mutation) =>
            (mutation.type === "childList" &&
              (popup.contains(mutation.target) || [...mutation.addedNodes].some((node) => node.contains(popup)))) ||
            (mutation.type === "characterData" && popup.contains(mutation.target)) ||
            (mutation.type === "attributes" && popup.contains(mutation.target) &&
              (mutation.attributeName === "href" || mutation.attributeName === "aria-label")));
          if (refreshed) freshPopups.add(popup);
        }
        const visible = popups.filter(isVisibleControl);
        if (visible.length !== 1 || !freshPopups.has(visible[0]!)) return;

        const popup = visible[0]!;
        sawFreshMenu = true;
        const items = [...popup.querySelectorAll(RADIO.items)];
        if (items.length === 0) return;

        const mixItems = items.filter((item) => item.getAttribute("aria-label") === RADIO.label);
        const mix = mixItems.length === 1 ? mixItems[0] : null;
        const link = mix?.querySelector(RADIO.endpoint);
        if (!mix || !isVisibleControl(mix) || !isEnabledControl(mix) || !(link instanceof HTMLAnchorElement)) {
          // Items, endpoint attributes and enabled state can arrive separately.
          return;
        }
        const target = new URL(link.href, this.doc.baseURI);
        const playlistId = target.searchParams.get(RADIO.playlistParam);
        if (target.origin !== this.doc.location.origin || target.pathname !== RADIO.watchPath || !playlistId) {
          finish({ ok: false, code: "unsupported_operation", error: "Start mix has no recognized playlist link" });
          return;
        }
        finish({
          ok: true, playlistId,
          activate: () => {
            const row = this.resolveResult(searchToken, resultId);
            if (!row.ok || row.row !== resolved.row || !isVisibleControl(popup) ||
                !isVisibleControl(mix) || !isEnabledControl(mix) || link.href !== target.href) {
              return { ok: false, error: "Mix menu or result changed before activation; search again" };
            }
            // Activate the site's menu item, never assign location or click Play.
            link.click();
            return row;
          },
        });
      };
      const observer = new MutationObserver(check);
      const timer = setTimeout(() => finish({
        ok: false, code: sawFreshMenu ? "unsupported_operation" : "timeout",
        error: sawFreshMenu ? "Start mix was unavailable before the deadline"
          : "The result menu did not expose a fresh mix action before the deadline",
      }), remainingMs);
      this.cancelRadio = () => finish({ ok: false, code: "stale_result", error: "Search superseded while opening the mix menu" });
      observer.observe(this.doc.body, {
        childList: true, subtree: true, characterData: true, attributes: true,
        attributeFilter: ["href", "aria-label", "style", "class", "hidden", "aria-hidden", "aria-disabled"],
      });
      menu.click();
      check(observer.takeRecords());
    });
  }

  // Playing a result opens the player page, which hides the search page and
  // every row menu without removing them. Close it with the player bar's own
  // toggle, then wait until the row's menu is visible: an observed outcome,
  // never an assumed one. The open state comes from a layout attribute, so
  // this does not depend on the interface language.
  private async revealResults(row: Element, deadlineMs: number): Promise<{ ok: true } | RadioFailure> {
    const menuVisible = (): boolean => {
      const menu = queryFirst(row, SEARCH.rowActionMenu);
      return menu !== null && isVisibleControl(menu);
    };
    if (menuVisible()) return { ok: true };

    const layout = this.doc.querySelector(PLAYER_PAGE.layout);
    // Not hidden by the player page; the menu check reports what is missing.
    if (!layout?.hasAttribute(PLAYER_PAGE.openAttribute)) return { ok: true };

    const toggle = this.doc.querySelector(PLAYER_PAGE.closeToggle);
    if (!toggle || !isVisibleControl(toggle) || !isEnabledControl(toggle)) {
      return {
        ok: false, code: "user_interaction_required",
        error: "Close the YouTube Music player page, then try Start mix again",
      };
    }
    toggle.click();

    const shown = await this.waitUntil(
      () => !layout.hasAttribute(PLAYER_PAGE.openAttribute) && menuVisible(), deadlineMs,
    );
    if (shown === "cancelled") {
      return { ok: false, code: "stale_result", error: "Search superseded while closing the player page" };
    }
    if (!shown) {
      return {
        ok: false, code: "timeout",
        error: "The player page did not close in time; close it, then try Start mix again",
      };
    }
    return { ok: true };
  }

  private waitUntil(condition: () => boolean, deadlineMs: number): Promise<boolean | "cancelled"> {
    return new Promise((resolve) => {
      let settled = false;
      const finish = (outcome: boolean | "cancelled"): void => {
        if (settled) return;
        settled = true;
        clearInterval(poll);
        clearTimeout(timer);
        this.cancelRadio = null;
        resolve(outcome);
      };
      const poll = setInterval(() => {
        if (condition()) finish(true);
      }, REVEAL_POLL_MS);
      const timer = setTimeout(() => finish(condition()), deadlineMs);
      this.cancelRadio = () => finish("cancelled");
    });
  }
}
