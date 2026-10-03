import { afterEach, expect, it, vi } from "vitest";
import { ProtocolClient } from "../../src/popup/client";
import type { PlayerState, ResponseMessage } from "../../src/protocol/types";

afterEach(() => vi.unstubAllGlobals());

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
