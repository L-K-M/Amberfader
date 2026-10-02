// Router behavior against a fake `browser` global: sender roles, target
// selection, binding-token enforcement, document-nonce invalidation.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PROTOCOL_VERSION } from "../../src/protocol/types";
import type { RequestMessage } from "../../src/protocol/types";

interface FakeTab {
  id: number;
  url: string;
  title?: string;
  audible?: boolean;
  hidden?: boolean;
  windowId?: number;
}

class FakeBrowser {
  tabsList: FakeTab[] = [];
  sentToTab: Array<{ tabId: number; msg: unknown }> = [];
  tabSendImpl: (tabId: number, msg: unknown) => Promise<unknown> = async (_tabId, msg) => {
    if ((msg as { type: string }).type === "adapter.snapshot") {
      return {
        scope: "amberfader-internal", type: "adapter.state", documentNonce: "nonce-1",
        artworkUrl: null,
        state: {
          revision: 1, track: null, status: "paused", contentKind: "unknown",
          positionSeconds: null, durationSeconds: null, playbackRate: null,
          volume: null, muted: null, capabilities: ["play", "pause"],
        },
      };
    }
    return {
      result: { ok: true, outcome: { observedStateRevision: 1 } },
      replayed: false,
    };
  };
  storage: Record<string, unknown> = {};
  removed: Array<(tabId: number) => void> = [];
  updated: Array<(tabId: number, ci: { url?: string }) => void> = [];

  api = {
    storage: {
      local: {
        get: async (k: string) => ({ [k]: this.storage[k] }),
        set: async (o: Record<string, unknown>) => {
          Object.assign(this.storage, o);
        },
      },
    },
    tabs: {
      query: async () => this.tabsList,
      get: async (id: number) => {
        const t = this.tabsList.find((x) => x.id === id);
        if (!t) throw new Error("No tab");
        return t;
      },
      sendMessage: (tabId: number, msg: unknown) => {
        this.sentToTab.push({ tabId, msg });
        return this.tabSendImpl(tabId, msg);
      },
      update: async (id: number, props: Record<string, unknown>) => {
        const t = this.tabsList.find((x) => x.id === id);
        if (t && props.active) t.hidden = false;
        return t;
      },
      show: async (ids: number[]) => ids,
      hide: async (ids: number[]) => ids,
      onRemoved: { addListener: (cb: (id: number) => void) => this.removed.push(cb) },
      onUpdated: {
        addListener: (cb: (id: number, ci: { url?: string }) => void) =>
          this.updated.push(cb),
      },
    },
    windows: {
      update: async () => ({}),
      getAll: async () => [],
      create: async () => ({}),
    },
    permissions: {
      contains: async ({ permissions, origins }: { permissions?: string[]; origins?: string[] }) =>
        (permissions ?? []).includes("tabHide") || (origins ?? []).includes("https://music.youtube.com/*"),
      getAll: async () => ({ permissions: [], origins: [] }),
    },
    runtime: {
      onMessage: { addListener: () => undefined },
      onConnect: { addListener: () => undefined },
      getManifest: () => ({ version: "0.1.0" }),
      getURL: (p: string) => `moz-extension://fake/${p}`,
    },
    action: { onClicked: { addListener: () => undefined } },
  };
}

async function makeRouter(): Promise<{
  router: import("../../src/background/router").Router;
  fake: FakeBrowser;
}> {
  const fake = new FakeBrowser();
  (globalThis as Record<string, unknown>).browser = fake.api;
  const { Router } = await import("../../src/background/router");
  const router = new Router();
  await router.init();
  return { router, fake };
}

function req(partial: Partial<RequestMessage> & { method: RequestMessage["method"] }): RequestMessage {
  return {
    protocolVersion: PROTOCOL_VERSION,
    kind: "request",
    id: "req-t",
    params: {},
    ...partial,
  };
}

const contentSender = (tabId: number) => ({ tab: { id: tabId }, frameId: 0, documentId: "doc-1" });
const pageSender = { internal: "ui" };

describe("Router", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it("validates messages and rejects malformed ones", async () => {
    const { router } = await makeRouter();
    const resp = (await router.handleClientMessage({ kind: "wut" }));
    expect(resp.ok).toBe(false);
  });

  it("accepts native diagnostics from an extension controller tab, not site content", async () => {
    const { router, fake } = await makeRouter();
    const notice = { component: "helper", status: "disconnected", reason: "No such native application" };
    const message = { scope: "amberfader-internal", type: "native.status", notice };
    await router.onInternalMessage(message, contentSender(7));
    expect(fake.storage.nativeConnection).toBeUndefined();
    await router.onInternalMessage(message, {
      tab: { id: 20 }, frameId: 0, url: fake.api.runtime.getURL("controller.html"),
    });
    expect(fake.storage.nativeConnection).toEqual(notice);
  });

  it("lists targets and auto-selects only a single unambiguous tab", async () => {
    const { router, fake } = await makeRouter();
    fake.tabsList = [
      { id: 7, url: "https://music.youtube.com/watch?v=x", title: "YouTube Music" },
    ];
    const resp = (await router.handleClientMessage(req({ method: "targets.list" })));
    expect(resp.ok).toBe(true);
    if (!resp.ok || !resp.result) throw new Error("unreachable");
    const targets = (resp.result as { targets: { selected: boolean }[] }).targets;
    expect(targets[0]?.selected).toBe(true);
  });

  it("does not auto-select when two music tabs exist", async () => {
    const { router, fake } = await makeRouter();
    fake.tabsList = [
      { id: 7, url: "https://music.youtube.com/" },
      { id: 9, url: "https://music.youtube.com/" },
    ];
    const resp = (await router.handleClientMessage(req({ method: "targets.list" })));
    if (!resp.ok || !resp.result) throw new Error("unreachable");
    const targets = (resp.result as { targets: { selected: boolean }[] }).targets;
    expect(targets.every((t) => !t.selected)).toBe(true);
    // Commands without a binding must fail cleanly.
    const play = (await router.handleClientMessage(
      req({ method: "player.play", sessionId: "x", bindingToken: "x" }),
    ));
    expect(play.ok).toBe(false);
    if (!play.ok) expect(play.error.code).toBe("stale_target");
  });

  it("rejects binding methods without matching session/binding token", async () => {
    const { router, fake } = await makeRouter();
    fake.tabsList = [{ id: 7, url: "https://music.youtube.com/" }];
    await router.handleClientMessage(req({ method: "targets.list" }));
    const resp = (await router.handleClientMessage(
      req({ method: "player.play", sessionId: "wrong", bindingToken: "wrong" }),
    ));
    expect(resp.ok).toBe(false);
    if (!resp.ok) expect(resp.error.code).toBe("disconnected");
  });

  it("routes a bound command to the adapter with the expected nonce", async () => {
    const { router, fake } = await makeRouter();
    fake.tabsList = [{ id: 7, url: "https://music.youtube.com/" }];
    await router.handleClientMessage(req({ method: "targets.list" }));

    // Adapter registers on the tab -> binds nonce + fresh token.
    await router.onInternalMessage(
      {
        scope: "amberfader-internal",
        type: "adapter.register",
        documentNonce: "nonce-1",
        capabilities: ["play", "pause"],
      },
      contentSender(7),
    );

    // Learn the issued binding token via a state push.
    await router.onInternalMessage(
      {
        scope: "amberfader-internal",
        type: "adapter.state",
        documentNonce: "nonce-1",
        artworkUrl: null,
        state: {
          revision: 1,
          track: null,
          status: "paused",
          contentKind: "unknown",
          positionSeconds: null,
          durationSeconds: null,
          playbackRate: null,
          volume: null,
          muted: null,
          capabilities: ["play"],
        },
      },
      contentSender(7),
    );

    const stateResp = (await router.handleClientMessage(
      req({ method: "state.get", sessionId: router.sessionId }),
    ));
    expect(stateResp.ok).toBe(true);
    const token = (stateResp as { bindingToken?: string }).bindingToken!;
    expect(token).toBeTruthy();

    const play = (await router.handleClientMessage(
      req({
        method: "player.play",
        sessionId: router.sessionId,
        bindingToken: token,
      }),
    ));
    expect(play.ok).toBe(true);
    expect(fake.sentToTab).toHaveLength(1);
    const sent = fake.sentToTab[0]!;
    expect(sent.tabId).toBe(7);
    expect((sent.msg as { expectedNonce: string }).expectedNonce).toBe("nonce-1");
  });

  it("invalidates the binding when the playback tab navigates away", async () => {
    const { router, fake } = await makeRouter();
    fake.tabsList = [{ id: 7, url: "https://music.youtube.com/" }];
    await router.handleClientMessage(req({ method: "targets.list" }));
    router.onTabUpdated(7, { url: "https://example.com/" });
    const resp = (await router.handleClientMessage(
      req({ method: "player.play", sessionId: router.sessionId, bindingToken: "x" }),
    ));
    expect(resp.ok).toBe(false);
    if (!resp.ok) expect(resp.error.code).toBe("stale_target");
  });

  it("ignores state pushes from the wrong tab and non-content senders", async () => {
    const { router, fake } = await makeRouter();
    fake.tabsList = [
      { id: 7, url: "https://music.youtube.com/" },
      { id: 9, url: "https://music.youtube.com/" },
    ];
    await router.handleClientMessage(
      req({ method: "targets.select", params: { targetKey: "tab:7" } }),
    );
    await router.onInternalMessage(
      {
        scope: "amberfader-internal",
        type: "adapter.state",
        documentNonce: "n9",
        artworkUrl: null,
        state: { revision: 1, track: null, status: "playing", contentKind: "track", positionSeconds: 1, durationSeconds: 1, playbackRate: 1, volume: 1, muted: false, capabilities: [] },
      },
      contentSender(9),
    );
    const resp = (await router.handleClientMessage(req({ method: "state.get" })));
    expect(resp.ok).toBe(true);
    expect((resp as { result: unknown }).result).toMatchObject({
      track: null, status: "paused", contentKind: "unknown",
    }); // Only the selected adapter's snapshot, never the other tab's push.
    void pageSender;
  });

  it("shares persistent recent queries with native and UI clients without a bound tab", async () => {
    const { router, fake } = await makeRouter();
    fake.storage.searchHistory = { queries: ["previous query"], artists: ["previous artist"] };
    const message = {
      scope: "amberfader-internal", type: "native.message",
      payload: req({ method: "search.history" }),
    };
    expect(await router.onInternalMessage(message, pageSender)).toMatchObject({
      ok: true, result: { queries: ["previous query"], artists: ["previous artist"] },
    });
    expect(await router.handleClientMessage(req({ method: "search.clearHistory" }))).toMatchObject({
      ok: true, result: { queries: [], artists: [] },
    });
    expect(fake.storage.searchHistory).toEqual({ queries: [], artists: [] });
    expect(fake.sentToTab).toEqual([]);
  });

  it("records artists only once per playing occurrence on the selected document", async () => {
    const { router, fake } = await makeRouter();
    fake.tabsList = [{ id: 7, url: "https://music.youtube.com/" }];
    await router.handleClientMessage(req({ method: "targets.select", params: { targetKey: "tab:7" } }));
    const message = {
      scope: "amberfader-internal", type: "adapter.state", documentNonce: "nonce-1", artworkUrl: null,
      state: {
        revision: 2, status: "paused", contentKind: "track", positionSeconds: 1,
        durationSeconds: 200, playbackRate: 1, volume: 1, muted: false, capabilities: [],
        track: { occurrenceId: "occ-1", providerId: "song", title: "Song", artists: ["Artist"], album: null, artworkId: null },
      },
    };
    await router.onInternalMessage(message, contentSender(7));
    expect(await router.handleClientMessage(req({ method: "search.history" }))).toMatchObject({
      result: { artists: [] },
    });
    message.state.status = "playing";
    await router.onInternalMessage(message, contentSender(9));
    expect(await router.handleClientMessage(req({ method: "search.history" }))).toMatchObject({
      result: { artists: [] },
    });
    await router.onInternalMessage(message, contentSender(7));
    expect(await router.handleClientMessage(req({ method: "search.history" }))).toMatchObject({
      result: { artists: ["Artist"] },
    });
    await router.handleClientMessage(req({ method: "search.clearHistory" }));
    await router.onInternalMessage(message, contentSender(7));
    expect(await router.handleClientMessage(req({ method: "search.history" }))).toMatchObject({
      result: { artists: [] },
    });
    message.state.track.occurrenceId = "occ-2";
    message.state.contentKind = "advertisement";
    await router.onInternalMessage(message, contentSender(7));
    expect(await router.handleClientMessage(req({ method: "search.history" }))).toMatchObject({
      result: { artists: [] },
    });
  });

  it("records successful searches but rejects malformed result payloads", async () => {
    const { router, fake } = await makeRouter();
    fake.tabsList = [{ id: 7, url: "https://music.youtube.com/" }];
    const selected = await router.handleClientMessage(req({ method: "targets.select", params: { targetKey: "tab:7" } }));
    const request = req({ method: "search.songs", sessionId: router.sessionId,
      bindingToken: selected.bindingToken, params: { query: "Example" } });
    fake.tabSendImpl = async () => ({ result: { searchToken: "s1", complete: true, results: [] }, replayed: false });
    expect(await router.handleClientMessage(request)).toMatchObject({ ok: true });
    expect(await router.handleClientMessage(req({ method: "search.history" }))).toMatchObject({
      result: { queries: ["Example"] },
    });
    fake.tabSendImpl = async () => ({ result: { results: "invalid" }, replayed: false });
    request.params.query = "Invalid";
    expect(await router.handleClientMessage(request)).toMatchObject({ ok: false });
    expect(await router.handleClientMessage(req({ method: "search.history" }))).toMatchObject({
      result: { queries: ["Example"] },
    });
  });
});
