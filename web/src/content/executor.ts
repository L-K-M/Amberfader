// Command executor inside the content script — the point where side effects
// happen, so request-ID deduplication lives here. Terminal responses and
// in-flight requests are cached for the current document generation; repeated
// IDs never execute twice. This is not exactly-once across browser crashes —
// clients reconnect with fresh state instead of retrying non-idempotent ops.
import type { CommandResult, SiteAdapter } from "../adapter/types";
import type { FakeAdapter } from "../adapter/fakeAdapter";
import type { YouTubeMusicAdapter } from "../adapter/youtubeMusic";
import type { Method } from "../protocol/types";

const DEDUP_CAP = 500;

interface CachedResult {
  status: "inflight" | "done";
  promise: Promise<CommandResult>;
  result?: CommandResult;
}

export class CommandExecutor {
  private readonly cache = new Map<string, CachedResult>();
  private readonly adapter: SiteAdapter;
  private readonly runSearchFn: (q: string) => Promise<unknown>;
  private readonly runPlayResultFn: (
    t: string,
    r: string,
  ) => Promise<CommandResult>;

  constructor(
    adapter: SiteAdapter,
    runSearch: (q: string) => Promise<unknown>,
    runPlayResult: (t: string, r: string) => Promise<CommandResult>,
  ) {
    this.adapter = adapter;
    this.runSearchFn = runSearch;
    this.runPlayResultFn = runPlayResult;
  }

  // Executes or attaches to an in-flight execution of the same requestId.
  // Returns { replayed: true } when the caller re-sent a completed request —
  // the stored terminal result is returned without side effects.
  async execute(
    requestId: string,
    method: Method,
    params: Record<string, unknown>,
  ): Promise<{ result: unknown; replayed: boolean }> {
    const cached = this.cache.get(requestId);
    if (cached) {
      const result = cached.status === "done" ? cached.result : await cached.promise;
      return { result, replayed: cached.status === "done" };
    }

    const asString = (v: unknown): string =>
      typeof v === "string" ? v : "";
    let promise: Promise<unknown>;
    switch (method) {
      case "search.songs":
        promise = this.runSearchFn(asString(params.query));
        break;
      case "search.playResult":
        promise = this.runPlayResultFn(
          asString(params.searchToken),
          asString(params.resultId),
        );
        break;
      default:
        promise = this.adapter.exec(requestId, method, params);
    }

    const entry: CachedResult = { status: "inflight", promise: promise as Promise<CommandResult> };
    this.cache.set(requestId, entry);
    this.trimCache();

    const result = await promise;
    entry.status = "done";
    entry.result = result as CommandResult;
    return { result, replayed: false };
  }

  private trimCache(): void {
    if (this.cache.size <= DEDUP_CAP) return;
    // Evict oldest entries (Map preserves insertion order).
    const excess = this.cache.size - DEDUP_CAP;
    let i = 0;
    for (const key of this.cache.keys()) {
      if (i >= excess) break;
      this.cache.delete(key);
      i += 1;
    }
  }

  get size(): number {
    return this.cache.size;
  }
}

// Search and result playback use narrower adapter APIs than exec(). Both page
// hosts (the Firefox content script and the embedded QtWebEngine bridge) wire
// them through this one factory so their command paths cannot drift apart.
export function executorFor(adapter: SiteAdapter): CommandExecutor {
  return new CommandExecutor(
    adapter,
    (q) =>
      "runSearch" in adapter
        ? (adapter as YouTubeMusicAdapter | FakeAdapter).runSearch(q)
        : Promise.reject(new Error("adapter has no search")),
    (t, r) =>
      "runPlayResult" in adapter
        ? (adapter as YouTubeMusicAdapter | FakeAdapter).runPlayResult(t, r)
        : Promise.resolve({
            ok: false as const,
            error: {
              code: "unsupported_operation" as const,
              message: "adapter has no playResult",
            },
          }),
  );
}
