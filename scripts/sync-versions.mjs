// Keeps every version field in the repo in lockstep with __version__ in
// native/amberfader/__init__.py (the release engine's version source). Run by
// RELEASE_POST_BUMP after the engine bumps __version__.
//   --check: verify all versions match; nonzero exit on drift.
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(fileURLToPath(import.meta.url), "../..");
const check = process.argv.includes("--check");

const SOURCE = "native/amberfader/__init__.py";
const version = readFileSync(join(root, SOURCE), "utf8").match(
  /^__version__ = "([^"]+)"/m,
)?.[1];
if (!version) {
  console.error(`no __version__ in ${SOURCE}`);
  process.exit(1);
}

const results = [];

function sync(path, re, render) {
  const file = join(root, path);
  const before = readFileSync(file, "utf8");
  const m = before.match(re);
  const found = m?.[1] ?? null;
  if (check) {
    results.push([path, found, found === version]);
    return;
  }
  if (found === version) {
    results.push([path, version, true]);
    return;
  }
  writeFileSync(file, before.replace(re, render(version)));
  results.push([path, `${found} -> ${version}`, true]);
}

sync("package.json", /"version": "([^"]+)"/, (v) => `"version": "${v}"`);
sync("pyproject.toml", /^version = "([^"]+)"/m, (v) => `version = "${v}"`);
sync(
  "uv.lock",
  /\[\[package\]\]\nname = "amberfader"\nversion = "([^"]+)"/,
  (v) => `[[package]]\nname = "amberfader"\nversion = "${v}"`,
);

let bad = false;
for (const [path, found, ok] of results) {
  if (!ok) bad = true;
  console.log(`${ok ? "  ok" : "DRIFT"}  ${path}: ${found}`);
}
if (check) {
  console.log(`version source: ${version} (${SOURCE})`);
  if (bad) process.exit(1);
}
