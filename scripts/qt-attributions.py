#!/usr/bin/env python3
"""Vendor Qt's third-party attributions for one Qt minor version as plain text.

PySide6/shiboken6 wheels ship Qt's libraries (and Qt WebEngine's Chromium,
FFmpeg, ICU, ...) without any license text. Qt publishes the attribution of
every bundled third-party component, with its license text, in the
"Licenses Used in Qt" and "Qt WebEngine Licensing" documentation pages.
This script fetches those index pages for a version, follows every
attribution link, and writes one deterministic text file to commit next to
the LGPL/GPL texts. Re-run it whenever the shipped Qt version changes.

  qt-attributions.py 6.11.2 --out packaging/licenses/qt-6.11-attributions.txt

Pass the exact Qt version the wheels ship (PySide6 X.Y.Z ships Qt X.Y.Z).
The pages describe only the newest patch release of that minor version; the
header records both, and the script warns when they differ so the
attributions can be checked against the shipped release. Python 3.9+
standard library only; needs network.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import re
import sys
import time
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

RULE = "-" * 72  # nested inside a python-notices entry, which uses "="
INDEXES = {
    "licenses-used-in-qt.html": re.compile(r'href="([a-z0-9-]+-attribution-[^"#/]+\.html)"'),
    "qtwebengine-licensing.html": re.compile(r'href="(qtwebengine-3rdparty-[^"#/]+\.html)"'),
}
OPTIONAL_INDEXES = {"qtwebengine-licensing.html"}


def fetch(url, tries=3):
    for attempt in range(tries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "qt-attributions/1"})
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read().decode("utf-8")
        except OSError as error:
            if attempt == tries - 1:
                sys.exit(f"qt-attributions: cannot fetch {url}: {error}")
            time.sleep(2 * (attempt + 1))
    return ""


class Text(HTMLParser):
    """HTML to plain text: paragraphs, list items, verbatim <pre>, external link targets."""

    BREAK2 = {"p", "div", "h1", "h2", "h3", "h4", "table", "ul", "ol", "pre"}
    BREAK1 = {"br", "li", "tr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.pre, self.href = [], 0, None

    def handle_starttag(self, tag, attrs):
        if tag in self.BREAK2:
            self.parts.append("\n\n")
        elif tag in self.BREAK1:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("- ")
        if tag == "pre":
            self.pre += 1
        if tag == "a":
            self.href = dict(attrs).get("href")

    def handle_endtag(self, tag):
        if tag == "pre":
            self.pre -= 1
        if tag in self.BREAK2:
            self.parts.append("\n\n")
        if tag == "a":
            if self.href and self.href.startswith(("http://", "https://")):
                self.parts.append(f" <{self.href}>")
            self.href = None

    def handle_data(self, data):
        if self.pre:
            # Qt's generator escapes <pre> contents twice (&amp;quot;).
            self.parts.append(html.unescape(data))
        else:
            self.parts.append(re.sub(r"\s+", " ", data))

    def text(self):
        joined = "".join(self.parts)
        lines = [line.rstrip() for line in joined.split("\n")]
        return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"


def to_text(fragment):
    parser = Text()
    parser.feed(fragment)
    parser.close()
    return parser.text()


def component(page):
    title = re.search(r'<h1 class="title"[^>]*>(.*?)</h1>', page, re.S)
    body = re.search(r'<div class="descr" id="details">(.*?)<!-- @@@', page, re.S)
    if not title or not body:
        return None, None
    return to_text(title.group(1)).strip(), to_text(body.group(1))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("version", help="shipped Qt version, e.g. 6.11.2 (6.11 accepted, without the check)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--no-webengine", action="store_true", help="skip Qt WebEngine's Chromium components")
    parser.add_argument("--delay", type=float, default=0.1, help="seconds between requests")
    args = parser.parse_args()
    if not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", args.version):
        parser.error("version must be MAJOR.MINOR.PATCH, e.g. 6.11.2")
    minor = ".".join(args.version.split(".")[:2])
    base = f"https://doc.qt.io/qt-{minor}/"

    links, documented = [], ""
    for index, pattern in INDEXES.items():
        if args.no_webengine and index in OPTIONAL_INDEXES:
            continue
        page = fetch(base + index)
        documented = documented or next(iter(re.findall(r"Qt (\d+\.\d+\.\d+)", page)), "")
        found = list(dict.fromkeys(pattern.findall(page)))
        if not found:
            sys.exit(f"qt-attributions: no attribution links in {base + index}; the page layout changed")
        links += [link for link in found if link not in links]

    shipped = args.version if args.version.count(".") == 2 else ""
    if shipped and documented != shipped:
        print(f"qt-attributions: warning: the pages document Qt {documented or 'an unknown patch'}, the "
              f"artifact ships Qt {shipped}; compare the component versions with the Qt {shipped} "
              "source before committing", file=sys.stderr)
    sections = [f"Qt {minor} third-party attributions\n\n"
                f"From {base}licenses-used-in-qt.html"
                + ("" if args.no_webengine else f"\nand {base}qtwebengine-licensing.html")
                + f"\n(documentation of Qt {documented or minor + '.x'}"
                + (f"; the artifact ships Qt {shipped}" if shipped and shipped != documented else "")
                + ").\nQt itself, Qt for Python (PySide6) and shiboken6 are available under\n"
                "LGPL-3.0-only, GPL-2.0-only or GPL-3.0-only; some Qt add-on modules only\n"
                "under GPL-3.0-only, and Qt's tools (designer, linguist, qml, ...) under\n"
                "GPL-3.0-only WITH Qt-GPL-exception-1.0. Those texts ship next to this file.\n"]
    seen, failures = {}, []
    for link in links:
        time.sleep(args.delay)
        name, body = component(fetch(base + link))
        if not name or not body.strip():
            failures.append(base + link)
            continue
        digest = hashlib.sha256(body.encode()).hexdigest()
        if len(body) >= 2000 and digest in seen:
            body = f"(Same text as {seen[digest]} above.)\n"
        else:
            seen.setdefault(digest, name)
        sections.append(f"\n{RULE}\n{name}\n{base}{link}\n\n{body}")
    if failures:
        sys.exit("qt-attributions: no attribution text found in:\n  " + "\n  ".join(failures))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(sections), encoding="utf-8", newline="\n")
    print(f"qt-attributions: wrote {args.out} ({len(links)} components)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
