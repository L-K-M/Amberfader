import { afterEach, expect, it, vi } from "vitest";
import { ProtocolClient } from "../../src/popup/client";
import type { PlayerState, ResponseMessage } from "../../src/protocol/types";

afterEach(() => vi.unstubAllGlobals());

async function pendingStartupSnapshot() {
  let onMessage!: (message: unknown) => void;
  let finishSnapshot!: (message: ResponseMessage) => void;
  const snapshot = new Promise<ResponseMessage>((resolve) => { finishSnapshot = resolve; });
  const sendMessage = vi.fn(async (message: { payload: { kind: string } }) =>
    message.payload.kind === "hello"
      ? { protocolVersion: 1, kind: "response", id: "hello", ok: true, result: { sessionId: "session" } }
      : snapshot);
  vi.stubGlobal("browser", { runtime: {
    sendMessage,
    connect: () => ({
      onMessage: { addListener: (listener: typeof onMessage) => { onMessage = listener; } },
      onDisconnect: { addListener: () => undefined },
    }),
  } });
  const onState = vi.fn();
  const client = new ProtocolClient({ onState });
  const connected = client.connect();
  await vi.waitFor(() => expect(sendMessage).toHaveBeenCalledTimes(2));
  return { client, connected, onState, onMessage, finishSnapshot };
}

const startupResponse = (): ResponseMessage => ({
  protocolVersion: 1, kind: "response", id: "snapshot", ok: true,
  sessionId: "session", bindingToken: "old-binding",
  result: {
    bindingToken: "old-binding", revision: 1, track: null, status: "paused", contentKind: "unknown",
    positionSeconds: 0, durationSeconds: null, volume: 1, muted: false, playbackRate: 1, capabilities: [],
  },
});

it.each(["revoked", "unbound"])("does not revive a %s startup binding from a late snapshot", async (status) => {
  const pending = await pendingStartupSnapshot();
  expect(pending.client.bindingToken).toBeNull();
  pending.onMessage({
    protocolVersion: 1, kind: "event", event: "binding", sessionId: "session", data: { status },
  });
  pending.finishSnapshot(startupResponse());
  await pending.connected;
  expect(pending.onState).not.toHaveBeenCalled();
  expect(pending.client.bindingToken).toBeNull();
});

it("learns the initial snapshot binding when no event supersedes it", async () => {
  const pending = await pendingStartupSnapshot();
  const response = startupResponse();
  pending.finishSnapshot(response);
  await pending.connected;
  expect(pending.client.bindingToken).toBe("old-binding");
  expect(pending.onState).toHaveBeenCalledExactlyOnceWith(response.ok && response.result);
});

it("does not replace a newer state event with an older resync response", async () => {
  let onMessage!: (message: unknown) => void;
  let finishSnapshot!: (message: ResponseMessage) => void;
  const snapshot = new Promise<ResponseMessage>((resolve) => { finishSnapshot = resolve; });
  const sendMessage = vi.fn(async (message: { payload: { kind: string } }) =>
    message.payload.kind === "hello"
      ? { protocolVersion: 1, kind: "response", id: "hello", ok: true, result: { sessionId: "session" } }
      : snapshot);
  vi.stubGlobal("browser", { runtime: {
    sendMessage,
    connect: () => ({
      onMessage: { addListener: (listener: typeof onMessage) => { onMessage = listener; } },
      onDisconnect: { addListener: () => undefined },
    }),
  } });
  const onState = vi.fn();
  const client = new ProtocolClient({ onState });
  const connected = client.connect();
  await vi.waitFor(() => expect(sendMessage).toHaveBeenCalledTimes(2));
  const newer: PlayerState = {
    bindingToken: "binding", revision: 2,
    track: { occurrenceId: "occ-new", providerId: "song", title: "New song", artists: [], album: null, artworkId: "new-cover" },
    status: "paused", contentKind: "track", positionSeconds: 1, durationSeconds: 100,
    volume: 1, muted: false, playbackRate: 1, capabilities: [],
  };
  onMessage({ protocolVersion: 1, kind: "event", event: "state", sessionId: "session", bindingToken: "binding", data: newer });
  finishSnapshot({
    protocolVersion: 1, kind: "response", id: "snapshot", ok: true, sessionId: "session", bindingToken: "binding",
    result: { ...newer, revision: 1, track: { ...newer.track!, occurrenceId: "occ-old", artworkId: "old-cover" } },
  });
  await connected;
  expect(onState).toHaveBeenCalledExactlyOnceWith(newer);
});
