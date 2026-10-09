"""Album covers follow observed track identity and tolerate asynchronous assets."""
import base64

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import QBuffer, QIODevice, QRect
from PySide6.QtGui import QColor, QImage, QPainter
from test_faces import png
from test_gui_features import _state

from amberfader.face_library import FaceLibrary
from amberfader.ui import main_window
from amberfader.ui.main_window import MainWindow


def _track_state(occurrence="occ-1", artwork="cover-1"):
    state = _state()
    state["track"].update(occurrenceId=occurrence, artworkId=artwork)
    return state


def _asset(occurrence="occ-1", artwork="cover-1", color=b"\xff\0\0\xff"):
    return {
        "occurrenceId": occurrence, "artworkId": artwork,
        "mime": "image/png", "width": 64, "height": 64,
        "dataBase64": base64.b64encode(png(64, 64, color)).decode(),
    }


@pytest.fixture()
def window(qapp, tmp_path):
    library = FaceLibrary(tmp_path / "faces", tmp_path / "appearance.json")
    window = MainWindow(lambda *_: None, faces=library)
    yield window
    window.close()
    window.deleteLater()
    qapp.processEvents()


def _color(window):
    image = window._cover.toImage()
    return image.pixelColor(image.rect().center()).name()


@pytest.mark.parametrize("occurrence,artwork", [
    ("occ-2", "cover-2"), ("occ-1", "cover-2"), ("occ-2", "cover-1"),
])
def test_new_track_clears_previous_cover_until_matching_asset(window, occurrence, artwork):
    window.apply_state(_track_state())
    window.apply_asset(_asset())
    assert _color(window) == "#ff0000"
    window.apply_state(_track_state(occurrence, artwork))
    assert window._cover.cacheKey() == window._placeholder.cacheKey()
    window.apply_asset(_asset(occurrence, artwork, b"\0\0\xff\xff"))
    assert _color(window) == "#0000ff"


@pytest.mark.parametrize("old_artwork", ["cover-1", "cover-2"])
def test_late_old_occurrence_asset_cannot_replace_current_cover(window, old_artwork):
    window.apply_state(_track_state("occ-2", "cover-2"))
    window.apply_asset(_asset("occ-2", "cover-2", b"\0\0\xff\xff"))
    window.apply_asset(_asset("occ-1", old_artwork))
    assert _color(window) == "#0000ff"
    window.apply_state(_track_state("occ-2", "cover-2"))
    assert _color(window) == "#0000ff"


def test_asset_arriving_before_state_is_replayed_for_matching_track(window):
    window.apply_asset(_asset())
    assert window._cover.cacheKey() == window._placeholder.cacheKey()
    window.apply_state(_track_state("occ-2", "cover-2"))
    assert window._cover.cacheKey() == window._placeholder.cacheKey()
    window.apply_state(_track_state())
    assert _color(window) == "#ff0000"


def test_temporarily_missing_artwork_id_restores_cached_cover_in_both_views(window):
    window.apply_state(_track_state())
    window.apply_asset(_asset())
    window.open_cover()
    window.apply_state(_track_state(artwork=None))
    assert window._cover.cacheKey() == window._placeholder.cacheKey()
    window.apply_state(_track_state())
    assert _color(window) == "#ff0000"
    assert window._cover_label.pixmap().toImage().pixelColor(192, 192).name() == "#ff0000"


@pytest.mark.parametrize("width,height", [(128, 64), (64, 128)])
def test_cover_view_preserves_image_edges_while_round_aperture_crops(window, qapp, width, height):
    image = QImage(width, height, QImage.Format.Format_RGBA8888)
    image.fill(QColor("#0000ff"))
    painter = QPainter(image)
    if width > height:
        edges = (QRect(0, 0, width // 4, height), QRect(3 * width // 4, 0, width // 4, height))
    else:
        edges = (QRect(0, 0, width, height // 4), QRect(0, 3 * height // 4, width, height // 4))
    painter.fillRect(edges[0], QColor("#ff0000"))
    painter.fillRect(edges[1], QColor("#00ff00"))
    painter.end()
    encoded = QBuffer()
    encoded.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(encoded, "PNG")
    asset = _asset()
    asset.update(
        width=width, height=height, dataBase64=base64.b64encode(bytes(encoded.data())).decode(),
    )
    window.apply_state(_track_state())
    window._art.set_shape("ellipse", 0, False)
    window.apply_asset(asset)
    window.open_cover()
    qapp.processEvents()

    expanded = window._cover_label.grab().toImage()
    aperture = window._art.grab().toImage()
    for rendered, colors in (
        (expanded, ("#ff0000", "#00ff00")), (aperture, ("#0000ff", "#0000ff")),
    ):
        ratio = rendered.devicePixelRatio()
        logical_width, logical_height = rendered.width() / ratio, rendered.height() / ratio
        if width > height:
            points = ((5, logical_height / 2), (logical_width - 5, logical_height / 2))
        else:
            points = ((logical_width / 2, 5), (logical_width / 2, logical_height - 5))
        for (x, y), color in zip(points, colors, strict=True):
            assert rendered.pixelColor(round(x * ratio), round(y * ratio)).name() == color


def test_high_resolution_cover_is_accepted(window):
    asset = _asset()
    asset.update(width=768, height=768, dataBase64=base64.b64encode(png(768, 768)).decode())
    window.apply_state(_track_state())
    window.apply_asset(asset)
    assert window._cover.size().width() == 768


def test_covers_render_at_the_display_pixel_ratio(window, qapp, monkeypatch):
    """A 1x pixmap on a 2x display is upscaled by the painter and looks soft."""
    window.apply_state(_track_state())
    window.apply_asset(_asset())
    window.open_cover()
    # QLabel.pixmap() answers at the widget's real ratio (1 offscreen), so
    # capture what the window hands each label.
    rendered = {}
    for label in (window._art, window._cover_label):
        monkeypatch.setattr(label, "devicePixelRatioF", lambda: 2.0)
        monkeypatch.setattr(
            label, "setPixmap", lambda pixmap, key=label: rendered.update({key: pixmap}),
        )
    window._render_cover()

    assert len(rendered) == 2
    for label, pixmap in rendered.items():
        assert pixmap.devicePixelRatio() == 2.0
        assert pixmap.size() == label.size() * 2


@pytest.mark.parametrize("field", ["occurrenceId", "artworkId"])
def test_missing_asset_identity_is_ignored(window, field):
    window.apply_state(_track_state())
    asset = _asset()
    asset.pop(field)
    window.apply_asset(asset)
    assert window._cover.cacheKey() == window._placeholder.cacheKey()


@pytest.mark.parametrize("encoded", [
    "not valid base64",
    base64.b64encode(b"not an image").decode(),
    base64.b64encode(png(main_window.MAX_ARTWORK_DIMENSION + 1, 64)).decode(),
])
def test_invalid_or_oversized_asset_cannot_replace_current_cover(window, encoded):
    window.apply_state(_track_state())
    window.apply_asset(_asset())
    asset = _asset()
    asset["dataBase64"] = encoded
    window.apply_asset(asset)
    assert _color(window) == "#ff0000"
    window.apply_state(_track_state())
    assert _color(window) == "#ff0000"


@pytest.mark.parametrize("limit,value", [
    ("ARTWORK_CACHE_BYTES", 2 * 64 * 64 * 4), ("MAX_ARTWORK_CACHE_ENTRIES", 2),
])
def test_artwork_cache_evicts_least_recently_used_within_limits(window, monkeypatch, limit, value):
    assert main_window.ARTWORK_CACHE_BYTES == 20 * 1024 * 1024
    monkeypatch.setattr(main_window, limit, value)
    window.apply_state(_track_state())
    window.apply_asset(_asset())
    window.apply_state(_track_state("occ-2", "cover-2"))
    window.apply_asset(_asset("occ-2", "cover-2", b"\0\0\xff\xff"))
    # Observing the first track again makes its cached cover more recent.
    window.apply_state(_track_state())
    window.apply_asset(_asset("occ-3", "cover-3", b"\0\xff\0\xff"))
    assert _color(window) == "#ff0000"
    window.apply_state(_track_state("occ-2", "cover-2"))
    assert window._cover.cacheKey() == window._placeholder.cacheKey()
    window.apply_state(_track_state())
    assert _color(window) == "#ff0000"
    window.apply_state(_track_state("occ-3", "cover-3"))
    assert _color(window) == "#00ff00"
