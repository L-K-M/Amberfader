"""Shared fixtures. Qt tests run offscreen — no display server needed."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def private_app_dirs(monkeypatch, tmp_path_factory):
    """Default face libraries, e.g. the editor's, use a temporary home.

    They never read the developer's installed faces or write a catalog
    cache next to them. Tests can still set XDG variables themselves.
    """
    from amberfader import face_autosave, face_library, paths

    home = tmp_path_factory.mktemp("home")
    for variable in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
        monkeypatch.delenv(variable, raising=False)
    private = lambda: paths.app_dirs(home=home)  # noqa: E731
    monkeypatch.setattr(face_library, "app_dirs", private)
    monkeypatch.setattr(face_autosave, "app_dirs", private)
    try:
        from amberfader.ui import editor_settings
    except ImportError:
        pass  # No Qt; only Qt-free tests run.
    else:
        monkeypatch.setattr(editor_settings, "app_dirs", private)
    return home


@pytest.fixture(autouse=True)
def no_unexpected_modal_dialogs(monkeypatch):
    """A modal dialog nobody answers would hang the suite; fail instead.

    Tests that expect a dialog replace these with their own answers.
    """
    try:
        from PySide6.QtWidgets import (
            QColorDialog,
            QDialog,
            QFileDialog,
            QInputDialog,
            QMenu,
            QMessageBox,
        )
    except ImportError:
        return

    def refuse(*args, **kwargs):
        detail = next((arg for arg in args if isinstance(arg, str)), "")
        pytest.fail(f"Unexpected modal dialog or menu {detail!r}")

    for owner, names in (
        (QDialog, ("exec",)),
        (QMessageBox, ("exec", "warning", "question", "information", "critical", "about")),
        (QFileDialog, ("getOpenFileName", "getExistingDirectory", "getSaveFileName")),
        (QColorDialog, ("getColor",)),
        (QInputDialog, ("getItem", "getText")),
        (QMenu, ("exec",)),
    ):
        for name in names:
            monkeypatch.setattr(owner, name, refuse)


@pytest.fixture(scope="session")
def qapp():
    # Importing the widget module is what actually loads Qt's shared
    # libraries — the bare package import is lazy and can mask a missing
    # libglib/libGL until instantiation.
    pytest.importorskip(
        "PySide6.QtWidgets",
        reason="GUI extra not installed or Qt unusable",
        exc_type=ImportError,
    )
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def pump(qapp, condition, timeout_s: float = 5.0) -> bool:
    """Process events until `condition()` holds or the deadline passes."""
    import time

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        qapp.processEvents()
        if condition():
            return True
        time.sleep(0.02)
    qapp.processEvents()
    return condition()
