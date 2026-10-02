// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

beforeEach(() => {
  vi.resetModules();
  document.documentElement.innerHTML = readFileSync(
    join(__dirname, "../../src/options/options.html"), "utf8",
  );
  vi.stubGlobal("browser", {
    permissions: {
      contains: async () => true,
      getAll: async () => ({ origins: [], permissions: [] }),
    },
    storage: {
      local: { get: async () => ({}) },
      onChanged: { addListener: () => undefined },
    },
    runtime: {
      getManifest: () => ({ version: "test" }),
      sendMessage: async () => ({ result: { targets: [{ targetKey: "tab:7", selected: true }] } }),
    },
    tabs: { sendMessage: async () => ({ probeVersion: 1, suites: { artwork: { hosts: ["music.youtube.com"] } } }) },
  });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("starts the report download with a connected link and a live object URL", async () => {
  vi.useFakeTimers();
  URL.createObjectURL = vi.fn(() => "blob:probe-report");
  URL.revokeObjectURL = vi.fn();
  let connected = false;
  let targetUrl: string | null = null;
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    connected = this.isConnected;
    targetUrl = this.href;
  });
  await import("../../src/options/options");
  document.getElementById("btn-probes")!.click();
  const download = document.getElementById("btn-probes-dl") as HTMLButtonElement;
  await vi.waitFor(() => expect(download.disabled).toBe(false));
  download.click();
  expect(click).toHaveBeenCalledOnce();
  expect(connected).toBe(true);
  expect(targetUrl).toBe("blob:probe-report");
  expect(URL.revokeObjectURL).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(60000);
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:probe-report");
});

it("shows a native-host failure even while native mode is enabled", async () => {
  browser.storage.local.get = async () => ({
    nativeEnabled: true,
    nativeConnection: {
      component: "helper", status: "disconnected", reason: "No such native application amberfader",
    },
  });
  await import("../../src/options/options");
  await vi.waitFor(() => expect(document.getElementById("native-status")!.textContent)
    .toContain("No such native application amberfader"));
});

it("does not enable report download when the content script returns no report", async () => {
  browser.tabs.sendMessage = async () => undefined;
  await import("../../src/options/options");
  document.getElementById("btn-probes")!.click();
  await vi.waitFor(() => expect(document.getElementById("probe-out")!.textContent)
    .toContain("did not return a report"));
  expect((document.getElementById("btn-probes-dl") as HTMLButtonElement).disabled).toBe(true);
});
