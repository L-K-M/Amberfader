"""Offscreen GUI tests: like toggle, search history, start-radio actions."""
import pytest

pytest.importorskip(
    "PySide6.QtWidgets",
    reason="GUI extra not installed or Qt unavailable",
    exc_type=ImportError,
)

from PySide6.QtCore import Qt

from amberfader.ui.main_window import MainWindow
from amberfader.ui.search_window import SearchWindow


def _state(**overrides):
    state = {
        "bindingToken": "binding-1",
        "revision": 1,
        "track": {
            "occurrenceId": "occ-1",
            "providerId": "prov-1",
            "title": "Song",
            "artists": ["Artist"],
            "album": None,
            "artworkId": None,
        },
        "status": "paused",
        "contentKind": "track",
        "positionSeconds": 10,
        "durationSeconds": 200,
        "playbackRate": 1.0,
        "volume": 0.8,
        "muted": False,
        "capabilities": ["play", "pause", "setLiked", "startRadio"],
        "liked": False,
    }
    state.update(overrides)
    return state


def _results():
    return [
        {
            "resultId": "r1",
            "kind": "song",
            "title": "One",
            "artists": ["A"],
            "album": None,
            "durationSeconds": 100,
            "supported": True,
            "radioSupported": True,
            "artworkId": None,
        },
        {
            "resultId": "r2",
            "kind": "song",
            "title": "Two",
            "artists": ["B"],
            "album": None,
            "durationSeconds": 90,
            "supported": True,
            "artworkId": None,
        },
    ]


def _load_results(win, token="tok"):
    win.apply_response(
        "search.songs",
        True,
        {"searchToken": token, "complete": True, "results": _results()},
    )


@pytest.fixture()
def window(qapp):
    sent: list[tuple[str, dict]] = []
    w = MainWindow(lambda method, params: sent.append((method, params)))
    yield w, sent
    w.close()
    w.deleteLater()


@pytest.fixture()
def search(qapp):
    sent: list[tuple[str, dict]] = []
    w = SearchWindow(lambda method, params: sent.append((method, params)))
    yield w, sent
    w.close()
    w.deleteLater()


def test_heart_filled_when_liked(window):
    w, _ = window
    w.apply_state(_state(liked=True))
    assert w._like.isEnabled()
    assert w._like.text() == "♥"


def test_heart_outline_when_not_liked(window):
    w, _ = window
    w.apply_state(_state(liked=False))
    assert w._like.isEnabled()
    assert w._like.text() == "♡"


def test_heart_disabled_when_like_state_unknown(window):
    w, _ = window
    assert not w._like.isEnabled()
    unknown = _state()
    del unknown["liked"]
    w.apply_state(unknown)
    assert not w._like.isEnabled()
    assert "unknown" in w._like.toolTip().lower()
    w.apply_state(_state(liked=None))
    assert not w._like.isEnabled()


def test_heart_disabled_without_track_or_capability(window):
    w, _ = window
    w.apply_state(_state(capabilities=["play"], liked=True))
    assert not w._like.isEnabled()
    w.apply_state(_state(track=None, liked=True))
    assert not w._like.isEnabled()


def test_heart_sends_set_liked_and_waits_for_state(window):
    w, sent = window
    w.apply_state(_state(liked=False))
    w._like.click()
    assert sent == [("player.setLiked", {"occurrenceId": "occ-1", "liked": True})]
    assert w._pending_like
    assert not w._like.isEnabled()
    # No optimistic flip: the icon follows reported state only.
    assert w._like.text() == "♡"
    w.apply_state(_state(liked=True))
    assert w._like.text() == "♥"
    assert not w._like.isEnabled()


def test_heart_rejects_duplicate_activation(window):
    w, sent = window
    w.apply_state(_state(liked=True))
    w._like.click()
    w._like.click()
    assert [m for m, _ in sent].count("player.setLiked") == 1
    assert sent[0][1]["liked"] is False


def test_heart_settles_only_on_set_liked(window):
    w, _ = window
    w.apply_state(_state(liked=False))
    w._like.click()
    w.route_response("search.songs", True, {})
    w.route_response("player.play", True, {})
    assert w._pending_like
    assert not w._like.isEnabled()
    w.route_response("player.setLiked", True, {})
    assert not w._pending_like
    assert w._like.isEnabled()


def test_play_pending_not_settled_by_like_response(window):
    w, _ = window
    w.apply_state(_state())
    w._toggle_play()
    assert w._pending_transport
    w.route_response("player.setLiked", True, {})
    assert w._pending_transport
    assert not w._play.isEnabled()
    w.route_response("player.play", True, {})
    assert not w._pending_transport


def test_history_loaded_on_every_open(search, qapp):
    w, sent = search
    w.show()
    qapp.processEvents()
    assert ("search.history", {}) in sent
    w.hide()
    sent.clear()
    w.show()
    qapp.processEvents()
    assert ("search.history", {}) in sent


def test_history_renders_and_entries_search_again(search):
    w, sent = search
    w.apply_response(
        "search.history",
        True,
        {"queries": ["old query"], "artists": ["Old Artist"]},
    )
    assert not w._history_box.isHidden()
    items = [w._history.item(i) for i in range(w._history.count())]
    values = [i.data(Qt.ItemDataRole.UserRole) for i in items]
    assert "old query" in values
    assert "Old Artist" in values

    w._history.itemClicked.emit(items[values.index("old query")])
    assert ("search.songs", {"query": "old query"}) in sent

    sent.clear()
    w.apply_response(
        "search.songs", True, {"searchToken": "t", "complete": True, "results": []}
    )
    # A successful search refreshes the recent list.
    assert ("search.history", {}) in sent
    w._history.itemClicked.emit(items[values.index("Old Artist")])
    assert ("search.songs", {"query": "Old Artist"}) in sent


def test_history_cleared_via_button(search):
    w, sent = search
    w.apply_response("search.history", True, {"queries": ["q"], "artists": []})
    w._btn_clear_history.click()
    assert ("search.clearHistory", {}) in sent
    w.apply_response("search.clearHistory", True, {"queries": [], "artists": []})
    assert w._history.count() == 0
    assert w._history_box.isHidden()


def test_history_responses_do_not_touch_search_busy(search):
    w, _ = search
    w._q.setText("abc")
    w._submit()
    assert w._busy
    w.apply_response("search.history", True, {"queries": [], "artists": []})
    w.apply_response("search.clearHistory", True, {"queries": [], "artists": []})
    assert w._busy


def test_start_radio_sends_request_without_playing(search):
    w, sent = search
    _load_results(w)
    w._list.setCurrentItem(w._list.item(0))
    assert w._btn_radio.isEnabled()
    sent.clear()
    w._btn_radio.click()
    assert sent == [
        ("search.startRadio", {"searchToken": "tok", "resultId": "r1"})
    ]
    assert w._busy
    w.apply_response("search.startRadio", True, {})
    assert not w._busy
    assert w._status.text() == "Mix started"


def test_radio_button_disabled_without_row_support(search):
    w, _ = search
    _load_results(w)
    w._list.setCurrentItem(w._list.item(1))
    assert not w._btn_radio.isEnabled()


def test_radio_and_play_guarded_when_stale(search):
    w, sent = search
    _load_results(w)
    w._list.setCurrentItem(w._list.item(0))
    w.mark_stale()
    assert w._token is None
    assert not w._busy
    assert not w._btn_radio.isEnabled()
    sent.clear()
    w._start_radio()
    w._play_item(w._list.item(0))
    assert sent == []
    assert not (w._list.item(0).flags() & Qt.ItemFlag.ItemIsEnabled)


def test_radio_guarded_while_busy(search):
    w, sent = search
    _load_results(w)
    w._list.setCurrentItem(w._list.item(0))
    w._start_radio()
    sent.clear()
    assert w._busy
    assert not w._btn_radio.isEnabled()
    w._start_radio()
    assert sent == []


def test_binding_change_marks_search_stale(window):
    w, _ = window
    w.open_search()
    s = w._search
    _load_results(s)
    assert s._token == "tok"
    w.apply_state(_state())
    assert s._token == "tok"
    w.apply_state(_state(bindingToken="binding-2"))
    assert s._token is None
    s._token = "tok2"
    w.apply_state(_state(bindingToken="binding-2"))
    assert s._token == "tok2"


@pytest.mark.parametrize("component", ["gui", "target", "adapter"])
def test_heart_disabled_after_disconnect(window, component):
    w, sent = window
    w.apply_state(_state(liked=True))
    w.set_connection(component, "disconnected", "Connection lost")
    assert not w._like.isEnabled()
    w._toggle_like()
    assert sent == []


def test_new_binding_disables_heart_and_mix_until_fresh_state(window):
    w, _ = window
    w.apply_state(_state(liked=True))
    w.open_search()
    _load_results(w._search)
    w.binding_changed()
    assert not w._like.isEnabled()
    assert w._like.text() == "♡?"
    assert w._search._token is None
    assert not w._search._btn_radio.isEnabled()
