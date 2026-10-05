# PyInstaller spec for Amberfader.app (macOS, Apple silicon). Run through
# scripts/build-macos.sh, which sets AMBERFADER_VERSION and the icon path.
# PyInstaller's PySide6.QtWebEngineCore hooks collect QtWebEngineCore.framework
# with its QtWebEngineProcess.app helper, resources and locales.
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).resolve().parents[1]
VERSION = os.environ["AMBERFADER_VERSION"]
ICON = os.environ["AMBERFADER_ICNS"]
# CFBundle versions must be numeric; a pre-release suffix stays in the .dmg name.
BUNDLE_VERSION = VERSION.split("-", 1)[0].split("+", 1)[0]

a = Analysis(
    [str(ROOT / "packaging" / "macos" / "launch.py")],
    pathex=[str(ROOT / "native")],
    # Faces, schemas and the page scripts are package data.
    datas=collect_data_files("amberfader"),
    hiddenimports=["amberfader.embedded.selftest"],
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Amberfader",
    console=False,
    target_arch="arm64",
    # Ad-hoc signature (D2: unsigned release); Apple silicon needs one.
    codesign_identity=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Amberfader")
app = BUNDLE(
    coll,
    name="Amberfader.app",
    icon=ICON,
    bundle_identifier="ch.lkmc.amberfader",
    version=BUNDLE_VERSION,
    info_plist={
        "CFBundleName": "Amberfader",
        "CFBundleDisplayName": "Amberfader",
        "CFBundleShortVersionString": BUNDLE_VERSION,
        "CFBundleVersion": BUNDLE_VERSION,
        "LSMinimumSystemVersion": "13.0",
        "LSApplicationCategoryType": "public.app-category.music",
        "NSHighResolutionCapable": True,
    },
)
