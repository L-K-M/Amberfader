"""Subset previews must not replace the complete documentation gallery."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("explicit_default", [False, True])
def test_subset_preview_preserves_default_gallery(tmp_path, explicit_default):
    gallery = tmp_path / "docs" / "faces-preview.png"
    gallery.parent.mkdir()
    gallery.write_bytes(b"Existing full-face gallery")
    arguments = ["--face", "orbit-99"]
    if explicit_default:
        arguments.extend(["--output", str(gallery)])
    result = subprocess.run(
        [
            sys.executable, "-c",
            """
import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("preview_faces", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.ROOT = Path(sys.argv[2])
module.PREVIEW_DIRECTORY = module.ROOT / "previews"
sys.argv = ["preview_faces.py", *sys.argv[3:]]
module.main()
""",
            str(ROOT / "artwork" / "preview_faces.py"), str(tmp_path), *arguments,
        ],
        cwd=ROOT, env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 2, result.stderr
    assert "--face needs a separate --output path" in result.stderr
    assert gallery.read_bytes() == b"Existing full-face gallery"
    assert not (tmp_path / "previews").exists()
