// Same-tab search state machine. Drives the site's own search UI (input fill
// via native setter + InputEvent, Enter to submit) and waits for observed
// results — never a fixed sleep, never a location.href navigation (that would
// reload the player). One search in flight; a newer query supersedes the old.
//
// All selectors come from selectors.ts and are UNVERIFIED until Phase 0.
import { SEARCH } from "./selectors";
import { cleanId, cleanText, isFiniteSeconds } from "../shared/sanitize";
import type {
  SearchResultRow,
  SearchSongsResult,
} from "../protocol/types";

export const SEARCH_RESULT_CAP = 30;

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
}

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
  return out;
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

  constructor(doc: Document = document) {
    this.doc = doc;
  }

  get currentEpoch(): number {
    return this.epoch;
  }

  cancelCurrent(reason = "superseded by a newer query"): void {
    this.teardownCurrent?.();
    this.teardownCurrent = null;
    this.entries.clear();
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
    const rows = queryAll(this.doc, SEARCH.resultRow);
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
        artworkId: resolved.artworkId,
      });
    }
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

    return {
      element: el,
      title,
      artists,
      durationSeconds,
      kind,
      artworkId,
      supported: kind === "song" && playable,
    };
  }

  // Re-resolve a previously returned result by verified identity (never by a
  // stale row index), then activate its play control.
  playResult(
    searchToken: string,
    resultId: string,
  ): { ok: true } | { ok: false; error: string } {
    const identity = this.entries.get(resultId);
    if (!identity || !resultId.startsWith(`${searchToken}/`)) {
      return { ok: false, error: "stale_result" };
    }
    const rows = queryAll(this.doc, SEARCH.resultRow);
    for (const el of rows) {
      const resolved = this.resolveRow(el);
      if (
        resolved &&
        resolved.title === identity.title &&
        resolved.kind === identity.kind &&
        (identity.artists.length === 0 ||
          resolved.artists.join(" ") === identity.artists.join(" "))
      ) {
        const play = queryFirst(el, SEARCH.rowPlayButton);
        if (play instanceof HTMLElement || play instanceof SVGElement) {
          (play as HTMLElement).click();
          return { ok: true };
        }
        return { ok: false, error: "result has no playable control" };
      }
    }
    return { ok: false, error: "stale_result" };
  }
}
