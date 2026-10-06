// ContinuePlaying against a synthetic page. The prompt's structure comes from
// the YouTube NonStop extension and is UNVERIFIED on the live site.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ContinuePlaying } from "../../src/adapter/continuePlaying";

function page({ promptVisible = true, insideContainer = true, paused = true } = {}) {
  document.body.innerHTML = `
    <video></video>
    <ytmusic-popup-container>
      <tp-yt-paper-dialog>${insideContainer ? "<ytmusic-you-there-renderer></ytmusic-you-there-renderer>" : ""}</tp-yt-paper-dialog>
    </ytmusic-popup-container>
    ${insideContainer ? "" : "<ytmusic-you-there-renderer></ytmusic-you-there-renderer>"}`;
  const prompt = document.querySelector("ytmusic-you-there-renderer") as HTMLElement;
  if (!promptVisible) prompt.style.display = "none";
  const container = document.querySelector("ytmusic-popup-container") as HTMLElement;
  const clicks = vi.fn();
  container.addEventListener("click", clicks);
  const video = document.querySelector("video")!;
  Object.defineProperty(video, "paused", { configurable: true, get: () => paused });
  const play = vi.fn(() => Promise.resolve());
  video.play = play;
  return { clicks, play, video };
}

// Listeners live on the shared jsdom document; stop every watcher a test made.
const watchers: ContinuePlaying[] = [];
function watcher(): ContinuePlaying {
  const created = new ContinuePlaying(document);
  watchers.push(created);
  return created;
}

describe("ContinuePlaying", () => {
  afterEach(() => {
    for (const created of watchers.splice(0)) created.stop();
  });

  beforeEach(() => {
    vi.spyOn(HTMLElement.prototype, "getClientRects").mockImplementation(() =>
      Object.assign([new DOMRect(0, 0, 24, 24)], { item: () => null }));
  });

  it("closes the prompt and resumes when YouTube Music opens it", () => {
    const { clicks, play } = page();
    watcher().start();

    document.dispatchEvent(new CustomEvent("yt-popup-opened"));

    expect(clicks).toHaveBeenCalledOnce();
    expect(play).toHaveBeenCalledOnce();
  });

  it("reacts to the pause the prompt causes", () => {
    const { clicks, play, video } = page();
    watcher().start();

    video.dispatchEvent(new Event("pause"));

    expect(clicks).toHaveBeenCalledOnce();
    expect(play).toHaveBeenCalledOnce();
  });

  it("does not resume a track that is already playing", () => {
    const { clicks, play } = page({ paused: false });
    expect(watcher().check()).toBe(true);
    expect(clicks).toHaveBeenCalledOnce();
    expect(play).not.toHaveBeenCalled();
  });

  it("ignores a hidden prompt and other popups", () => {
    const hidden = page({ promptVisible: false });
    const watching = watcher();
    watching.start();
    document.dispatchEvent(new CustomEvent("yt-popup-opened"));
    expect(hidden.clicks).not.toHaveBeenCalled();
    expect(hidden.play).not.toHaveBeenCalled();

    document.body.innerHTML = "<video></video><ytmusic-popup-container><ytmusic-menu-popup-renderer></ytmusic-menu-popup-renderer></ytmusic-popup-container>";
    const menuClicks = vi.fn();
    document.querySelector("ytmusic-popup-container")!.addEventListener("click", menuClicks);
    expect(watching.check()).toBe(false);
    expect(menuClicks).not.toHaveBeenCalled();
  });

  it("never clicks a container the prompt is not inside", () => {
    const { clicks, play } = page({ insideContainer: false });
    expect(watcher().check()).toBe(false);
    expect(clicks).not.toHaveBeenCalled();
    expect(play).not.toHaveBeenCalled();
  });

  it("stops listening when stopped", () => {
    const { clicks } = page();
    const watching = watcher();
    watching.start();
    watching.stop();
    document.dispatchEvent(new CustomEvent("yt-popup-opened"));
    expect(clicks).not.toHaveBeenCalled();
  });
});
