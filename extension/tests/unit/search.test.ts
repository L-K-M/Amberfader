// SiteSearch state machine against synthetic jsdom pages. The DOM here is a
// stand-in for probing — it proves the race/supersede/cap logic, not that the
// real YouTube Music page looks like this.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { fillControlledInput, SiteSearch } from "../../src/adapter/search";

// Page shell: search input + an empty results root. Result rows are appended
// AFTER a search starts — the machine only accepts post-submit mutations.
function pageShell(): void {
  document.body.innerHTML = `
    <ytmusic-search-box><input type="search"></ytmusic-search-box>
    <ytmusic-search-page>
      <ytmusic-section-list-renderer id="root"></ytmusic-section-list-renderer>
    </ytmusic-search-page>`;
}

function addRows(count: number): void {
  const root = document.getElementById("root")!;
  for (let i = 0; i < count; i += 1) {
    const row = document.createElement("ytmusic-responsive-list-item-renderer");
    row.innerHTML = `
      <span class="title">Song ${i}</span>
      <span class="subtitle">Artist ${i} • Album • 3:0${i % 10}</span>
      <img src="https://i.ytimg.com/vi/abc${i}/hq.jpg">
      <ytmusic-play-button-renderer></ytmusic-play-button-renderer>`;
    root.append(row);
  }
}

async function radioSearch() {
  pageShell();
  vi.spyOn(HTMLElement.prototype, "getClientRects").mockImplementation(() =>
    Object.assign([new DOMRect(0, 0, 24, 24)], { item: () => null }));
  const search = new SiteSearch(document);
  const { token, promise } = search.search("query", 500);
  addRows(2);
  const rows = [...document.querySelectorAll("ytmusic-responsive-list-item-renderer")];
  for (const row of rows) {
    row.insertAdjacentHTML("beforeend", `<ytmusic-menu-renderer><yt-button-shape>
      <button aria-label="Action menu"></button></yt-button-shape></ytmusic-menu-renderer>`);
  }
  const result = await promise;
  return { search, token, rows, result };
}

const mixMenu = () => readFileSync("extension/tests/fixtures/mix-menu-2026-10-02.html", "utf8");

describe("SiteSearch", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("fillControlledInput sets a controlled-style input value", () => {
    const input = document.createElement("input");
    let observed = "";
    input.addEventListener("input", (e) => {
      observed = (e.target as HTMLInputElement).value;
    });
    fillControlledInput(input, "test query");
    expect(input.value).toBe("test query");
    expect(observed).toBe("test query");
  });

  it("resolves with normalized song rows after results mutate", async () => {
    pageShell();
    const s = new SiteSearch(document);
    const { token, promise } = s.search("anything", 500);
    addRows(3);
    const result = await promise;
    expect(result.searchToken).toBe(token);
    expect(result.results.length).toBe(3);
    const first = result.results[0]!;
    expect(first.kind).toBe("song");
    expect(first.title).toBe("Song 0");
    expect(first.artists[0]).toContain("Artist 0");
    expect(first.supported).toBe(true);
    expect(first.resultId.startsWith(`${token}/`)).toBe(true);
  });

  it("a newer query supersedes the older one (stale rejection)", async () => {
    pageShell();
    const s = new SiteSearch(document);
    const first = s.search("old query", 5000);
    const second = s.search("new query", 5000);
    await expect(first.promise).rejects.toThrow(/superseded/i);
    addRows(1);
    const res = await second.promise;
    expect(res.searchToken).toBe(second.token);
  });

  it("caps results at 30 and reports complete honestly", async () => {
    pageShell();
    const s = new SiteSearch(document);
    const { promise } = s.search("q", 500);
    addRows(40);
    const res = await promise;
    expect(res.results.length).toBe(30);
    expect(res.complete).toBe(false);
  });

  it("times out instead of hanging forever", async () => {
    pageShell();
    const s = new SiteSearch(document);
    const { promise } = s.search("q", 50);
    await expect(promise).rejects.toThrow(/deadline/i);
  });

  it("playResult re-resolves by identity, not row index", async () => {
    pageShell();
    const s = new SiteSearch(document);
    const { token, promise } = s.search("q", 500);
    addRows(2);
    const res = await promise;
    const target = res.results[1]!;

    // Reorder the DOM: the second row now sits first — identity must win.
    const rows = document.querySelectorAll("ytmusic-responsive-list-item-renderer");
    rows[0]!.parentElement!.append(rows[0]!);
    const clicks: string[] = [];
    for (const el of document.querySelectorAll("ytmusic-play-button-renderer")) {
      (el as HTMLElement).click = function (this: HTMLElement) {
        clicks.push(
          this.parentElement?.querySelector(".title")?.textContent ?? "?",
        );
      };
    }
    const out = s.playResult(token, target.resultId);
    expect(out.ok).toBe(true);
    expect(clicks).toEqual(["Song 1"]);
  });

  it("rejects stale result handles after cancellation", async () => {
    pageShell();
    const s = new SiteSearch(document);
    const { token, promise } = s.search("q", 500);
    addRows(1);
    const res = await promise;
    s.cancelCurrent();
    expect(s.playResult(token, res.results[0]!.resultId).ok).toBe(false);
  });

  it("ignores cached rows outside the search root and deduplicates selector matches", async () => {
    pageShell();
    document.body.insertAdjacentHTML("beforeend", `
      <ytmusic-responsive-list-item-renderer>
        <span class="title">Old home result</span><span class="subtitle">Home artist</span>
        <ytmusic-play-button-renderer></ytmusic-play-button-renderer>
      </ytmusic-responsive-list-item-renderer>`);
    const search = new SiteSearch(document);
    const { promise } = search.search("query", 500);
    document.getElementById("root")!.innerHTML = `
      <ytmusic-shelf-renderer><ytmusic-responsive-list-item-renderer>
        <span class="title">Search song</span><span class="subtitle">Artist • 3:00</span>
        <ytmusic-play-button-renderer></ytmusic-play-button-renderer>
      </ytmusic-responsive-list-item-renderer></ytmusic-shelf-renderer>`;
    expect((await promise).results.map((row) => row.title)).toEqual(["Search song"]);
  });

  it("opens the re-resolved result menu and activates only its captured mix link", async () => {
    const { search, token, rows, result } = await radioSearch();
    expect(result.results[1]?.radioSupported).toBe(true);
    rows[0]!.parentElement!.append(rows[0]!);
    const menu = rows[1]!.querySelector("button")!;
    const play = vi.fn();
    rows[1]!.querySelector("ytmusic-play-button-renderer")!.addEventListener("click", play);
    const mix = vi.fn((event: Event) => event.preventDefault());
    const shuffle = vi.fn();
    menu.addEventListener("click", () => {
      document.body.insertAdjacentHTML("beforeend", mixMenu());
      document.querySelector("[aria-label='Start mix'] a")!.addEventListener("click", mix);
      document.querySelector("[aria-label='Shuffle play'] a")!.addEventListener("click", shuffle);
    });
    const prepared = await search.prepareRadio(token, result.results[1]!.resultId, 500);
    expect(prepared.ok).toBe(true);
    expect(mix).not.toHaveBeenCalled();
    if (!prepared.ok) throw new Error(prepared.error);
    expect(prepared.playlistId).toBe("fixture-mix");
    expect(prepared.activate().ok).toBe(true);
    expect(mix).toHaveBeenCalledOnce();
    expect(play).not.toHaveBeenCalled();
    expect(shuffle).not.toHaveBeenCalled();
  });

  it("refuses an already-open unrelated menu without clicking a row", async () => {
    const { search, token, rows, result } = await radioSearch();
    document.body.insertAdjacentHTML("beforeend", mixMenu());
    const clicked = vi.fn();
    rows[0]!.querySelector("button")!.addEventListener("click", clicked);
    expect(await search.prepareRadio(token, result.results[0]!.resultId, 500)).toMatchObject({
      ok: false, code: "user_interaction_required",
    });
    expect(clicked).not.toHaveBeenCalled();
  });

  it("does not activate stale cached menu content merely becoming visible", async () => {
    const { search, token, rows, result } = await radioSearch();
    document.body.insertAdjacentHTML("beforeend", mixMenu());
    const popup = document.querySelector("ytmusic-menu-popup-renderer") as HTMLElement;
    popup.hidden = true;
    const clicked = vi.fn();
    popup.querySelector("[aria-label='Start mix'] a")!.addEventListener("click", clicked);
    rows[0]!.querySelector("button")!.addEventListener("click", () => { popup.hidden = false; });
    expect(await search.prepareRadio(token, result.results[0]!.resultId, 30)).toMatchObject({
      ok: false, code: "timeout",
    });
    expect(clicked).not.toHaveBeenCalled();
  });

  it("cancels menu preparation when a newer search invalidates its handle", async () => {
    const { search, token, result } = await radioSearch();
    const pending = search.prepareRadio(token, result.results[0]!.resultId, 500);
    search.cancelCurrent();
    expect(await pending).toMatchObject({ ok: false, code: "stale_result" });
  });

  it("rechecks the target link and result immediately before mix activation", async () => {
    const { search, token, rows, result } = await radioSearch();
    rows[0]!.querySelector("button")!.addEventListener("click", () => {
      document.body.insertAdjacentHTML("beforeend", mixMenu());
    });
    const prepared = await search.prepareRadio(token, result.results[0]!.resultId, 500);
    if (!prepared.ok) throw new Error(prepared.error);
    const link = document.querySelector("[aria-label='Start mix'] a")!;
    const clicked = vi.fn();
    link.addEventListener("click", clicked);
    link.setAttribute("href", "watch?playlist=other-mix");
    expect(prepared.activate().ok).toBe(false);
    expect(clicked).not.toHaveBeenCalled();
  });

  it("reports unsupported when a fresh result menu lacks Start mix", async () => {
    const { search, token, rows, result } = await radioSearch();
    rows[0]!.querySelector("button")!.addEventListener("click", () => {
      document.body.insertAdjacentHTML("beforeend", mixMenu().replaceAll("Start mix", "Other action"));
    });
    expect(await search.prepareRadio(token, result.results[0]!.resultId, 30)).toMatchObject({
      ok: false, code: "unsupported_operation",
    });
  });

  it("waits for a progressively rendered mix item and its endpoint", async () => {
    const { search, token, rows, result } = await radioSearch();
    rows[0]!.querySelector("button")!.addEventListener("click", () => {
      document.body.insertAdjacentHTML("beforeend", mixMenu());
      const mix = document.querySelector("[aria-label='Start mix']")!;
      mix.remove();
      setTimeout(() => {
        const link = mix.querySelector("a")!;
        const href = link.getAttribute("href")!;
        link.removeAttribute("href");
        document.querySelector("ytmusic-menu-popup-renderer #items")!.append(mix);
        setTimeout(() => link.setAttribute("href", href), 0);
      }, 0);
    });
    expect(await search.prepareRadio(token, result.results[0]!.resultId, 500)).toMatchObject({
      ok: true, playlistId: "fixture-mix",
    });
  });

  it("does not advertise mixes for a disabled action menu", async () => {
    pageShell();
    const search = new SiteSearch(document);
    const { promise } = search.search("query", 500);
    addRows(1);
    document.querySelector("ytmusic-responsive-list-item-renderer")!.insertAdjacentHTML("beforeend", `
      <ytmusic-menu-renderer><button aria-label="Action menu" aria-disabled="true"></button></ytmusic-menu-renderer>`);
    expect((await promise).results[0]?.radioSupported).toBe(false);
  });
});
