"""The release hook must keep the project's lockfile version in step."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def release_project(tmp_path):
    files = {
        "extension/manifest.json": json.dumps({"version": "0.1.5"}),
        "package.json": json.dumps({"version": "0.1.5"}),
        "pyproject.toml": 'version = "0.1.5"\n',
        "native/amberfader/__init__.py": '__version__ = "0.1.5"\n',
        "uv.lock": (
            '[[package]]\nname = "amberfader"\nversion = "0.1.4"\n'
            '\n[[package]]\nname = "other"\nversion = "1.2.3"\n'
        ),
    }
    for path, contents in files.items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents)
    (tmp_path / "scripts").mkdir()
    shutil.copyfile(ROOT / "scripts/sync-versions.mjs", tmp_path / "scripts/sync-versions.mjs")
    return tmp_path


def test_version_check_rejects_project_lockfile_drift(release_project):
    result = subprocess.run(
        ["node", str(release_project / "scripts/sync-versions.mjs"), "--check"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "uv.lock" in result.stdout


def test_release_hook_updates_only_the_project_lockfile_version(release_project):
    subprocess.run(["node", str(release_project / "scripts/sync-versions.mjs")], check=True)
    lock = (release_project / "uv.lock").read_text()
    assert 'name = "amberfader"\nversion = "0.1.5"' in lock
    assert 'name = "other"\nversion = "1.2.3"' in lock
