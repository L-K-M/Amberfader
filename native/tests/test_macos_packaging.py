"""Exercise macOS signature gates through the build-and-install entry point."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP_NAMES = ("Amberfader.app", "Amberfader Face Editor.app")


@pytest.fixture()
def build_environment(tmp_path):
    root = tmp_path / "project with spaces"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    for name in ("build.sh", "build-macos.sh"):
        shutil.copy(ROOT / "scripts" / name, scripts / name)

    native = root / "native/amberfader"
    web = native / "embedded/web"
    web.mkdir(parents=True)
    (native / "__init__.py").write_text('__version__ = "0.2.0"\n')
    for name in ("adapter.js", "ad-filter.js"):
        (web / name).touch()

    # Isolate macOS tools and /Applications while running both real scripts.
    initialization = tmp_path / "tools.bash"
    initialization.write_text("""
uname() { [[ "$1" == -s ]] && printf '%s\\n' Darwin || printf '%s\\n' arm64; }
node() { :; }
npm() { :; }
sips() { :; }
iconutil() { :; }
python3() {
  [[ "$1" == -c ]] && return 0
  local distpath
  while [[ $# -gt 0 ]]; do
    [[ "$1" == --distpath ]] && distpath="$2"
    shift
  done
  mkdir -p "$distpath/Amberfader.app" "$distpath/Amberfader Face Editor.app"
}
codesign() {
  printf '%s\\n' "$*" >> "$AF_TEST_CODESIGN_LOG"
  local mode=adhoc
  [[ "${!#}" == */"$AF_TEST_BAD_APP" ]] && mode="$AF_TEST_SIGNATURE_MODE"
  if [[ "$1" == --verify ]]; then
    [[ "$mode" != invalid ]]
    return
  fi
  if [[ "$mode" == not-adhoc ]]; then
    printf '%s\\n' 'Signature=DeveloperID' >&2
    return
  fi
  # Exceed a pipe buffer after the match to reproduce grep -q's early close.
  "$AF_TEST_PYTHON" -c '
import os
import signal
signal.signal(signal.SIGPIPE, signal.SIG_DFL)
os.write(2, b"Signature=adhoc\\n")
os.write(2, b"Internal requirements=" + b"0" * 262144 + b"\\n")
' || return "$?"
  [[ "$mode" != display-failure ]]
}
ditto() { printf '%s\\n' "$2" >> "$AF_TEST_COPY_LOG"; }
hdiutil() { touch "${!#}"; }
shasum() { printf '%s\\n' checksum; }
pgrep() { return 1; }
rm() {
  [[ "${!#}" == /Applications/* ]] && return 0
  command rm "$@"
}
open() { printf '%s\\n' "$@" >> "$AF_TEST_OPEN_LOG"; }
""")
    env = {
        "PATH": os.environ["PATH"],
        "BASH_ENV": str(initialization),
        "AF_TEST_PYTHON": sys.executable,
        "AF_TEST_CODESIGN_LOG": str(tmp_path / "codesign.log"),
        "AF_TEST_COPY_LOG": str(tmp_path / "copy.log"),
        "AF_TEST_OPEN_LOG": str(tmp_path / "open.log"),
        "AF_TEST_BAD_APP": "",
        "AF_TEST_SIGNATURE_MODE": "adhoc",
    }
    return root, env


def run_builder(root, env):
    return subprocess.run(
        ["bash", str(root / "scripts/build.sh"), "--install"],
        env=env, capture_output=True, text=True, timeout=10,
    )


def test_install_accepts_adhoc_signatures_with_trailing_metadata(build_environment):
    root, env = build_environment
    result = run_builder(root, env)
    assert result.returncode == 0, result.stdout + result.stderr

    assert Path(env["AF_TEST_CODESIGN_LOG"]).read_text().splitlines() == [
        invocation
        for name in APP_NAMES
        for invocation in (
            f"--verify --deep --strict dist/macos/dist/{name}",
            f"-dv dist/macos/dist/{name}",
        )
    ]
    assert (root / "dist/Amberfader-0.2.0-macos-arm64.dmg").exists()
    assert Path(env["AF_TEST_COPY_LOG"]).read_text().splitlines() == [
        *(f"dist/macos/dmg/{name}" for name in APP_NAMES),
        *(f"/Applications/{name}" for name in APP_NAMES),
    ]
    assert Path(env["AF_TEST_OPEN_LOG"]).read_text().splitlines() == [
        "-R", *(f"/Applications/{name}" for name in APP_NAMES),
    ]


@pytest.mark.parametrize("app_name", APP_NAMES)
@pytest.mark.parametrize(
    ("mode", "error"),
    [
        ("invalid", "does not verify"),
        ("not-adhoc", "is not ad-hoc signed"),
        ("display-failure", "could not inspect signature"),
    ],
)
def test_install_rejects_signature_failures_before_packaging(
    build_environment, app_name, mode, error,
):
    root, env = build_environment
    env.update(AF_TEST_BAD_APP=app_name, AF_TEST_SIGNATURE_MODE=mode)
    result = run_builder(root, env)
    assert result.returncode != 0
    assert error in result.stderr
    assert app_name in result.stderr
    assert not (root / "dist/Amberfader-0.2.0-macos-arm64.dmg").exists()
    assert not Path(env["AF_TEST_COPY_LOG"]).exists()
    assert not Path(env["AF_TEST_OPEN_LOG"]).exists()
