"""All faces retain command guards, art, search sessions and scaling."""
import base64
import json
import os
import subprocess
import sys

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QRegion
from PySide6.QtWidgets import QFileDialog
from test_faces import BUNDLED_IDS, make_pack, png
from test_gui_features import _load_results, _state

from amberfader.face_library import DEFAULT_FACE_ID, FaceError, FaceLibrary
from amberfader.ui.face_surface import prepare_face
from amberfader.ui.main_window import MainWindow


@pytest.fixture(name="pack")
def _pack(tmp_path):
    return make_pack(tmp_path)


@pytest.fixture()
def themed(qapp, tmp_path):
    library = FaceLibrary(tmp_path / "faces", tmp_path / "appearance.json")
    sent = []
    window = MainWindow(lambda method, params: sent.append((method, params)), faces=library)
    window.show()
    qapp.processEvents()
    yield window, library, sent
    window.close()
    window.deleteLater()
    qapp.processEvents()


@pytest.mark.parametrize("face_id", sorted(BUNDLED_IDS))
def test_each_face_keeps_all_controls_usable(themed, qapp, face_id):
    window, library, sent = themed
    window.apply_state(_state(capabilities=[
        "play", "pause", "setLiked", "seek", "volume", "next", "previous",
    ]))
    original_widgets = dict(window._controls)
    window.select_face(face_id)
    qapp.processEvents()
    assert window._controls == original_widgets
    assert library.preferred_id() == face_id
    assert not sent
    for control in window._controls.values():
        assert control.isVisible()
        assert window.rect().contains(control.geometry())
        assert QRegion(control.geometry()).subtracted(window.mask()).isEmpty()
    window._like.click()
    window._next.click()
    window._prev.click()
    assert sent == [
        ("player.setLiked", {"occurrenceId": "occ-1", "liked": True}),
        ("player.next", {}), ("player.previous", {}),
    ]
    assert not window._like.isEnabled()


def test_switch_preserves_pending_guards_search_session_and_art(themed, qapp):
    window, library, sent = themed
    state = _state()
    state["track"]["artworkId"] = "cover"
    window.apply_state(state)
    window.apply_asset({
        "occurrenceId": "occ-1", "artworkId": "cover",
        "dataBase64": base64.b64encode(png(256, 256)).decode(),
    })
    cover_key = window._cover.cacheKey()
    assert cover_key != window._placeholder.cacheKey()
    window.open_search()
    search = window._search
    _load_results(search)
    search._list.setCurrentRow(0)
    search._q.setText("Keep this query")
    window._like.click()
    window._play.click()
    sent.clear()
    window.select_face("paper-signal")
    qapp.processEvents()
    assert sent == []
    assert window._pending_like and window._pending_transport
    assert not window._like.isEnabled() and not window._play.isEnabled()
    assert window._like.text() == "♡"
    assert window._search is search
    assert search._q.text() == "Keep this query"
    assert search._token == "tok"
    assert search._btn_radio.isEnabled()
    assert search.styleSheet() == window.styleSheet()
    assert window._cover.cacheKey() == cover_key
    assert window._art.pixmap().width() == library.load("paper-signal").controls["art"][2]
    window.route_response("player.setLiked", True, {})
    assert window._like.isEnabled()
    assert not window._play.isEnabled()
    window.route_response("player.play", True, {})
    assert window._play.isEnabled()


def test_cover_view_follows_assets_and_survives_theme_change(themed):
    window, _, _ = themed
    state = _state()
    state["track"]["artworkId"] = "cover"
    window.apply_state(state)
    window.open_cover()
    dialog = window._cover_window
    window.apply_asset({
        "occurrenceId": "occ-1", "artworkId": "cover",
        "dataBase64": base64.b64encode(png(128, 128, b"\xff\0\0\xff")).decode(),
    })
    assert window._cover.cacheKey() != window._placeholder.cacheKey()
    assert window._cover_label.pixmap().toImage().pixelColor(100, 100).red() == 255
    window.select_face("moonstone")
    assert window._cover_window is dialog
    assert window._cover_label.pixmap().toImage().pixelColor(100, 100).red() == 255


@pytest.mark.parametrize("scale", [1.0, 1.5, 2.0])
def test_scaled_faces_keep_controls_inside_the_shape(qapp, tmp_path, scale):
    library = FaceLibrary(tmp_path / "faces", tmp_path / "appearance.json")
    window = MainWindow(lambda *_: None, scale=scale, faces=library)
    window.show()
    try:
        for face_id in BUNDLED_IDS:
            window.select_face(face_id)
            qapp.processEvents()
            for name, control in window._controls.items():
                assert QRegion(control.geometry()).subtracted(window.mask()).isEmpty(), name
            assert window.width() <= window.screen().availableGeometry().width()
            assert window.height() <= window.screen().availableGeometry().height()
    finally:
        window.close()
        window.deleteLater()


def test_face_picker_previews_and_applies_without_player_commands(themed, qapp):
    window, _, sent = themed
    window.open_faces()
    dialog = window._faces_window
    dialog._list.setCurrentRow(2)
    selected = dialog._list.currentItem().data(Qt.ItemDataRole.UserRole)
    qapp.processEvents()
    assert not dialog._preview.grab().isNull()
    dialog._apply.click()
    assert window._face_id == selected
    assert not sent


def test_gui_installs_a_face_folder(themed, pack, monkeypatch):
    window, library, _ = themed
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_: str(pack[0]))
    window.open_faces()
    dialog = window._faces_window
    dialog._install()
    assert "my-face" in {face.id for face in library.faces}
    assert window._face_id == DEFAULT_FACE_ID
    dialog._apply.click()
    assert window._face_id == "my-face"


def test_transparent_control_area_is_rejected_before_selection(themed, pack):
    window, library, _ = themed
    (pack[0] / "background.png").write_bytes(png(*pack[1]["size"], rgba=b"\0\0\0\0"))
    library.install(pack[0])
    with pytest.raises(FaceError, match="transparent cutout"):
        window.select_face("my-face")
    assert library.preferred_id() == DEFAULT_FACE_ID
    assert window._face_id == DEFAULT_FACE_ID


def test_corrupt_png_cannot_poison_selection_or_crash_restart(themed, pack, qapp, tmp_path):
    window, library, _ = themed
    info = library.install(pack[0])
    window.select_face(info.id)
    background = info.source / "background.png"
    background.write_bytes(background.read_bytes()[:33])
    with pytest.raises(FaceError, match="cannot decode"):
        window.select_face(info.id)
    restarted = MainWindow(lambda *_: None, faces=library)
    try:
        assert restarted._face_id == DEFAULT_FACE_ID
        assert "could not load" in restarted._status.text()
    finally:
        restarted.close()
        restarted.deleteLater()


def test_failed_preference_save_leaves_current_face_untouched(themed, monkeypatch):
    window, library, _ = themed
    def fail(_):
        raise FaceError("Cannot save appearance")
    monkeypatch.setattr(library, "remember", fail)
    with pytest.raises(FaceError, match="Cannot save"):
        window.select_face("moonstone")
    assert window._face_id == DEFAULT_FACE_ID


def test_sprites_keep_real_labels_and_disabled_guards(themed, pack, qapp):
    window, library, _ = themed
    pack[1]["buttons"] = {"like": {"normal": "heart.png", "pressed": "heart-pressed.png"}}
    (pack[0] / "heart.png").write_bytes(png(32, 32))
    (pack[0] / "heart-pressed.png").write_bytes(png(32, 32, b"\xff\0\0\xff"))
    (pack[0] / "face.json").write_text(json.dumps(pack[1]))
    library.install(pack[0])
    window.apply_state(_state(liked=True))
    window.select_face("my-face")
    assert window._like.text() == "♥"
    assert not window._like.grab().isNull()
    window._like.click()
    qapp.processEvents()
    assert not window._like.isEnabled()
    assert window._like.text() == "♥"
    assert not window._like.grab().isNull()


def test_long_metadata_remains_plain_and_available_in_tooltip(themed):
    window, _, _ = themed
    state = _state()
    state["track"]["title"] = "<b>" + "A long track name " * 30
    window.apply_state(state)
    window.select_face("paper-signal")
    assert window._title.textFormat() == Qt.TextFormat.PlainText
    assert window._title.toolTip() == state["track"]["title"]
    assert not window._title.grab().isNull()


def test_disconnect_keeps_unknown_heart_in_every_face(themed):
    window, _, _ = themed
    window.apply_state(_state(liked=True))
    window.set_connection("gui", "disconnected")
    for face_id in BUNDLED_IDS:
        window.select_face(face_id)
        assert window._like.text() == "♡?"
        assert not window._like.isEnabled()


def test_bundled_masks_have_real_cutouts(themed):
    _, library, _ = themed
    for face_id in ("moonstone", "copper-reel"):
        artwork = prepare_face(library.load(face_id))
        assert not artwork.mask.contains(QRect(0, 0, 1, 1))


def test_missing_saved_face_explains_fallback_in_browser(qapp, tmp_path):
    preferences = tmp_path / "appearance.json"
    preferences.write_text('{"face": "removed-face"}')
    library = FaceLibrary(tmp_path / "faces", preferences)
    window = MainWindow(lambda *_: None, faces=library)
    try:
        window.open_faces()
        assert "Saved face is unavailable" in window._faces_window._status.text()
    finally:
        window.close()
        window.deleteLater()


def test_close_player_closes_auxiliary_windows_without_commands(themed):
    window, _, sent = themed
    window.open_faces()
    window.open_cover()
    window.open_search()
    sent.clear()
    window.close()
    assert not window._faces_window.isVisible()
    assert not window._cover_window.isVisible()
    assert not window._search.isVisible()
    assert sent == []


def test_broken_default_face_has_reinstall_diagnostic(qapp, tmp_path, monkeypatch):
    library = FaceLibrary(tmp_path / "faces", tmp_path / "appearance.json")

    def broken(_):
        raise FaceError("Default face damaged")

    monkeypatch.setattr(library, "load", broken)
    with pytest.raises(FaceError, match="Reinstall Amberfader"):
        MainWindow(lambda *_: None, faces=library)


def test_cli_reports_broken_face_install_and_cleans_socket(tmp_path):
    pytest.importorskip(
        "PySide6.QtWebEngineWidgets", reason="Qt WebEngine unavailable", exc_type=ImportError,
    )
    socket = tmp_path / "control.sock"
    env = {
        **os.environ, "QT_QPA_PLATFORM": "offscreen",
        # The offline test page never loads here; no sandbox is exercised.
        "QTWEBENGINE_DISABLE_SANDBOX": "1",
        "XDG_DATA_HOME": str(tmp_path / "data"), "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"), "XDG_STATE_HOME": str(tmp_path / "state"),
    }
    process = subprocess.run([
        sys.executable, "-c", """
import sys
from pathlib import Path
import amberfader.embedded.page as page
import amberfader.face_library as faces
from amberfader.embedded.__main__ import main
faces.BUILTIN_DIRECTORY = Path(sys.argv[1])
page.load_bundle = lambda: ""
raise SystemExit(main(["--test-page", "--background", "--socket", sys.argv[2]]))
""", str(tmp_path / "missing-faces"), str(socket),
    ], capture_output=True, text=True, timeout=30, env=env)
    assert process.returncode == 2
    assert "Reinstall Amberfader" in process.stderr
    assert "Traceback" not in process.stderr
    assert not socket.exists()


def test_deleted_face_selection_is_reported_by_picker_without_false_success(themed, pack):
    window, library, sent = themed
    info = library.install(pack[0])
    window.open_faces()
    dialog = window._faces_window
    row = next(
        index for index in range(dialog._list.count())
        if dialog._list.item(index).data(Qt.ItemDataRole.UserRole) == info.id
    )
    dialog._list.setCurrentRow(row)
    (info.source / "face.json").unlink()
    dialog._apply.click()
    assert "face.json" in dialog._status.text()
    assert "Face saved" not in dialog._status.text()
    assert window._face_id == DEFAULT_FACE_ID
    assert library.preferred_id() == DEFAULT_FACE_ID
    assert not sent
