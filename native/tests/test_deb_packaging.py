"""Exercise Debian staging with isolated dependency installers and archive tools."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def build_environment(tmp_path):
    root = tmp_path / "project"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    shutil.copyfile(ROOT / "scripts/build-deb.sh", scripts / "build-deb.sh")
    icons = root / "extension/icons"
    icons.mkdir(parents=True)
    shutil.copyfile(ROOT / "extension/icons/icon-96.png", icons / "icon-96.png")

    # Bash functions isolate external tooling, including the absolute launcher
    # interpreter. File staging still runs through the unmodified build script.
    initialization = tmp_path / "tools.bash"
    initialization.write_text("""
function /usr/bin/python3 {
  if [[ "$1" == -c ]]; then
    printf '%s\\n' "$AF_TEST_SYSTEM_VERSION"
  else
    printf '%s\\n' /usr/bin/python3 "$@" > "$AF_TEST_INSTALL_LOG"
  fi
}
python3() { printf '%s\\n' ambient-python "$@" > "$AF_TEST_INSTALL_LOG"; }
uv() { printf '%s\\n' uv "$@" > "$AF_TEST_INSTALL_LOG"; }
command() {
  if [[ "$1" == -v && "$2" == uv ]]; then
    [[ "$AF_TEST_BACKEND" == uv ]]
  else
    builtin command "$@"
  fi
}
dpkg() { printf '%s\\n' amd64; }
dpkg-deb() { :; }
""")
    env = {
        "PATH": os.environ["PATH"],
        "BASH_ENV": str(initialization),
        "AF_TEST_INSTALL_LOG": str(tmp_path / "install.log"),
    }
    return root, env


def run_builder(root, env):
    return subprocess.run(
        ["bash", str(root / "scripts/build-deb.sh"), "0.1.9", "dist"],
        env=env, capture_output=True, text=True, timeout=10,
    )


@pytest.mark.parametrize("backend", ["uv", "pip"])
@pytest.mark.parametrize("minor", [11, 12, 13])
def test_deb_installs_for_launcher_interpreter_and_declares_its_abi(
    build_environment, backend, minor,
):
    root, env = build_environment
    env.update(AF_TEST_BACKEND=backend, AF_TEST_SYSTEM_VERSION=f"3.{minor}")
    result = run_builder(root, env)
    assert result.returncode == 0, result.stderr

    stage = root / "dist/deb/stage"
    control = (stage / "DEBIAN/control").read_text()
    assert (
        f"Depends: python3 (>= 3.{minor}), python3 (<< 3.{minor + 1})\n" in control
    )

    invocation = Path(env["AF_TEST_INSTALL_LOG"]).read_text().splitlines()
    if backend == "uv":
        assert invocation[0] == "uv"
        assert "--python" in invocation
        assert invocation[invocation.index("--python") + 1] == "/usr/bin/python3"
    else:
        assert invocation[:4] == ["/usr/bin/python3", "-m", "pip", "install"]
    assert invocation[invocation.index("--target") + 1] == "dist/deb/stage/opt/amberfader/lib"

    for name in ("amberfader", "amberfader-helper"):
        assert "/usr/bin/python3 -m amberfader." in (stage / "usr/bin" / name).read_text()


def test_deb_rejects_unsupported_launcher_python_before_installing(build_environment):
    root, env = build_environment
    env.update(AF_TEST_BACKEND="uv", AF_TEST_SYSTEM_VERSION="3.10")
    result = run_builder(root, env)
    assert result.returncode != 0
    assert "Python 3.11" in result.stderr
    assert not Path(env["AF_TEST_INSTALL_LOG"]).exists()
    assert not (root / "dist/deb").exists()
