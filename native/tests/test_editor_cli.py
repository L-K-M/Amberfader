"""Standalone authoring stays separate from native messaging and player startup."""
import os
import subprocess
import sys

import pytest

from amberfader import __version__


@pytest.mark.parametrize("argument", ["--help", "--version"])
def test_editor_information_commands_do_not_import_qt_or_player(argument):
    script = """
import importlib.abc
import runpy
import sys

class BlockPlayer(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('PySide6') or fullname in (
            'amberfader.app', 'amberfader.embedded', 'amberfader.qt_transport'
        ):
            raise ImportError(f'Forbidden import: {fullname}')

sys.meta_path.insert(0, BlockPlayer())
sys.argv = ['amberfader-face-editor', sys.argv[1]]
runpy.run_module('amberfader.editor_app', run_name='__main__')
"""
    result = subprocess.run(
        [sys.executable, "-c", script, argument],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "amberfader-face-editor" in result.stdout
    if argument == "--version":
        assert __version__ in result.stdout


def test_editor_missing_face_exits_before_starting_a_window(tmp_path):
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    result = subprocess.run(
        [sys.executable, "-m", "amberfader.editor_app", str(tmp_path / "missing")],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 2
    assert "face.json" in result.stderr
    assert "install Amberfader" not in result.stderr
