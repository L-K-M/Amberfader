// YouTubeMusicAdapter against a synthetic jsdom player. This fixture is
// honestly labeled synthetic — Phase 0 replaces it with captured DOM.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { YouTubeMusicAdapter } from "../../src/adapter/youtubeMusic";
import type { AdapterPlayerState } from "../../src/adapter/types";

function mountPlayer(): { video: HTMLVideoElement } {
  document.body.innerHTML = `
    <ytmusic-app>
      <ytmusic-player-bar>
        <div class="content-info-wrapper">
          <span class="title">Fixture Song</span>
          <span class="byline">Fixture Artist • Fixture Album</span>
          <img class="image" src="https://lh3.googleusercontent.com/abc=120">
        </div>
        <tp-yt-paper-icon-button id="play-pause-button" aria-label="Play"></tp-yt-paper-icon-button>
        <tp-yt-paper-icon-button class="previous-button" aria-label="Previous"></tp-yt-paper-icon-button>
        <tp-yt-paper-icon-button class="next-button" aria-label="Next"></tp-yt-paper-icon-button>
      </ytmusic-player-bar>
      <video></video>
    </ytmusic-app>`;
  const video = document.querySelector("video")!;
  // jsdom media elements need stubbed props/methods.
  let paused = true;
  let currentTime = 0;
  let volume = 0.8;
  Object.defineProperty(video, "paused", { get: () => paused, configurable: true });
  Object.defineProperty(video, "ended", { get: () => false, configurable: true });
  Object.defineProperty(video, "readyState", { get: () => 4, configurable: true });
  Object.defineProperty(video, "duration", { get: () => 200, configurable: true });
  Object.defineProperty(video, "currentTime", {
    get: () => currentTime,
    set: (v: number) => {
      currentTime = v;
      video.dispatchEvent(new Event("seeked"));
      video.dispatchEvent(new Event("timeupdate"));
    },
    configurable: true,
  });
  Object.defineProperty(video, "volume", {
    get: () => volume,
    set: (v: number) => {
      volume = v;
      video.dispatchEvent(new Event("volumechange"));
    },
    configurable: true,
  });
  Object.defineProperty(video, "seekable", {
    get: () => ({ length: 1, start: () => 0, end: () => 200 }),
    configurable: true,
  });
  video.play = () => {
    paused = false;
    video.dispatchEvent(new Event("play"));
    video.dispatchEvent(new Event("playing"));
    return Promise.resolve();
  };
  video.pause = () => {
    paused = true;
    video.dispatchEvent(new Event("pause"));
  };
  // The site's own JS translates a transport-button click into media calls.
  document
    .getElementById("play-pause-button")!
    .addEventListener("click", () => {
      if (paused) void video.play();
      else video.pause();
    });
  return { video };
}

describe("YouTubeMusicAdapter (synthetic fixture)", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    history.replaceState(null, "", "https://music.youtube.com/watch?v=fixture1");
  });

  it("reads track metadata and media state into a snapshot", async () => {
    const { video } = mountPlayer();
    const adapter = new YouTubeMusicAdapter();
    const states: AdapterPlayerState[] = [];
    adapter.onState((s) => states.push(s));
    await adapter.start();
    const s = adapter.snapshot();
    expect(s.track?.title).toBe("Fixture Song");
    expect(s.track?.artists).toEqual(["Fixture Artist"]);
    expect(s.track?.album).toBe("Fixture Album");
    expect(s.track?.providerId).toBe("fixture1");
    expect(s.status).toBe("unknown"); // paused at position 0 is honestly unknown
    expect(s.capabilities).toContain("play");
    expect(s.capabilities).toContain("seek");
    expect(adapter.proposedArtworkUrl).toContain("googleusercontent");
    adapter.stop();
    void video;
    void states;
  });

  it("explicit play resolves only after observed playing state", async () => {
    mountPlayer();
    const adapter = new YouTubeMusicAdapter();
    await adapter.start();
    const r = await adapter.exec("r1", "player.play", {});
    expect(r.ok).toBe(true);
    expect(adapter.snapshot().status).toBe("playing");
    adapter.stop();
  });

  it("previous/next click exactly one control per invocation", async () => {
    mountPlayer();
    const clicks: string[] = [];
    const btn = document.querySelector(".next-button") as HTMLElement;
    btn.click = () => {
      clicks.push("next");
      // Simulate the site advancing: new track metadata + media signal.
      (document.querySelector(".title") as HTMLElement).textContent = "Next Song";
      document.querySelector("video")!.dispatchEvent(new Event("durationchange"));
    };
    const adapter = new YouTubeMusicAdapter();
    await adapter.start();
    const r = await adapter.exec("r2", "player.next", {});
    expect(r.ok).toBe(true);
    expect(clicks).toEqual(["next"]);
    adapter.stop();
  });

  it("seek clamps to the seekable range and rejects stale occurrences", async () => {
    const { video } = mountPlayer();
    const adapter = new YouTubeMusicAdapter();
    await adapter.start();
    const occ = adapter.snapshot().track!.occurrenceId;
    const r = await adapter.exec("r3", "player.seek", {
      occurrenceId: occ,
      positionSeconds: 500, // beyond duration 200 — must clamp
    });
    expect(r.ok).toBe(true);
    expect(video.currentTime).toBe(200);
    const stale = await adapter.exec("r4", "player.seek", {
      occurrenceId: "occ-dead",
      positionSeconds: 10,
    });
    expect(stale.ok).toBe(false);
    if (!stale.ok) expect(stale.error.code).toBe("stale_target");
    adapter.stop();
  });

  it("volume desired values reconcile against observed state", async () => {
    const { video } = mountPlayer();
    const adapter = new YouTubeMusicAdapter();
    await adapter.start();
    const r = await adapter.exec("r5", "player.setVolume", { volume: 0.4 });
    expect(r.ok).toBe(true);
    expect(video.volume).toBeCloseTo(0.4, 2);
    adapter.stop();
  });

  it("reports pending_outcome when the player never confirms", async () => {
    mountPlayer();
    // No transport button and a media.play that produces no observable change.
    document.getElementById("play-pause-button")!.remove();
    const adapter = new YouTubeMusicAdapter();
    await adapter.start();
    const video = document.querySelector("video")!;
    video.play = () => new Promise(() => undefined); // hangs, emits nothing
    vi.useFakeTimers();
    try {
      const p = adapter.exec("r6", "player.play", {});
      await vi.advanceTimersByTimeAsync(6000);
      const r = await p;
      expect(r.ok).toBe(false);
      if (!r.ok) {
        expect(["pending_outcome", "user_interaction_required"]).toContain(
          r.error.code,
        );
      }
    } finally {
      vi.useRealTimers();
      adapter.stop();
    }
  });
});
