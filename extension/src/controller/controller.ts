// Controller extension page. Owns the native-messaging port for as long as
// this document exists (a native connection's lifetime is tied to its context),
// relays framed protocol messages between the helper and the router, and runs
// the artwork fetch/normalize service. This page is created only after native
// mode is enabled and is normally hidden — it must never become a second
// music client or expose arbitrary execution.
import { ArtworkService } from "./artwork";
import { PROTOCOL_VERSION } from "../protocol/types";
import type { ConnectionEventData, ProtocolMessage } from "../protocol/types";
import { validateMessage } from "../protocol/validate";


const NATIVE_HOST = "amberfader";
const statusEl = () => document.getElementById("status");

function say(text: string): void {
  const el = statusEl();
  if (el) el.textContent = text;
  console.error(`[controller] ${text}`);
}

interface NativePort {
  error?: { message?: string } | undefined;
  onMessage: { addListener(cb: (m: unknown) => void): void };
  onDisconnect: { addListener(cb: () => void): void };
  postMessage(m: unknown): void;
  disconnect(): void;
}

function main(): void {
  // Port to the router for state/assets/internal traffic.
  const routerPort = browser.runtime.connect({ name: "amberfader-controller" });
  const artwork = new ArtworkService();

  let nativePort: NativePort | null = null;
  let lastNotice: ConnectionEventData | null = null;

  const nativeStatus = (
    status: ConnectionEventData["status"], reason?: string,
    component: "helper" | "gui" = "helper",
  ) => {
    if (lastNotice?.status === status && lastNotice.component === component &&
        lastNotice.reason === reason) return;
    lastNotice = { component, status };
    if (reason) lastNotice.reason = reason.slice(0, 500);
    void browser.runtime
      .sendMessage({
        scope: "amberfader-internal",
        type: "native.status",
        notice: lastNotice,
      })
      .catch(() => undefined);
  };

  const openNative = (): void => {
    let port: NativePort;
    try {
      port = browser.runtime.connectNative(NATIVE_HOST);
      nativePort = port;
    } catch (err) {
      say(`connectNative failed: ${err instanceof Error ? err.message : "error"}`);
      nativeStatus("disconnected", "connectNative threw — native host not registered?");
      return;
    }
    say("native port open");
    nativeStatus("degraded", "Connecting to the native helper.");
    let observedHelper = false;

    port.onMessage.addListener((m: unknown) => {
      // Validate the framed protocol message before forwarding; a hostile or
      // broken helper must not inject garbage into the router.
      if (!validateMessage(m)) {
        say("dropped invalid native message");
        return;
      }
      if (!observedHelper) {
        observedHelper = true;
        nativeStatus("connected");
      }
      if (m.kind === "event" && m.event === "connection") {
        const notice = m.data as ConnectionEventData;
        if (notice.component === "gui") {
          nativeStatus(notice.status, notice.reason, "gui");
          return;
        }
      }
      void browser.runtime
        .sendMessage({
          scope: "amberfader-internal",
          type: "native.message",
          payload: m,
        })
        .then((resp: unknown) => {
          if (resp !== undefined && resp !== null && nativePort) {
            try {
              nativePort.postMessage(resp);
            } catch {
              // port went away mid-send
            }
          }
        })
        .catch(() => undefined);
    });

    port.onDisconnect.addListener(() => {
      nativePort = null;
      const reason = port.error?.message ?? "native port closed (helper exited or host terminated)";
      say("native port disconnected");
      nativeStatus("disconnected", reason);
      // No reconnect loop: the router decides whether native mode is still
      // enabled; a dead helper is a real disconnect, not a polling target.
    });
    // A Port object only proves a launch was requested. The helper's reply
    // confirms it started, even when the desktop socket is still unavailable.
    try {
      port.postMessage({
        protocolVersion: PROTOCOL_VERSION, kind: "hello", component: "controller",
        componentVersion: browser.runtime.getManifest().version,
      });
    } catch {
      nativeStatus("disconnected", port.error?.message ?? "Native helper could not be started.");
    }
  };

  routerPort.onMessage.addListener((m: unknown) => {
    if (typeof m !== "object" || m === null) return;
    const t = (m as { type?: unknown }).type;
    if (t === "native.send") {
      const payload = (m as { payload?: unknown }).payload;
      if (nativePort && validateMessage(payload)) {
        try {
          nativePort.postMessage(payload);
        } catch {
          // helper gone
        }
      }
    } else if (t === "artwork.propose") {
      const { url, artworkId, occurrenceId } = m as {
        url?: unknown;
        artworkId?: unknown;
        occurrenceId?: unknown;
      };
      if (typeof url === "string" && typeof artworkId === "string" && artworkId) {
        void artwork
          .fetchAsset({
            url,
            artworkId,
            occurrenceId: typeof occurrenceId === "string" ? occurrenceId : null,
          })
          .then((asset) => {
            if (!asset || !nativePort) return;
            const event: ProtocolMessage = {
              protocolVersion: PROTOCOL_VERSION,
              kind: "event",
              event: "asset",
              data: asset,
            };
            // Asset events go straight to the native channel — extension-page
            // clients fetch artwork themselves via their own service.
            try {
              nativePort.postMessage(event);
            } catch {
              // helper gone
            }
          });
      }
    }
  });

  openNative();
}

main();
