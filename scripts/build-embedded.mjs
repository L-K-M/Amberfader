// Builds the page scripts into the Python package, where amberfader.embedded
// injects them into the YouTube Music page:
//   adapter.js    site adapter, command executor and QWebChannel bridge
//                 (application world)
//   ad-filter.js  removes ad data from player responses (main world, only
//                 while ad blocking is on)
import { build } from "esbuild";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const OUT_DIR = join(root, "native", "amberfader", "embedded", "web");
const ENTRIES = [
  ["embedded/index.ts", "adapter.js"],
  ["adfilter/index.ts", "ad-filter.js"],
];

for (const [entry, name] of ENTRIES) {
  await build({
    entryPoints: [join(root, "web", "src", entry)],
    outfile: join(OUT_DIR, name),
    bundle: true,
    format: "iife",
    // PySide6 6.8 ships Qt WebEngine on Chromium 122.
    target: "chrome122",
    logLevel: "info",
  });
}

console.log(`page scripts built -> ${OUT_DIR}`);
