"""License notices for a frozen app, shared by both PyInstaller specs.

PyInstaller copies Qt, Qt WebEngine, PySide6, the Python packages and the
CPython interpreter into each app; they keep their own licenses. This lists
exactly the files Analysis collected, runs scripts/python-notices.py over
them (it fails on a component without license text, see
packaging/licenses/python-notices.toml) and returns the notices as data
entries, so they land in Contents/Resources before BUNDLE signs the app.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def notices_datas(analysis, workpath, app_name):
    notices = Path(workpath) / "notices"
    notices.mkdir(parents=True, exist_ok=True)
    work = Path(workpath).resolve()
    # Files PyInstaller generates in workpath (base_library.zip holds the
    # standard library, which --cpython covers) belong to no distribution.
    collected = sorted({
        entry[1] for entry in analysis.scripts + analysis.pure + analysis.binaries + analysis.datas
        if entry[1] and Path(entry[1]).is_file() and work not in Path(entry[1]).resolve().parents
    })
    files_from = notices / "collected-files.txt"
    files_from.write_text("\n".join(collected) + "\n", encoding="utf-8")
    subprocess.run(
        [sys.executable, "-I", str(ROOT / "scripts" / "python-notices.py"),
         "--files-from", str(files_from), "--cpython", "--own", "amberfader",
         "--own-path", str(ROOT / "native"), "--own-path", str(ROOT / "packaging"),
         "--overrides", str(ROOT / "packaging" / "licenses" / "python-notices.toml"),
         "--rust-licenses", str(ROOT / "packaging" / "licenses" / "Rust-Licenses.html"),
         "--title", f"{app_name} bundles the software below.",
         "--out", str(notices / "Third-Party-Notices.txt")],
        check=True,
    )
    # PyInstaller puts data files of a .app in Contents/Resources.
    return [
        ("Third-Party-Notices.txt", str(notices / "Third-Party-Notices.txt"), "DATA"),
        ("Rust-Licenses.html", str(notices / "Rust-Licenses.html"), "DATA"),
    ]
