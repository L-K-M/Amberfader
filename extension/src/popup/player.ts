// Prototype player window (Stage A). Renders PlayerState, collects user
// actions, never decides independently what is playing. Functional first —
// this UI exists to validate the adapter and protocol before the native app.
import { ProtocolClient } from "./client";
import { ArtworkService } from "../controller/artwork";
import type {
  Capability,
  PlayerState,
  SearchSongsResult,
} from "../protocol/types";


const $ = <T extends HTMLElement>(id: string): T => {
  const el = document.getElementById(id);
  if (!el) throw new Error(`missing element #${id}`);
  return el as T;
};

const artEl = $<HTMLImageElement>("art");
const titleEl = $("title");
const artistsEl = $("artists");
const timeEl = $("time");
const seekEl = $<HTMLInputElement>("seek");
const volEl = $<HTMLInputElement>("volume");
const statusEl = $("status");
const btnPlay = $<HTMLButtonElement>("btn-play");
const btnPrev = $<HTMLButtonElement>("btn-prev");
const btnNext = $<HTMLButtonElement>("btn-next");
const btnSearch = $<HTMLButtonElement>("btn-search");
const btnShow = $<HTMLButtonElement>("btn-show");
const btnHide = $<HTMLButtonElement>("btn-hide");
const btnMenu = $<HTMLButtonElement>("btn-menu");

const artwork = new ArtworkService();

let state: PlayerState | null = null;
let stateAt = 0; // monotonic receipt time for interpolation
let seeking = false;
let pendingTransport = false;
let connectionError: string | null = null;

const client = new ProtocolClient({
  onState: (s) => {
    if (state?.bindingToken !== s.bindingToken ||
        state?.track?.occurrenceId !== s.track?.occurrenceId ||
        state?.track?.artworkId !== s.track?.artworkId) {
      artwork.invalidateAll();
      artEl.removeAttribute("src");
    }
    connectionError = null;
    state = s;
    stateAt = performance.now();
    render();
  },
  onBinding: (status, reason) => {
    if (status !== "bound") {
      state = null;
      connectionError = reason ? `Target lost: ${reason}` : "No playback target selected";
      render();
    }
  },
  onConnection: (component, status, reason) => {
    if ((component === "target" || component === "adapter") && status !== "connected") {
      state = null;
      connectionError = reason ?? "Playback tab disconnected";
      render();
    }
  },
  onDisconnected: () => {
    state = null;
    connectionError = "Disconnected from Firefox. Retrying…";
    render();
  },
});

client.onArtworkPropose = ({ url, artworkId, occurrenceId }) => {
  const bindingToken = client.bindingToken;
  void artwork.fetchAsset({ url, artworkId, occurrenceId }).then((asset) => {
    if (state?.bindingToken !== bindingToken ||
        state?.track?.occurrenceId !== occurrenceId || state?.track?.artworkId !== artworkId) return;

    if (!asset) {
      artEl.removeAttribute("src");
      return;
    }
    artEl.src = `data:${asset.mime};base64,${asset.dataBase64}`;
  });
};

function fmt(sec: number | null): string {
  if (sec === null || !Number.isFinite(sec)) return "–:––";
  const s = Math.max(0, Math.floor(sec));
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}

function showStatus(text: string, isError = false): void {
  statusEl.textContent = text;
  statusEl.classList.toggle("error", isError);
  if (!isError && text) {
    window.setTimeout(() => {
      if (statusEl.textContent === text) statusEl.textContent = "";
    }, 4000);
  }
}

// Interpolate between ~1 Hz samples using monotonic local receipt time; stop
// on pause, buffering, disconnect, or track change (spec §4).
function interpolatedPosition(): number | null {
  if (!state || state.positionSeconds === null) return null;
  if (state.status !== "playing" || seeking) return state.positionSeconds;
  const elapsed = (performance.now() - stateAt) / 1000;
  const rate = state.playbackRate ?? 1;
  const est = state.positionSeconds + elapsed * rate;
  return state.durationSeconds !== null
    ? Math.min(est, state.durationSeconds)
    : est;
}

function hasCap(c: Capability): boolean {
  return state?.capabilities.includes(c) ?? false;
}

function render(): void {
  const t = state?.track ?? null;
  titleEl.textContent = t?.title ?? "Nothing selected";
  titleEl.title = t?.title ?? "";
  const sub = [t?.artists.join(", "), t?.album].filter(Boolean).join(" — ");
  artistsEl.textContent = sub || "Select a YouTube Music tab to begin";
  artistsEl.title = sub;
  if (!t?.artworkId) artEl.removeAttribute("src");

  const pos = interpolatedPosition();
  timeEl.textContent = `${fmt(pos)} / ${fmt(state?.durationSeconds ?? null)}`;
  if (!seeking) {
    const dur = state?.durationSeconds ?? null;
    seekEl.value = dur && pos !== null ? String(Math.round((pos / dur) * 1000)) : "0";
    seekEl.max = dur && dur > 0 ? "1000" : "1";
  }

  const playing = state?.status === "playing";
  btnPlay.textContent = playing ? "⏸" : "▶";
  btnPlay.setAttribute("aria-label", playing ? "Pause" : "Play");
  btnPlay.classList.toggle("pending", pendingTransport);

  btnPlay.disabled = pendingTransport || !(hasCap(playing ? "pause" : "play"));
  btnPrev.disabled = !hasCap("previous");
  btnNext.disabled = !hasCap("next");
  seekEl.disabled = !hasCap("seek") || state?.durationSeconds == null;
  volEl.disabled = !hasCap("volume") && !hasCap("seek");
  btnHide.disabled = !state;
  btnShow.disabled = !state;

  if (state === null) {
    showStatus(connectionError ?? "Waiting for a YouTube Music tab…", connectionError !== null);
  } else if (state.status === "unknown" && !t) {
    showStatus("Player state unknown — the page may still be loading");
  }
}

async function transport(method: "player.play" | "player.pause"): Promise<void> {
  pendingTransport = true;
  render();
  const resp = await client.request(method, {});
  pendingTransport = false;
  if (!resp.ok) {
    showStatus(resp.error.message, true);
    if (resp.error.code === "stale_target" || resp.error.code === "disconnected") {
      await client.connect();
    }
  }
  render();
}

btnPlay.addEventListener("click", () => {
  const playing = state?.status === "playing";
  void transport(playing ? "player.pause" : "player.play");
});
btnPrev.addEventListener("click", () => {
  void client.request("player.previous", {}).then((r) => {
    if (!r.ok) showStatus(r.error.message, true);
  });
});
btnNext.addEventListener("click", () => {
  void client.request("player.next", {}).then((r) => {
    if (!r.ok) showStatus(r.error.message, true);
  });
});

// Seek: preview locally during drag; one command on release; cancel the
// gesture if the track changed (spec §9).
let seekStartOccurrence: string | null = null;
seekEl.addEventListener("input", () => {
  seeking = true;
  if (state?.durationSeconds) {
    const dur = state.durationSeconds;
    const pos = (Number(seekEl.value) / 1000) * dur;
    timeEl.textContent = `${fmt(pos)} / ${fmt(dur)}`;
  }
});
seekEl.addEventListener("pointerdown", () => {
  seekStartOccurrence = state?.track?.occurrenceId ?? null;
});
seekEl.addEventListener("change", () => {
  const occ = seekStartOccurrence ?? state?.track?.occurrenceId ?? null;
  seeking = false;
  seekStartOccurrence = null;
  const dur = state?.durationSeconds;
  if (!occ || !dur || occ !== state?.track?.occurrenceId) {
    render();
    return;
  }
  const pos = (Number(seekEl.value) / 1000) * dur;
  void client
    .request("player.seek", { occurrenceId: occ, positionSeconds: pos })
    .then((r) => {
      if (!r.ok) showStatus(r.error.message, true);
    });
});

// Volume: same drag discipline — local preview, commit on release.
volEl.addEventListener("change", () => {
  void client
    .request("player.setVolume", { volume: Number(volEl.value) / 100 })
    .then((r) => {
      if (!r.ok) showStatus(r.error.message, true);
    });
});

btnShow.addEventListener("click", () => {
  void client.request("browser.showPlayer", {}).then((r) => {
    if (!r.ok) showStatus(r.error.message, true);
  });
});
btnHide.addEventListener("click", () => {
  void client.request("browser.hidePlayer", {}).then((r) => {
    if (!r.ok) showStatus(r.error.message, true);
    else showStatus("Playback tab hidden");
  });
});
btnMenu.addEventListener("click", () => {
  void browser.runtime.openOptionsPage();
});

const SEARCH_URL = "search.html";
btnSearch.addEventListener("click", () => {
  void browser.windows.create({
    url: browser.runtime.getURL(SEARCH_URL),
    type: "popup",
    width: 420,
    height: 480,
  });
});

document.addEventListener("keydown", (e) => {
  const target = e.target as HTMLElement;
  const editable = target.tagName === "INPUT" && target !== seekEl && target !== volEl;
  if (e.key === " " && !editable) {
    e.preventDefault();
    btnPlay.click();
  } else if (e.key === "f" && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    btnSearch.click();
  }
});

// 500 ms UI tick for interpolation; adapter itself samples ~1 Hz.
setInterval(render, 500);
void client.connect().then(render);

// Shared for the search window's quick select-and-play path.
export type { SearchSongsResult };
