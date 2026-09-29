// Search window (Stage A). Enter-to-search only — no keystroke network
// activity. Shows normalized song rows and plays a validated selection.
import { ProtocolClient } from "./client";
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

let busy = false;
let current: SearchSongsResult | null = null;

const client = new ProtocolClient({
  onBinding: (status) => {
    if (status !== "bound") setStatus("Playback target changed — results are stale; search again", true);
  },
  onDisconnected: () => setStatus("Disconnected — retrying…", true),
});

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
      li.addEventListener("click", () => void playRow(row));
      li.title = "Play this song";
    }
    listEl.append(li);
  }
  if (!result.complete) {
    setStatus("Showing the first results — the page may have more (load-more lands later)");
  } else {
    setStatus("");
  }
}

async function playRow(row: SearchResultRow): Promise<void> {
  if (!current || busy) return;
  busy = true;
  const resp = await client.request("search.playResult", {
    searchToken: current.searchToken,
    resultId: row.resultId,
  });
  busy = false;
  if (!resp.ok) {
    setStatus(resp.error.message, true);
  } else {
    setStatus(`Playing: ${row.title}`);
  }
}

async function runSearch(): Promise<void> {
  const query = qEl.value.trim();
  if (!query || busy) return;
  busy = true;
  listEl.textContent = "";
  setStatus("Searching…");
  const resp = await client.request("search.songs", { query });
  busy = false;
  if (!resp.ok) {
    if (resp.error.code === "stale_result") {
      setStatus("Search superseded — run it again", true);
    } else {
      setStatus(resp.error.message, true);
    }
    return;
  }
  current = resp.result as unknown as SearchSongsResult;
  renderRows(current);
}

qEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    void runSearch();
  }
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") window.close();
});

void client.connect();
qEl.focus();
