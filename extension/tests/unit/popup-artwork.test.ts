// Router -> real page client -> artwork service -> popup, with a paused site
// snapshot and a fake network/bitmap decoder. This does not exercise live YTM.
import { Blob as NodeBlob } from "node:buffer";
import { readFileSync } from "node:fs";
import { afterEach, expect, it, vi } from "vitest";
import type { AdapterStatePush } from "../../src/protocol/internal";

const push = (artworkId = "cover", occurrenceId = "occ-1"): AdapterStatePush => ({
  scope: "amberfader-internal", type: "adapter.state", documentNonce: "document",
  artworkUrl: `https://yt3.googleusercontent.com/${artworkId}`,
  state: {
    revision: 1, track: { occurrenceId, providerId: "song", title: "Paused song",
      artists: ["Artist"], album: null, artworkId },
    status: "paused", contentKind: "track", positionSeconds: 12, durationSeconds: 200,
    playbackRate: 1, volume: 1, muted: false, liked: null, capabilities: ["play"],
  },
});

async function mountPlayer(fetchImpl: typeof fetch) {
  vi.resetModules();
  vi.useFakeTimers();
  vi.stubGlobal("fetch", fetchImpl);
  vi.stubGlobal("Blob", NodeBlob);
  vi.stubGlobal("createImageBitmap", async (blob: NodeBlob) => ({
    width: 60, height: 60, bytes: new Uint8Array(await blob.arrayBuffer()),
  }));
  const pixels = new WeakMap<HTMLCanvasElement, Uint8Array>();
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(function (this: HTMLCanvasElement) {
    return { drawImage: (bitmap: { bytes: Uint8Array }) => pixels.set(this, bitmap.bytes) } as unknown as CanvasRenderingContext2D;
  });
  vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation(function (this: HTMLCanvasElement, callback) {
    callback(new NodeBlob([pixels.get(this)!], { type: "image/jpeg" }) as unknown as Blob);
  });
  const { Router } = await import("../../src/background/router");
  const router = new Router();
  const storage: Record<string, unknown> = {};
  vi.stubGlobal("browser", {
    storage: { local: {
      get: async (key: string) => ({ [key]: storage[key] }),
      set: async (value: Record<string, unknown>) => { Object.assign(storage, value); },
    } },
    permissions: { contains: async () => true },
    tabs: {
      query: async () => [{ id: 7, url: "https://music.youtube.com/" }],
      sendMessage: async () => push(),
    },
    runtime: {
      getURL: (path: string) => `moz-extension://fixture/${path}`,
      sendMessage: (message: unknown) => router.onInternalMessage(message, {}),
      connect: () => {
        let listener: ((message: unknown) => void) | undefined;
        const port = {
          postMessage: (message: unknown) => { void Promise.resolve().then(() => listener?.(message)); },
          onMessage: { addListener: (callback: typeof listener) => { listener = callback; } },
          onDisconnect: { addListener: () => undefined },
        };
        router.subscribeUiPort(port);
        return port;
      },
    },
  });
  await router.init();
  await router.handleClientMessage({
    protocolVersion: 1, kind: "request", id: "initial", method: "state.get", params: {},
  });
  document.body.innerHTML = readFileSync("extension/src/popup/player.html", "utf8");
  await import("../../src/popup/player");
  return { router, art: document.getElementById("art") as HTMLImageElement };
}

const response = (bytes = [1, 2, 3]) => new Response(new Uint8Array(bytes), {
  headers: { "content-type": "image/png" },
});

afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("restores a paused cover on open and clears it when the target closes", async () => {
  const fetchImpl = vi.fn(async () => response());
  const { router, art } = await mountPlayer(fetchImpl);
  await vi.waitFor(() => expect(art.getAttribute("src")).toBe("data:image/jpeg;base64,AQID"));
  expect(fetchImpl).toHaveBeenCalledOnce();
  expect(document.getElementById("title")?.textContent).toBe("Paused song");
  router.onTabRemoved(7);
  await vi.waitFor(() => expect(art.hasAttribute("src")).toBe(false));
});

it("discards a slow cover after the current track changes", async () => {
  let finish!: (value: Response) => void;
  const pending = new Promise<Response>((resolve) => { finish = resolve; });
  const fetchImpl = vi.fn(async (url: unknown) => String(url).endsWith("/cover") ? pending : response([4, 5, 6]));
  const { router, art } = await mountPlayer(fetchImpl);
  await vi.waitFor(() => expect(fetchImpl).toHaveBeenCalledOnce());
  await router.onInternalMessage(push("new-cover", "occ-2"), { tab: { id: 7 }, frameId: 0 });
  await vi.waitFor(() => expect(art.getAttribute("src")).toBe("data:image/jpeg;base64,BAUG"));
  finish(response());
  await vi.advanceTimersByTimeAsync(0);
  expect(fetchImpl).toHaveBeenCalledTimes(2);
  expect(art.getAttribute("src")).toBe("data:image/jpeg;base64,BAUG");
});
