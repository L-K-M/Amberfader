// Phase 0 probes. Run inside the YouTube Music content script on demand from
// the options page. Output is SANITIZED: element structure, attribute names,
// and hostnames only — never page/user text beyond the site's own control
// labels (those labels are what the adapter needs to verify, and they are
// chrome text, not user data).
import {
  ARIA_STATE_ATTRS,
  CONTROLS,
  MEDIA_ELEMENT_SELECTOR,
  SEARCH,
  TRACK_INFO,
} from "../adapter/selectors";
import { fillControlledInput } from "../adapter/search";
import { hostname } from "../shared/sanitize";

export interface ProbeReport {
  probeVersion: 1;
  ranAt: string;
  urlHost: string | null;
  locale: string;
  suites: Record<string, unknown>;
}

function describeEl(el: Element): Record<string, unknown> {
  const path: string[] = [];
  let cur: Element | null = el;
  for (let i = 0; i < 6 && cur; i += 1) {
    let part = cur.tagName.toLowerCase();
    if (cur.id) part += `#${cur.id}`;
    const cls = typeof cur.className === "string" ? cur.className.trim() : "";
    if (cls) part += `.${cls.split(/\s+/).slice(0, 3).join(".")}`;
    path.unshift(part);
    cur = cur.parentElement;
  }
  const attrs: Record<string, string | null> = {};
  for (const name of ARIA_STATE_ATTRS) {
    attrs[name] = el.getAttribute(name);
  }
  return { path: path.join(" > "), attrs, visible: (el as HTMLElement).offsetParent !== null };
}

function suiteDom(): Record<string, unknown> {
  const media = [...document.querySelectorAll(MEDIA_ELEMENT_SELECTOR)]
    .filter((el): el is HTMLVideoElement => el instanceof HTMLMediaElement)
    .map((m) => ({
      tag: m.tagName.toLowerCase(),
      readyState: m.readyState,
      paused: m.paused,
      ended: m.ended,
      duration: Number.isFinite(m.duration) ? m.duration : null,
      seekableRanges: m.seekable.length,
      srcHost: hostname(m.currentSrc || m.src),
      controls: m.controls,
      muted: m.muted,
      volume: m.volume,
      playbackRate: m.playbackRate,
      describe: describeEl(m),
    }));

  const controls: Record<string, unknown> = {};
  for (const [name, q] of Object.entries(CONTROLS)) {
    const found: unknown[] = [];
    for (const sel of q.selectors) {
      try {
        for (const el of document.querySelectorAll(sel)) {
          found.push({ via: sel, ...describeEl(el) });
        }
      } catch {
        found.push({ via: sel, error: "selector rejected" });
      }
    }
    // aria-label fallback visibility
    const labelled: unknown[] = [];
    for (const el of document.querySelectorAll("[aria-label]")) {
      const label = el.getAttribute("aria-label") ?? "";
      if (q.ariaLabels.some((re) => re.test(label))) {
        labelled.push({ via: `aria:${label.slice(0, 60)}`, ...describeEl(el) });
      }
    }
    controls[name] = { found: found.slice(0, 4), labelled: labelled.slice(0, 4) };
  }

  const track = {
    title: TRACK_INFO.title.map((sel) => ({
      sel,
      present: document.querySelector(sel) !== null,
    })),
    byline: TRACK_INFO.byline.map((sel) => ({
      sel,
      present: document.querySelector(sel) !== null,
    })),
  };

  return { media, controls, track };
}

function suiteSearchInput(): Record<string, unknown> {
  const candidates = SEARCH.input.map((sel) => ({
    sel,
    elements: [...document.querySelectorAll(sel)].map(describeEl).slice(0, 3),
  }));
  const input = SEARCH.input
    .map((sel) => document.querySelector(sel))
    .find((el): el is HTMLInputElement => el instanceof HTMLInputElement);

  let fillWorks: boolean | null = null;
  let fillNote = "no input found";
  if (input) {
    const before = input.value;
    try {
      fillControlledInput(input, "amberfader-probe");
      fillWorks = input.value === "amberfader-probe";
      fillNote = fillWorks
        ? "native setter + InputEvent populated the controlled input"
        : "value did not stick — framework ignored the synthetic input path";
    } catch (err) {
      fillWorks = false;
      fillNote = err instanceof Error ? err.message : "fill threw";
    } finally {
      try {
        fillControlledInput(input, before);
      } catch {
        // best-effort restore
      }
    }
  }

  const resultsRoots = SEARCH.resultsRoot.map((sel) => ({
    sel,
    present: document.querySelector(sel) !== null,
  }));

  return { candidates, fillWorks, fillNote, resultsRoots };
}

function suiteArtwork(): Record<string, unknown> {
  const hosts = new Set<string>();
  const images = document.querySelectorAll("img");
  let count = 0;
  for (const img of images) {
    count += 1;
    const h = hostname(img.currentSrc || img.src);
    if (h) hosts.add(h);
    if (img.srcset) {
      for (const part of img.srcset.split(",")) {
        const u = part.trim().split(" ")[0];
        const hh = hostname(u);
        if (hh) hosts.add(hh);
      }
    }
  }
  return { imageCount: count, hosts: [...hosts].sort() };
}

async function suiteMediaOps(): Promise<Record<string, unknown>> {
  // Autoplay posture without touching the live element: a detached muted
  // element still exercises the user-gesture policy for play().
  const probe = document.createElement("video");
  probe.muted = true;
  probe.src =
    "data:video/mp4;base64,AAAAIGZ0eXBpc29tAAACAGlzb21pc28yYXZjMW1wNDE=";
  let detachedPlay = "unresolved";
  try {
    await probe.play();
    detachedPlay = "allowed";
  } catch (err) {
    detachedPlay = `rejected:${err instanceof Error ? err.name : "error"}`;
  }

  const live = document.querySelector(MEDIA_ELEMENT_SELECTOR);
  const volumeRoundTrip: Record<string, unknown> = { attempted: false };
  if (live instanceof HTMLMediaElement) {
    const v = live.volume;
    try {
      const target = Math.abs(v - 0.5) < 0.01 ? 0.49 : v - 0.01;
      live.volume = Math.max(target, 0);
      volumeRoundTrip.attempted = true;
      volumeRoundTrip.took = Math.abs(live.volume - Math.max(target, 0)) < 0.02;
      live.volume = v; // restore
    } catch (err) {
      volumeRoundTrip.error = err instanceof Error ? err.message : "threw";
    }
  }

  return { detachedMutedPlay: detachedPlay, volumeRoundTrip };
}

const SUITES: Record<string, () => Record<string, unknown> | Promise<Record<string, unknown>>> = {
  dom: () => suiteDom(),
  searchInput: () => suiteSearchInput(),
  artwork: () => suiteArtwork(),
  mediaOps: () => suiteMediaOps(),
};

export async function runProbes(suites?: string[]): Promise<ProbeReport> {
  const names = suites?.length ? suites : Object.keys(SUITES);
  const out: Record<string, unknown> = {};
  for (const name of names) {
    const fn = SUITES[name];
    if (!fn) {
      out[name] = { error: "unknown suite" };
      continue;
    }
    try {
      out[name] = await fn();
    } catch (err) {
      out[name] = { error: err instanceof Error ? err.message : "suite threw" };
    }
  }
  return {
    probeVersion: 1,
    ranAt: new Date().toISOString(),
    urlHost: hostname(location.href),
    locale: navigator.language,
    suites: out,
  };
}
