import { readFileSync } from "node:fs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ClientEvents } from "../../src/popup/client";
import type { PlayerState, SearchSongsResult } from "../../src/protocol/types";

const mock = vi.hoisted((): { events: ClientEvents; request: ReturnType<typeof vi.fn> } => ({
  events: {},
  request: vi.fn(),
}));

vi.mock("../../src/popup/client", () => ({
  ProtocolClient: class {
    constructor(events: ClientEvents) { mock.events = events; }
    connect = async () => undefined;
    request = mock.request;
  },
}));

const state: PlayerState = {
  bindingToken: "binding", revision: 1,
  track: { occurrenceId: "occ-1", providerId: "song", title: "Song", artists: ["Artist"], album: null, artworkId: null },
  status: "playing", contentKind: "track", positionSeconds: 1, durationSeconds: 200,
  playbackRate: 1, volume: 1, muted: false, liked: false, capabilities: ["play", "pause", "setLiked"],
};

const results: SearchSongsResult = {
  searchToken: "search-1", complete: true,
  results: [{ resultId: "search-1/row", kind: "song", title: "Song", artists: ["Artist"],
    album: null, durationSeconds: 200, supported: true, radioSupported: true, artworkId: null }],
};

async function flush(): Promise<void> {
  // Let connect -> request -> render promise continuations finish.
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

async function mount(page: "player" | "search"): Promise<void> {
  document.body.innerHTML = readFileSync(`extension/src/popup/${page}.html`, "utf8");
  if (page === "player") await import("../../src/popup/player");
  else await import("../../src/popup/search");
  await flush();
}

beforeEach(() => {
  vi.resetModules();
  vi.useFakeTimers();
  mock.request.mockReset();
  mock.request.mockImplementation(async (method: string) => ({
    ok: true, result: method === "search.songs" ? results : { queries: ["Past query"], artists: ["Past artist"] },
  }));
});

afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});

describe("player heart", () => {
  it("renders observed states and disables unknown likes", async () => {
    await mount("player");
    const heart = document.getElementById("btn-like") as HTMLButtonElement;
    expect(heart.disabled).toBe(true);
    mock.events.onState?.(state);
    expect(heart.textContent).toBe("♡");
    expect(heart.getAttribute("aria-pressed")).toBe("false");
    mock.events.onState?.({ ...state, liked: true });
    expect(heart.textContent).toBe("♥");
    expect(heart.getAttribute("aria-label")).toBe("Unlike this song");
    mock.events.onState?.({ ...state, liked: null });
    expect(heart.disabled).toBe(true);
    expect(heart.textContent).toBe("♡?");
    expect(heart.hasAttribute("aria-pressed")).toBe(false);
  });

  it("sends one occurrence-bound desired state without optimistic success", async () => {
    await mount("player");
    mock.events.onState?.(state);
    let finish!: (response: unknown) => void;
    mock.request.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    const heart = document.getElementById("btn-like") as HTMLButtonElement;
    heart.click();
    heart.click();
    expect(mock.request).toHaveBeenCalledExactlyOnceWith("player.setLiked", { occurrenceId: "occ-1", liked: true });
    expect(heart.disabled).toBe(true);
    expect(heart.textContent).toBe("♡");
    finish({ ok: false, error: { message: "Not confirmed" } });
    await flush();
    expect(heart.disabled).toBe(false);
    expect(heart.textContent).toBe("♡");
    expect(document.getElementById("status")?.textContent).toBe("Not confirmed");
    mock.events.onState?.({ ...state, liked: true });
    heart.click();
    expect(mock.request).toHaveBeenLastCalledWith("player.setLiked", { occurrenceId: "occ-1", liked: false });
  });
});

describe("search recents and radio", () => {
  it("loads and reuses shared recent queries and artists, and clears history", async () => {
    await mount("search");
    expect(mock.request).toHaveBeenCalledWith("search.history", {});
    const query = document.getElementById("q") as HTMLInputElement;
    (document.querySelector("#recent-artists button") as HTMLButtonElement).click();
    await flush();
    expect(query.value).toBe("Past artist");
    expect(mock.request).toHaveBeenCalledWith("search.songs", { query: "Past artist" });
    (document.querySelector("#recent-queries button") as HTMLButtonElement).click();
    await flush();
    expect(mock.request).toHaveBeenCalledWith("search.songs", { query: "Past query" });
    (document.getElementById("clear-history") as HTMLButtonElement).click();
    await flush();
    expect(mock.request).toHaveBeenCalledWith("search.clearHistory", {});
  });

  it("starts radio without also playing and clears actions when binding changes", async () => {
    await mount("search");
    const query = document.getElementById("q") as HTMLInputElement;
    query.value = "query";
    query.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    await flush();
    const radio = [...document.querySelectorAll<HTMLButtonElement>("#results button")]
      .find((button) => button.textContent === "Start mix")!;
    radio.click();
    await flush();
    expect(mock.request).toHaveBeenCalledWith("search.startRadio", { searchToken: "search-1", resultId: "search-1/row" });
    expect(mock.request).not.toHaveBeenCalledWith("search.playResult", expect.anything());
    mock.events.onBinding?.("bound");
    expect(document.querySelector("#results button")).toBeNull();
    const calls = mock.request.mock.calls.length;
    radio.click();
    expect(mock.request.mock.calls).toHaveLength(calls);
  });

  it("discards a search response arriving after disconnection", async () => {
    await mount("search");
    let finish!: (response: unknown) => void;
    mock.request.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    const query = document.getElementById("q") as HTMLInputElement;
    query.value = "query";
    query.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    mock.events.onDisconnected?.();
    finish({ ok: true, result: results });
    await flush();
    expect(document.getElementById("results")?.children).toHaveLength(0);
  });
});
