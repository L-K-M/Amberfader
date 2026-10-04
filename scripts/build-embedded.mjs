// Builds the page bundle for the embedded QtWebEngine prototype into the
// Python package, where amberfader.embedded loads it at startup. The bundle
// reuses the extension's site adapter and executor unchanged; only the
// transport (QWebChannel instead of the extension bus) differs.
import { build } from "esbuild";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const OUT = join(root, "native", "amberfader", "embedded", "web", "adapter.js");

await build({
  entryPoints: [join(root, "extension", "src", "embedded", "index.ts")],
  outfile: OUT,
  bundle: true,
  format: "iife",
  // PySide6 6.8 ships Qt WebEngine on Chromium 122.
  target: "chrome122",
  logLevel: "info",
});

console.log(`embedded page bundle built -> ${OUT}`);
