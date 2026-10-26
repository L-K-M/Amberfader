#!/usr/bin/env python3
"""Fetch CPython's notices for the third-party code built into the interpreter.

An interpreter's LICENSE.txt holds only the PSF license history and terms.
The notices for code compiled into CPython itself (Mersenne Twister, expat,
libmpdec, OpenSSL in the macOS/Windows installers, libffi, zlib, ...) live
in the "Licenses and Acknowledgements for Incorporated Software" section of
Doc/license.rst. This script downloads that file at the release tag, keeps
that section, strips reST role markup, and writes a text file to commit and
list in the [cpython] override of python-notices.

  fetch-cpython-notices.py 3.12.10 --out packaging/licenses/cpython-3.12-incorporated.txt

Python 3.9+ standard library only; needs network.
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.request
from pathlib import Path

HEADING = "Licenses and Acknowledgements for Incorporated Software"
# Subsections present in every CPython 3 release; their absence means a truncated or changed file.
REQUIRED = ("Mersenne Twister", "expat", "libffi", "zlib")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("version", help="exact CPython version, e.g. 3.12.10 (python3 -c 'import platform; "
                                        "print(platform.python_version())')")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"\d+\.\d+\.\d+", args.version):
        parser.error("version must be MAJOR.MINOR.PATCH")
    url = f"https://raw.githubusercontent.com/python/cpython/v{args.version}/Doc/license.rst"
    with urllib.request.urlopen(url, timeout=60) as response:
        source = response.read().decode("utf-8")
    start = source.find(HEADING)
    if start < 0:
        sys.exit(f"fetch-cpython-notices: '{HEADING}' not found in {url}")
    # Keep the section only: stop at the next heading underlined like this one.
    lines = source[start:].split("\n")
    underline = lines[1] if len(lines) > 1 else ""
    if not underline or underline.strip(underline[0]):
        sys.exit(f"fetch-cpython-notices: '{HEADING}' in {url} is not a section heading")
    end = next((i for i in range(2, len(lines) - 1)
                if lines[i].strip() and lines[i + 1].startswith(underline[0] * 3)
                and not lines[i + 1].strip(underline[0])), len(lines))
    text = "\n".join(lines[:end])
    missing = [name for name in REQUIRED if not re.search(rf"(?m)^{re.escape(name)}\n[-=~^]{{3,}}$", text)]
    if missing:
        sys.exit(f"fetch-cpython-notices: subsections {', '.join(missing)} not found in {url}; "
                 "the layout changed, check the output by hand")
    text = re.sub(r"(?m)^\.\. _[^:]+:\n", "", text)                   # reST labels
    text = re.sub(r":[a-z:]+:`~?([^`<]*?)\s*(?:<[^>]+>)?`", r"\1", text)  # :mod:`x <y>` roles
    text = text.replace("``", "")
    header = (f"CPython {args.version}: {HEADING}\n"
              f"From {url}.\nThe interpreter's own PSF license is in its LICENSE.txt.\n\n")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(header + text.rstrip() + "\n", encoding="utf-8", newline="\n")
    print(f"fetch-cpython-notices: wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
