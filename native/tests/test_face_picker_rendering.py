"""The chooser must show the typography the selected face will use."""
from dataclasses import replace
from types import MappingProxyType

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtGui import QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QWidget

from amberfader.face_library import BUILTIN_DIRECTORY, DEFAULT_FACE_ID, load_face
from amberfader.ui import faces_window
from amberfader.ui.face_surface import FONT_FAMILIES, prepare_face


@pytest.fixture()
def preview(qapp, monkeypatch):
    draws = {}

    class RecordingPainter(QPainter):
        def drawText(self, rect, flags, text):
            draws[text] = (QFont(self.font()), rect)
            return super().drawText(rect, flags, text)

    monkeypatch.setattr(faces_window, "QPainter", RecordingPainter)
    parent = QWidget()
    widget = faces_window.FacePreview(parent)
    widget.resize(480, 320)
    face = load_face(BUILTIN_DIRECTORY / DEFAULT_FACE_ID)
    yield widget, face, draws
    parent.close()
    parent.deleteLater()
    qapp.processEvents()


@pytest.mark.parametrize("family", ["sans", "mono", "serif"])
def test_preview_uses_face_font_and_bold_title(preview, family):
    widget, face, draws = preview
    face = replace(face, font=family)
    widget.set_face(face, prepare_face(face))
    widget.grab()
    title, _ = draws[faces_window.PREVIEW_LABELS["title"]]
    artists, _ = draws[faces_window.PREVIEW_LABELS["artists"]]
    assert title.family() == FONT_FAMILIES[family]
    assert artists.family() == FONT_FAMILIES[family]
    assert title.bold()
    assert not artists.bold()


def test_preview_fits_complete_time_readout(preview):
    widget, face, draws = preview
    controls = dict(face.controls)
    controls["time"] = (160, 110, 140, 26)
    face = replace(face, controls=MappingProxyType(controls), time_size=30)
    widget.set_face(face, prepare_face(face))
    widget.grab()
    text = faces_window.PREVIEW_LABELS["time"]
    assert text in draws, "The chooser must retain every time digit rather than eliding it"
    font, rect = draws[text]
    assert font.family() == FONT_FAMILIES["mono"]
    assert QFontMetrics(font).horizontalAdvance(text) <= rect.width()
    assert font.pixelSize() <= rect.height() - 2
