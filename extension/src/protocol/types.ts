// Protocol types. Mirrors protocol/schemas/envelope.schema.json — keep the two
// in lockstep; the shared examples in protocol/examples are the conformance
// corpus both language implementations validate against.

export const PROTOCOL_VERSION = 1;

export type PlaybackStatus =
  | "playing"
  | "paused"
  | "buffering"
  | "ended"
  | "unknown";

export type Capability =
  | "play"
  | "pause"
  | "previous"
  | "next"
  | "seek"
  | "volume"
  | "setLiked"
  | "searchSongs"
  | "playSearchResult"
  | "startRadio";

export interface TrackInfo {
  occurrenceId: string;
  providerId: string | null;
  title: string;
  artists: string[];
  album: string | null;
  artworkId: string | null;
}

export interface PlayerState {
  bindingToken: string;
  revision: number;
  track: TrackInfo | null;
  status: PlaybackStatus;
  contentKind: "track" | "advertisement" | "unknown";
  positionSeconds: number | null;
  durationSeconds: number | null;
  playbackRate: number | null;
  volume: number | null;
  muted: boolean | null;
  // Missing on older peers; null means the site exposes no reliable state.
  liked?: boolean | null;
  capabilities: Capability[];
}

export interface SearchResultRow {
  resultId: string;
  kind: "song" | "album" | "playlist" | "artist" | "video" | "other";
  title: string;
  artists: string[];
  album: string | null;
  durationSeconds: number | null;
  supported: boolean;
  radioSupported?: boolean;
  artworkId: string | null;
}

export interface SearchHistory {
  queries: string[];
  artists: string[];
}

export interface SearchSongsResult {
  searchToken: string;
  complete: boolean;
  results: SearchResultRow[];
}

export interface TargetDescriptor {
  targetKey: string;
  label: string;
  audible: boolean;
  selected: boolean;
}

export interface TargetsListResult {
  targets: TargetDescriptor[];
}

export type Method =
  | "connection.ping"
  | "state.get"
  | "state.subscribe"
  | "state.unsubscribe"
  | "targets.list"
  | "targets.select"
  | "player.play"
  | "player.pause"
  | "player.previous"
  | "player.next"
  | "player.seek"
  | "player.setVolume"
  | "player.setMuted"
  | "player.setLiked"
  | "search.songs"
  | "search.playResult"
  | "search.startRadio"
  | "search.history"
  | "search.clearHistory"
  | "browser.showPlayer"
  | "browser.hidePlayer";

// Methods that act on the bound playback tab and therefore require a live
// sessionId + bindingToken (schema enforces presence; the router enforces
// that the values match the current binding).
export const BINDING_METHODS: ReadonlySet<Method> = new Set([
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
  "browser.showPlayer",
  "browser.hidePlayer",
]);

export type ErrorCode =
  | "validation_error"
  | "unsupported_operation"
  | "timeout"
  | "pending_outcome"
  | "stale_target"
  | "stale_result"
  | "missing_permission"
  | "authentication_required"
  | "user_interaction_required"
  | "version_incompatible"
  | "disconnected"
  | "internal_error";

export interface ProtocolError {
  code: ErrorCode;
  message: string;
}

export type ComponentRole = "ui" | "helper" | "gui-instance" | "controller";

export interface HelloMessage {
  protocolVersion: typeof PROTOCOL_VERSION;
  kind: "hello";
  component: ComponentRole;
  componentVersion: string;
  instanceId?: string;
  profileId?: string;
}

export interface RequestMessage {
  protocolVersion: typeof PROTOCOL_VERSION;
  kind: "request";
  id: string;
  sessionId?: string | undefined;
  bindingToken?: string | undefined;
  method: Method;
  params: Record<string, unknown>;
}

export type ResponseMessage =
  | {
      protocolVersion: typeof PROTOCOL_VERSION;
      kind: "response";
      id: string;
      sessionId?: string | undefined;
      bindingToken?: string | undefined;
      ok: true;
      result: Record<string, unknown> | null;
    }
  | {
      protocolVersion: typeof PROTOCOL_VERSION;
      kind: "response";
      id: string;
      sessionId?: string | undefined;
      bindingToken?: string | undefined;
      ok: false;
      error: ProtocolError;
    };

export type EventName = "state" | "asset" | "connection" | "binding";

export interface AssetData {
  artworkId: string;
  occurrenceId: string | null;
  mime: "image/jpeg" | "image/png" | "image/webp";
  width: number;
  height: number;
  dataBase64: string;
}

export interface ConnectionEventData {
  component: "gui" | "controller" | "target" | "helper" | "adapter";
  status: "connected" | "disconnected" | "degraded";
  reason?: string;
}

export interface BindingEventData {
  status: "bound" | "unbound" | "revoked";
  reason?: string;
}

export interface EventMessage {
  protocolVersion: typeof PROTOCOL_VERSION;
  kind: "event";
  sessionId?: string | undefined;
  bindingToken?: string | undefined;
  event: EventName;
  data: PlayerState | AssetData | ConnectionEventData | BindingEventData;
}

export type ProtocolMessage =
  | HelloMessage
  | RequestMessage
  | ResponseMessage
  | EventMessage;

export function okResponse(
  id: string,
  result: Record<string, unknown> | null,
  extra?: { sessionId?: string | undefined; bindingToken?: string | undefined },
): ResponseMessage {
  return {
    protocolVersion: PROTOCOL_VERSION,
    kind: "response",
    id,
    ok: true,
    result,
    ...extra,
  };
}

export function errResponse(
  id: string,
  code: ErrorCode,
  message: string,
  extra?: { sessionId?: string | undefined; bindingToken?: string | undefined },
): ResponseMessage {
  return {
    protocolVersion: PROTOCOL_VERSION,
    kind: "response",
    id,
    ok: false,
    error: { code, message },
    ...extra,
  };
}

export function isFiniteNumber(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}
