// Bootstrap for the page bundle. The Python host prepends Qt's
// qwebchannel.js and a configuration object to this bundle, then injects the
// result into an isolated world of the top frame only. Page scripts run in
// the main world and cannot reach the channel.
import { ContinuePlaying } from "../adapter/continuePlaying";
import { FakeAdapter } from "../adapter/fakeAdapter";
import type { SiteAdapter } from "../adapter/types";
import { YouTubeMusicAdapter } from "../adapter/youtubeMusic";
import { executorFor } from "../content/executor";
import { EmbeddedBridge } from "./bridge";
import type { PageMessage } from "./bridge";

interface EmbeddedConfig {
  // "fake" drives the bridge from the scripted adapter on a local test page.
  adapter: "youtube-music" | "fake";
  // The only origin this bundle may attach to.
  origin: string;
  // Close YouTube Music's "Continue watching?" prompt and resume playback.
  continuePlaying: boolean;
}

interface HostObject {
  post(message: string): void;
  command: { connect(callback: (raw: string) => void): void };
}

interface WebChannel {
  objects: Record<string, unknown>;
}

declare const QWebChannel: new (
  transport: unknown,
  ready: (channel: WebChannel) => void,
) => unknown;
declare const qt: { webChannelTransport?: unknown } | undefined;
declare const __AMBERFADER_EMBEDDED__: EmbeddedConfig | undefined;

const HOST_OBJECT_NAME = "amberfader";
const STARTED_KEY = "__amberfaderEmbeddedStarted";

function isHostObject(value: unknown): value is HostObject {
  const host = value as Partial<HostObject> | null;
  return typeof host?.post === "function" && typeof host.command?.connect === "function";
}

function createAdapter(config: EmbeddedConfig): SiteAdapter {
  return config.adapter === "fake" ? new FakeAdapter() : new YouTubeMusicAdapter();
}

function attach(config: EmbeddedConfig, host: HostObject): void {
  const nonce = crypto.randomUUID();
  const post = (message: PageMessage): void => host.post(JSON.stringify(message));
  const adapter = createAdapter(config);
  const bridge = new EmbeddedBridge(nonce, adapter, executorFor(adapter), post);

  host.command.connect((raw) => void bridge.handleCommand(raw));
  if (config.continuePlaying) new ContinuePlaying(document).start();
  window.addEventListener("pagehide", () => bridge.unload());
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) bridge.reannounce();
  });
  void bridge.start().catch(() => {
    post({
      type: "notice",
      documentNonce: nonce,
      notice: {
        component: "adapter",
        status: "degraded",
        reason: "Adapter initialization failed. Reload YouTube Music from Show YT.",
      },
    });
  });
}

function main(): void {
  const config = typeof __AMBERFADER_EMBEDDED__ === "undefined" ? undefined : __AMBERFADER_EMBEDDED__;
  if (!config || window.top !== window || location.origin !== config.origin) return;

  const context = globalThis as typeof globalThis & { [STARTED_KEY]?: boolean };
  if (context[STARTED_KEY]) return;
  context[STARTED_KEY] = true;

  const transport = typeof qt === "undefined" ? undefined : qt.webChannelTransport;
  if (!transport) return;
  new QWebChannel(transport, (channel) => {
    const host = channel.objects[HOST_OBJECT_NAME];
    if (isHostObject(host)) attach(config, host);
  });
}

main();
