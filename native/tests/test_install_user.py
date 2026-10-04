"""Register an installed Flatpak app using the actual host-side installer."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP_ID = "ch.lkmc.amberfader"
ZEN_ID = "io.github.zen_browser.zen"


@pytest.fixture()
def install_environment(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    flatpak = bin_dir / "flatpak"
    flatpak.write_text("""#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
if args[0] == 'info':
    app = args[-1]
    if app == 'ch.lkmc.amberfader':
        sys.exit(0)
    if app != os.environ.get('TEST_BROWSER_FLATPAK'):
        sys.exit(1)
    if '--show-permissions' in args:
        print('[Session Bus Policy]\\norg.freedesktop.Flatpak=talk')
    sys.exit(0)
with open(os.environ['TEST_FLATPAK_LOG'], 'a') as output:
    output.write(json.dumps(args) + '\\n')
""")
    flatpak.chmod(0o755)
    env = {
        "HOME": str(home),
        "XDG_RUNTIME_DIR": str(runtime),
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "TEST_FLATPAK_LOG": str(tmp_path / "flatpak.log"),
    }
    return home, runtime, env


def run_installer(env):
    return subprocess.run(
        ["bash", str(ROOT / "scripts/install-user"), "--app", "flatpak"],
        env=env, capture_output=True, text=True, timeout=10,
    )


def test_register_flatpak_app_for_native_zen(install_environment):
    home, runtime, env = install_environment
    (home / ".zen").mkdir()
    result = run_installer(env)
    assert result.returncode == 0, result.stderr
    manifest = json.loads((home / ".mozilla/native-messaging-hosts/amberfader.json").read_text())
    assert manifest["allowed_extensions"] == ["amberfader@ch.lkmc"]
    helper = Path(manifest["path"])
    subprocess.run([str(helper), "--socket", "test socket"], env=env, check=True)
    invocation = json.loads(Path(env["TEST_FLATPAK_LOG"]).read_text().strip())
    assert invocation == ["run", "--command=amberfader-helper", APP_ID, "--socket", "test socket"]
    assert not (home / ".local/share/amberfader/venv").exists()
    assert (runtime / "amberfader").stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize("browser_id", ["org.mozilla.firefox", "app.zen_browser.zen", ZEN_ID])
def test_register_flatpak_app_for_flatpak_browser(install_environment, browser_id):
    home, _, env = install_environment
    env["TEST_BROWSER_FLATPAK"] = browser_id
    result = run_installer(env)
    assert result.returncode == 0, result.stderr
    profile = home / ".var/app" / browser_id / ".mozilla"
    manifest = json.loads((profile / "native-messaging-hosts/amberfader.json").read_text())
    sandbox_path = home / ".mozilla/native-messaging-hosts/amberfader-helper"
    assert manifest["path"] == str(sandbox_path)
    launcher = profile / "native-messaging-hosts/amberfader-helper"
    assert launcher.stat().st_mode & 0o111
    assert 'flatpak-spawn --host' in launcher.read_text()
    assert 'amberfader-helper' in launcher.read_text()


def test_register_flatpak_app_from_packaged_script_on_stdin(install_environment):
    home, _, env = install_environment
    (home / ".zen").mkdir()
    result = subprocess.run(
        ["bash", "-s", "--", "--app", "flatpak"],
        input=(ROOT / "scripts/install-user").read_text(),
        cwd=home, env=env, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert (home / ".mozilla/native-messaging-hosts/amberfader.json").is_file()


def test_flatpak_editor_launcher_preserves_folder_arguments(install_environment):
    home, _, env = install_environment
    result = run_installer(env)
    assert result.returncode == 0, result.stderr
    editor = home / ".local/share/amberfader/bin/amberfader-face-editor"
    subprocess.run([str(editor), "a face folder"], env=env, check=True)
    invocation = json.loads(Path(env["TEST_FLATPAK_LOG"]).read_text().strip())
    assert invocation == ["run", "--command=amberfader-face-editor", APP_ID, "a face folder"]


def test_existing_source_install_mode_still_registers_the_python_helper(install_environment):
    home, _, env = install_environment
    (home / ".zen").mkdir()
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/install-user"), "--no-venv", "--python", sys.executable],
        env=env, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    manifest = json.loads((home / ".mozilla/native-messaging-hosts/amberfader.json").read_text())
    helper = Path(manifest["path"])
    assert 'amberfader.helper' in helper.read_text()
    assert 'flatpak run' not in helper.read_text()
    editor = home / ".local/share/amberfader/bin/amberfader-face-editor"
    assert editor.stat().st_mode & 0o111
    assert 'amberfader.editor_app' in editor.read_text()


def test_missing_manifest_writer_fails_before_changing_the_installation(install_environment):
    home, _, env = install_environment
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/install-user"), "--app", "flatpak",
         "--python", "missing-python"],
        env=env, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 1
    assert "needs 'missing-python'" in result.stderr
    assert not (home / ".local/share/amberfader").exists()


def test_uninstall_removes_flatpak_registration_but_preserves_other_hosts(install_environment):
    home, _, env = install_environment
    env["TEST_BROWSER_FLATPAK"] = ZEN_ID
    result = run_installer(env)
    assert result.returncode == 0, result.stderr
    hosts = home / ".var/app" / ZEN_ID / ".mozilla/native-messaging-hosts"
    other = hosts / "other.json"
    other.write_text('{}')
    subprocess.run(["bash", str(ROOT / "scripts/uninstall-user")], env=env, check=True)
    assert not (hosts / "amberfader.json").exists()
    assert not (hosts / "amberfader-helper").exists()
    assert other.is_file()
