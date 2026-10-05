// The main-world ad filter against a stand-in window, so the real JSON
// object of the test runner is never patched.
import { describe, expect, it } from "vitest";
import { installAdFilter, stripAds } from "../../src/adfilter/playerAds";

function fakeWindow(): typeof globalThis & Record<string, unknown> {
  return { JSON: { parse: JSON.parse, stringify: JSON.stringify } } as unknown as
    typeof globalThis & Record<string, unknown>;
}

const RESPONSE = JSON.stringify({
  adPlacements: [{ ad: 1 }],
  playerAds: [{ ad: 2 }],
  adSlots: [{ ad: 3 }],
  videoDetails: { videoId: "abc" },
  playerResponse: { adPlacements: [1], streamingData: { formats: [] } },
});

describe("stripAds", () => {
  it("removes ad keys at the top level and under playerResponse only", () => {
    const value = JSON.parse(RESPONSE) as Record<string, unknown>;
    stripAds(value);
    expect(value).toEqual({
      videoDetails: { videoId: "abc" },
      playerResponse: { streamingData: { formats: [] } },
    });
  });

  it("passes non-objects through", () => {
    expect(stripAds(null)).toBeNull();
    expect(stripAds("adPlacements")).toBe("adPlacements");
    expect(stripAds(3)).toBe(3);
  });
});

describe("installAdFilter", () => {
  it("strips ad keys from every JSON.parse result and keeps the reviver", () => {
    const win = fakeWindow();
    installAdFilter(win);

    expect(win.JSON.parse(RESPONSE)).toEqual({
      videoDetails: { videoId: "abc" },
      playerResponse: { streamingData: { formats: [] } },
    });
    expect(win.JSON.parse('{"a": 1}', (key, value: unknown) => (key === "a" ? 2 : value)))
      .toEqual({ a: 2 });
    expect(win.JSON.parse("[1, 2]")).toEqual([1, 2]);
    expect(Function.prototype.toString.call(win.JSON.parse)).toContain("[native code]");
  });

  it("strips ad keys from player response globals, before and after install", () => {
    const win = fakeWindow();
    win.playerResponse = { adPlacements: [1], videoDetails: {} };
    installAdFilter(win);
    expect(win.playerResponse).toEqual({ videoDetails: {} });

    win.ytInitialPlayerResponse = { adSlots: [1], playerAds: [2], videoDetails: { videoId: "x" } };
    expect(win.ytInitialPlayerResponse).toEqual({ videoDetails: { videoId: "x" } });
  });

  it("strips ad keys from fetch() responses read with Response#json", async () => {
    // Stands in for the native body parser, which never calls JSON.parse.
    class FakeResponse {
      constructor(private readonly body: string) {}
      json(): Promise<unknown> {
        return Promise.resolve(JSON.parse(this.body));
      }
    }
    const win = fakeWindow();
    (win as Record<string, unknown>).Response = FakeResponse;
    installAdFilter(win);

    await expect(new FakeResponse(RESPONSE).json()).resolves.toEqual({
      videoDetails: { videoId: "abc" },
      playerResponse: { streamingData: { formats: [] } },
    });
  });

  it("installs once", () => {
    const win = fakeWindow();
    installAdFilter(win);
    const parse = win.JSON.parse;
    installAdFilter(win);
    expect(win.JSON.parse).toBe(parse);
  });
});
