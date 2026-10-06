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
    shutil.copytree(ROOT / "packaging/icons", root / "packaging/icons")
    linux = root / "packaging/linux"
    linux.mkdir(parents=True)
    shutil.copyfile(ROOT / "packaging/linux/apparmor-amberfader", linux / "apparmor-amberfader")

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
uv() {
  printf '%s\\n' uv "$@" > "$AF_TEST_INSTALL_LOG"
  # Installer caches can hand out owner-only files, as uv's did in a dev box.
  local target
  while [[ $# -gt 0 ]]; do [[ "$1" == --target ]] && target="$2"; shift; done
  mkdir -p "$target/PySide6" && install -m 640 /dev/null "$target/PySide6/__init__.py"
}
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
        f"Depends: python3 (>= 3.{minor}), python3 (<< 3.{minor + 1}~), libdbus-1-3, "
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
        assert (stage / "usr/bin" / name).stat().st_mode & 0o111
    # AppArmor attaches to the launcher's path, so it must be the script the
    # interpreter runs, not a shell wrapper that execs it.
    launcher = (stage / "usr/bin/amberfader").read_text()
    assert launcher.startswith("#!/usr/bin/python3\n")
    assert 'sys.path.insert(0, "/opt/amberfader/lib")' in launcher
    assert 'runpy.run_module("amberfader", run_name="__main__"' in launcher
    editor = (stage / "usr/bin/amberfader-face-editor").read_text()
    assert "/usr/bin/python3 -m amberfader.editor_app" in editor
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


def test_deb_declares_qt_webengine_libraries_and_apparmor_profile(build_environment):
    root, env = build_environment
    env.update(AF_TEST_BACKEND="uv", AF_TEST_SYSTEM_VERSION="3.12")
    result = run_builder(root, env)
    assert result.returncode == 0, result.stderr

    stage = root / "dist/deb/stage"
    control = (stage / "DEBIAN/control").read_text()
    depends = next(line for line in control.splitlines() if line.startswith("Depends: "))
    packages = depends.removeprefix("Depends: ").split(", ")
    for package in ("libnss3", "libgbm1", "libxkbfile1", "libasound2t64 | libasound2"):
        assert package in packages
    assert "\\" not in depends

    profile = (stage / "etc/apparmor.d/amberfader").read_text()
    assert "profile amberfader /usr/bin/amberfader flags=(unconfined)" in profile
    assert "/opt/amberfader/lib/PySide6/Qt/libexec/QtWebEngineProcess" in profile
    assert profile.count("userns,") == 2
    assert (stage / "DEBIAN/conffiles").read_text() == "/etc/apparmor.d/amberfader\n"
    for script in ("postinst", "postrm"):
        assert (stage / "DEBIAN" / script).stat().st_mode & 0o111
    # Installed files must be readable by the user who runs the app.
    module = stage / "opt/amberfader/lib/PySide6/__init__.py"
    assert module.stat().st_mode & 0o777 == 0o644
    assert "apparmor_parser -r" in (stage / "DEBIAN/postinst").read_text()


def test_deb_installs_the_desktop_entrys_icon_at_every_size(build_environment):
    root, env = build_environment
    env.update(AF_TEST_BACKEND="uv", AF_TEST_SYSTEM_VERSION="3.12")
    result = run_builder(root, env)
    assert result.returncode == 0, result.stderr

    stage = root / "dist/deb/stage"
    entry = (stage / "usr/share/applications/ch.lkmc.amberfader.desktop").read_text()
    assert "Icon=ch.lkmc.amberfader\n" in entry
    icons = sorted(
        path.relative_to(stage / "usr/share/icons/hicolor").as_posix()
        for path in (stage / "usr/share/icons").rglob("*.png")
    )
    assert icons == [
        f"{size}x{size}/apps/ch.lkmc.amberfader.png" for size in (128, 256, 512)
    ]


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
        r"^Depends: python3 \(>= ([^)]+)\), python3 \(<< ([^)]+)\), libdbus-1-3, ",
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
