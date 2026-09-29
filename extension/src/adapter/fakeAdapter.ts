// Fake adapter: a scripted SiteAdapter with the same interface as the real
// one. Drives the prototype UI offline, unit tests, and development without a
// YouTube Music session. Enabled at runtime via the options-page dev toggle.
import type {
  AdapterPlayerState,
  CommandResult,
  SiteAdapter,
} from "./types";
import type {
  Capability,
  Method,
  PlaybackStatus,
  SearchSongsResult,
} from "../protocol/types";

const ALL_CAPS: Capability[] = [
  "play",
  "pause",
  "previous",
  "next",
  "seek",
  "volume",
  "searchSongs",
  "playSearchResult",
];

const SCRIPT = [
  {
    providerId: "fake-001",
    title: "Midnight at the Volcano Lounge",
    artists: ["The Coral Keys"],
    album: "Basalt Sessions",
    durationSeconds: 232,
  },
  {
    providerId: "fake-002",
    title: "Amber Fade",
    artists: ["Slow Decay"],
    album: "Warm Static",
    durationSeconds: 187,
  },
  {
    providerId: "fake-003",
    title: "Transistor Cathedral",
    artists: ["Grey Antenna", "Marlow Signals"],
    album: null,
    durationSeconds: 264,
  },
];

export interface FakeAdapterOptions {
  tickMs?: number;
  searchDelayMs?: number;
  failNextCommand?: boolean;
}

export class FakeAdapter implements SiteAdapter {
  capabilities: Capability[] = [...ALL_CAPS];
  proposedArtworkUrl: string | null = null;

  private readonly listeners = new Set<(s: AdapterPlayerState) => void>();
  private readonly noticeListeners = new Set<
    (n: { component: "adapter"; status: "connected" | "disconnected" | "degraded"; reason?: string }) => void
  >();

  private readonly tickMs: number;
  private readonly searchDelayMs: number;
  private failNext: boolean;

  private revision = 0;
  private occurrence = 0;
  private trackIndex = 0;
  private status: PlaybackStatus = "paused";
  private position = 0;
  private volume = 0.8;
  private muted = false;
  private rate = 1;
  private timer: ReturnType<typeof setInterval> | null = null;
  private running = false;
  private searchSeq = 0;

  constructor(opts: FakeAdapterOptions = {}) {
    this.tickMs = opts.tickMs ?? 1000;
    this.searchDelayMs = opts.searchDelayMs ?? 150;
    this.failNext = opts.failNextCommand ?? false;
  }

  onState(cb: (s: AdapterPlayerState) => void): void {
    this.listeners.add(cb);
  }

  onNotice(
    cb: (n: { component: "adapter"; status: "connected" | "disconnected" | "degraded"; reason?: string }) => void,
  ): void {
    this.noticeListeners.add(cb);
  }

  snapshot(): AdapterPlayerState {
    return this.build();
  }

  start(): Promise<void> {
    this.running = true;
    this.armTimer();
    this.emit();
    return Promise.resolve();
  }

  stop(): void {
    this.running = false;
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  }

  private armTimer(): void {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    if (!this.running || this.status !== "playing") return;
    this.timer = setInterval(() => {
      const dur = SCRIPT[this.trackIndex]!.durationSeconds;
      this.position += (this.tickMs / 1000) * this.rate;
      if (this.position >= dur) {
        this.trackIndex = (this.trackIndex + 1) % SCRIPT.length;
        this.occurrence += 1;
        this.position = 0;
      }
      this.emit();
    }, this.tickMs);
  }

  private build(): AdapterPlayerState {
    const t = SCRIPT[this.trackIndex]!;
    return {
      revision: ++this.revision,
      track: {
        occurrenceId: `fake-occ-${this.occurrence}`,
        providerId: t.providerId,
        title: t.title,
        artists: t.artists,
        album: t.album,
        artworkId: null,
      },
      status: this.status,
      contentKind: "track",
      positionSeconds: this.position,
      durationSeconds: t.durationSeconds,
      playbackRate: this.rate,
      volume: this.volume,
      muted: this.muted,
      capabilities: [...this.capabilities],
    };
  }

  private emit(): void {
    const s = this.build();
    for (const cb of this.listeners) cb(s);
  }

  private outcome(): CommandResult {
    return { ok: true, outcome: { observedStateRevision: this.revision } };
  }

  private maybeFail(): CommandResult | null {
    if (!this.failNext) return null;
    this.failNext = false;
    return {
      ok: false,
      error: { code: "pending_outcome", message: "fake: outcome not observed" },
    };
  }

  exec(
    requestId: string,
    method: Method,
    params: Record<string, unknown>,
  ): Promise<CommandResult> {
    return Promise.resolve(this.execSync(requestId, method, params));
  }

  private execSync(
    _requestId: string,
    method: Method,
    params: Record<string, unknown>,
  ): CommandResult {
    const failed = this.maybeFail();
    if (failed) return failed;
    switch (method) {
      case "player.play":
        this.status = "playing";
        this.armTimer();
        this.emit();
        return this.outcome();
      case "player.pause":
        this.status = "paused";
        this.armTimer();
        this.emit();
        return this.outcome();
      case "player.next":
        this.trackIndex = (this.trackIndex + 1) % SCRIPT.length;
        this.occurrence += 1;
        this.position = 0;
        this.emit();
        return this.outcome();
      case "player.previous":
        this.trackIndex = (this.trackIndex + SCRIPT.length - 1) % SCRIPT.length;
        this.occurrence += 1;
        this.position = 0;
        this.emit();
        return this.outcome();
      case "player.seek": {
        const occ = params.occurrenceId;
        const pos = params.positionSeconds;
        if (typeof occ !== "string" || occ !== `fake-occ-${this.occurrence}`) {
          return {
            ok: false,
            error: { code: "stale_target", message: "occurrence mismatch" },
          };
        }
        if (typeof pos !== "number" || !Number.isFinite(pos)) {
          return {
            ok: false,
            error: { code: "internal_error", message: "bad position" },
          };
        }
        const dur = SCRIPT[this.trackIndex]!.durationSeconds;
        this.position = Math.min(Math.max(pos, 0), dur);
        this.emit();
        return this.outcome();
      }
      case "player.setVolume": {
        const v = params.volume;
        if (typeof v !== "number" || !Number.isFinite(v)) {
          return {
            ok: false,
            error: { code: "internal_error", message: "bad volume" },
          };
        }
        this.volume = Math.min(Math.max(v, 0), 1);
        this.emit();
        return this.outcome();
      }
      case "player.setMuted":
        this.muted = params.muted === true;
        this.emit();
        return this.outcome();
      default:
        return {
          ok: false,
          error: { code: "unsupported_operation", message: `fake: no ${method}` },
        };
    }
  }

  async runSearch(query: string): Promise<SearchSongsResult> {
    await new Promise((r) => setTimeout(r, this.searchDelayMs));
    const token = `fake-s${++this.searchSeq}`;
    return {
      searchToken: token,
      complete: true,
      results: SCRIPT.map((t, i) => ({
        resultId: `${token}/${i}`,
        kind: "song" as const,
        title: `${t.title} (${query})`,
        artists: t.artists,
        album: t.album,
        durationSeconds: t.durationSeconds,
        supported: true,
        artworkId: null,
      })),
    };
  }

  runPlayResult(searchToken: string, resultId: string): Promise<CommandResult> {
    return Promise.resolve(this.runPlayResultSync(searchToken, resultId));
  }

  private runPlayResultSync(searchToken: string, resultId: string): CommandResult {
    if (!searchToken.startsWith("fake-s") || !resultId.startsWith(`${searchToken}/`)) {
      return {
        ok: false,
        error: { code: "stale_result", message: "unknown result handle" },
      };
    }
    const idx = Number(resultId.slice(searchToken.length + 1));
    if (!Number.isInteger(idx) || idx < 0 || idx >= SCRIPT.length) {
      return {
        ok: false,
        error: { code: "stale_result", message: "unknown result handle" },
      };
    }
    this.trackIndex = idx;
    this.occurrence += 1;
    this.position = 0;
    this.status = "playing";
    this.armTimer();
    this.emit();
    return this.outcome();
  }
}
