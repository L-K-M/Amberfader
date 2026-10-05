"""Exercise Debian staging with isolated dependency installers and archive tools."""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DPKG = shutil.which("dpkg")


@pytest.fixture()
def build_environment(tmp_path):
    root = tmp_path / "project"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    shutil.copyfile(ROOT / "scripts/build-deb.sh", scripts / "build-deb.sh")
    icons = root / "packaging/icons"
    icons.mkdir(parents=True)
    shutil.copyfile(ROOT / "packaging/icons/amberfader-96.png", icons / "amberfader-96.png")

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
        f"Depends: python3 (>= 3.{minor}), python3 (<< 3.{minor + 1}~), libdbus-1-3\n"
        in control
    )

    invocation = Path(env["AF_TEST_INSTALL_LOG"]).read_text().splitlines()
    if backend == "uv":
        assert invocation[0] == "uv"
        assert "--python" in invocation
        assert invocation[invocation.index("--python") + 1] == "/usr/bin/python3"
    else:
        assert invocation[:4] == ["/usr/bin/python3", "-m", "pip", "install"]
    assert invocation[invocation.index("--target") + 1] == "dist/deb/stage/opt/amberfader/lib"

    for name in ("amberfader", "amberfader-face-editor"):
        assert "/usr/bin/python3 -m amberfader" in (stage / "usr/bin" / name).read_text()
        assert (stage / "usr/bin" / name).stat().st_mode & 0o111
    assert "-m amberfader \"$@\"" in (stage / "usr/bin/amberfader").read_text()
    assert "amberfader.editor_app" in (stage / "usr/bin/amberfader-face-editor").read_text()
    assert sorted(path.name for path in (stage / "usr/bin").iterdir()) == [
        "amberfader", "amberfader-face-editor",
    ]
    assert not (stage / "usr/lib/mozilla").exists()


def test_deb_rejects_unsupported_launcher_python_before_installing(build_environment):
    root, env = build_environment
    env.update(AF_TEST_BACKEND="uv", AF_TEST_SYSTEM_VERSION="3.10")
    result = run_builder(root, env)
    assert result.returncode != 0
    assert "Python 3.11" in result.stderr
    assert not Path(env["AF_TEST_INSTALL_LOG"]).exists()
    assert not (root / "dist/deb").exists()


def test_deb_declares_global_menu_dbus_runtime(build_environment):
    root, env = build_environment
    env.update(AF_TEST_BACKEND="uv", AF_TEST_SYSTEM_VERSION="3.12")
    result = run_builder(root, env)
    assert result.returncode == 0, result.stderr

    control = (root / "dist/deb/stage/DEBIAN/control").read_text()
    depends = next(line for line in control.splitlines() if line.startswith("Depends: "))
    assert "libdbus-1-3" in depends.removeprefix("Depends: ").split(", ")


def test_flatpak_allows_only_the_global_menu_registrar_bus_name():
    manifest = (ROOT / "packaging/flatpak/ch.lkmc.amberfader.yml").read_text()
    bus_permissions = [
        line.strip().removeprefix("- ") for line in manifest.splitlines()
        if any(flag in line for flag in ("--talk-name=", "--own-name=", "--socket=session-bus"))
    ]
    assert bus_permissions == ["--talk-name=com.canonical.AppMenu.Registrar"]


def test_flatpak_permission_guard_rejects_unrelated_owned_bus_names(tmp_path, monkeypatch):
    manifest = ROOT / "packaging/flatpak/ch.lkmc.amberfader.yml"
    injected = tmp_path / "packaging/flatpak/ch.lkmc.amberfader.yml"
    injected.parent.mkdir(parents=True)
    injected.write_text(manifest.read_text().replace(
        "finish-args:\n", "finish-args:\n  - --own-name=org.example.Evil\n",
    ))
    monkeypatch.setitem(globals(), "ROOT", tmp_path)

    with pytest.raises(AssertionError):
        test_flatpak_allows_only_the_global_menu_registrar_bus_name()


@pytest.mark.skipif(DPKG is None, reason="Debian version ordering requires dpkg")
@pytest.mark.parametrize(
    ("version", "accepted"),
    [
        ("3.12", True),
        ("3.12.3-1", True),
        ("3.13~a1-1", False),
        ("3.13~rc1-1", False),
        ("3.13", False),
        ("3.11", False),
    ],
)
def test_deb_python_bounds_reject_next_minor_prereleases(build_environment, version, accepted):
    root, env = build_environment
    env.update(AF_TEST_BACKEND="uv", AF_TEST_SYSTEM_VERSION="3.12")
    result = run_builder(root, env)
    assert result.returncode == 0, result.stderr
    control = (root / "dist/deb/stage/DEBIAN/control").read_text()
    bounds = re.search(
        r"^Depends: python3 \(>= ([^)]+)\), python3 \(<< ([^)]+)\), libdbus-1-3$",
        control, re.MULTILINE,
    )
    assert bounds is not None
    comparisons = []
    for operator, bound in zip(("ge", "lt"), bounds.groups(), strict=True):
        comparison = subprocess.run(
            [DPKG, "--compare-versions", version, operator, bound],
            capture_output=True, text=True, timeout=10,
        )
        assert comparison.returncode in (0, 1), comparison.stderr
        comparisons.append(comparison.returncode == 0)
    assert all(comparisons) == accepted
