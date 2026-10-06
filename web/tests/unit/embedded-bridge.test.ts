// Embedded QtWebEngine bridge: same adapter + executor as the content script,
// different transport. These tests pin the page-side contract the Python host
// relies on: registration order, nonce checks, dedup, and error mapping.
import { afterEach, describe, expect, it, vi } from "vitest";
import { FakeAdapter } from "../../src/adapter/fakeAdapter";
import { SearchTimeoutError } from "../../src/adapter/search";
import type { CommandResult } from "../../src/adapter/types";
import { executorFor } from "../../src/content/executor";
import {
  EmbeddedBridge,
  outcomeFor,
  parseHostCommand,
} from "../../src/embedded/bridge";
import type { PageMessage } from "../../src/embedded/bridge";

const NONCE = "doc-1";
let adapter: FakeAdapter;

function makeBridge(): { bridge: EmbeddedBridge; posted: PageMessage[] } {
  adapter = new FakeAdapter({ tickMs: 60_000, searchDelayMs: 0 });
  const posted: PageMessage[] = [];
  const bridge = new EmbeddedBridge(NONCE, adapter, executorFor(adapter), (m) => posted.push(m));
  return { bridge, posted };
}

function command(requestId: string, method: string, params = {}, expectedNonce = NONCE): string {
  return JSON.stringify({ requestId, method, params, expectedNonce });
}

function replies(posted: PageMessage[]): Extract<PageMessage, { type: "reply" }>[] {
  return posted.filter((m): m is Extract<PageMessage, { type: "reply" }> => m.type === "reply");
}

afterEach(() => adapter?.stop());

describe("EmbeddedBridge startup", () => {
  it("registers the document before publishing any state", async () => {
    const { bridge, posted } = makeBridge();
    await bridge.start();

    expect(posted[0]).toEqual({
      type: "register", documentNonce: NONCE, capabilities: adapter.capabilities,
    });
    const states = posted.filter((m) => m.type === "state");
    expect(states.length).toBeGreaterThan(0);
    expect(posted.indexOf(states[0]!)).toBeGreaterThan(0);
    expect(states.every((m) => m.documentNonce === NONCE)).toBe(true);
  });
});

describe("EmbeddedBridge commands", () => {
  it("executes a request once and replays the stored reply", async () => {
    const { bridge, posted } = makeBridge();
    await bridge.start();
    const exec = vi.spyOn(adapter, "exec");

    await bridge.handleCommand(command("req-1", "player.next"));
    await bridge.handleCommand(command("req-1", "player.next"));

    expect(exec).toHaveBeenCalledTimes(1);
    const [first, second] = replies(posted);
    expect(first).toMatchObject({ requestId: "req-1", replayed: false, outcome: { ok: true } });
    expect(second).toMatchObject({ requestId: "req-1", replayed: true });
    expect(second!.outcome).toEqual(first!.outcome);
  });

  it("answers a command for an earlier document as stale without running it", async () => {
    const { bridge, posted } = makeBridge();
    await bridge.start();
    const exec = vi.spyOn(adapter, "exec");

    await bridge.handleCommand(command("req-2", "player.play", {}, "doc-0"));

    expect(exec).not.toHaveBeenCalled();
    expect(replies(posted)).toEqual([{
      type: "reply",
      documentNonce: NONCE,
      requestId: "req-2",
      replayed: false,
      outcome: {
        ok: false,
        error: {
          code: "stale_target",
          message: "The YouTube Music page reloaded since the command was issued",
        },
      },
    }]);
  });

  it("drops malformed commands and host-only methods", async () => {
    const { bridge, posted } = makeBridge();
    await bridge.start();
    const exec = vi.spyOn(adapter, "exec");
    const before = posted.length;

    await bridge.handleCommand("not json");
    await bridge.handleCommand(command("req-3", "state.get"));
    await bridge.handleCommand(command("req-4", "browser.showPlayer"));
    await bridge.handleCommand(JSON.stringify({ requestId: "req-5", method: "player.play" }));
    await bridge.handleCommand(command("x".repeat(129), "player.play"));

    expect(exec).not.toHaveBeenCalled();
    expect(posted.length).toBe(before);
  });

  it("returns search rows as the result", async () => {
    const { bridge, posted } = makeBridge();
    await bridge.start();

    await bridge.handleCommand(command("req-6", "search.songs", { query: "amber" }));

    const [reply] = replies(posted);
    expect(reply!.outcome.ok).toBe(true);
    const result = (reply!.outcome as { result: Record<string, unknown> }).result;
    expect(typeof result.searchToken).toBe("string");
    expect(Array.isArray(result.results)).toBe(true);
  });

  it("maps a search timeout to the timeout code", async () => {
    const { bridge, posted } = makeBridge();
    await bridge.start();
    vi.spyOn(adapter, "runSearch").mockRejectedValue(new SearchTimeoutError("no results in time"));

    await bridge.handleCommand(command("req-7", "search.songs", { query: "slow" }));

    expect(replies(posted)[0]!.outcome).toEqual({
      ok: false, error: { code: "timeout", message: "no results in time" },
    });
  });

  it("does not leak unexpected exception text", async () => {
    const { bridge, posted } = makeBridge();
    await bridge.start();
    vi.spyOn(adapter, "exec").mockRejectedValue(new Error("secret page detail"));

    await bridge.handleCommand(command("req-8", "player.pause"));

    expect(replies(posted)[0]!.outcome).toEqual({
      ok: false,
      error: { code: "internal_error", message: "The page could not complete the command" },
    });
  });
});

describe("outcome mapping", () => {
  it("passes adapter failures through with their code", () => {
    const failed: CommandResult = {
      ok: false, error: { code: "pending_outcome", message: "not observed yet" },
    };
    expect(outcomeFor("player.play", failed)).toEqual({
      ok: false, error: { code: "pending_outcome", message: "not observed yet" },
    });
  });

  it("reports unrecognized adapter results instead of passing them on", () => {
    expect(outcomeFor("player.play", { surprise: true })).toEqual({
      ok: false,
      error: { code: "internal_error", message: "Adapter returned an unrecognized result" },
    });
    expect(outcomeFor("player.play", null).ok).toBe(false);
  });

  it("validates command fields", () => {
    expect(parseHostCommand(command("r", "player.seek", { positionSeconds: 3 }))).toEqual({
      requestId: "r", method: "player.seek", params: { positionSeconds: 3 }, expectedNonce: NONCE,
    });
    expect(parseHostCommand(JSON.stringify({
      requestId: "r", method: "player.seek", params: [], expectedNonce: NONCE,
    }))).toBeNull();
    expect(parseHostCommand(command("r", "player.seek", {}, ""))).toBeNull();
  });
});
