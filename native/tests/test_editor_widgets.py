"""Inspector controls behave like AppKit fields, wells and the responder chain."""
from __future__ import annotations

import pytest


@pytest.fixture()
def host(qapp):
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    widget = QWidget()
    QVBoxLayout(widget)
    widget.show()
    qapp.processEvents()
    yield widget
    widget.hide()
    widget.deleteLater()
    qapp.processEvents()


def _add(host, widget):
    host.layout().addWidget(widget)
    widget.show()
    return widget


def test_number_field_commits_on_return_and_escape_reverts(host, qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from amberfader.ui.editor_widgets import NumberField

    field = _add(host, NumberField(host, -100, 100))
    field.setValue(10)
    values = []
    field.valueChanged.connect(values.append)
    field.setFocus()
    field.lineEdit().selectAll()
    QTest.keyClicks(field, "4")
    assert values == []  # Typing alone does not commit.
    QTest.keyClick(field, Qt.Key.Key_Escape)
    assert field.text() == "10 px"
    field.lineEdit().selectAll()
    QTest.keyClicks(field, "-")  # An incomplete value is allowed while typing.
    assert field.text().startswith("-")
    QTest.keyClicks(field, "7")
    QTest.keyClick(field, Qt.Key.Key_Return)
    assert values == [-7]


def test_shift_arrow_steps_by_ten_and_marks_the_change_as_stepping(host):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from amberfader.ui.editor_widgets import NumberField

    field = _add(host, NumberField(host, 0, 100))
    seen = []
    field.valueChanged.connect(lambda value: seen.append((value, field.stepping)))
    field.setFocus()
    QTest.keyClick(field, Qt.Key.Key_Up, Qt.KeyboardModifier.ShiftModifier)
    QTest.keyClick(field, Qt.Key.Key_Up)
    assert seen == [(10, True), (11, True)]
    assert not field.stepping


def test_unfocused_number_field_lets_the_wheel_scroll_the_inspector(host):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent

    from amberfader.ui.editor_widgets import NumberField

    field = _add(host, NumberField(host, 0, 100))
    event = QWheelEvent(
        QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, 120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase, False,
    )
    field.wheelEvent(event)
    assert field.value() == 0
    assert not event.isAccepted()


def test_text_field_commits_changes_once_and_keeps_typing_over_refreshes(host):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from amberfader.ui.editor_widgets import TextField

    field = _add(host, TextField(host, limit=20))
    field.show_model_value("Amber")
    committed = []
    field.committed.connect(committed.append)
    field.editingFinished.emit()
    assert committed == []  # Nothing changed.
    field.setFocus()
    field.selectAll()
    QTest.keyClicks(field, "Copper")
    field.show_model_value("Amber")  # An unrelated refresh keeps the typing.
    assert field.text() == "Copper"
    QTest.keyClick(field, Qt.Key.Key_Escape)
    assert field.text() == "Amber"
    assert field.selectedText() == "Amber"  # Reverted text is selected, ready to retype.
    QTest.keyClick(field, Qt.Key.Key_End)
    QTest.keyClicks(field, " Night")
    QTest.keyClick(field, Qt.Key.Key_Return)
    assert committed == ["Amber Night"]


def test_undo_shortcut_reaches_the_menu_once_the_field_has_nothing_to_undo(host, qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QAction, QKeySequence
    from PySide6.QtTest import QTest

    from amberfader.ui.editor_widgets import TextField, UndoPassthrough

    triggered = []
    action = QAction("Undo", host)
    action.setShortcut(QKeySequence.StandardKey.Undo)
    action.triggered.connect(lambda: triggered.append(True))
    host.addAction(action)
    field = _add(host, TextField(host, limit=20))
    field.installEventFilter(UndoPassthrough(host))
    host.activateWindow()
    field.setFocus()
    QTest.keyClicks(field, "ab")
    QTest.keyClick(field, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert field.text() == ""  # The field undid its own typing.
    assert triggered == []
    QTest.keyClick(field, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert triggered == [True]


def test_color_well_edits_live_in_one_session_per_attachment(host):
    from PySide6.QtGui import QColor

    from amberfader.ui.editor_widgets import ColorWell, _ColorPanel

    panel = _ColorPanel.shared()
    first = _add(host, ColorWell("Accent", host))
    second = _add(host, ColorWell("Text", host))
    first.set_color("#112233")
    picks = []
    first.picked.connect(lambda color, session: picks.append((color.name(), session)))
    second.picked.connect(lambda color, session: picks.append(("second", session)))
    first.click()
    try:
        assert panel._dialog.currentColor().name() == "#112233"
        assert first._active
        panel._dialog.setCurrentColor(QColor("#445566"))
        panel._dialog.setCurrentColor(QColor("#778899"))
        assert [name for name, _ in picks] == ["#445566", "#778899"]
        assert picks[0][1] is picks[1][1]
        second.click()
        assert not first._active and second._active
        panel._dialog.setCurrentColor(QColor("#ff0000"))
        assert picks[-1][0] == "second" and picks[-1][1] is not picks[0][1]
    finally:
        panel._dialog.hide()
        panel.detach()


def test_collapsed_section_hides_its_content(host):
    from amberfader.ui.editor_widgets import InspectorSection

    section = _add(host, InspectorSection("Layout", host, name="layoutSection"))
    assert section.is_expanded() and section.body.isVisible()
    section._header.click()
    assert not section.is_expanded() and not section.body.isVisible()
    assert section._header.accessibleDescription() == "Collapsed"
