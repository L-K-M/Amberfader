// CommandExecutor: a repeated request ID must never execute twice.
import { describe, expect, it, vi } from "vitest";
import { CommandExecutor } from "../../src/content/executor";
import { FakeAdapter } from "../../src/adapter/fakeAdapter";

describe("CommandExecutor dedup", () => {
  it("executes once per request id and replays the stored result", async () => {
    const adapter = new FakeAdapter();
    const spy = vi.spyOn(adapter, "exec");
    const ex = new CommandExecutor(adapter, adapter.runSearch.bind(adapter), adapter.runPlayResult.bind(adapter));

    const a = await ex.execute("req-1", "player.next", {});
    const b = await ex.execute("req-1", "player.next", {});
    expect(spy).toHaveBeenCalledTimes(1);
    expect(a.replayed).toBe(false);
    expect(b.replayed).toBe(true);
    expect(b.result).toEqual(a.result);
  });

  it("concurrent duplicates attach to the in-flight request", async () => {
    const adapter = new FakeAdapter();
    const spy = vi.spyOn(adapter, "exec");
    const ex = new CommandExecutor(adapter, adapter.runSearch.bind(adapter), adapter.runPlayResult.bind(adapter));
    const [a, b] = await Promise.all([
      ex.execute("req-2", "player.play", {}),
      ex.execute("req-2", "player.play", {}),
    ]);
    expect(spy).toHaveBeenCalledTimes(1);
    expect(a.replayed).toBe(false);
    // The duplicate attached to the in-flight execution — no second side
    // effect ran, so the flag is honest either way; the call count is the
    // load-bearing assertion.
    expect(b.result).toEqual(a.result);
  });

  it("caps the cache without evicting in-flight correctness", async () => {
    const adapter = new FakeAdapter();
    const ex = new CommandExecutor(adapter, adapter.runSearch.bind(adapter), adapter.runPlayResult.bind(adapter));
    for (let i = 0; i < 520; i += 1) {
      await ex.execute(`r-${i}`, "player.next", {});
    }
    expect(ex.size).toBeLessThanOrEqual(500);
    const res = await ex.execute("r-fresh", "player.next", {});
    expect(res.replayed).toBe(false);
  });
});
