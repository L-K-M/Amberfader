// Internal extension-bus messages: router <-> content script (adapter) and
// router <-> controller <-> native helper. These are NOT the public protocol;
// the public protocol (protocol/schemas) is the contract shown to clients
// (popup UI, native GUI). Internal messages carry that protocol where a client
// is attached.
import type {
  ConnectionEventData,
  Method,
  PlayerState,
  ProtocolMessage,
  SearchSongsResult,
} from "./types";

export type InternalRole = "router" | "adapter" | "controller" | "ui" | "probe";

// Content script -> router: registration + state/event pushes.
export interface AdapterRegister {
  scope: "amberfader-internal";
  type: "adapter.register";
  documentNonce: string;
  capabilities: import("./types").Capability[];
}

// Adapter -> router. State arrives without a bindingToken; the router stamps
// the current token before fanning out to clients.
export interface AdapterStatePush {
  scope: "amberfader-internal";
  type: "adapter.state";
  documentNonce: string;
  state: Omit<PlayerState, "bindingToken">;
  // Full HTTPS image URL proposed by the adapter for the current track. This
  // stays extension-internal: clients receive the normalized thumbnail as an
  // "asset" event, never the URL (spec §6).
  artworkUrl: string | null;
}

export interface AdapterSearchResult {
  scope: "amberfader-internal";
  type: "adapter.searchResult";
  documentNonce: string;
  requestId: string;
  result: SearchSongsResult | { error: { code: string; message: string } };
}

export interface AdapterConnectionNotice {
  scope: "amberfader-internal";
  type: "adapter.notice";
  documentNonce: string;
  notice: ConnectionEventData;
}

// Router -> adapter (via tabs.sendMessage to the bound tab). expectedNonce
// must equal the content script's DOCUMENT_NONCE — a reloaded/navigated
// document rejects the command as stale_target instead of executing it
// against the wrong track.
export interface AdapterExec {
  scope: "amberfader-internal";
  type: "adapter.exec";
  requestId: string;
  method: Method;
  params: Record<string, unknown>;
  expectedNonce: string;
}

// Read-only handshake, also used after an event-page restart. The reply is an
// AdapterStatePush with the current document nonce, state and artwork source.
export interface AdapterSnapshot {
  scope: "amberfader-internal";
  type: "adapter.snapshot";
}

export interface AdapterActivate {
  scope: "amberfader-internal";
  type: "adapter.activate";
  documentNonce: string;
}

export interface ProbeRun {
  scope: "amberfader-internal";
  type: "probe.run";
  suites: string[];
}

// Controller <-> router: native port plumbing.
export interface NativeAttach {
  scope: "amberfader-internal";
  type: "native.attach";
  instanceId: string;
}

export interface NativeToRouter {
  scope: "amberfader-internal";
  type: "native.message";
  payload: ProtocolMessage;
}

export interface RouterToNative {
  scope: "amberfader-internal";
  type: "native.send";
  payload: ProtocolMessage;
}

export interface NativeStatus {
  scope: "amberfader-internal";
  type: "native.status";
  notice: ConnectionEventData;
}

// Controller -> router: a normalized artwork asset produced by the
// controller-side artwork service, fanned out to all subscribed clients.
export interface ControllerAsset {
  scope: "amberfader-internal";
  type: "controller.asset";
  payload: ProtocolMessage;
}

// Router -> UI ports and controller: the adapter proposed an artwork source;
// whichever side holds the artwork service fetches and normalizes it.
export interface ArtworkPropose {
  scope: "amberfader-internal";
  type: "artwork.propose";
  url: string;
  artworkId: string;
  occurrenceId: string | null;
}

// UI page -> router over runtime.sendMessage (commands) and a Port
// ("amberfader-ui") for subscriptions.
export interface UiCommand {
  scope: "amberfader-internal";
  type: "ui.command";
  payload: ProtocolMessage;
}

export type InternalMessage =
  | AdapterRegister
  | AdapterStatePush
  | AdapterSearchResult
  | AdapterConnectionNotice
  | AdapterExec
  | AdapterSnapshot
  | AdapterActivate
  | ProbeRun
  | NativeAttach
  | NativeToRouter
  | RouterToNative
  | NativeStatus
  | ControllerAsset
  | ArtworkPropose
  | UiCommand;

export function isInternalMessage(msg: unknown): msg is InternalMessage {
  return (
    typeof msg === "object" &&
    msg !== null &&
    (msg as { scope?: unknown }).scope === "amberfader-internal" &&
    typeof (msg as { type?: unknown }).type === "string"
  );
}
