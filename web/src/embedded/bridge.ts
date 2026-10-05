// Page side of the embedded QtWebEngine prototype. The desktop app loads
// music.youtube.com in its own QtWebEngine profile and injects this bundle
// into an isolated script world. It hosts the same site adapter and command
// executor as the Firefox content script, but talks to the Python host over a
// QWebChannel instead of the extension message bus.
//
// The host is trusted (it injected us), yet commands are still validated:
// a malformed command is dropped, and a command addressed to an earlier
// document is answered with stale_target instead of running here.
import type { AdapterPlayerState, SiteAdapter } from "../adapter/types";
import { SearchStaleError, SearchTimeoutError } from "../adapter/search";
import type { CommandExecutor } from "../content/executor";
import type { Capability, ConnectionEventData, ErrorCode, Method } from "../protocol/types";

const MAX_REQUEST_ID_LENGTH = 128;
const MAX_ERROR_MESSAGE_LENGTH = 1000;

// Only adapter-executed methods cross into the page. The host answers
// state, history and window methods itself.
export const PAGE_METHODS: ReadonlySet<Method> = new Set<Method>([
  "player.play",
  "player.pause",
  "player.previous",
  "player.next",
  "player.seek",
  "player.setVolume",
  "player.setMuted",
  "player.setLiked",
  "search.songs",
  "search.playResult",
  "search.startRadio",
]);

export interface HostCommand {
  requestId: string;
  method: Method;
  params: Record<string, unknown>;
  expectedNonce: string;
}

export type PageOutcome =
  | { ok: true; result: Record<string, unknown> }
  | { ok: false; error: { code: ErrorCode; message: string } };

export type PageMessage =
  | { type: "register"; documentNonce: string; capabilities: Capability[] }
  | {
      type: "state";
      documentNonce: string;
      state: AdapterPlayerState;
      // Internal to the host, which fetches and normalizes the image. The
      // GUI receives an asset event, never this URL.
      artworkUrl: string | null;
    }
  | { type: "notice"; documentNonce: string; notice: ConnectionEventData }
  // The document is going away (reload or navigation). Lets the host revoke
  // the binding at once instead of letting pending commands time out.
  | { type: "unload"; documentNonce: string }
  | {
      type: "reply";
      documentNonce: string;
      requestId: string;
      replayed: boolean;
      outcome: PageOutcome;
    };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function parseHostCommand(raw: string): HostCommand | null {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!isRecord(value)) return null;

  const { requestId, method, params, expectedNonce } = value;
  if (typeof requestId !== "string" || !requestId) return null;
  if (requestId.length > MAX_REQUEST_ID_LENGTH) return null;
  if (typeof method !== "string" || !PAGE_METHODS.has(method as Method)) return null;
  if (!isRecord(params)) return null;
  if (typeof expectedNonce !== "string" || !expectedNonce) return null;
  return { requestId, method: method as Method, params, expectedNonce };
}

function failure(code: ErrorCode, message: string): PageOutcome {
  return { ok: false, error: { code, message: message.slice(0, MAX_ERROR_MESSAGE_LENGTH) } };
}

// search.songs resolves to rows; every other method resolves to a
// CommandResult. Anything else is reported, never passed through.
export function outcomeFor(method: Method, result: unknown): PageOutcome {
  if (!isRecord(result)) return failure("internal_error", "Adapter returned no result");
  if (method === "search.songs") return { ok: true, result };

  if (result.ok === true) {
    return { ok: true, result: isRecord(result.outcome) ? result.outcome : {} };
  }
  if (result.ok === false && isRecord(result.error)) {
    const { code, message } = result.error;
    return failure(
      typeof code === "string" ? (code as ErrorCode) : "internal_error",
      typeof message === "string" ? message : "Adapter command failed",
    );
  }
  return failure("internal_error", "Adapter returned an unrecognized result");
}

export function outcomeForError(error: unknown): PageOutcome {
  if (error instanceof SearchTimeoutError) return failure("timeout", error.message);
  if (error instanceof SearchStaleError) return failure("stale_result", error.message);
  return failure("internal_error", "The page could not complete the command");
}

export class EmbeddedBridge {
  constructor(
    private readonly documentNonce: string,
    private readonly adapter: SiteAdapter,
    private readonly executor: CommandExecutor,
    private readonly post: (message: PageMessage) => void,
  ) {}

  // Register first: the host binds this document before it accepts state.
  // Startup state emitted before registration would be dropped as unbound,
  // so publish one snapshot after the adapter starts.
  async start(): Promise<void> {
    this.adapter.onState((state) => this.postState(state));
    this.adapter.onNotice((notice) => {
      this.post({ type: "notice", documentNonce: this.documentNonce, notice });
    });
    this.announce();
    await this.adapter.start();
    this.postState(this.adapter.snapshot());
  }

  // The back/forward cache can restore this document after an unload
  // notice. Registering the same nonce again makes the host issue a new
  // binding for it.
  reannounce(): void {
    this.announce();
    this.postState(this.adapter.snapshot());
  }

  unload(): void {
    this.post({ type: "unload", documentNonce: this.documentNonce });
  }

  async handleCommand(raw: string): Promise<void> {
    const command = parseHostCommand(raw);
    if (!command) return;

    if (command.expectedNonce !== this.documentNonce) {
      this.reply(command, false, failure(
        "stale_target", "The YouTube Music page reloaded since the command was issued",
      ));
      return;
    }

    try {
      const { result, replayed } = await this.executor.execute(
        command.requestId, command.method, command.params,
      );
      this.reply(command, replayed, outcomeFor(command.method, result));
    } catch (error) {
      this.reply(command, false, outcomeForError(error));
    }
  }

  private announce(): void {
    this.post({
      type: "register",
      documentNonce: this.documentNonce,
      capabilities: this.adapter.capabilities,
    });
  }

  private postState(state: AdapterPlayerState): void {
    this.post({
      type: "state",
      documentNonce: this.documentNonce,
      state,
      artworkUrl: this.adapter.proposedArtworkUrl,
    });
  }

  private reply(command: HostCommand, replayed: boolean, outcome: PageOutcome): void {
    this.post({
      type: "reply",
      documentNonce: this.documentNonce,
      requestId: command.requestId,
      replayed,
      outcome,
    });
  }
}
