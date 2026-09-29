// ArtworkService: allowlist, size caps, cache bound, superseded discard.
import { describe, expect, it, vi } from "vitest";
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
