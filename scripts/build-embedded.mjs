// Builds the page bundle (site adapter, command executor and QWebChannel
// bridge) into the Python package, where amberfader.embedded injects it into
// the YouTube Music page at startup.
import { build } from "esbuild";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const OUT = join(root, "native", "amberfader", "embedded", "web", "adapter.js");

await build({
  entryPoints: [join(root, "web", "src", "embedded", "index.ts")],
  outfile: OUT,
  bundle: true,
  format: "iife",
  // PySide6 6.8 ships Qt WebEngine on Chromium 122.
  target: "chrome122",
  logLevel: "info",
});

console.log(`embedded page bundle built -> ${OUT}`);
