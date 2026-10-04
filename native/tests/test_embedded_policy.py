"""Embedded prototype: search-history store and navigation policy (Qt-free)."""
import json
import os

import pytest

from amberfader.embedded.history import (
    MAX_ITEM_LENGTH,
    RECENT_ITEMS_CAP,
    SearchHistoryStore,
    normalized_items,
)
from amberfader.embedded.navigation import navigation_allowed, opens_externally


def test_history_normalization_matches_the_extension_rules():
    items = normalized_items(["  Amber\x00Fade ", "amber fade", 7, "", "\x85", "x" * 600])

    assert items == ("Amber Fade", "x" * MAX_ITEM_LENGTH)
    assert len(normalized_items([str(i) for i in range(50)])) == RECENT_ITEMS_CAP
    assert normalized_items("not a list") == ()


def test_history_store_round_trip(tmp_path):
    store = SearchHistoryStore(tmp_path / "state" / "history.json")

    store.record_query("one")
    store.record_query("two")
    store.record_query("ONE")
    store.record_artists(["Slow Decay", "Guest"])

    history = store.get()
    assert history.queries == ("ONE", "two")
    assert history.artists == ("Slow Decay", "Guest")
    assert oct(os.stat(tmp_path / "state").st_mode & 0o777) == "0o700"
    assert store.clear().as_result() == {"queries": [], "artists": []}
    assert json.loads((tmp_path / "state" / "history.json").read_text()) == {
        "queries": [], "artists": [],
    }


@pytest.mark.parametrize("content", [b"{broken", b"\xff\xfe", b"[]", b"x" * (300 * 1024)])
def test_unreadable_history_reads_as_empty_and_is_replaced(tmp_path, content):
    path = tmp_path / "history.json"
    path.write_bytes(content)
    store = SearchHistoryStore(path)

    assert store.get().queries == ()
    store.record_query("fresh")
    assert store.get().queries == ("fresh",)


def test_history_write_failures_are_raised(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("")
    store = SearchHistoryStore(blocker / "history.json")

    with pytest.raises(OSError):
        store.record_query("cannot save")


@pytest.mark.parametrize("url", [
    "https://music.youtube.com/watch?v=abc",
    "https://accounts.google.com/v3/signin/identifier",
    "https://accounts.youtube.com/accounts/SetSID",
    "https://consent.youtube.com/m",
    "https://accounts.google.ch/accounts/SetSID",
    "https://accounts.google.co.uk/accounts/SetSID",
    "https://accounts.google.com.au/accounts/SetSID",
    "https://www.google.com/",
    "https://music.youtube.com:443/",
])
def test_sign_in_and_music_pages_stay_in_the_view(url):
    assert navigation_allowed(url)


@pytest.mark.parametrize("url", [
    "http://music.youtube.com/",
    "https://music.youtube.com:8443/",
    "https://music.youtube.com.example.net/",
    "https://evilyoutube.com/",
    "https://notgoogle.com/",
    "https://google.example.com/",
    "https://google.xyz/",
    "https://accounts.google.xyz/",
    "https://www.google.co.uk/",
    "https://google.com.au/",
    "https://mail.google.ch/",
    "https://accounts.google.com.example.net/",
    "https://music.youtube.com@example.net/",
    "https://www.example.org/artist",
    "file:///etc/passwd",
    "javascript:alert(1)",
    "https://[::1/",
])
def test_other_pages_do_not_load_in_the_view(url):
    assert not navigation_allowed(url)


def test_home_origin_is_configurable_for_the_test_page():
    assert navigation_allowed("https://amberfader.invalid/", "https://amberfader.invalid")
    assert not navigation_allowed("https://amberfader.invalid/")


@pytest.mark.parametrize(("url", "expected"), [
    ("https://www.example.org/", True),
    ("http://example.org/", True),
    ("file:///etc/passwd", False),
    ("javascript:alert(1)", False),
    ("mailto:someone@example.org", False),
])
def test_only_web_links_open_externally(url, expected):
    assert opens_externally(url) is expected
