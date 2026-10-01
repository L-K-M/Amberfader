// Background router. Validates senders, manages selected-tab binding, routes
// protocol messages, fans out state events, and recovers session state after
// event-page unload. Contains NO site selectors — adapter owns those.
//
// Design notes (spec §3):
// - All listeners register at module top level via router.install(); state
//   needed after a restart is rebuilt from storage + a fresh adapter snapshot.
// - Sender roles: site content scripts may only push internal
//   adapter messages; extension pages may send client commands and
//   internal page traffic; everything else is rejected.
// - The binding token binds (tabId, content-document nonce). Both are checked
//   on every command; a reload or navigation invalidates the token.
import {
  BINDING_METHODS,
  PROTOCOL_VERSION,
  errResponse,
  okResponse,
} from "../protocol/types";
import type {
  ConnectionEventData,
  ErrorCode,
  EventMessage,
  PlayerState,
  ProtocolError,
  RequestMessage,
  ResponseMessage,
  TargetDescriptor,
} from "../protocol/types";
import { describeValidationError, validateMessage } from "../protocol/validate";
import { isInternalMessage } from "../protocol/internal";


const MUSIC_URL = "https://music.youtube.com/*";
const CONTENT_SCRIPT_FILE = "js/content.js";
const ADAPTER_CONNECT_DEADLINE_MS = 5000;
const ADAPTER_CONNECT_TIMEOUT = new Error("adapter connection timed out");
const SITE_ACCESS_MESSAGE = "Allow site access to music.youtube.com in the extension permissions, then reopen Amberfader.";
const STORAGE_KEYS = {
  installId: "installId",
  nativeEnabled: "nativeEnabled",
} as const;

export interface Selection {
  targetKey: string;
  tabId: number;
  documentNonce: string | null;
  bindingToken: string;
}

export interface RouterPorts {
  ui: Set<unknown>; // runtime.Port
  controller: unknown; // runtime.Port | null
}

interface ExecEnvelope {
  result: unknown;
  replayed: boolean;
}

export class Router {
  readonly sessionId = crypto.randomUUID();
  installId = "";

  private selection: Selection | null = null;
  private lastState: PlayerState | null = null;
  private readonly ports: RouterPorts = { ui: new Set(), controller: null };
  private nativeAttached = false;

  // ---- lifecycle --------------------------------------------------------

  async init(): Promise<void> {
    const stored = (await browser.storage.local.get(
      STORAGE_KEYS.installId,
    )) as Record<string, unknown>;
    if (typeof stored[STORAGE_KEYS.installId] === "string") {
      this.installId = stored[STORAGE_KEYS.installId] as string;
    } else {
      this.installId = crypto.randomUUID();
      await browser.storage.local.set({ [STORAGE_KEYS.installId]: this.installId });
    }
  }

  get selectedTabId(): number | null {
    return this.selection?.tabId ?? null;
  }

  // ---- sender classification ---------------------------------------------

  private senderIsContentScript(sender: unknown): sender is { tab: { id: number }; documentId?: string; frameId: number } {
    const url = typeof sender === "object" && sender !== null
      ? (sender as { url?: unknown }).url
      : undefined;
    return (
      typeof sender === "object" &&
      sender !== null &&
      (sender as { tab?: unknown }).tab !== undefined &&
      (sender as { frameId?: unknown }).frameId === 0 &&
      !(typeof url === "string" && url.startsWith(browser.runtime.getURL("")))
    );
  }

  // ---- internal bus ------------------------------------------------------

  // Returns a promise resolving to the internal response (or undefined when
  // the message is not ours / not reply-worthy).
  async onInternalMessage(msg: unknown, sender: unknown): Promise<unknown> {
    if (!isInternalMessage(msg)) return undefined;
    const isContent = this.senderIsContentScript(sender);

    switch (msg.type) {
      case "adapter.register": {
        if (!isContent) return undefined;
        const tabId = (sender as { tab: { id: number } }).tab.id;
        // A music tab may open after the UI, or register before the first
        // client request. Discover it without guessing between multiple tabs.
        if (!this.selection) await this.listTargets();
        if (this.selection?.tabId === tabId) {
          // New document for a selected tab: rebind to the fresh nonce.
          if (this.selection.documentNonce !== msg.documentNonce) {
            this.selection = {
              ...this.selection,
              documentNonce: msg.documentNonce,
              bindingToken: this.selection.documentNonce === null
                ? this.selection.bindingToken
                : crypto.randomUUID(),
            };
            this.lastState = null;
            this.broadcast({
              protocolVersion: PROTOCOL_VERSION,
              kind: "event",
              event: "binding",
              sessionId: this.sessionId,
              bindingToken: this.selection.bindingToken,
              data: { status: "bound" },
            });
          }
        }
        return { ok: true };
      }
      case "adapter.state": {
        if (!isContent) return undefined;
        const tabId = (sender as { tab: { id: number } }).tab.id;
        if (this.selection?.tabId !== tabId) return undefined;
        if (this.selection.documentNonce !== msg.documentNonce) return undefined;
        const stamped: PlayerState = {
          ...msg.state,
          bindingToken: this.selection.bindingToken,
        };
        this.lastState = stamped;
        this.broadcast({
          protocolVersion: PROTOCOL_VERSION,
          kind: "event",
          event: "state",
          sessionId: this.sessionId,
          bindingToken: this.selection.bindingToken,
          data: stamped,
        });
        if (typeof msg.artworkUrl === "string" && msg.artworkUrl) {
          this.broadcastInternal({
            scope: "amberfader-internal",
            type: "artwork.propose",
            url: msg.artworkUrl,
            artworkId: stamped.track?.artworkId ?? "",
            occurrenceId: stamped.track?.occurrenceId ?? null,
          });
        }
        return { ok: true };
      }
      case "adapter.notice": {
        if (!isContent) return undefined;
        const tabId = (sender as { tab: { id: number } }).tab.id;
        if (this.selection?.tabId !== tabId) return undefined;
        const data: ConnectionEventData = {
          component: "adapter",
          status: msg.notice.status,
        };
        if (msg.notice.reason !== undefined) data.reason = msg.notice.reason;
        this.broadcast({
          protocolVersion: PROTOCOL_VERSION,
          kind: "event",
          event: "connection",
          sessionId: this.sessionId,
          data,
        });
        return { ok: true };
      }
      case "controller.asset": {
        // Controller produced a normalized artwork asset; fan it out.
        // Only events may broadcast — a hello/request must not leak onward.
        if (!validateMessage(msg.payload) || msg.payload.kind !== "event") {
          return undefined;
        }
        this.broadcast(msg.payload);
        return { ok: true };
      }
      case "native.message": {
        // A framed protocol message arriving from the GUI via the controller.
        const response = await this.handleClientMessage(msg.payload);
        return response;
      }
      case "native.status": {
        if (isContent) return undefined;
        const event: EventMessage = {
          protocolVersion: PROTOCOL_VERSION,
          kind: "event",
          event: "connection",
          sessionId: this.sessionId,
          data: msg.notice,
        };
        if (!validateMessage(event)) return undefined;
        await browser.storage.local.set({ nativeConnection: msg.notice });
        this.broadcast(event);
        return { ok: true };
      }
      case "ui.command": {
        return this.handleClientMessage(msg.payload);
      }
      default:
        return undefined;
    }
  }

  // ---- client protocol ----------------------------------------------------

  async handleClientMessage(raw: unknown): Promise<ResponseMessage> {
    if (!validateMessage(raw)) {
      return errResponse(
        "unknown",
        "validation_error",
        `message failed schema validation (${describeValidationError()})`,
      );
    }
    const msg = raw;
    if (msg.kind === "hello") {
      return okResponse("hello", {
        sessionId: this.sessionId,
        installId: this.installId,
        protocolVersion: PROTOCOL_VERSION,
      });
    }
    if (msg.kind !== "request") {
      const id = "id" in msg && typeof msg.id === "string" ? msg.id : "unknown";
      return errResponse(id, "validation_error", "expected a request");
    }
    return this.dispatch(msg);
  }

  private bindingError(req: RequestMessage): ResponseMessage | null {
    if (!BINDING_METHODS.has(req.method)) return null;
    if (!this.selection) {
      return errResponse(req.id, "stale_target", "no playback tab is selected");
    }
    if (req.sessionId !== this.sessionId) {
      return errResponse(
        req.id,
        "disconnected",
        "session changed — reconnect and request a fresh snapshot",
      );
    }
    if (req.bindingToken !== this.selection.bindingToken) {
      return errResponse(req.id, "stale_target", "binding token is stale or wrong");
    }
    if (this.selection.documentNonce === null) {
      return errResponse(
        req.id,
        "stale_target",
        "adapter has not registered on the selected tab (page may need reload)",
      );
    }
    return null;
  }

  private async dispatch(req: RequestMessage): Promise<ResponseMessage> {
    const binding = this.bindingError(req);
    if (binding) return binding;

    const extra = { sessionId: this.sessionId };
    switch (req.method) {
      case "connection.ping":
        return okResponse(req.id, { pong: Date.now(), sessionId: this.sessionId }, extra);
      case "state.get": {
        const hasSiteAccess = await browser.permissions.contains({ origins: [MUSIC_URL] });
        if (!hasSiteAccess) return errResponse(req.id, "missing_permission", SITE_ACCESS_MESSAGE, extra);

        // Every client (including native) starts with state.get. Recover from
        // an existing tab rather than relying on a one-shot page-load push.
        await this.listTargets();
        if (this.selection && !this.lastState) {
          const error = await this.refreshAdapter(this.selection);
          if (error) return errResponse(req.id, error.code, error.message, extra);
        }
        return okResponse(
          req.id,
          (this.lastState as unknown as Record<string, unknown>) ?? null,
          { sessionId: this.sessionId, bindingToken: this.selection?.bindingToken },
        );
      }
      case "state.subscribe":
      case "state.unsubscribe":
        // Port lifetime is the subscription; these exist so clients on
        // transports without ports (native) can mark intent.
        return okResponse(req.id, { subscribed: req.method === "state.subscribe" }, extra);
      case "targets.list":
        return okResponse(req.id, await this.listTargets(), extra);
      case "targets.select":
        return this.selectTarget(req);
      case "browser.showPlayer":
        return this.showPlayer(req);
      case "browser.hidePlayer":
        return this.hidePlayer(req);
      default:
        return this.execOnAdapter(req);
    }
  }

  private async listTargets(): Promise<{ targets: TargetDescriptor[] }> {
    const tabs = await browser.tabs.query({ url: MUSIC_URL });
    const targets: TargetDescriptor[] = [];
    for (const tab of tabs) {
      if (tab.id === undefined) continue;
      targets.push({
        targetKey: `tab:${tab.id}`,
        label: tab.title ?? "YouTube Music",
        audible: tab.audible === true,
        selected: this.selection?.tabId === tab.id,
      });
    }
    // Auto-select only when unambiguous; never silently switch targets.
    if (!this.selection && targets.length === 1 && targets[0]) {
      this.bind(targets[0].targetKey, Number(targets[0].targetKey.slice(4)));
      targets[0].selected = true;
    }
    return { targets };
  }

  private bind(targetKey: string, tabId: number): Selection {
    const prev = this.selection;
    this.selection = {
      targetKey,
      tabId,
      // Keep the nonce only if it is the same tab; a different tab means a
      // different document entirely.
      documentNonce: prev?.tabId === tabId ? prev.documentNonce : null,
      bindingToken: crypto.randomUUID(),
    };
    this.lastState = null;
    this.broadcast({
      protocolVersion: PROTOCOL_VERSION,
      kind: "event",
      sessionId: this.sessionId,
      bindingToken: this.selection.bindingToken,
      event: "binding",
      data: { status: "bound" },
    });
    return this.selection;
  }

  private async selectTarget(req: RequestMessage): Promise<ResponseMessage> {
    const key = req.params.targetKey;
    if (typeof key !== "string" || !key.startsWith("tab:")) {
      return errResponse(req.id, "validation_error", "unknown targetKey");
    }
    const tabId = Number(key.slice(4));
    try {
      const tab = await browser.tabs.get(tabId);
      if (!tab.url?.startsWith("https://music.youtube.com")) {
        return errResponse(req.id, "stale_target", "tab no longer shows YouTube Music");
      }
    } catch {
      return errResponse(req.id, "stale_target", "tab is gone");
    }
    const selection = this.bind(key, tabId);
    const error = await this.refreshAdapter(selection);
    if (error) return errResponse(req.id, error.code, error.message, {
      sessionId: this.sessionId, bindingToken: this.selection?.bindingToken,
    });
    return okResponse(
      req.id,
      { selected: key },
      { sessionId: this.sessionId, bindingToken: this.selection?.bindingToken },
    );
  }

  private async snapshotFromTab(tabId: number): Promise<unknown> {
    const message = { scope: "amberfader-internal", type: "adapter.snapshot" };
    try {
      return await browser.tabs.sendMessage(tabId, message, { frameId: 0 });
    } catch {
      // Firefox does not inject declarative scripts into already-open tabs.
      // Attach only after the handshake fails; never reload or touch playback.
      await browser.scripting.executeScript({
        target: { tabId, frameIds: [0] },
        files: [CONTENT_SCRIPT_FILE],
      });
      return browser.tabs.sendMessage(tabId, message, { frameId: 0 });
    }
  }

  private async refreshAdapter(selection: Selection): Promise<ProtocolError | null> {
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      const snapshot = await Promise.race([
        this.snapshotFromTab(selection.tabId),
        new Promise<never>((_, reject) => {
          timer = setTimeout(() => reject(ADAPTER_CONNECT_TIMEOUT),
            ADAPTER_CONNECT_DEADLINE_MS);
        }),
      ]);
      if (this.selection?.bindingToken !== selection.bindingToken) {
        return { code: "stale_target", message: "playback target changed while connecting" };
      }
      if (!isInternalMessage(snapshot) || snapshot.type !== "adapter.state" ||
          typeof snapshot.documentNonce !== "string" || !snapshot.documentNonce ||
          !validateMessage({
            protocolVersion: PROTOCOL_VERSION, kind: "event", event: "state",
            data: { ...snapshot.state, bindingToken: this.selection.bindingToken },
          })) {
        return { code: "disconnected", message: "adapter returned an invalid snapshot" };
      }
      // Initial registration keeps the token. A newer document can therefore
      // attach while this snapshot is pending without changing that token.
      if (this.selection.documentNonce !== selection.documentNonce &&
          this.selection.documentNonce !== snapshot.documentNonce) {
        return { code: "stale_target", message: "playback document changed while connecting" };
      }
      const sender = { tab: { id: selection.tabId }, frameId: 0 };
      await this.onInternalMessage({
        scope: "amberfader-internal", type: "adapter.register",
        documentNonce: snapshot.documentNonce, capabilities: snapshot.state.capabilities,
      }, sender);
      await this.onInternalMessage(snapshot, sender);
      return null;
    } catch (error) {
      if (error === ADAPTER_CONNECT_TIMEOUT) return {
        code: "timeout",
        message: `YouTube Music did not respond within ${ADAPTER_CONNECT_DEADLINE_MS / 1000} seconds. Reload the music tab, then reopen Amberfader.`,
      };

      return {
        code: "disconnected",
        message: `Cannot connect to YouTube Music. ${SITE_ACCESS_MESSAGE} If needed, reload the music tab.`,
      };
    } finally {
      if (timer !== undefined) clearTimeout(timer);
    }
  }

  private unbind(reason: string): void {
    if (!this.selection) return;
    this.selection = null;
    this.lastState = null;
    this.broadcast({
      protocolVersion: PROTOCOL_VERSION,
      kind: "event",
      sessionId: this.sessionId,
      event: "binding",
      data: { status: "revoked", reason },
    });
    this.broadcast({
      protocolVersion: PROTOCOL_VERSION,
      kind: "event",
      sessionId: this.sessionId,
      event: "connection",
      data: { component: "target", status: "disconnected", reason },
    });
  }

  onTabRemoved(tabId: number): void {
    if (this.selection?.tabId === tabId) {
      this.unbind("playback tab closed");
    }
  }

  onTabUpdated(
    tabId: number,
    changeInfo: { url?: string | undefined },
  ): void {
    if (this.selection?.tabId !== tabId) return;
    if (
      typeof changeInfo.url === "string" &&
      !changeInfo.url.startsWith("https://music.youtube.com")
    ) {
      this.unbind("playback tab navigated away from music.youtube.com");
    }
  }

  private async execOnAdapter(req: RequestMessage): Promise<ResponseMessage> {
    const sel = this.selection;
    if (!sel || sel.documentNonce === null) {
      return errResponse(req.id, "stale_target", "no bound adapter");
    }
    let env: ExecEnvelope;
    try {
      env = (await browser.tabs.sendMessage(sel.tabId, {
        scope: "amberfader-internal",
        type: "adapter.exec",
        requestId: req.id,
        method: req.method,
        params: req.params,
        expectedNonce: sel.documentNonce,
      })) as ExecEnvelope;
    } catch (err) {
      return errResponse(
        req.id,
        "disconnected",
        `content script unreachable (${err instanceof Error ? err.message : "sendMessage failed"}); the page may need a reload`,
      );
    }
    const result = env?.result;
    if (result && typeof result === "object" && "ok" in (result)) {
      const r = result as { ok: boolean; outcome?: unknown; error?: { code?: string; message?: string } };
      if (r.ok) {
        return okResponse(
          req.id,
          (r.outcome as Record<string, unknown>) ?? {},
          { sessionId: this.sessionId, bindingToken: sel.bindingToken },
        );
      }
      const code = (r.error?.code ?? "internal_error") as ErrorCode;
      return errResponse(req.id, code, r.error?.message ?? "adapter command failed", {
        sessionId: this.sessionId,
        bindingToken: sel.bindingToken,
      });
    }
    // search.songs returns its row payload directly (not a CommandResult).
    if (req.method === "search.songs") {
      return okResponse(req.id, result as Record<string, unknown>, {
        sessionId: this.sessionId,
        bindingToken: sel.bindingToken,
      });
    }
    return errResponse(req.id, "internal_error", "unrecognized adapter result", {
      sessionId: this.sessionId,
      bindingToken: sel.bindingToken,
    });
  }

  private async selectedTab(): Promise<{ id: number; windowId?: number | undefined; hidden?: boolean | undefined } | null> {
    if (!this.selection) return null;
    try {
      const tab = await browser.tabs.get(this.selection.tabId);
      return { id: tab.id ?? this.selection.tabId, windowId: tab.windowId, hidden: tab.hidden };
    } catch {
      return null;
    }
  }

  private async showPlayer(req: RequestMessage): Promise<ResponseMessage> {
    const tab = await this.selectedTab();
    if (!tab) return errResponse(req.id, "stale_target", "playback tab is gone");
    try {
      // Unhide if hidden (requires tabHide), then activate + focus. The
      // resolved hide() call alone does not prove visibility — check ids.
      if (tab.hidden === true) {
        try {
          await browser.tabs.show([tab.id]);
        } catch {
          // Not fatal: activation still makes it reachable.
        }
      }
      await browser.tabs.update(tab.id, { active: true });
      if (typeof tab.windowId === "number") {
        await browser.windows.update(tab.windowId, { focused: true });
      }
      return okResponse(req.id, { shown: true }, { sessionId: this.sessionId });
    } catch (err) {
      return errResponse(
        req.id,
        "internal_error",
        err instanceof Error ? err.message : "showPlayer failed",
      );
    }
  }

  private async hidePlayer(req: RequestMessage): Promise<ResponseMessage> {
    const has = await browser.permissions.contains({ permissions: ["tabHide"] });
    if (!has) {
      return errResponse(
        req.id,
        "missing_permission",
        "tabHide permission has not been granted; enable hiding in the extension options",
      );
    }
    const tab = await this.selectedTab();
    if (!tab) return errResponse(req.id, "stale_target", "playback tab is gone");
    try {
      const ids = await browser.tabs.hide([tab.id]);
      if (!Array.isArray(ids) || !ids.includes(tab.id)) {
        return errResponse(
          req.id,
          "internal_error",
          "tab could not be hidden (it may be active, pinned, or sharing media); choose another active tab first",
        );
      }
      return okResponse(req.id, { hidden: true }, { sessionId: this.sessionId });
    } catch (err) {
      return errResponse(
        req.id,
        "internal_error",
        err instanceof Error ? err.message : "hidePlayer failed",
      );
    }
  }

  // ---- fan-out -------------------------------------------------------------

  subscribeUiPort(port: unknown): void {
    this.ports.ui.add(port);
    const p = port as {
      onDisconnect?: { addListener(cb: () => void): void };
      postMessage(msg: unknown): void;
    };
    p.onDisconnect?.addListener(() => this.ports.ui.delete(port));
    // Full snapshot on subscribe — clients resync from this, not from deltas.
    if (this.lastState) {
      p.postMessage({
        protocolVersion: PROTOCOL_VERSION,
        kind: "event",
        event: "state",
        sessionId: this.sessionId,
        bindingToken: this.selection?.bindingToken,
        data: this.lastState,
      });
    }
  }

  attachControllerPort(port: unknown): void {
    this.ports.controller = port;
    this.nativeAttached = true;
    const p = port as {
      onDisconnect?: { addListener(cb: () => void): void };
      onMessage?: { addListener(cb: (m: unknown) => void): void };
      postMessage(msg: unknown): void;
    };
    p.onDisconnect?.addListener(() => {
      if (this.ports.controller === port) {
        this.ports.controller = null;
        this.nativeAttached = false;
        void browser.storage.local.set({ nativeConnection: {
          component: "controller", status: "disconnected", reason: "controller page closed",
        } });
        this.broadcast({
          protocolVersion: PROTOCOL_VERSION,
          kind: "event",
          event: "connection",
          sessionId: this.sessionId,
          data: { component: "controller", status: "disconnected", reason: "controller page closed" },
        });
      }
    });
    p.onMessage?.addListener((m: unknown) => {
      void this.onInternalMessage(m, { internal: "controller" }).then((resp) => {
        if (resp !== undefined && resp !== null) {
          p.postMessage({ scope: "amberfader-internal", type: "native.send", payload: resp });
        }
      });
    });
  }

  get nativeIsAttached(): boolean {
    return this.nativeAttached;
  }

  private broadcast(msg: EventMessage): void {
    for (const port of this.ports.ui) {
      try {
        (port as { postMessage(m: unknown): void }).postMessage(msg);
      } catch {
        // dropped port; removal happens on its disconnect listener
      }
    }
    if (this.ports.controller) {
      try {
        (this.ports.controller as { postMessage(m: unknown): void }).postMessage({
          scope: "amberfader-internal",
          type: "native.send",
          payload: msg,
        });
      } catch {
        // controller just died; disconnect listener will clean up
      }
    }
  }

  // Internal (non-protocol) traffic to extension pages: artwork proposals and
  // controller status plumbing travel on the same ports.
  private broadcastInternal(msg: Record<string, unknown>): void {
    for (const port of this.ports.ui) {
      try {
        (port as { postMessage(m: unknown): void }).postMessage(msg);
      } catch {
        // dropped port
      }
    }
    if (this.ports.controller) {
      try {
        (this.ports.controller as { postMessage(m: unknown): void }).postMessage(msg);
      } catch {
        // controller just died
      }
    }
  }
}

export function installRuntime(router: Router): void {
  browser.runtime.onMessage.addListener((msg: unknown, sender: unknown) => {
    const result = router.onInternalMessage(msg, sender);
    // Returning a Promise keeps sendMessage's async response channel open.
    return result;
  });

  browser.runtime.onConnect.addListener((port: unknown) => {
    const p = port as { name?: string };
    if (p.name === "amberfader-ui") {
      router.subscribeUiPort(port);
    } else if (p.name === "amberfader-controller") {
      router.attachControllerPort(port);
    }
  });

  browser.tabs.onRemoved.addListener((tabId: number) => {
    router.onTabRemoved(tabId);
  });

  browser.tabs.onUpdated.addListener(
    (tabId: number, changeInfo: { url?: string | undefined }) => {
      router.onTabUpdated(tabId, changeInfo);
    },
  );

  // Toolbar action opens (or focuses) the detached prototype player window.
  browser.action.onClicked.addListener(() => {
    void openOrFocusPlayerWindow();
  });
}

const PLAYER_URL = "player.html";

async function openOrFocusPlayerWindow(): Promise<void> {
  const url = browser.runtime.getURL(PLAYER_URL);
  try {
    const wins = await browser.windows.getAll({ populate: true });
    for (const win of wins) {
      const tab = win.tabs?.find((t) => t.url === url);
      if (tab?.id !== undefined && win.id !== undefined) {
        await browser.tabs.update(tab.id, { active: true });
        await browser.windows.update(win.id, { focused: true });
        return;
      }
    }
  } catch {
    // fall through and create a window
  }
  await browser.windows.create({
    url,
    type: "popup",
    width: 400,
    height: 210,
  });
}
