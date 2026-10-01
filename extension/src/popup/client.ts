// Shared protocol client for extension pages (player window, search window,
// options). Commands go over runtime.sendMessage; events arrive on a
// reconnecting "amberfader-ui" port. Port lifetime does not pin the event
// page, so on reconnect we always take a fresh state.get snapshot.
import { PROTOCOL_VERSION } from "../protocol/types";
import type {
  ErrorCode,
  EventMessage,
  Method,
  PlayerState,
  ResponseMessage,
} from "../protocol/types";


export interface ClientEvents {
  onState?(s: PlayerState): void;
  onBinding?(status: string, reason?: string): void;
  onConnection?(component: string, status: string, reason?: string): void;
  onDisconnected?(): void;
}

export class ProtocolClient {
  sessionId: string | null = null;
  bindingToken: string | null = null;
  private port: {
    onMessage: { addListener(cb: (m: unknown) => void): void };
    onDisconnect: { addListener(cb: () => void): void };
  } | null = null;
  private reqSeq = 0;
  private readonly events: ClientEvents;
  private reconnectTimer: number | null = null;

  constructor(events: ClientEvents) {
    this.events = events;
  }

  async connect(): Promise<void> {
    const hello = await this.rawSend({
      protocolVersion: PROTOCOL_VERSION,
      kind: "hello",
      component: "ui",
      componentVersion: "0.1.0",
    });
    const session = (hello as { result?: { sessionId?: unknown } }).result?.sessionId;
    if (typeof session === "string") this.sessionId = session;
    this.openPort();
    await this.resync();
  }

  private openPort(): void {
    let port: {
      onMessage: { addListener(cb: (m: unknown) => void): void };
      onDisconnect: { addListener(cb: () => void): void };
    };
    try {
      port = browser.runtime.connect({ name: "amberfader-ui" });
    } catch {
      this.port = null;
      this.events.onDisconnected?.();
      return;
    }
    this.port = port;
    port.onMessage.addListener((m: unknown) => this.onPortMessage(m));
    port.onDisconnect.addListener(() => {
      this.port = null;
      this.events.onDisconnected?.();
      // Wake the event page and take a fresh snapshot; an old port is never
      // assumed to carry state across a router restart.
      if (this.reconnectTimer !== null) window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = window.setTimeout(() => {
        void this.connect();
      }, 1000);
    });
  }

  private onPortMessage(m: unknown): void {
    if (typeof m !== "object" || m === null) return;
    const kind = (m as { kind?: unknown }).kind;
    if (kind === "event") {
      const ev = m as EventMessage;
      if (typeof ev.sessionId === "string") this.sessionId = ev.sessionId;
      if (typeof ev.bindingToken === "string") this.bindingToken = ev.bindingToken;
      if (ev.event === "state") {
        this.events.onState?.(ev.data as PlayerState);
      } else if (ev.event === "binding") {
        const d = ev.data as { status: string; reason?: string };
        if (d.status === "revoked" || d.status === "unbound") this.bindingToken = null;
        this.events.onBinding?.(d.status, d.reason);
      } else if (ev.event === "connection") {
        const d = ev.data as { component: string; status: string; reason?: string };
        this.events.onConnection?.(d.component, d.status, d.reason);
      }
    } else if (
      (m as { scope?: unknown }).scope === "amberfader-internal" &&
      (m as { type?: unknown }).type === "artwork.propose"
    ) {
      // Handled by the page's own artwork service (player.ts).
      const { url, artworkId, occurrenceId } = m as {
        url?: unknown;
        artworkId?: unknown;
        occurrenceId?: unknown;
      };
      if (typeof url === "string" && typeof artworkId === "string") {
        this.onArtworkPropose?.({
          url,
          artworkId,
          occurrenceId: typeof occurrenceId === "string" ? occurrenceId : null,
        });
      }
    }
  }

  onArtworkPropose?: (req: {
    url: string;
    artworkId: string;
    occurrenceId: string | null;
  }) => void;

  private async resync(): Promise<void> {
    const resp = await this.request("state.get", {});
    if (resp.ok && resp.result) {
      this.events.onState?.(resp.result as unknown as PlayerState);
    } else if (!resp.ok && resp.error.code !== "stale_target") {
      this.events.onConnection?.("adapter", "disconnected", resp.error.message);
    }
  }

  async request(
    method: Method,
    params: Record<string, unknown>,
  ): Promise<ResponseMessage> {
    const id = `ui-${(++this.reqSeq).toString(36)}-${Date.now().toString(36)}`;
    const needsBinding = method.startsWith("player.") || method.startsWith("search.") || method.startsWith("browser.");
    const req: Record<string, unknown> = {
      protocolVersion: PROTOCOL_VERSION,
      kind: "request",
      id,
      method,
      params,
    };
    if (this.sessionId) req.sessionId = this.sessionId;
    if (needsBinding && this.bindingToken) req.bindingToken = this.bindingToken;
    const resp = await this.rawSend(req);
    // Learn binding tokens from responses too (select, state.get).
    const bt = (resp as { bindingToken?: unknown }).bindingToken;
    if (typeof bt === "string") this.bindingToken = bt;
    return resp;
  }

  private async rawSend(payload: Record<string, unknown>): Promise<ResponseMessage> {
    try {
      const resp = (await browser.runtime.sendMessage({
        scope: "amberfader-internal",
        type: "ui.command",
        payload,
      })) as ResponseMessage | undefined;
      if (!resp) {
        return {
          protocolVersion: PROTOCOL_VERSION,
          kind: "response",
          id: typeof payload.id === "string" ? payload.id : "unknown",
          ok: false,
          error: { code: "disconnected" satisfies ErrorCode, message: "no response from router" },
        };
      }
      return resp;
    } catch (err) {
      return {
        protocolVersion: PROTOCOL_VERSION,
        kind: "response",
        id: typeof payload.id === "string" ? payload.id : "unknown",
        ok: false,
        error: {
          code: "disconnected" satisfies ErrorCode,
          message: err instanceof Error ? err.message : "sendMessage failed",
        },
      };
    }
  }

  disconnect(): void {
    if (this.reconnectTimer !== null) window.clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
  }
}
