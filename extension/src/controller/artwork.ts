// Artwork pipeline. Shared by the controller page (native mode) and the
// prototype player window: page supplies an image URL; we fetch it here under
// an extension principal, validate, downscale, and emit an asset event.
//
// Rules (spec §6): HTTPS only, narrow origin allowlist discovered in Phase 0,
// no credentials, redirect validation, 2 MiB input cap, <=256 px and <=64 KiB
// output, 20 MiB cache, bounded concurrent fetches, stale results discarded.
import type { AssetData } from "../protocol/types";

const MAX_INPUT_BYTES = 2 * 1024 * 1024;
const MAX_EDGE = 256;
const MAX_OUTPUT_BYTES = 64 * 1024;
const CACHE_BUDGET_BYTES = 20 * 1024 * 1024;
const MAX_CONCURRENT = 3;
const FETCH_TIMEOUT_MS = 10000;

// UNVERIFIED until Phase 0 captures the real artwork origins. The manifest
// gains optional host_permissions for exactly these origins only after the
// probe confirms them.
export const ARTWORK_HOST_ALLOWLIST: RegExp[] = [
  /^lh3\.googleusercontent\.com$/,
  /^i\d*\.ytimg\.com$/,
  /^yt\d\.ggpht\.com$/,
  /^music\.youtube\.com$/,
];

export interface ArtworkRequest {
  artworkId: string;
  occurrenceId: string | null;
  url: string;
}

export function allowedArtworkUrl(url: string): boolean {
  let u: URL;
  try {
    u = new URL(url);
  } catch {
    return false;
  }
  if (u.protocol !== "https:") return false;
  return ARTWORK_HOST_ALLOWLIST.some((re) => re.test(u.hostname));
}

interface CacheEntry {
  asset: AssetData;
  bytes: number;
}

export class ArtworkService {
  private readonly cache = new Map<string, CacheEntry>();
  private cacheBytes = 0;
  private inFlight = 0;
  private readonly waiters: Array<() => void> = [];
  private epoch = 0;

  // Decoders differ between an extension page (DOM canvas) and tests; inject.
  private readonly decode: (bytes: Uint8Array, mime: string) => Promise<{
    bitmap: ImageBitmap | { width: number; height: number };
    draw?: (bitmap: unknown, w: number, h: number) => Promise<Blob>;
  }>;

  constructor(
    decode?: (bytes: Uint8Array, mime: string) => Promise<{
      bitmap: ImageBitmap | { width: number; height: number };
      draw?: (bitmap: unknown, w: number, h: number) => Promise<Blob>;
    }>,
    private readonly fetchImpl: typeof fetch = fetch,
  ) {
    this.decode =
      decode ??
      (async (bytes, mime) => {
        const blob = new Blob([bytes], { type: mime });
        const bitmap = await createImageBitmap(blob);
        return { bitmap };
      });
  }

  // Returns the asset event data, or null when the request was
  // invalid/superseded/failed (callers emit a placeholder in that case).
  async fetchAsset(req: ArtworkRequest): Promise<AssetData | null> {
    if (!allowedArtworkUrl(req.url)) return null;
    const cached = this.cache.get(req.artworkId);
    if (cached) return cached.asset;

    const epoch = ++this.epoch;
    await this.acquire();
    try {
      const data = await this.download(req.url);
      if (!data) return null;
      const asset = await this.normalize(req, data.bytes, data.mime);
      if (epoch !== this.epoch) return null; // superseded while decoding
      if (!asset) return null;
      this.store(req.artworkId, asset);
      return asset;
    } finally {
      this.release();
    }
  }

  invalidateAll(): void {
    this.epoch += 1;
  }

  private async acquire(): Promise<void> {
    if (this.inFlight < MAX_CONCURRENT) {
      this.inFlight += 1;
      return;
    }
    await new Promise<void>((resolve) => this.waiters.push(resolve));
    this.inFlight += 1;
  }

  private release(): void {
    this.inFlight -= 1;
    this.waiters.shift()?.();
  }

  private async download(
    url: string,
  ): Promise<{ bytes: Uint8Array; mime: string } | null> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
    try {
      const resp = await this.fetchImpl(url, {
        credentials: "omit",
        redirect: "follow",
        signal: controller.signal,
        cache: "default",
      });
      if (!resp.ok) return null;
      if (resp.url) {
        // Redirects re-validated: the final URL must also be allowlisted.
        if (!allowedArtworkUrl(resp.url)) return null;
      }
      const mime = (resp.headers.get("content-type") ?? "").split(";")[0]!.trim();
      if (!["image/jpeg", "image/png", "image/webp"].includes(mime)) return null;
      const len = Number(resp.headers.get("content-length") ?? 0);
      if (len > MAX_INPUT_BYTES) return null;
      const buf = await resp.arrayBuffer();
      if (buf.byteLength > MAX_INPUT_BYTES) return null;
      return { bytes: new Uint8Array(buf), mime };
    } catch {
      return null;
    } finally {
      clearTimeout(timer);
    }
  }

  private async normalize(
    req: ArtworkRequest,
    bytes: Uint8Array,
    mime: string,
  ): Promise<AssetData | null> {
    let decoded;
    try {
      decoded = await this.decode(bytes, mime);
    } catch {
      return null;
    }
    const { width, height } = decoded.bitmap;
    if (!width || !height || width > 4096 || height > 4096) return null;
    const scale = Math.min(1, MAX_EDGE / Math.max(width, height));
    const w = Math.max(1, Math.round(width * scale));
    const h = Math.max(1, Math.round(height * scale));

    // Try canvas re-encode; fall back to passthrough bytes when they already
    // satisfy the caps (small source thumbs) and a decoder path exists.
    let outBytes: Uint8Array | null = null;
    let outMime: AssetData["mime"] = "image/jpeg";
    if (decoded.draw) {
      try {
        const blob = await decoded.draw(decoded.bitmap, w, h);
        if (blob && blob.size <= MAX_OUTPUT_BYTES) {
          outBytes = new Uint8Array(await blob.arrayBuffer());
          outMime = "image/jpeg";
        }
      } catch {
        outBytes = null;
      }
    }
    if (!outBytes) {
      if (bytes.byteLength <= MAX_OUTPUT_BYTES && width <= MAX_EDGE && height <= MAX_EDGE) {
        outBytes = bytes;
        outMime = mime as AssetData["mime"];
      } else {
        return null;
      }
    }

    const base64 = bytesToBase64(outBytes);
    if (base64.length > 87382) return null; // schema cap: 64 KiB binary
    return {
      artworkId: req.artworkId,
      occurrenceId: req.occurrenceId,
      mime: outMime,
      width: w,
      height: h,
      dataBase64: base64,
    };
  }

  private store(key: string, asset: AssetData): void {
    const bytes = asset.dataBase64.length;
    // LRU-ish eviction: Map insertion order approximates recency for our use.
    while (this.cacheBytes + bytes > CACHE_BUDGET_BYTES && this.cache.size > 0) {
      const [k, v] = this.cache.entries().next().value as [string, CacheEntry];
      this.cache.delete(k);
      this.cacheBytes -= v.bytes;
    }
    this.cache.set(key, { asset, bytes });
    this.cacheBytes += bytes;
  }
}

function bytesToBase64(bytes: Uint8Array): string {
  let bin = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    bin += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(bin);
}
