"""The offline exporter rewrites only the face pack files it owns."""
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

ROOT = Path(__file__).resolve().parents[2]
FACE_ID = "amber-classic"


@pytest.fixture()
def exporter(qapp, tmp_path, monkeypatch):
    path = ROOT / "artwork" / "render_faces.py"
    spec = importlib.util.spec_from_file_location("render_faces", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    faces = tmp_path / "faces"
    shutil.copytree(module.FACES_ROOT / FACE_ID, faces / FACE_ID)
    monkeypatch.setattr(module, "FACES_ROOT", faces)
    manifest = faces / FACE_ID / "face.json"
    face = json.loads(manifest.read_text())
    # Declare whatever the exporter expects so the test isolates file ownership.
    face["buttons"] = {
        name: {
            state: f"{module._sprite_family(face, name)}-{state}.png"
            for state in module.BUTTON_STATES
        }
        for name in module.BUTTON_GROUPS
    }
    manifest.write_text(json.dumps(face))
    return module, faces / FACE_ID, face


def _export(module, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["render_faces.py", "--face", FACE_ID])
    module.main()


def test_export_removes_only_stale_exporter_sprites(exporter, monkeypatch, capsys):
    module, directory, face = exporter
    declared = {file for states in face["buttons"].values() for file in states.values()}
    candidates = [
        f"{name}-normal.png" for name in (*module.BUTTON_GROUPS, *module.BUTTON_GROUPS.values())
        if f"{name}-normal.png" not in declared
    ]
    assert candidates, "every exporter sprite name is declared; nothing stale to plant"
    stale = candidates[0]
    (directory / stale).write_bytes(b"old layout")
    (directory / "notes.png").write_bytes(b"not exported here")
    _export(module, monkeypatch)
    assert not (directory / stale).exists()
    assert f"removed stale sprite {stale}" in capsys.readouterr().out
    assert (directory / "notes.png").read_bytes() == b"not exported here"
    assert declared <= {path.name for path in directory.glob("*.png")}


def test_unknown_button_declaration_is_named(exporter, monkeypatch):
    module, directory, face = exporter
    face["buttons"]["shuffle"] = face["buttons"]["play"]
    (directory / "face.json").write_text(json.dumps(face))
    with pytest.raises(RuntimeError, match="shuffle"):
        _export(module, monkeypatch)


def test_plate_wider_than_drag_region_is_rejected(exporter, monkeypatch):
    module, _, face = exporter
    monkeypatch.setitem(module.FACE_PLATE_WIDTH, FACE_ID, face["drag"][2] + 1)
    with pytest.raises(RuntimeError, match="exceeds drag width"):
        _export(module, monkeypatch)
