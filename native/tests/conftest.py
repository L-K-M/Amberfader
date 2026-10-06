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
    from amberfader import face_library, paths

    home = tmp_path_factory.mktemp("home")
    for variable in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setattr(face_library, "app_dirs", lambda: paths.app_dirs(home=home))
    return home


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
