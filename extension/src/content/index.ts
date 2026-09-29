// Content script entry point for music.youtube.com (top frame only, per
// manifest). Instantiates the site adapter, wires state pushes and command
// execution to the background router, and answers probe requests.
import type { AdapterPlayerState } from "../adapter/types";
import { isInternalMessage } from "../protocol/internal";
import { FakeAdapter } from "../adapter/fakeAdapter";
import { YouTubeMusicAdapter } from "../adapter/youtubeMusic";
import type { SiteAdapter } from "../adapter/types";
import { runProbes } from "../probe/probe";
import { CommandExecutor } from "./executor";


// Fresh per document lifetime; the router binds commands to it so a command
// issued before a reload can never execute against a different document.
const DOCUMENT_NONCE = crypto.randomUUID();

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

function post(msg: Record<string, unknown>): void {
  void browser.runtime.sendMessage(msg).catch(() => {
    // Router may be mid-restart; state pushes are best-effort by design —
    // clients resynchronize via state.get after reconnect.
  });
}

async function main(): Promise<void> {
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

  const executor = new CommandExecutor(
    adapter,
    (q) =>
      "runSearch" in adapter
        ? (adapter as YouTubeMusicAdapter | FakeAdapter).runSearch(q)
        : Promise.reject(new Error("adapter has no search")),
    (t, r) =>
      "runPlayResult" in adapter
        ? (adapter as YouTubeMusicAdapter | FakeAdapter).runPlayResult(t, r)
        : Promise.resolve({
            ok: false as const,
            error: {
              code: "unsupported_operation" as const,
              message: "adapter has no playResult",
            },
          }),
  );

  browser.runtime.onMessage.addListener((msg: unknown, sender: unknown) => {
    if (!isInternalMessage(msg)) return undefined;
    const s = sender as { id?: string; tab?: unknown };
    if (s.id !== browser.runtime.id || s.tab) {
      // Only the router's own pages/background may command the adapter.
      return undefined;
    }
    switch (msg.type) {
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
        return executor.execute(
          execMsg.requestId,
          execMsg.method,
          execMsg.params,
        );
      }
      case "probe.run": {
        const probeMsg = msg;
        return runProbes(probeMsg.suites);
      }
      default:
        return undefined;
    }
  });

  await adapter.start();

  post({
    scope: "amberfader-internal",
    type: "adapter.register",
    documentNonce: DOCUMENT_NONCE,
    capabilities: adapter.capabilities,
  });
}

void main();
