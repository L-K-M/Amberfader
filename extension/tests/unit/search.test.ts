// SiteSearch state machine against synthetic jsdom pages. The DOM here is a
// stand-in for probing — it proves the race/supersede/cap logic, not that the
// real YouTube Music page looks like this.
import { beforeEach, describe, expect, it } from "vitest";
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
});
