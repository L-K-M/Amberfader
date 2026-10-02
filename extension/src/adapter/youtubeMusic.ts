// YouTube Music site adapter. DOM + standard media-element operations only;
// selectors come from selectors.ts (UNVERIFIED until Phase 0) and every
// capability is feature-detected rather than assumed.
//
// Explicit play/pause operations (never toggle-retry). Every command resolves
// only after the requested change is observed in emitted state; a dispatch
// without observation yields pending_outcome, and a timed-out dispatch is
// never retried automatically — a timeout does not prove inaction.
import {
  CONTROLS,
  LIKE_BUTTON_SELECTOR,
  MEDIA_ELEMENT_SELECTOR,
  PLAYER_BAR_SELECTOR,
  PLAYER_ROOT_SELECTORS,
  RADIO,
  TRACK_INFO,
} from "./selectors";
import { cleanId, cleanText, isFiniteSeconds } from "../shared/sanitize";
import type {
  AdapterPlayerState,
  CommandResult,
  SiteAdapter,
} from "./types";
import type {
  Capability,
  Method,
  PlaybackStatus,
  TrackInfo,
} from "../protocol/types";
import { SiteSearch } from "./search";
import { isEnabledControl, isVisibleControl } from "./dom";

const POSITION_SAMPLE_MS = 1000;
const CONTROL_DEADLINE_MS = 5000;
const SEARCH_DEADLINE_MS = 15000;
const MAX_SEARCH_LEN = 500;

type StateListener = (state: AdapterPlayerState) => void;
type NoticeListener = (notice: {
  component: "adapter";
  status: "connected" | "disconnected" | "degraded";
  reason?: string;
}) => void;

interface SerialJob {
  method: Method;
  run: () => Promise<CommandResult>;
  resolve: (r: CommandResult) => void;
}

function findControl(name: keyof typeof CONTROLS): HTMLElement | null {
  const q = CONTROLS[name];
  if (!q) return null;
  for (const sel of q.selectors) {
    try {
      const el = document.querySelector(sel);
      if (el instanceof HTMLElement && !el.hidden) return el;
    } catch {
      // skip malformed selector candidates
    }
  }
  // Accessible-label fallback (feature-detected, EN patterns so far).
  const candidates = document.querySelectorAll(
    "ytmusic-player-bar button, ytmusic-player-bar tp-yt-paper-icon-button, ytmusic-player-bar [role='button']",
  );
  for (const el of candidates) {
    if (!(el instanceof HTMLElement)) continue;
    const label = el.getAttribute("aria-label") ?? el.getAttribute("title") ?? "";
    if (q.ariaLabels.some((re) => re.test(label))) return el;
  }
  return null;
}

function mediaElement(): HTMLMediaElement | null {
  const el = document.querySelector(MEDIA_ELEMENT_SELECTOR);
  return el instanceof HTMLMediaElement ? el : null;
}

function playerRoot(): Element | null {
  for (const sel of PLAYER_ROOT_SELECTORS) {
    try {
      const el = document.querySelector(sel);
      if (el) return el;
    } catch {
      // continue
    }
  }
  return null;
}

function videoIdFromLocation(): string | null {
  try {
    return cleanId(new URLSearchParams(location.search).get("v")) || null;
  } catch {
    return null;
  }
}

function likeControl(): { button: HTMLElement; liked: boolean } | null {
  const buttons = [...document.querySelectorAll(LIKE_BUTTON_SELECTOR)].filter(isVisibleControl);
  if (buttons.length === 0) return null;

  const pressed = buttons[0]!.getAttribute("aria-pressed");
  if (pressed !== "true" && pressed !== "false") return null;
  // Conflicting visible controls are ambiguous; never guess which song wins.
  if (buttons.some((button) => button.getAttribute("aria-pressed") !== pressed)) return null;

  return { button: buttons[0]!, liked: pressed === "true" };
}

export class YouTubeMusicAdapter implements SiteAdapter {
  capabilities: Capability[] = [];
  proposedArtworkUrl: string | null = null;

  private readonly listeners = new Set<StateListener>();
  private readonly noticeListeners = new Set<NoticeListener>();
  private readonly search = new SiteSearch(document);

  private revision = 0;
  private lastState: AdapterPlayerState | null = null;
  private occurrenceCounter = 0;
  private trackKey = "";
  private queue: SerialJob[] = [];
  private queueRunning = false;

  private media: HTMLMediaElement | null = null;
  private mediaListenersBound = false;
  private positionTimer: number | null = null;
  private reconcileTimer: number | null = null;
  private observer: MutationObserver | null = null;
  private running = false;

  onState(cb: StateListener): void {
    this.listeners.add(cb);
  }

  onNotice(cb: NoticeListener): void {
    this.noticeListeners.add(cb);
  }

  snapshot(): AdapterPlayerState {
    return this.lastState ?? this.buildState();
  }

  start(): Promise<void> {
    if (this.running) return Promise.resolve();
    this.running = true;
    this.bindMedia();
    this.observePlayer();
    this.startReconcile();
    this.emit();
    this.notice({ component: "adapter", status: "connected" });
    return Promise.resolve();
  }

  stop(): void {
    this.running = false;
    this.observer?.disconnect();
    this.observer = null;
    this.unbindMedia();
    if (this.positionTimer !== null) window.clearInterval(this.positionTimer);
    if (this.reconcileTimer !== null) window.clearInterval(this.reconcileTimer);
    this.positionTimer = this.reconcileTimer = null;
    this.search.cancelCurrent("adapter stopped");
    this.notice({
      component: "adapter",
      status: "disconnected",
      reason: "adapter stopped",
    });
  }

  // ---------- observation ----------

  private bindMedia(): void {
    const el = mediaElement();
    if (el === this.media && this.mediaListenersBound) return;
    this.unbindMedia();
    this.media = el;
    if (!el) return;
    for (const ev of [
      "play",
      "pause",
      "playing",
      "waiting",
      "ended",
      "seeked",
      "durationchange",
      "ratechange",
      "volumechange",
      "emptied",
      "error",
      "loadedmetadata",
    ] as const) {
      el.addEventListener(ev, this.onMediaEvent);
    }
    this.mediaListenersBound = true;
    this.resetPositionTimer();
  }

  private unbindMedia(): void {
    if (!this.media || !this.mediaListenersBound) return;
    for (const ev of [
      "play",
      "pause",
      "playing",
      "waiting",
      "ended",
      "seeked",
      "durationchange",
      "ratechange",
      "volumechange",
      "emptied",
      "error",
      "loadedmetadata",
    ] as const) {
      this.media.removeEventListener(ev, this.onMediaEvent);
    }
    this.mediaListenersBound = false;
  }

  private readonly onMediaEvent = (): void => {
    this.resetPositionTimer();
    this.emit();
  };

  private resetPositionTimer(): void {
    if (this.positionTimer !== null) {
      window.clearInterval(this.positionTimer);
      this.positionTimer = null;
    }
    if (!this.running || !this.media) return;
    if (!this.media.paused && !this.media.ended) {
      // ~1 Hz samples while playing; UI interpolates between them.
      this.positionTimer = window.setInterval(
        () => this.emit(),
        POSITION_SAMPLE_MS,
      );
    }
  }

  private observePlayer(): void {
    const bars = [...document.querySelectorAll(PLAYER_BAR_SELECTOR)];
    const roots = bars.length > 0 ? bars : [playerRoot() ?? document.body];
    this.observer?.disconnect();
    this.observer = new MutationObserver(() => {
      // A replaced media element means our listeners are stale — rebind.
      const el = mediaElement();
      if (el !== this.media) this.bindMedia();
      this.emit();
    });
    for (const root of roots) {
      this.observer.observe(root, {
        childList: true,
        subtree: true,
        characterData: true,
        attributes: true,
        // Animation styles are sampled by reconciliation, not every frame.
        attributeFilter: ["aria-label", "aria-pressed", "aria-disabled", "aria-hidden", "disabled", "hidden", "title", "class", "value"],
      });
    }
  }

  // Slow bounded reconciliation: catches anything observers missed without
  // continuous whole-document scanning.
  private startReconcile(): void {
    if (this.reconcileTimer !== null) return;
    this.reconcileTimer = window.setInterval(() => {
      const el = mediaElement();
      if (el !== this.media) this.bindMedia();
      this.emit();
    }, 5000);
  }

  // ---------- state ----------

  private detectCapabilities(liked: boolean | null): Capability[] {
    const caps: Capability[] = [];
    const media = this.media;
    if (findControl("playPause") || media) {
      caps.push("play", "pause");
    }
    if (findControl("previous")) caps.push("previous");
    if (findControl("next")) caps.push("next");
    if (media && media.seekable.length > 0) caps.push("seek");
    if (media) caps.push("volume");
    const like = liked !== null ? likeControl() : null;
    if (like && isEnabledControl(like.button)) caps.push("setLiked");
    // Search capabilities are advertised once the probe-verified input path
    // exists; the input's mere presence is not proof search works.
    if (document.querySelector("ytmusic-search-box, input[type='search']")) {
      caps.push("searchSongs", "playSearchResult");
    }
    if (this.search.canStartRadio) caps.push("startRadio");
    return caps;
  }

  private readTrack(): TrackInfo | null {
    const media = this.media;
    const titleEl = document.querySelector(TRACK_INFO.title.join(", "));
    const bylineEl = document.querySelector(TRACK_INFO.byline.join(", "));
    const title = cleanText(titleEl?.textContent);
    const byline = cleanText(bylineEl?.textContent);

    const providerId = videoIdFromLocation();
    if (!title && !providerId && (!media || media.readyState === 0)) {
      return null;
    }

    // Split "Artist • Album • views" style byline; album stays best-effort.
    const parts = byline
      .split(/[•·]/)
      .map((s) => cleanText(s))
      .filter(Boolean);
    const artists = parts.length > 0 ? [parts[0]!] : [];
    const album = parts.length > 1 ? parts[1]! : null;

    const key = `${providerId ?? "?"}|${title}|${artists.join(",")}|${Math.round(
      media?.duration ?? 0,
    )}`;
    if (key !== this.trackKey) {
      this.trackKey = key;
      this.occurrenceCounter += 1;
    }
    const occurrenceId = `occ-${this.occurrenceCounter.toString(36)}`;

    const artworkImg = document.querySelector(TRACK_INFO.artwork.join(", "));
    let artworkId: string | null = null;
    this.proposedArtworkUrl = null;
    if (artworkImg instanceof HTMLImageElement && (artworkImg.currentSrc || artworkImg.src)) {
      // Only HTTPS URLs are proposed; the artwork service re-validates
      // protocol + origin before fetching.
      try {
        const u = new URL(artworkImg.currentSrc || artworkImg.src);
        if (u.protocol === "https:") {
          this.proposedArtworkUrl = u.href;
          artworkId = cleanId(u.href.slice(-64)) || null;
        }
      } catch {
        // not a usable URL
      }
    }

    return {
      occurrenceId,
      providerId,
      title: title || "Unknown track",
      artists,
      album,
      artworkId,
    };
  }

  private playbackStatus(): PlaybackStatus {
    const media = this.media;
    if (!media) return "unknown";
    if (media.ended) return "ended";
    if (media.paused) return media.currentTime > 0 ? "paused" : "unknown";
    if (media.readyState < 3) return "buffering";
    return "playing";
  }

  private contentKind(): AdapterPlayerState["contentKind"] {
    // Only classify advertisements with reliable evidence — otherwise honest
    // "unknown". UNVERIFIED marker; Phase 0 determines a real ad indicator.
    const bar = document.querySelector("ytmusic-player-bar");
    if (bar?.getAttribute("ad-slot") || bar?.querySelector(".ad-showing")) {
      return "advertisement";
    }
    return "unknown";
  }

  private buildState(): AdapterPlayerState {
    const media = this.media;
    const track = this.readTrack();
    const status = this.playbackStatus();
    const contentKind = this.contentKind();
    const liked = track && contentKind !== "advertisement" ? likeControl()?.liked ?? null : null;
    const state: AdapterPlayerState = {
      revision: ++this.revision,
      track,
      status,
      contentKind,
      positionSeconds: media ? isFiniteSeconds(media.currentTime) : null,
      durationSeconds: media ? isFiniteSeconds(media.duration) : null,
      playbackRate:
        media && Number.isFinite(media.playbackRate) ? media.playbackRate : null,
      volume: media ? media.volume : null,
      muted: media ? media.muted : null,
      liked,
      capabilities: this.detectCapabilities(liked),
    };
    this.capabilities = state.capabilities;
    this.lastState = state;
    return state;
  }

  private emit(): void {
    if (!this.running) return;
    const state = this.buildState();
    for (const cb of this.listeners) cb(state);
  }

  private notice(n: {
    component: "adapter";
    status: "connected" | "disconnected" | "degraded";
    reason?: string;
  }): void {
    for (const cb of this.noticeListeners) cb(n);
  }

  // ---------- commands (serialized, outcome-confirmed) ----------

  exec(
    requestId: string,
    method: Method,
    params: Record<string, unknown>,
  ): Promise<CommandResult> {
    // Serialize conflicting actions; a superseded slider value is dropped by
    // the caller before it gets here.
    void requestId;
    return new Promise((resolve) => {
      this.queue.push({ method, run: () => this.dispatch(method, params), resolve });
      void this.pump();
    });
  }

  private async pump(): Promise<void> {
    if (this.queueRunning) return;
    this.queueRunning = true;
    try {
      while (this.queue.length > 0) {
        const job = this.queue.shift()!;
        try {
          job.resolve(await job.run());
        } catch (err) {
          job.resolve({
            ok: false,
            error: {
              code: "internal_error",
              message: err instanceof Error ? err.message : "unknown adapter error",
            },
          });
        }
      }
    } finally {
      this.queueRunning = false;
    }
  }

  private async dispatch(
    method: Method,
    params: Record<string, unknown>,
  ): Promise<CommandResult> {
    switch (method) {
      case "player.play":
        return this.transport("play");
      case "player.pause":
        return this.transport("pause");
      case "player.previous":
        return this.clickTransport("previous");
      case "player.next":
        return this.clickTransport("next");
      case "player.seek":
        return this.seek(params);
      case "player.setVolume":
        return this.setVolume(params);
      case "player.setMuted":
        return this.setMuted(params);
      case "player.setLiked":
        return this.setLiked(params);
      case "search.songs":
        return this.searchSongs(params);
      case "search.playResult":
        return this.playSearchResult(params);
      case "search.startRadio":
        return this.startRadio(params);
      default:
        return {
          ok: false,
          error: { code: "unsupported_operation", message: `no adapter path for ${method}` },
        };
    }
  }

  // Resolve when emitted state satisfies `want`, or pending_outcome on
  // deadline. Listening starts BEFORE dispatch so nothing is missed.
  private awaitOutcome(
    want: (s: AdapterPlayerState) => boolean,
    deadlineMs: number,
  ): { done: Promise<CommandResult>; cancel: () => void } {
    let listener: StateListener | null = null;
    let timer: number | null = null;
    let settled = false;
    const done = new Promise<CommandResult>((resolve) => {
      const finish = (r: CommandResult) => {
        if (settled) return;
        settled = true;
        if (listener) this.listeners.delete(listener);
        if (timer !== null) window.clearTimeout(timer);
        resolve(r);
      };
      listener = (s) => {
        if (want(s)) {
          finish({ ok: true, outcome: { observedStateRevision: s.revision } });
        }
      };
      this.listeners.add(listener);
      timer = window.setTimeout(() => {
        finish({
          ok: false,
          error: {
            code: "pending_outcome",
            message:
              "command dispatched but the player did not confirm the outcome before the deadline",
          },
        });
      }, deadlineMs);
      // The wanted state may already hold before dispatch.
      const snap = this.snapshot();
      if (want(snap)) {
        finish({ ok: true, outcome: { observedStateRevision: snap.revision } });
      }
    });
    return {
      done,
      cancel: () => {
        if (listener) this.listeners.delete(listener);
        if (timer !== null) window.clearTimeout(timer);
        settled = true;
      },
    };
  }

  private async transport(kind: "play" | "pause"): Promise<CommandResult> {
    const want = (s: AdapterPlayerState) =>
      kind === "play" ? s.status === "playing" : s.status === "paused" || s.status === "ended";
    const waiter = this.awaitOutcome(want, CONTROL_DEADLINE_MS);

    const button = findControl("playPause");
    const media = this.media;
    let dispatchError: CommandResult | null = null;
    if (button) {
      button.click();
    } else if (media) {
      try {
        if (kind === "play") {
          // A programmatic play() can be rejected by autoplay policy; report
          // user_interaction_required rather than pretending it worked.
          void media.play().catch((err: unknown) => {
            dispatchError = {
              ok: false,
              error: {
                code: "user_interaction_required",
                message: `playback start rejected by the browser (${err instanceof Error ? err.name : "error"}); use "Show YouTube Music" and press play`,
              },
            };
          });
        } else {
          media.pause();
        }
      } catch (err) {
        dispatchError = {
          ok: false,
          error: {
            code: "internal_error",
            message: err instanceof Error ? err.message : "media call failed",
          },
        };
      }
    } else {
      return {
        ok: false,
        error: { code: "unsupported_operation", message: "no play control or media element" },
      };
    }

    const result = await waiter.done;
    return dispatchError ?? result;
  }

  private async clickTransport(
    name: "previous" | "next",
  ): Promise<CommandResult> {
    const media = this.media;
    const beforeTrack = this.snapshot().track?.occurrenceId ?? null;
    const beforePos = media?.currentTime ?? 0;
    // "Once per invocation": fire exactly one control activation and wait for
    // an observed track/position change — no retries that could double-skip.
    const want = (s: AdapterPlayerState) =>
      (beforeTrack !== null && s.track?.occurrenceId !== beforeTrack) ||
      (media ? Math.abs((s.positionSeconds ?? beforePos) - beforePos) > 0.5 : false);
    const waiter = this.awaitOutcome(want, CONTROL_DEADLINE_MS);

    const button = findControl(name);
    if (!button) {
      waiter.cancel();
      return {
        ok: false,
        error: { code: "unsupported_operation", message: `${name} control not found` },
      };
    }
    button.click();
    return waiter.done;
  }

  private async seek(
    params: Record<string, unknown>,
  ): Promise<CommandResult> {
    const media = this.media;
    if (!media) {
      return {
        ok: false,
        error: { code: "unsupported_operation", message: "no media element" },
      };
    }
    const occurrenceId = typeof params.occurrenceId === "string" ? params.occurrenceId : null;
    const requested = typeof params.positionSeconds === "number" ? params.positionSeconds : null;
    if (!occurrenceId || requested === null || !Number.isFinite(requested)) {
      return {
        ok: false,
        error: { code: "internal_error", message: "seek requires occurrenceId and finite positionSeconds" },
      };
    }
    const snap = this.snapshot();
    if (snap.track?.occurrenceId !== occurrenceId) {
      return {
        ok: false,
        error: { code: "stale_target", message: "track changed since the seek was requested" },
      };
    }
    // Clamp to the real seekable interval; when the ranges are empty fall
    // back to the finite media duration.
    let target = requested;
    if (media.seekable.length > 0) {
      const lo = media.seekable.start(0);
      const hi = media.seekable.end(media.seekable.length - 1);
      target = Math.min(Math.max(requested, lo), hi);
    } else if (Number.isFinite(media.duration)) {
      target = Math.min(Math.max(requested, 0), media.duration);
    }
    const waiter = this.awaitOutcome(
      (s) =>
        s.track?.occurrenceId === occurrenceId &&
        s.positionSeconds !== null &&
        Math.abs(s.positionSeconds - target) < 1.5,
      CONTROL_DEADLINE_MS,
    );
    media.currentTime = target;
    return waiter.done;
  }

  private async setVolume(
    params: Record<string, unknown>,
  ): Promise<CommandResult> {
    const media = this.media;
    const v = typeof params.volume === "number" ? params.volume : null;
    if (!media || v === null || !Number.isFinite(v)) {
      return {
        ok: false,
        error: { code: "internal_error", message: "setVolume requires finite volume and a media element" },
      };
    }
    const target = Math.min(Math.max(v, 0), 1);
    const waiter = this.awaitOutcome(
      (s) => s.volume !== null && Math.abs(s.volume - target) < 0.02,
      CONTROL_DEADLINE_MS,
    );
    media.volume = target;
    return waiter.done;
  }

  private async setMuted(
    params: Record<string, unknown>,
  ): Promise<CommandResult> {
    const media = this.media;
    const muted = params.muted === true;
    if (!media) {
      return {
        ok: false,
        error: { code: "unsupported_operation", message: "no media element" },
      };
    }
    const waiter = this.awaitOutcome(
      (s) => s.muted === muted,
      CONTROL_DEADLINE_MS,
    );
    media.muted = muted;
    return waiter.done;
  }

  private async searchSongs(
    params: Record<string, unknown>,
  ): Promise<CommandResult> {
    const query = typeof params.query === "string" ? params.query : "";
    if (!query.trim() || query.length > MAX_SEARCH_LEN) {
      return {
        ok: false,
        error: { code: "internal_error", message: "query must be 1-500 characters" },
      };
    }
    const { token, promise } = this.search.search(query.trim(), SEARCH_DEADLINE_MS);
    try {
      await promise;
      return {
        ok: true,
        outcome: { observedStateRevision: this.snapshot().revision },
        // The caller needs the rows; they are forwarded as the internal
        // searchResult payload by the content-script executor, which reads
        // this via the extended result channel below.
      };
    } catch (err) {
      const stale = err instanceof Error && err.name === "SearchStaleError";
      return {
        ok: false,
        error: {
          code: stale ? "stale_result" : "timeout",
          message: err instanceof Error ? err.message : "search failed",
        },
      };
    } finally {
      void token;
    }
  }

  private async setLiked(params: Record<string, unknown>): Promise<CommandResult> {
    if (typeof params.occurrenceId !== "string" || typeof params.liked !== "boolean") {
      return { ok: false, error: { code: "internal_error", message: "setLiked requires occurrenceId and a desired liked state" } };
    }
    // Refresh at dispatch, including after waiting behind another command.
    const state = this.buildState();
    if (state.track?.occurrenceId !== params.occurrenceId) {
      return { ok: false, error: { code: "stale_target", message: "Track changed before the like request" } };
    }
    const control = likeControl();
    if (!control || !isEnabledControl(control.button) || state.liked === null) {
      return { ok: false, error: { code: "unsupported_operation", message: "No unambiguous like control is available" } };
    }
    if (control.liked === params.liked) {
      return { ok: true, outcome: { observedStateRevision: state.revision } };
    }

    const waiter = this.awaitOutcome(
      (observed) => observed.track?.occurrenceId === params.occurrenceId && observed.liked === params.liked,
      CONTROL_DEADLINE_MS,
    );
    control.button.click();
    this.emit();
    return waiter.done;
  }

  // searchSongs needs to return the rows, not just an outcome. The content
  // executor calls this narrower API directly (internal channel), keeping
  // exec() for transport commands.
  async runSearch(query: string): Promise<import("../protocol/types").SearchSongsResult> {
    const { promise } = this.search.search(query, SEARCH_DEADLINE_MS);
    const result = await promise;
    this.emit();
    return result;
  }

  private async startRadio(params: Record<string, unknown>): Promise<CommandResult> {
    const searchToken = typeof params.searchToken === "string" ? params.searchToken : "";
    const resultId = typeof params.resultId === "string" ? params.resultId : "";
    const deadlineAt = performance.now() + CONTROL_DEADLINE_MS;
    const prepared = await this.search.prepareRadio(searchToken, resultId, CONTROL_DEADLINE_MS);
    if (!prepared.ok) {
      return { ok: false, error: { code: prepared.code, message: prepared.error } };
    }

    const before = this.buildState();
    const playlistBefore = new URL(location.href).searchParams.get(RADIO.playlistParam);
    if (playlistBefore === prepared.playlistId && before.status === "playing") {
      return { ok: true, outcome: { observedStateRevision: before.revision } };
    }
    const waiter = this.awaitOutcome(
      (state) => state.status === "playing" && state.track !== null &&
        new URL(location.href).searchParams.get(RADIO.playlistParam) === prepared.playlistId &&
        (state.track.occurrenceId !== before.track?.occurrenceId ||
          (state.positionSeconds !== null && before.positionSeconds !== null &&
            state.positionSeconds < before.positionSeconds - 0.5)),
      Math.max(0, deadlineAt - performance.now()),
    );
    const dispatched = prepared.activate();
    if (!dispatched.ok) {
      waiter.cancel();
      return { ok: false, error: { code: "stale_result", message: dispatched.error } };
    }
    this.emit();
    return waiter.done;
  }

  private async playSearchResult(
    params: Record<string, unknown>,
  ): Promise<CommandResult> {
    const searchToken = typeof params.searchToken === "string" ? params.searchToken : "";
    const resultId = typeof params.resultId === "string" ? params.resultId : "";
    const res = this.search.playResult(searchToken, resultId);
    if (!res.ok) {
      return {
        ok: false,
        error: { code: "stale_result", message: res.error },
      };
    }
    // Confirm playback actually changed to the selected row before reporting.
    const before = this.snapshot().track?.occurrenceId ?? null;
    const waiter = this.awaitOutcome(
      (s) => s.track !== null && s.track.occurrenceId !== before,
      CONTROL_DEADLINE_MS,
    );
    return waiter.done;
  }

  async runPlayResult(searchToken: string, resultId: string): Promise<CommandResult> {
    return this.playSearchResult({ searchToken, resultId });
  }
}
