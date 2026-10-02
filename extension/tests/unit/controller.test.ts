// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { PROTOCOL_VERSION } from "../../src/protocol/types";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("reports native readiness only after a message and preserves disconnect details", async () => {
  vi.resetModules();
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  let onNativeMessage!: (message: unknown) => void;
  let onNativeDisconnect!: () => void;
  const port = {
    error: { message: "No such native application amberfader" },
    onMessage: { addListener: (listener: typeof onNativeMessage) => { onNativeMessage = listener; } },
    onDisconnect: { addListener: (listener: typeof onNativeDisconnect) => { onNativeDisconnect = listener; } },
    postMessage: vi.fn(),
  };
  const sendMessage = vi.fn(async (_message: unknown) => undefined);
  vi.stubGlobal("browser", {
    runtime: {
      connect: () => ({ onMessage: { addListener: () => undefined } }),
      connectNative: () => port,
      getManifest: () => ({ version: "test" }),
      sendMessage,
    },
  });
  await import("../../src/controller/controller");
  expect(sendMessage.mock.calls[0]?.[0]).toMatchObject({
    type: "native.status", notice: { status: "degraded" },
  });
  expect(port.postMessage).toHaveBeenCalledWith({
    protocolVersion: PROTOCOL_VERSION, kind: "hello", component: "controller",
    componentVersion: "test",
  });
  onNativeMessage({
    protocolVersion: PROTOCOL_VERSION, kind: "hello", component: "helper", componentVersion: "test",
  });
  expect(sendMessage.mock.calls.some(([message]) =>
    (message as { notice?: { status: string } }).notice?.status === "connected")).toBe(true);
  onNativeDisconnect();
  expect(sendMessage.mock.calls.at(-1)?.[0]).toMatchObject({
    type: "native.status",
    notice: { status: "disconnected", reason: "No such native application amberfader" },
  });
});
