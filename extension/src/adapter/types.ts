// Adapter boundary. The adapter is the only component allowed to contain
// YouTube Music DOM knowledge. Everything above it sees normalized state and
// validated commands.
import type {
  Capability,
  Method,
  PlayerState,
  SearchSongsResult,
} from "../protocol/types";

export type AdapterPlayerState = Omit<PlayerState, "bindingToken">;

export interface CommandOutcome {
  // Set when the adapter observed the requested change (or already-state).
  observedStateRevision: number;
}

export interface CommandError {
  code:
    | "unsupported_operation"
    | "timeout"
    | "pending_outcome"
    | "stale_target"
    | "stale_result"
    | "authentication_required"
    | "user_interaction_required"
    | "internal_error";
  message: string;
}

export type CommandResult =
  | { ok: true; outcome: CommandOutcome }
  | { ok: false; error: CommandError };

export interface SearchHandle {
  token: string;
  promise: Promise<SearchSongsResult>;
  cancel(reason?: string): void;
}

export interface SiteAdapter {
  readonly capabilities: Capability[];
  // Full HTTPS URL the adapter proposes for current-track artwork. Internal
  // only — clients get the normalized asset, never this URL.
  readonly proposedArtworkUrl: string | null;
  // Monotonic state pushes. The adapter emits a snapshot after every observed
  // change; position samples arrive ~1 Hz while playing.
  onState(cb: (state: AdapterPlayerState) => void): void;
  onNotice(
    cb: (notice: {
      component: "adapter";
      status: "connected" | "disconnected" | "degraded";
      reason?: string;
    }) => void,
  ): void;
  snapshot(): AdapterPlayerState;
  exec(
    requestId: string,
    method: Method,
    params: Record<string, unknown>,
  ): Promise<CommandResult>;
  start(): Promise<void>;
  stop(): void;
}
