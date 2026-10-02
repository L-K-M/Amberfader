// ArtworkService: allowlist, size caps, cache bound, superseded discard.
import { afterEach, describe, expect, it, vi } from "vitest";
import manifest from "../../manifest.json";
import capturedProbe from "../fixtures/artwork-probe-2026-10-02.json";
import {
  allowedArtworkUrl,
  ArtworkService,
} from "../../src/controller/artwork";

function fakeFetch(
  body: Uint8Array,
  mime = "image/png",
  extra?: { status?: number; redirectedTo?: string },
): typeof fetch {
  return vi.fn(async () => ({
    ok: (extra?.status ?? 200) >= 200 && (extra?.status ?? 200) < 300,
    status: extra?.status ?? 200,
    url: extra?.redirectedTo ?? "https://lh3.googleusercontent.com/img",
    headers: {
      get: (k: string) =>
        k.toLowerCase() === "content-type"
          ? mime
          : k.toLowerCase() === "content-length"
            ? String(body.byteLength)
            : null,
    },
    arrayBuffer: async () => body.buffer.slice(0),
  })) as unknown as typeof fetch;
}

const tinyDecode = (_bytes: Uint8Array, _mime: string) =>
  Promise.resolve({
    bitmap: { width: 64, height: 64 },
  });

describe("allowedArtworkUrl", () => {
  it("allows and declares access to the cover origin observed in the live probe", async () => {
    const origin = capturedProbe.artwork.playerArtwork[0]!.sourceOrigin!;
    expect(allowedArtworkUrl(`${origin}/captured-cover`)).toBe(true);
    expect(manifest.host_permissions).toContain(`${origin}/*`);
    const fetch = fakeFetch(new Uint8Array(100), "image/png", {
      redirectedTo: `${origin}/captured-cover`,
    });
    const service = new ArtworkService(tinyDecode, fetch);
    expect(await service.fetchAsset({
      artworkId: "captured-cover", occurrenceId: "current-track", url: `${origin}/captured-cover`,
    })).toMatchObject({ artworkId: "captured-cover", occurrenceId: "current-track" });
    expect(fetch).toHaveBeenCalledOnce();
    expect(allowedArtworkUrl("http://yt3.googleusercontent.com/cover")).toBe(false);
    expect(allowedArtworkUrl("https://yt3.googleusercontent.com.attacker.example/cover")).toBe(false);
    expect(allowedArtworkUrl("https://yt3.googleusercontent.com:444/cover")).toBe(false);
  });

  it("accepts allowlisted https image hosts only", () => {
    expect(allowedArtworkUrl("https://lh3.googleusercontent.com/a=b")).toBe(true);
    expect(allowedArtworkUrl("https://i.ytimg.com/vi/x/hq.jpg")).toBe(true);
    expect(allowedArtworkUrl("http://lh3.googleusercontent.com/a=b")).toBe(false);
    expect(allowedArtworkUrl("https://evil.example.com/x.png")).toBe(false);
    expect(allowedArtworkUrl("javascript:alert(1)")).toBe(false);
    expect(allowedArtworkUrl("not a url")).toBe(false);
  });
});

describe("ArtworkService", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shares a slow download across repeated state samples", async () => {
    let finish!: () => void;
    const ready = new Promise<void>((resolve) => { finish = resolve; });
    const response = fakeFetch(new Uint8Array(100));
    const fetch = vi.fn(async (...args: Parameters<typeof globalThis.fetch>) => {
      await ready;
      return response(...args);
    });
    const service = new ArtworkService(tinyDecode, fetch);
    const request = { artworkId: "cover", occurrenceId: "track", url: "https://lh3.googleusercontent.com/img" };
    const pending = [service.fetchAsset(request), service.fetchAsset(request), service.fetchAsset(request)];
    await Promise.resolve();
    finish();
    const assets = await Promise.all(pending);
    expect(fetch).toHaveBeenCalledOnce();
    expect(assets.every((asset) => asset !== null)).toBe(true);
  });

  it("binds cached artwork to the current track occurrence", async () => {
    const service = new ArtworkService(tinyDecode, fakeFetch(new Uint8Array(100)));
    const request = { artworkId: "cover", occurrenceId: "first", url: "https://lh3.googleusercontent.com/img" };
    await service.fetchAsset(request);
    const asset = await service.fetchAsset({ ...request, occurrenceId: "second" });
    expect(asset?.occurrenceId).toBe("second");
  });

  it("discards an older download after switching to a cached cover", async () => {
    let finish!: () => void;
    const ready = new Promise<void>((resolve) => { finish = resolve; });
    const response = fakeFetch(new Uint8Array(100));
    const fetch = vi.fn(async (...args: Parameters<typeof globalThis.fetch>) => {
      if (typeof args[0] === "string" && args[0].endsWith("slow")) await ready;
      return response(...args);
    });
    const service = new ArtworkService(tinyDecode, fetch);
    const cached = { artworkId: "cached", occurrenceId: "cached-track", url: "https://lh3.googleusercontent.com/cached" };
    await service.fetchAsset(cached);
    const old = service.fetchAsset({ artworkId: "old", occurrenceId: "old-track", url: "https://lh3.googleusercontent.com/slow" });
    expect(await service.fetchAsset(cached)).not.toBeNull();
    const repeatedCached = service.fetchAsset(cached);
    finish();
    expect(await old).toBeNull();
    expect(await repeatedCached).toMatchObject({ artworkId: "cached", occurrenceId: "cached-track" });
  });

  it("downscales a full-size cover with the default browser decoder", async () => {
    vi.stubGlobal("createImageBitmap", async () => ({ width: 600, height: 600 }));
    const drawImage = vi.fn();
    vi.stubGlobal("document", {
      createElement: () => ({
        getContext: () => ({ drawImage }),
        toBlob: (callback: (blob: Blob) => void) => callback(new Blob([new Uint8Array(100)], { type: "image/jpeg" })),
      }),
    });
    const service = new ArtworkService(undefined, fakeFetch(new Uint8Array(100)));
    const asset = await service.fetchAsset({ artworkId: "cover", occurrenceId: "track", url: "https://lh3.googleusercontent.com/img" });
    expect(asset).toMatchObject({ width: 256, height: 256, mime: "image/jpeg" });
    expect(drawImage).toHaveBeenCalledOnce();
  });

  it("invalidates old artwork when the new track proposes a disallowed origin", async () => {
    let finish!: () => void;
    const ready = new Promise<void>((resolve) => { finish = resolve; });
    const response = fakeFetch(new Uint8Array(100));
    const fetch = vi.fn(async (...args: Parameters<typeof globalThis.fetch>) => {
      await ready;
      return response(...args);
    });
    const service = new ArtworkService(tinyDecode, fetch);
    const old = service.fetchAsset({ artworkId: "old", occurrenceId: "old-track", url: "https://lh3.googleusercontent.com/img" });
    expect(await service.fetchAsset({ artworkId: "new", occurrenceId: "new-track", url: "https://unapproved.example/cover" })).toBeNull();
    finish();
    expect(await old).toBeNull();
  });

  it("fetches, normalizes within caps, and caches by artworkId", async () => {
    const svc = new ArtworkService(
      tinyDecode,
      fakeFetch(new Uint8Array(1000)),
    );
    const req = {
      artworkId: "a1",
      occurrenceId: "occ",
      url: "https://lh3.googleusercontent.com/img",
    };
    const a1 = await svc.fetchAsset(req);
    expect(a1).not.toBeNull();
    expect(a1!.width).toBeLessThanOrEqual(256);
    expect(a1!.dataBase64.length).toBeLessThanOrEqual(87382);
    const a2 = await svc.fetchAsset(req);
    expect(a2).toBe(a1); // cached
  });

  it("rejects non-allowlisted or non-https URLs without fetching", async () => {
    const f = fakeFetch(new Uint8Array(10));
    const svc = new ArtworkService(tinyDecode, f);
    expect(
      await svc.fetchAsset({
        artworkId: "x",
        occurrenceId: null,
        url: "https://evil.example.com/x.png",
      }),
    ).toBeNull();
    expect(
      await svc.fetchAsset({
        artworkId: "y",
        occurrenceId: null,
        url: "http://lh3.googleusercontent.com/x.png",
      }),
    ).toBeNull();
    expect(f).not.toHaveBeenCalled();
  });

  it("rejects oversized input", async () => {
    const big = new Uint8Array(2 * 1024 * 1024 + 1);
    const svc = new ArtworkService(tinyDecode, fakeFetch(big));
    expect(
      await svc.fetchAsset({
        artworkId: "big",
        occurrenceId: null,
        url: "https://lh3.googleusercontent.com/img",
      }),
    ).toBeNull();
  });

  it("rejects non-image content types", async () => {
    const svc = new ArtworkService(
      tinyDecode,
      fakeFetch(new Uint8Array(500), "text/html"),
    );
    expect(
      await svc.fetchAsset({
        artworkId: "html",
        occurrenceId: null,
        url: "https://lh3.googleusercontent.com/img",
      }),
    ).toBeNull();
  });

  it("rejects redirects escaping the allowlist", async () => {
    const svc = new ArtworkService(
      tinyDecode,
      fakeFetch(new Uint8Array(100), "image/png", {
        redirectedTo: "https://evil.example.com/x.png",
      }),
    );
    expect(
      await svc.fetchAsset({
        artworkId: "redir",
        occurrenceId: null,
        url: "https://lh3.googleusercontent.com/img",
      }),
    ).toBeNull();
  });
});
