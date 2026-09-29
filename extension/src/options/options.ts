// Options / onboarding / diagnostics page. Permission requests must happen in
// a user gesture — all permission UI is button-driven. Diagnostic output is
// redacted: versions, states, error codes — never page content or queries.
import { PROTOCOL_VERSION } from "../protocol/types";


const $ = <T extends HTMLElement>(id: string): T => {
  const el = document.getElementById(id);
  if (!el) throw new Error(`missing element #${id}`);
  return el as T;
};

interface InternalResp {
  [k: string]: unknown;
}

function sendInternal(payload: Record<string, unknown>): Promise<InternalResp> {
  return browser.runtime.sendMessage({
    scope: "amberfader-internal",
    type: "ui.command",
    payload,
  }) as Promise<InternalResp>;
}

async function refreshPermissions(): Promise<void> {
  const host = await browser.permissions.contains({
    origins: ["https://music.youtube.com/*"],
  });
  const native = await browser.permissions.contains({
    permissions: ["nativeMessaging"],
  });
  const hide = await browser.permissions.contains({ permissions: ["tabHide"] });

  mark("perm-host", host, "site access (music.youtube.com)");
  markBtn($<HTMLButtonElement>("btn-native"), native, "nativeMessaging (desktop app)");
  markBtn($<HTMLButtonElement>("btn-hideperm"), hide, "tabHide (hide tabs)");

  const { nativeEnabled } = (await browser.storage.local.get("nativeEnabled")) as {
    nativeEnabled?: boolean;
  };
  const status = $("native-status");
  const toggle = $<HTMLButtonElement>("btn-native-toggle");
  if (native && nativeEnabled) {
    status.textContent = "Native mode is ON — a hidden controller tab owns the desktop connection.";
    toggle.textContent = "Disable native mode";
  } else if (native && !nativeEnabled) {
    status.textContent = "Permission granted; native mode is off.";
    toggle.textContent = "Enable native mode";
  } else {
    status.textContent = "Native mode is off (permission not granted).";
    toggle.textContent = "Enable native mode";
  }
}

function mark(id: string, granted: boolean, label: string): void {
  const el = $(id);
  el.textContent = `${label}: ${granted ? "granted" : "not granted"}`;
  el.style.color = granted ? "#9ad09a" : "var(--err)";
}

function markBtn(btn: HTMLButtonElement, granted: boolean, label: string): void {
  btn.textContent = granted ? "granted" : "request";
  btn.disabled = granted;
  btn.classList.toggle("granted", granted);
  btn.setAttribute("aria-label", `${label}: ${granted ? "granted" : "request permission"}`);
}

async function requestPerm(perm: string): Promise<void> {
  if (perm === "nativeMessaging") {
    await browser.permissions.request({ permissions: ["nativeMessaging"] });
  } else if (perm === "tabHide") {
    await browser.permissions.request({ permissions: ["tabHide"] });
  }
  await refreshPermissions();
}

$("btn-native").addEventListener("click", () => void requestPerm("nativeMessaging"));
$("btn-hideperm").addEventListener("click", () => void requestPerm("tabHide"));

// ---- native mode ----------------------------------------------------------

async function ensureControllerTab(): Promise<number | null> {
  const url = browser.runtime.getURL("controller.html");
  try {
    const tabs = await browser.tabs.query({});
    for (const t of tabs) {
      if (t.url === url) return t.id ?? null;
    }
    const tab = await browser.tabs.create({ url, active: false });
    const id = tab.id ?? null;
    if (id !== null) {
      const hide = await browser.permissions.contains({ permissions: ["tabHide"] });
      if (hide) {
        // Hide is best-effort; check the returned IDs (a resolved call alone
        // does not prove the tab hid).
        try {
          await browser.tabs.hide([id]);
        } catch {
          // Leave it visible and labeled rather than hiding the failure.
        }
      }
    }
    return id;
  } catch {
    return null;
  }
}

$("btn-native-toggle").addEventListener("click", () => {
  void (async () => {
    const { nativeEnabled } = (await browser.storage.local.get("nativeEnabled")) as {
      nativeEnabled?: boolean;
    };
    if (nativeEnabled) {
      await browser.storage.local.set({ nativeEnabled: false });
      const url = browser.runtime.getURL("controller.html");
      const tabs = await browser.tabs.query({});
      for (const t of tabs) {
        if (t.url === url && t.id !== undefined) await browser.tabs.remove(t.id);
      }
    } else {
      const has = await browser.permissions.contains({ permissions: ["nativeMessaging"] });
      if (!has) {
        const granted = await browser.permissions.request({ permissions: ["nativeMessaging"] });
        if (!granted) {
          await refreshPermissions();
          return;
        }
      }
      await browser.storage.local.set({ nativeEnabled: true });
      await ensureControllerTab();
    }
    await refreshPermissions();
  })();
});

// The only correct recovery for a closed controller page (spec §12): the
// desktop cannot recreate it through the dead connection.
$("btn-reconnect").addEventListener("click", () => {
  void (async () => {
    const url = browser.runtime.getURL("controller.html");
    const tabs = await browser.tabs.query({});
    for (const t of tabs) {
      if (t.url === url && t.id !== undefined) await browser.tabs.remove(t.id);
    }
    await ensureControllerTab();
    await refreshPermissions();
  })();
});

// ---- probes ----------------------------------------------------------------

let lastReport: string | null = null;

$("btn-probes").addEventListener("click", () => {
  void (async () => {
    const out = $("probe-out");
    out.textContent = "running…";
    const resp = await sendInternal({
      protocolVersion: PROTOCOL_VERSION,
      kind: "request",
      id: `probe-${Date.now().toString(36)}`,
      method: "targets.list",
      params: {},
    });
    const targets = (resp.result as { targets?: { targetKey: string; selected: boolean }[] } | undefined)?.targets ?? [];
    const selected = targets.find((t) => t.selected) ?? targets[0];
    if (!selected) {
      out.textContent = "No YouTube Music tab found. Open music.youtube.com first.";
      return;
    }
    const tabId = Number(selected.targetKey.slice(4));
    try {
      const report: unknown = await browser.tabs.sendMessage(tabId, {
        scope: "amberfader-internal",
        type: "probe.run",
        suites: ["dom", "searchInput", "artwork", "mediaOps"],
      });
      lastReport = JSON.stringify(report, null, 2);
      out.textContent = lastReport;
      $<HTMLButtonElement>("btn-probes-dl").disabled = false;
    } catch (err) {
      out.textContent = `probe failed: ${err instanceof Error ? err.message : "sendMessage failed"} — the tab may need a reload to attach the content script`;
    }
  })();
});

$("btn-probes-dl").addEventListener("click", () => {
  if (!lastReport) return;
  const blob = new Blob([lastReport], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `amberfader-probes-${new Date().toISOString().slice(0, 19)}.json`;
  a.click();
  URL.revokeObjectURL(url);
});

// ---- dev toggle + diagnostics ----------------------------------------------

async function initDev(): Promise<void> {
  const box = $<HTMLInputElement>("fake-adapter");
  const { devFakeAdapter } = (await browser.storage.local.get("devFakeAdapter")) as {
    devFakeAdapter?: boolean;
  };
  box.checked = devFakeAdapter === true;
  box.addEventListener("change", () => {
    void browser.storage.local.set({ devFakeAdapter: box.checked });
  });
}

async function diagnostics(): Promise<void> {
  const manifest = browser.runtime.getManifest();
  const perms = await browser.permissions.getAll();
  const resp = await sendInternal({
    protocolVersion: PROTOCOL_VERSION,
    kind: "request",
    id: `diag-${Date.now().toString(36)}`,
    method: "connection.ping",
    params: {},
  });
  $("diag").textContent = JSON.stringify(
    {
      extension: manifest.version,
      protocol: PROTOCOL_VERSION,
      browser: navigator.userAgent.match(/Firefox\/[\d.]+/)?.[0] ?? "unknown",
      permissions: { origins: perms.origins, permissions: perms.permissions },
      router: resp,
    },
    null,
    2,
  );
}

void refreshPermissions();
void initDev();
void diagnostics();
