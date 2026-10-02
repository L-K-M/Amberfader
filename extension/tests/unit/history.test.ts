import { beforeEach, describe, expect, it, vi } from "vitest";
import { RECENT_ITEMS_CAP, SearchHistoryService } from "../../src/background/searchHistory";

let stored: Record<string, unknown>;
const set = vi.fn(async (values: Record<string, unknown>) => {
  Object.assign(stored, values);
});

beforeEach(() => {
  stored = {};
  set.mockClear();
  vi.stubGlobal("browser", { storage: { local: {
    get: async (key: string) => ({ [key]: stored[key] }), set,
  } } });
});

describe("shared search history", () => {
  it("persists newest-first history and promotes repeated queries without duplicates", async () => {
    const history = new SearchHistoryService();
    await history.recordQuery(" First query ");
    await history.recordQuery("Second query");
    await history.recordQuery("FIRST query");
    expect(await new SearchHistoryService().get()).toEqual({
      queries: ["FIRST query", "Second query"], artists: [],
    });
  });

  it("bounds and validates stored history", async () => {
    stored.searchHistory = {
      queries: [null, "", "  spaced  ", "SPACED", "x".repeat(600),
        ...Array.from({ length: 30 }, (_, i) => `query-${i}`)],
      artists: "invalid",
    };
    const result = await new SearchHistoryService().get();
    expect(result.queries).toHaveLength(RECENT_ITEMS_CAP);
    expect(result.queries.slice(0, 2)).toEqual(["spaced", "x".repeat(500)]);
    expect(result.artists).toEqual([]);
  });

  it("serializes concurrent query, artist and clear operations", async () => {
    const history = new SearchHistoryService();
    await Promise.all([
      history.recordQuery("old"), history.recordArtists(["old artist"]),
      history.clear(), history.recordQuery("new"), history.recordArtists(["new artist"]),
    ]);
    expect(await history.get()).toEqual({ queries: ["new"], artists: ["new artist"] });
  });

  it("keeps artists separate and preserves their order", async () => {
    const history = new SearchHistoryService();
    await history.recordArtists(["First", "Second"]);
    await history.recordArtists(["Third", "First"]);
    expect(await history.get()).toEqual({ queries: [], artists: ["Third", "First", "Second"] });
  });

  it("recovers after a storage failure instead of poisoning the queue", async () => {
    const history = new SearchHistoryService();
    set.mockRejectedValueOnce(new Error("storage unavailable"));
    await expect(history.recordQuery("lost")).rejects.toThrow("storage unavailable");
    expect(await history.recordQuery("saved")).toEqual({ queries: ["saved"], artists: [] });
  });
});
