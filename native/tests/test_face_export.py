"""The offline exporter rewrites only the face pack files it owns."""
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtGui import QImage

from amberfader.face_library import BUILTIN_DIRECTORY, load_face

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


# Raster rounding varies with the machine's CPU and libraries, so a re-export
# elsewhere can differ slightly from the shipped pixels. A stale pack differs
# by far more: a changed shape or colour moves whole regions.
TOLERATED_LEVELS = 8
TOLERATED_SHARE = 0.005


def _changed_share(image, shipped):
    """Share of pixels whose channels differ by more than TOLERATED_LEVELS,
    and the largest channel difference."""
    current = bytes(image.convertToFormat(QImage.Format.Format_RGBA8888).constBits())
    original = bytes(shipped.convertToFormat(QImage.Format.Format_RGBA8888).constBits())
    deltas = [abs(a - b) for a, b in zip(current, original, strict=True)]
    changed = sum(
        max(deltas[index:index + 4]) > TOLERATED_LEVELS for index in range(0, len(deltas), 4)
    )
    return changed / (len(deltas) // 4), max(deltas)


@pytest.mark.parametrize("face_id", ["nightglass", "inner-sleeve", "instant-print", "j-card"])
def test_painted_faces_export_the_shipped_pack(exporter, monkeypatch, face_id):
    """Cover faces are painted in code; the shipped PNGs must be its output."""
    module, original, _ = exporter
    directory = original.parent / face_id
    shutil.copytree(BUILTIN_DIRECTORY / face_id, directory)
    manifest = (directory / "face.json").read_bytes()
    shipped = {path.name: QImage(str(path)) for path in directory.glob("*.png")}
    for path in directory.glob("*.png"):
        path.unlink()
    monkeypatch.setattr(sys, "argv", ["render_faces.py", "--face", face_id])

    module.main()

    assert (directory / "face.json").read_bytes() == manifest
    exported = {path.name: QImage(str(path)) for path in directory.glob("*.png")}
    assert exported.keys() == shipped.keys()
    for name, image in exported.items():
        assert image.size() == shipped[name].size(), name
        share, largest = _changed_share(image, shipped[name])
        assert share <= TOLERATED_SHARE, (name, f"{share:.4%} changed", f"largest {largest}")


@pytest.mark.parametrize("face_id", ["aureole", "viridian"])
def test_export_preserves_supplied_lens_layout_and_sprite_sizes(exporter, monkeypatch, face_id):
    module, original, _ = exporter
    directory = original.parent / face_id
    shutil.copytree(BUILTIN_DIRECTORY / face_id, directory)
    manifest = (directory / "face.json").read_bytes()
    image_sizes = {path.name: QImage(str(path)).size() for path in directory.glob("*.png")}
    monkeypatch.setattr(sys, "argv", ["render_faces.py", "--face", face_id])

    module.main()

    assert (directory / "face.json").read_bytes() == manifest
    assert {path.name: QImage(str(path)).size() for path in directory.glob("*.png")} == image_sizes
    assert load_face(directory).info.id == face_id
