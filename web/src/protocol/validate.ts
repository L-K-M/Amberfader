// Schema validation. The envelope schema is pre-compiled to plain code by
// scripts/gen-validators.mjs — MV3 extension pages run under a CSP that
// forbids the eval/Function codegen ajv performs at runtime.
import type { ErrorObject } from "ajv";
import {
  validateMessage as vMessage,
  validatePlayerState as vPlayerState,
  validateSearchSongsResult as vSearchSongsResult,
  validateSearchHistory as vSearchHistory,
  validateTargetsListResult as vTargetsListResult,
} from "./validators.gen.js";
import type {
  PlayerState,
  ProtocolMessage,
  SearchSongsResult,
  SearchHistory,
  TargetsListResult,
} from "./types";

// The generated validators carry their schema's error objects on `.errors`
// after a failed call, matching the ajv contract.
type Validator<T> = ((data: unknown) => data is T) & {
  errors?: ErrorObject[] | null;
};

let lastErrors: ErrorObject[] | null | undefined = null;

export function validateMessage(msg: unknown): msg is ProtocolMessage {
  const ok = (vMessage as Validator<ProtocolMessage>)(msg);
  lastErrors = ok ? null : vMessage.errors;
  return ok;
}

export function validatePlayerState(data: unknown): data is PlayerState {
  return (vPlayerState as Validator<PlayerState>)(data);
}

export function validateSearchSongsResult(
  data: unknown,
): data is SearchSongsResult {
  return (vSearchSongsResult as Validator<SearchSongsResult>)(data);
}

export function validateTargetsListResult(
  data: unknown,
): data is TargetsListResult {
  return (vTargetsListResult as Validator<TargetsListResult>)(data);
}

export function validateSearchHistory(data: unknown): data is SearchHistory {
  return (vSearchHistory as Validator<SearchHistory>)(data);
}

// Validation failure description for log lines — never log the message body
// itself (it can carry page-derived text).
export function describeValidationError(): string {
  const err = lastErrors?.[0];
  if (!err) return "unknown schema error";
  return `${err.instancePath || "/"} ${err.message ?? "invalid"}`;
}
