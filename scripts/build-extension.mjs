// Builds the unpacked extension into dist/extension/: bundles every TypeScript
// entry point with esbuild and copies the static files (manifest, HTML, CSS,
// icons) alongside. Output layout is what manifest.json and the HTML pages
// reference; `web-ext run -s dist/extension` loads it directly.
import { build } from "esbuild";
import { cp, mkdir, rm } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const SRC = join(root, "extension");
const OUT = join(root, "dist", "extension");

const entries = {
  "js/background": "src/background/index.ts",
  "js/content": "src/content/index.ts",
  "js/controller": "src/controller/controller.ts",
  "js/player": "src/popup/player.ts",
  "js/search": "src/popup/search.ts",
  "js/options": "src/options/options.ts",
};

const statics = [
  ["manifest.json", "manifest.json"],
  ["src/controller/controller.html", "controller.html"],
  ["src/popup/player.html", "player.html"],
  ["src/popup/player.css", "css/player.css"],
  ["src/popup/search.html", "search.html"],
  ["src/options/options.html", "options.html"],
  ["src/options/options.css", "css/options.css"],
  ["icons/icon.svg", "icons/icon.svg"],
  ["icons/icon-48.png", "icons/icon-48.png"],
  ["icons/icon-96.png", "icons/icon-96.png"],
  ["_locales", "_locales"],
];

await rm(OUT, { recursive: true, force: true });
await mkdir(OUT, { recursive: true });

await build({
  entryPoints: Object.fromEntries(
    Object.entries(entries).map(([out, src]) => [out, join(SRC, src)]),
  ),
  outdir: OUT,
  bundle: true,
  format: "iife",
  target: "firefox128",
  sourcemap: true,
  logLevel: "info",
  // Content scripts and background event pages are standalone bundles; keep
  // each entry self-contained (no code splitting).
  splitting: false,
});

for (const [src, dst] of statics) {
  const to = join(OUT, dst);
  await mkdir(dirname(to), { recursive: true });
  await cp(join(SRC, src), to, { recursive: true });
}

console.log(`extension built -> ${OUT}`);
