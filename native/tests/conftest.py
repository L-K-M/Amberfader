"""Shared fixtures. Qt tests run offscreen — no display server needed."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


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
