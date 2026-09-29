// Controller extension page. Owns the native-messaging port for as long as
// this document exists (a native connection's lifetime is tied to its context),
// relays framed protocol messages between the helper and the router, and runs
// the artwork fetch/normalize service. This page is created only after native
// mode is enabled and is normally hidden — it must never become a second
// music client or expose arbitrary execution.
import { ArtworkService } from "./artwork";
import { PROTOCOL_VERSION } from "../protocol/types";
import type { ProtocolMessage } from "../protocol/types";
import { validateMessage } from "../protocol/validate";


const NATIVE_HOST = "amberfader";
const statusEl = () => document.getElementById("status");

function say(text: string): void {
  const el = statusEl();
  if (el) el.textContent = text;
  console.error(`[controller] ${text}`);
}

interface NativePort {
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

  const nativeStatus = (status: "connected" | "disconnected" | "degraded", reason?: string) => {
    void browser.runtime
      .sendMessage({
        scope: "amberfader-internal",
        type: "native.status",
        notice: { component: "helper", status, reason },
      })
      .catch(() => undefined);
  };

  const openNative = (): void => {
    try {
      nativePort = browser.runtime.connectNative(NATIVE_HOST);
    } catch (err) {
      say(`connectNative failed: ${err instanceof Error ? err.message : "error"}`);
      nativeStatus("disconnected", "connectNative threw — native host not registered?");
      return;
    }
    say("native port open");
    nativeStatus("connected");

    nativePort.onMessage.addListener((m: unknown) => {
      // Validate the framed protocol message before forwarding; a hostile or
      // broken helper must not inject garbage into the router.
      if (!validateMessage(m)) {
        say("dropped invalid native message");
        return;
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

    nativePort.onDisconnect.addListener(() => {
      nativePort = null;
      say("native port disconnected");
      nativeStatus("disconnected", "native port closed (helper exited or host terminated)");
      // No reconnect loop: the router decides whether native mode is still
      // enabled; a dead helper is a real disconnect, not a polling target.
    });
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
