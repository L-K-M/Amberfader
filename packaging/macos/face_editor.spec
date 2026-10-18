# PyInstaller spec for Amberfader Face Editor.app (macOS, Apple silicon). Run
# through scripts/build-macos.sh, which sets AMBERFADER_VERSION and the icon
# path. Same collection rules as amberfader.spec; only the entry point,
# names and bundle id differ.
import os
import re
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).resolve().parents[1]
VERSION = os.environ["AMBERFADER_VERSION"]
ICON = os.environ["AMBERFADER_ICNS"]
# CFBundle versions must be numeric; a pre-release suffix (0.2.0rc1,
# 0.2.0-beta) stays in the .dmg name only.
_numeric = re.match(r"\d+(?:\.\d+)*", VERSION)
if _numeric is None:
    raise SystemExit(f"AMBERFADER_VERSION must start with a number: {VERSION!r}")
BUNDLE_VERSION = _numeric.group(0)

a = Analysis(
    [str(ROOT / "packaging" / "macos" / "launch_face_editor.py")],
    pathex=[str(ROOT / "native")],
    # Faces, schemas and the page scripts are package data.
    datas=collect_data_files("amberfader"),
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Amberfader Face Editor",
    console=False,
    target_arch="arm64",
    # Ad-hoc signature (D2: unsigned release); Apple silicon needs one.
    codesign_identity=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Amberfader Face Editor")
app = BUNDLE(
    coll,
    name="Amberfader Face Editor.app",
    icon=ICON,
    bundle_identifier="ch.lkmc.amberfader.face-editor",
    version=BUNDLE_VERSION,
    info_plist={
        "CFBundleName": "Amberfader Face Editor",
        "CFBundleDisplayName": "Amberfader Face Editor",
        "CFBundleShortVersionString": BUNDLE_VERSION,
        "CFBundleVersion": BUNDLE_VERSION,
        "LSMinimumSystemVersion": "13.0",
        "LSApplicationCategoryType": "public.app-category.graphics-design",
        "NSHighResolutionCapable": True,
        # Faces are plain folders with a face.json. Finder offers the editor
        # for them (Open With, a drop on the Dock icon) without becoming the
        # default app for every folder or JSON file.
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeName": "Amberfader Face Folder",
                "CFBundleTypeRole": "Editor",
                "LSHandlerRank": "Alternate",
                "LSItemContentTypes": ["public.folder"],
            },
            {
                "CFBundleTypeName": "Amberfader Face Manifest",
                "CFBundleTypeRole": "Editor",
                "LSHandlerRank": "Alternate",
                "LSItemContentTypes": ["public.json"],
            },
        ],
    },
)
