"""App settings: defaults, round trip, and recovery from broken files."""
import json
import os
import sys

import pytest

from amberfader.settings import (
    MAX_FILE_BYTES,
    AppSettings,
    SettingsStore,
    default_settings_path,
)


def test_defaults_turn_both_features_on(tmp_path):
    assert SettingsStore(tmp_path / "missing.json").load() == AppSettings(
        block_ads=True, continue_playing=True,
    )


def test_round_trip(tmp_path):
    path = tmp_path / "config" / "settings.json"
    store = SettingsStore(path)
    store.save(AppSettings(block_ads=False, continue_playing=True))

    assert json.loads(path.read_text()) == {"blockAds": False, "continuePlaying": True}
    assert store.load() == AppSettings(block_ads=False, continue_playing=True)
    assert [p.name for p in path.parent.iterdir()] == ["settings.json"]


# "\udcff" is written back as a lone 0xff byte: invalid UTF-8.
@pytest.mark.parametrize("contents", ["not json", "[]", '"text"', "\udcff"])
def test_broken_files_read_as_defaults(tmp_path, contents):
    path = tmp_path / "settings.json"
    path.write_text(contents, errors="surrogateescape")
    assert SettingsStore(path).load() == AppSettings()


def test_each_invalid_value_falls_back_on_its_own(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"blockAds": "no", "continuePlaying": False}))
    assert SettingsStore(path).load() == AppSettings(block_ads=True, continue_playing=False)


def test_oversized_file_reads_as_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"blockAds": False, "pad": "x" * MAX_FILE_BYTES}))
    assert SettingsStore(path).load() == AppSettings()


def test_failed_write_raises_and_leaves_no_temporary_file(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    store = SettingsStore(path)

    def broken_replace(*_args):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "replace", broken_replace)
    with pytest.raises(OSError):
        store.save(AppSettings(block_ads=False))
    assert list(tmp_path.iterdir()) == []


def test_memory_store_never_touches_disk(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = SettingsStore(None)
    store.save(AppSettings(continue_playing=False))
    assert store.load() == AppSettings(continue_playing=False)
    assert list(tmp_path.iterdir()) == []


def test_default_path_follows_xdg_config_home_on_linux(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert default_settings_path() == tmp_path / "amberfader" / "settings.json"
    monkeypatch.setenv("XDG_CONFIG_HOME", "relative")
    assert default_settings_path().parent.parent.name == ".config"
