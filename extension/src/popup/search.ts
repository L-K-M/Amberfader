// Search window (Stage A). Enter-to-search only — no keystroke network
// activity. Shows normalized song rows and plays a validated selection.
import { ProtocolClient } from "./client";
import { validateSearchHistory, validateSearchSongsResult } from "../protocol/validate";
import type {
  SearchResultRow,
  SearchSongsResult,
} from "../protocol/types";

const $ = <T extends HTMLElement>(id: string): T => {
  const el = document.getElementById(id);
  if (!el) throw new Error(`missing element #${id}`);
  return el as T;
};

const qEl = $<HTMLInputElement>("q");
const listEl = $("results");
const statusEl = $("sstatus");
const recentQueries = $("recent-queries");
const recentArtists = $("recent-artists");
const clearHistory = $<HTMLButtonElement>("clear-history");

let busy = false;
let current: SearchSongsResult | null = null;
let actionEpoch = 0;

const client = new ProtocolClient({
  onBinding: (status) => {
    invalidateResults();
    if (status !== "bound") setStatus("Playback target changed; search again", true);
  },
  onDisconnected: () => {
    invalidateResults();
    setStatus("Disconnected; retrying…", true);
  },
});

function invalidateResults(): void {
  actionEpoch += 1;
  current = null;
  busy = false;
  listEl.textContent = "";
}

function renderRecents(container: HTMLElement, items: string[]): void {
  container.textContent = "";
  if (items.length === 0) {
    container.textContent = "None yet";
    return;
  }
  for (const item of items) {
    const button = document.createElement("button");
    button.textContent = item;
    button.addEventListener("click", () => {
      if (busy) return;

      qEl.value = item;
      void runSearch();
    });
    container.append(button);
  }
}

async function loadHistory(): Promise<void> {
  const response = await client.request("search.history", {});
  if (!response.ok) {
    setStatus(response.error.message, true);
    return;
  }
  if (!validateSearchHistory(response.result)) {
    setStatus("Invalid search history", true);
    return;
  }
  renderRecents(recentQueries, response.result.queries);
  renderRecents(recentArtists, response.result.artists);
}

function setStatus(text: string, isError = false): void {
  statusEl.textContent = text;
  statusEl.classList.toggle("error", isError);
}

function renderRows(result: SearchSongsResult): void {
  listEl.textContent = "";
  if (result.results.length === 0) {
    setStatus("No songs found");
    return;
  }
  for (const row of result.results) {
    const li = document.createElement("li");
    const title = document.createElement("span");
    title.className = "r-title";
    title.textContent = row.title; // plain text — page-derived, never HTML
    const sub = document.createElement("span");
    sub.className = "r-sub";
    const dur =
      row.durationSeconds !== null
        ? ` · ${Math.floor(row.durationSeconds / 60)}:${String(Math.floor(row.durationSeconds % 60)).padStart(2, "0")}`
        : "";
    sub.textContent = `${row.artists.join(", ")}${row.album ? ` · ${row.album}` : ""}${dur}`;
    li.append(title, sub);
    if (!row.supported) {
      li.classList.add("unsupported");
      li.title = `${row.kind} results are not supported yet`;
    } else {
      li.title = "Play this song";
    }
    const actions = document.createElement("div");
    actions.className = "row-actions";
    const play = document.createElement("button");
    play.textContent = "Play";
    play.disabled = !row.supported;
    play.addEventListener("click", () => void activateRow(row, "search.playResult"));
    const radio = document.createElement("button");
    radio.textContent = "Start mix";
    radio.disabled = row.radioSupported !== true;
    radio.title = radio.disabled ? "Mix control unavailable for this result" : "Start a radio playlist";
    radio.addEventListener("click", () => void activateRow(row, "search.startRadio"));
    actions.append(play, radio);
    li.append(actions);
    listEl.append(li);
  }
  if (!result.complete) {
    setStatus("Showing the first results — the page may have more (load-more lands later)");
  } else {
    setStatus("");
  }
}

async function activateRow(row: SearchResultRow, method: "search.playResult" | "search.startRadio"): Promise<void> {
  if (!current || busy) return;
  if (method === "search.playResult" ? !row.supported : row.radioSupported !== true) return;

  const epoch = actionEpoch;
  busy = true;
  const resp = await client.request(method, {
    searchToken: current.searchToken,
    resultId: row.resultId,
  });
  if (epoch !== actionEpoch) return;

  busy = false;
  if (!resp.ok) {
    setStatus(resp.error.message, true);
  } else {
    setStatus(method === "search.startRadio" ? `Mix started: ${row.title}` : `Playing: ${row.title}`);
  }
}

async function runSearch(): Promise<void> {
  const query = qEl.value.trim();
  if (!query || busy) return;
  const epoch = ++actionEpoch;
  busy = true;
  current = null;
  listEl.textContent = "";
  setStatus("Searching…");
  const resp = await client.request("search.songs", { query });
  if (epoch !== actionEpoch) return;

  busy = false;
  if (!resp.ok) {
    if (resp.error.code === "stale_result") {
      setStatus("Search superseded — run it again", true);
    } else {
      setStatus(resp.error.message, true);
    }
    return;
  }
  if (!validateSearchSongsResult(resp.result)) {
    setStatus("Invalid search results", true);
    return;
  }
  current = resp.result;
  renderRows(current);
  void loadHistory();
}

clearHistory.addEventListener("click", () => {
  clearHistory.disabled = true;
  void client.request("search.clearHistory", {}).then((response) => {
    clearHistory.disabled = false;
    if (!response.ok) {
      setStatus(response.error.message, true);
      return;
    }
    void loadHistory();
  });
});

qEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    void runSearch();
  }
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") window.close();
});

void client.connect().then(loadHistory);
qEl.focus();
