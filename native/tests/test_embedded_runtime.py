"""How the runtime applies a menu switch, with the page and store faked."""
from types import SimpleNamespace

import pytest

pytest.importorskip(
    "PySide6.QtWebEngineCore", reason="Qt WebEngine unavailable", exc_type=ImportError,
)

from amberfader.embedded.runtime import SETTING_SAVED, EmbeddedRuntime
from amberfader.settings import AppSettings


class _Store:
    def __init__(self, error=None):
        self.error = error
        self.saved = []

    def save(self, settings):
        if self.error:
            raise self.error
        self.saved.append(settings)


def _runtime(store):
    # Only _change runs here; it needs no QtWebEngine page.
    runtime = EmbeddedRuntime.__new__(EmbeddedRuntime)
    applied, statuses = [], []
    runtime.settings = AppSettings()
    runtime.settings_store = store
    runtime.ad_requests = SimpleNamespace(enabled=True)
    runtime.host = SimpleNamespace(apply_settings=applied.append)
    runtime.amber = SimpleNamespace(window=SimpleNamespace(
        show_status=lambda text, error=False: statuses.append((text, error)),
    ))
    return runtime, applied, statuses


def test_switch_applies_saves_and_reports():
    store = _Store()
    runtime, applied, statuses = _runtime(store)
    off = AppSettings(block_ads=False)

    runtime._change(off)

    assert runtime.settings == off
    assert runtime.ad_requests.enabled is False
    assert applied == [off]
    assert store.saved == [off]
    assert statuses == [(SETTING_SAVED, False)]


def test_switch_still_applies_when_saving_fails():
    runtime, applied, statuses = _runtime(_Store(OSError(28, "No space left on device")))
    off = AppSettings(continue_playing=False)

    runtime._change(off)

    assert runtime.settings == off
    assert applied == [off]
    assert statuses == [(
        "Applied for now, but could not be saved: No space left on device", True,
    )]
