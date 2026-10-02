import { afterEach, beforeEach, expect, it, vi } from "vitest";

let receive!: (message: unknown, sender: unknown) => unknown;
const EXTENSION_ROOT = "moz-extension://probe-test/";
const RUNTIME_ID = "amberfader-test";
const request = { scope: "amberfader-internal", type: "probe.run", suites: ["artwork"] };

beforeEach(async () => {
  vi.resetModules();
  vi.stubGlobal("__amberfaderContentStarted", undefined);
  const sendMessage = vi.fn(async (_message: unknown) => ({ ok: true }));
  vi.stubGlobal("browser", {
    storage: { local: { get: async () => ({ devFakeAdapter: true }) } },
    runtime: {
      id: RUNTIME_ID,
      getURL: (path: string) => `${EXTENSION_ROOT}${path}`,
      sendMessage,
      onMessage: { addListener: (listener: typeof receive) => { receive = listener; } },
    },
  });
  document.body.innerHTML = '<ytmusic-player-bar><img class="image" src="https://lh3.googleusercontent.com/fixture"></ytmusic-player-bar>';
  await import("../../src/content/index");
  await vi.waitFor(() => expect(receive).toBeTypeOf("function"));
  await vi.waitFor(() => expect(sendMessage.mock.calls.length).toBeGreaterThanOrEqual(3));
});

afterEach(() => vi.unstubAllGlobals());

it("answers a probe from the extension options tab", async () => {
  const report = await receive(request, {
    id: RUNTIME_ID, tab: { id: 9 }, url: `${EXTENSION_ROOT}options.html`,
  });
  expect(report).toMatchObject({ probeVersion: 1, suites: { artwork: {
    hosts: ["lh3.googleusercontent.com"],
    origins: ["https://lh3.googleusercontent.com"],
    playerArtwork: expect.arrayContaining([expect.objectContaining({
      selector: "ytmusic-player-bar img.image", present: true,
      sourceOrigin: "https://lh3.googleusercontent.com",
    })]),
  } } });
});

it("does not accept a probe from a site content script", () => {
  expect(receive(request, {
    id: RUNTIME_ID, tab: { id: 7 }, url: "https://music.youtube.com/",
  })).toBeUndefined();
});
