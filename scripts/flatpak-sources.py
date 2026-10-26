#!/usr/bin/env python3
"""List the exact sources of every module bundled in a Flatpak, from its manifests.

  flatpak-sources.py FILES_DIR_OR_MANIFEST... --app NAME [--out SOURCES.txt]

flatpak-builder records the resolved manifest of the app in /app/manifest.json
and, when the app is built on a BaseApp ("base:"), each base's manifest in
/app/manifest-base-N.json. Everything those modules install is bundled in the
.flatpak; the runtime (runtime: org.kde.Platform, org.gnome.Platform, ...) is
not: Flathub distributes it separately with its own notices and sources.

Pass the flatpak-builder build directory's files/ (or the manifest JSON files
directly). The script writes SOURCES.txt: per module, its git URL and commit
or tag, or its archive URL and SHA-256, marking which come from a BaseApp,
and names the runtime as not bundled. It fails when a bundled module has a
remote source without a pinned commit, tag or checksum, so the pointers stay
exact. Local "dir"/"file" sources are reported as part of the app's (or the
BaseApp's Flathub) repository. Includes given as file names are resolved next
to the manifest when present. --allow MODULE=REASON accepts one module's
unpinned source with a recorded reason. Python 3.8+, standard library only.
"""

import argparse
import glob
import json
import os
import sys
from pathlib import Path

RULE = "=" * 72


def die(message):
    sys.exit(f"flatpak-sources: error: {message}")


def load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as error:
        die(f"{path}: {error}")


def modules(items, base_dir, origin, out, errors, home="this repository"):
    for item in items or []:
        if isinstance(item, str):
            included = base_dir / item
            if included.exists():
                data = load(included)
                nested = data if isinstance(data, list) else [data]
                modules(nested, included.parent, origin, out, errors, home)
            else:
                errors.append(f"{origin}: module include {item!r} is not resolved (pass the installed "
                              f"/app/manifest*.json, which inlines includes)")
            continue
        if item.get("disabled"):
            continue
        name = item.get("name", "?")
        sources = []
        for src in item.get("sources", []):
            if isinstance(src, str):
                included = base_dir / src
                src = load(included) if included.exists() else {"type": "unresolved", "path": src}
                if isinstance(src, list):
                    sources.extend(s for s in src if isinstance(s, dict))
                    continue
            sources.append(src)
        described = []
        for src in sources:
            kind = src.get("type", "?")
            if kind == "git":
                pin = src.get("commit") or src.get("tag")
                if not src.get("url") or not pin:
                    errors.append(f"{origin}: module {name}: git source without url and commit/tag")
                    continue
                ref = " ".join(filter(None, [f"tag {src['tag']}" if src.get("tag") else "",
                                             f"commit {src['commit']}" if src.get("commit") else ""]))
                described.append(f"git {src['url']} {ref}")
            elif kind in ("archive", "file", "extra-data") and (src.get("url") or src.get("urls")):
                url = src.get("url") or src["urls"][0]
                algo = next((a for a in ("sha256", "sha512", "sha1", "md5") if src.get(a)), None)
                if not algo:
                    errors.append(f"{origin}: module {name}: {url} has no checksum")
                    continue
                described.append(f"{kind} {url} {algo}:{src[algo]}")
            elif kind in ("dir", "file", "script", "shell", "patch", "inline"):
                local = src.get("path") or src.get("dest-filename") or ""
                described.append(f"{kind} {local}".rstrip() + f" (in {home})")
            elif kind == "unresolved":
                errors.append(f"{origin}: module {name}: source include {src['path']!r} is not resolved")
            else:
                described.append(f"{kind} {json.dumps(src, sort_keys=True)}")
        out.append({"name": name, "origin": origin, "sources": described})
        modules(item.get("modules"), base_dir, origin, out, errors, home)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("inputs", nargs="+", help="build dir files/ or manifest JSON files")
    parser.add_argument("--app", required=True, help="product name for the header")
    parser.add_argument("--out", help="write SOURCES.txt here (default: stdout)")
    parser.add_argument("--allow", action="append", default=[], metavar="MODULE=REASON",
                        help="accept one module's unpinned or unresolved sources, with a recorded reason")
    args = parser.parse_args()
    allowed = {}
    for item in args.allow:
        module, _, reason = item.partition("=")
        if not reason.strip():
            die(f"--allow {item!r} needs MODULE=REASON")
        allowed[module] = reason.strip()

    manifests = []
    for path in args.inputs:
        if os.path.isdir(path):
            found = sorted(glob.glob(os.path.join(path, "manifest*.json")))
            if not found:
                die(f"{path} has no manifest*.json; pass flatpak-builder's build directory files/")
            manifests += found
        else:
            manifests.append(path)
    entries, errors, runtimes = [], [], set()
    for path in manifests:
        data = load(path)
        app_id = data.get("id") or data.get("app-id") or Path(path).stem
        is_base = Path(path).name.startswith("manifest-base-")
        origin = f"BaseApp {app_id} {data.get('branch', '')}".strip() if is_base else f"app {app_id}"
        if data.get("runtime"):
            runtimes.add(f"{data['runtime']}//{data.get('runtime-version', '?')}")
        # Flathub keeps each BaseApp's manifest and local files in github.com/flathub/<id>.
        branch = data.get("branch")
        home = "this repository"
        if is_base:
            home = (f"https://github.com/flathub/{app_id}/tree/branch/{branch}" if branch
                    else f"https://github.com/flathub/{app_id}")
        modules(data.get("modules"), Path(path).resolve().parent, origin, entries, errors, home)
    kept = []
    for error in errors:
        module = next((m for m in allowed if f"module {m}:" in error), None)
        if module:
            print(f"flatpak-sources: allowed ({allowed[module]}): {error}", file=sys.stderr)
        else:
            kept.append(error)
            print(f"flatpak-sources: error: {error}", file=sys.stderr)
    if kept:
        sys.exit(1)

    lines = [f"Corresponding source for the modules bundled in the {args.app} Flatpak\n{RULE}\n\n",
             "Not bundled (installed separately from Flathub, with its own notices\nand sources): "
             + ", ".join(sorted(runtimes)) + "\n"]
    for entry in sorted(entries, key=lambda e: (not e["origin"].startswith("BaseApp"), e["origin"], e["name"].lower())):
        lines.append(f"\n{entry['name']} ({entry['origin']})\n")
        for source in entry["sources"] or ["(no sources: generated during the build)"]:
            lines.append(f"  {source}\n")
    text = "".join(lines)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"flatpak-sources: {len(entries)} modules from {len(manifests)} manifests -> {args.out}")
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
