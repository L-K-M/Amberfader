// Content script entry point for music.youtube.com (top frame only, per
// manifest). Instantiates the site adapter, wires state pushes and command
// execution to the background router, and answers probe requests.
import type { AdapterPlayerState } from "../adapter/types";
import { isInternalMessage } from "../protocol/internal";
import type { AdapterStatePush, InternalMessage } from "../protocol/internal";
import { FakeAdapter } from "../adapter/fakeAdapter";
import { YouTubeMusicAdapter } from "../adapter/youtubeMusic";
import type { SiteAdapter } from "../adapter/types";
import { runProbes } from "../probe/probe";
import { executorFor } from "./executor";
import type { CommandExecutor } from "./executor";


// Fresh per document lifetime; the router binds commands to it so a command
// issued before a reload can never execute against a different document.
const DOCUMENT_NONCE = crypto.randomUUID();
const CONTENT_CONTEXT_KEY = "__amberfaderContentStarted";

async function pickAdapter(): Promise<SiteAdapter> {
  try {
    const { devFakeAdapter } = (await browser.storage.local.get(
      "devFakeAdapter",
    )) as { devFakeAdapter?: boolean };
    if (devFakeAdapter) return new FakeAdapter();
  } catch {
    // fall through to the real adapter
  }
  return new YouTubeMusicAdapter();
}

function post(msg: InternalMessage): void {
  void browser.runtime.sendMessage(msg).catch(() => {
    // Router may be mid-restart; state pushes are best-effort by design —
    // clients resynchronize via state.get after reconnect.
  });
}

function snapshot(adapter: SiteAdapter): AdapterStatePush {
  return {
    scope: "amberfader-internal",
    type: "adapter.state",
    documentNonce: DOCUMENT_NONCE,
    state: adapter.snapshot(),
    artworkUrl: adapter.proposedArtworkUrl,
  };
}

async function startAdapter(): Promise<{ adapter: SiteAdapter; executor: CommandExecutor }> {
  const adapter = await pickAdapter();

  adapter.onState((state: AdapterPlayerState) => {
    post({
      scope: "amberfader-internal",
      type: "adapter.state",
      documentNonce: DOCUMENT_NONCE,
      state,
      artworkUrl: adapter.proposedArtworkUrl,
    });
  });
  adapter.onNotice((notice) => {
    post({
      scope: "amberfader-internal",
      type: "adapter.notice",
      documentNonce: DOCUMENT_NONCE,
      notice,
    });
  });

  const executor = executorFor(adapter);

  await adapter.start();
  return { adapter, executor };
}

async function main(): Promise<void> {
  const started = startAdapter();

  // Install the receiver synchronously. executeScript finishing does not mean
  // asynchronous storage reads or adapter startup have finished.
  browser.runtime.onMessage.addListener((msg: unknown, sender: unknown) => {
    if (!isInternalMessage(msg)) return undefined;
    const s = sender as { id?: string; tab?: unknown; url?: string };
    if (s.id !== browser.runtime.id) {
      return undefined;
    }
    // An options page opened in a tab can carry sender.tab. Allow only its
    // diagnostic probe; site content scripts cannot probe or drive a peer tab.
    if (s.tab && (msg.type !== "probe.run" ||
        !s.url?.startsWith(browser.runtime.getURL("")))) return undefined;
    switch (msg.type) {
      case "adapter.snapshot":
        return started.then(({ adapter }) => snapshot(adapter));
      case "adapter.exec": {
        const execMsg = msg;
        if (execMsg.expectedNonce !== DOCUMENT_NONCE) {
          // onMessage must answer with a Promise (or true); a raw object is
          // not a valid async response on this channel.
          return Promise.resolve({
            result: {
              ok: false,
              error: {
                code: "stale_target",
                message: "document reloaded since the command was issued",
              },
            },
            replayed: false,
          });
        }
        return started.then(({ executor }) => executor.execute(
          execMsg.requestId,
          execMsg.method,
          execMsg.params,
        ));
      }
      case "probe.run": {
        const probeMsg = msg;
        return runProbes(probeMsg.suites);
      }
      default:
        return undefined;
    }
  });

  const { adapter } = await started;

  try {
    await browser.runtime.sendMessage({
      scope: "amberfader-internal",
      type: "adapter.register",
      documentNonce: DOCUMENT_NONCE,
      capabilities: adapter.capabilities,
    });
    // Startup state may have arrived before binding. Publish again after the
    // router acknowledges registration, including for a paused player.
    post(snapshot(adapter));
  } catch {
    // A restarting router recovers through the read-only snapshot handshake.
  }
}

// Declarative and programmatic injection can race. Keep one adapter/executor
// per document so duplicate injection cannot duplicate commands or observers.
const context = globalThis as typeof globalThis & { [CONTENT_CONTEXT_KEY]?: boolean };
if (!context[CONTENT_CONTEXT_KEY]) {
  context[CONTENT_CONTEXT_KEY] = true;
  void main().catch(() => {
    post({
      scope: "amberfader-internal",
      type: "adapter.notice",
      documentNonce: DOCUMENT_NONCE,
      notice: {
        component: "adapter", status: "degraded",
        reason: "Adapter initialization failed. Reload the YouTube Music tab.",
      },
    });
  });
}
