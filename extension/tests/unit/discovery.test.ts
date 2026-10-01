// Exercise the actual client, router and content-script bus with a paused fake
// adapter. A paused tab must bind without waiting for another state push.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { PlayerState } from "../../src/protocol/types";

type Listener = (message: unknown, sender: unknown) => unknown;
const TAB_ID = 7;
const MUSIC_URL = "https://music.youtube.com/";
const CONTENT_CONTEXT_KEY = "__amberfaderContentStarted";

async function setup() {
  const { Router } = await import("../../src/background/router");
  let router = new Router();
  const listeners: Listener[] = [];
  const pending: Promise<unknown>[] = [];
  let tabs = [{ id: TAB_ID, url: MUSIC_URL, title: "YouTube Music" }];
  const inject = vi.fn(async () => {
    await import("../../src/content/index");
    await settle();
    return [];
  });
  const sendToTab = vi.fn(async (_tabId: number, message: unknown): Promise<unknown> => {
    for (const listener of listeners) {
      const response = listener(message, { id: "amberfader-test" });
      if (response !== undefined) return response;
    }
    throw new Error("Could not establish connection. Receiving end does not exist.");
  });
  const api = {
    storage: {
      local: {
        get: vi.fn(async (_key: string) => ({ installId: "test-install", devFakeAdapter: true })),
        set: async () => undefined,
      },
    },
    tabs: {
      query: async () => tabs,
      get: async () => tabs[0],
      sendMessage: sendToTab,
    },
    scripting: { executeScript: inject },
    permissions: { contains: vi.fn(async () => true) },
    runtime: {
      id: "amberfader-test",
      onMessage: { addListener: (listener: Listener) => listeners.push(listener) },
      sendMessage: (message: unknown) => {
        const type = (message as { type: string }).type;
        const sender = type.startsWith("adapter.")
          ? { tab: { id: TAB_ID }, frameId: 0 }
          : { id: "amberfader-test" };
        const response = router.onInternalMessage(message, sender);
        if (type.startsWith("adapter.")) pending.push(response);
        return response;
      },
      connect: () => {
        let onMessage: (message: unknown) => void = () => undefined;
        router.subscribeUiPort({ postMessage: (message: unknown) => onMessage(message) });
        return {
          onMessage: { addListener: (listener: typeof onMessage) => { onMessage = listener; } },
          onDisconnect: { addListener: () => undefined },
        };
      },
    },
  };
  vi.stubGlobal("browser", api);
  vi.stubGlobal("window", globalThis);
  await router.init();

  async function settle() {
    // Drain startup pushes, including any router work they start.
    for (let index = 0; index < pending.length; index += 1) await pending[index];
  }

  const { ProtocolClient } = await import("../../src/popup/client");
  const states: PlayerState[] = [];
  const onConnection = vi.fn();
  const client = new ProtocolClient({ onState: (state) => states.push(state), onConnection });
  return {
    client, states, inject, sendToTab, listeners, onConnection,
    storageGet: api.storage.local.get,
    hasSiteAccess: api.permissions.contains,
    loadContent: async () => {
      await import("../../src/content/index");
      await settle();
    },
    restartRouter: async () => { router = new Router(); await router.init(); },
    setTabs: (value: typeof tabs) => { tabs = value; },
    getRouter: () => router,
  };
}

describe("playback tab discovery", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubGlobal(CONTENT_CONTEXT_KEY, undefined);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("discovers a paused tab whose adapter registered before the player opened", async () => {
    const bus = await setup();
    await bus.loadContent();
    await bus.client.connect();
    expect(bus.states.at(-1)?.track?.providerId).toBe("fake-001");
    expect(bus.client.bindingToken).toBeTruthy();
    expect(bus.inject).not.toHaveBeenCalled();
    const pause = await bus.client.request("player.pause", {});
    expect(pause.ok, JSON.stringify(pause)).toBe(true);
  });

  it("attaches to an already-open tab without reloading or playback commands", async () => {
    const bus = await setup();
    await bus.client.connect();
    expect(bus.states.at(-1)?.track?.providerId).toBe("fake-001");
    expect(bus.inject).toHaveBeenCalledOnce();
    expect(bus.inject).toHaveBeenCalledWith({
      target: { tabId: TAB_ID, frameIds: [0] }, files: ["js/content.js"],
    });
    expect(bus.sendToTab.mock.calls.some(([, message]) =>
      (message as { type: string }).type === "adapter.exec")).toBe(false);
  });

  it("takes a fresh snapshot after the event page restarts", async () => {
    const bus = await setup();
    await bus.loadContent();
    await bus.client.connect();
    const oldSession = bus.client.sessionId;
    const oldToken = bus.client.bindingToken;
    await bus.restartRouter();
    await bus.client.connect();
    expect(bus.states.at(-1)?.track?.providerId).toBe("fake-001");
    expect(bus.client.sessionId).not.toBe(oldSession);
    expect(bus.client.bindingToken).not.toBe(oldToken);
    expect(bus.inject).not.toHaveBeenCalled();
    const pause = await bus.client.request("player.pause", {});
    expect(pause.ok, JSON.stringify(pause)).toBe(true);
  });

  it("answers the injection handshake while adapter initialization is pending", async () => {
    const bus = await setup();
    let finishStorageRead!: (value: { installId: string; devFakeAdapter: boolean }) => void;
    bus.storageGet.mockImplementation(() => new Promise((resolve) => { finishStorageRead = resolve; }));
    bus.inject.mockImplementation(async () => {
      await import("../../src/content/index");
      return [];
    });
    const connecting = bus.client.connect();
    await vi.waitFor(() => expect(bus.sendToTab).toHaveBeenCalledTimes(2));
    finishStorageRead({ installId: "test-install", devFakeAdapter: true });
    await connecting;
    expect(bus.states.at(-1)?.track?.providerId).toBe("fake-001");
  });

  it("discovers a tab opened after the player", async () => {
    const bus = await setup();
    bus.setTabs([]);
    await bus.client.connect();
    expect(bus.states).toHaveLength(0);
    bus.setTabs([{ id: TAB_ID, url: MUSIC_URL, title: "YouTube Music" }]);
    await bus.loadContent();
    expect(bus.states.at(-1)?.track?.providerId).toBe("fake-001");
    expect((await bus.client.request("player.pause", {})).ok).toBe(true);
  });

  it("keeps multiple tabs unbound until explicitly selected", async () => {
    const bus = await setup();
    bus.setTabs([
      { id: TAB_ID, url: MUSIC_URL, title: "First tab" },
      { id: 9, url: MUSIC_URL, title: "Second tab" },
    ]);
    await bus.loadContent();
    await bus.client.connect();
    expect(bus.states).toHaveLength(0);
    expect(bus.getRouter().selectedTabId).toBeNull();
    expect(bus.inject).not.toHaveBeenCalled();
    const selected = await bus.client.request("targets.select", { targetKey: `tab:${TAB_ID}` });
    expect(selected.ok, JSON.stringify(selected)).toBe(true);
    expect(bus.states.at(-1)?.track?.providerId).toBe("fake-001");
    expect((await bus.client.request("player.pause", {})).ok).toBe(true);
  });

  it("does not install duplicate executors when injection races page startup", async () => {
    const bus = await setup();
    await bus.loadContent();
    const listenerCount = bus.listeners.length;
    vi.resetModules();
    await bus.loadContent();
    expect(bus.listeners).toHaveLength(listenerCount);
  });

  it("reports site-access failure instead of silently waiting", async () => {
    const bus = await setup();
    bus.inject.mockRejectedValue(new Error("Missing host permission"));
    await bus.client.connect();
    expect(bus.states).toHaveLength(0);
    expect(bus.onConnection).toHaveBeenCalledWith(
      "adapter", "disconnected", expect.stringContaining("site access"),
    );
  });

  it("reports withheld site access even when Firefox hides matching tab URLs", async () => {
    const bus = await setup();
    bus.setTabs([]);
    bus.hasSiteAccess.mockResolvedValue(false);
    await bus.client.connect();
    expect(bus.onConnection).toHaveBeenCalledWith(
      "adapter", "disconnected", expect.stringContaining("site access"),
    );
    expect(bus.inject).not.toHaveBeenCalled();
  });

  it("bounds an unresponsive adapter handshake without replaying commands", async () => {
    vi.useFakeTimers();
    const bus = await setup();
    bus.sendToTab.mockImplementation(() => new Promise(() => undefined));
    const connecting = bus.client.connect();
    await vi.advanceTimersByTimeAsync(5000);
    await connecting;
    expect(bus.states).toHaveLength(0);
    expect(bus.onConnection).toHaveBeenCalledOnce();
    expect(bus.inject).not.toHaveBeenCalled();
  });

  it("ignores a snapshot that arrives after the selected tab closes", async () => {
    const bus = await setup();
    await bus.loadContent();
    await bus.restartRouter();
    const snapshot = await bus.sendToTab(TAB_ID, {
      scope: "amberfader-internal", type: "adapter.snapshot",
    });
    let finishSnapshot!: (value: unknown) => void;
    bus.sendToTab.mockImplementation(() => new Promise((resolve) => { finishSnapshot = resolve; }));
    const connecting = bus.client.connect();
    await vi.waitFor(() => expect(finishSnapshot).toBeTypeOf("function"));
    bus.getRouter().onTabRemoved(TAB_ID);
    finishSnapshot(snapshot);
    await connecting;
    expect(bus.states).toHaveLength(0);
    expect(bus.getRouter().selectedTabId).toBeNull();
  });
});
