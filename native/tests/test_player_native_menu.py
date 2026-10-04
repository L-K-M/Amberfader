"""Player menu actions share command paths without changing shaped faces."""

from __future__ import annotations

import pytest

from amberfader.face_library import FaceLibrary


@pytest.fixture()
def player(qapp, tmp_path):
    from amberfader.ui.main_window import MainWindow

    sent = []
    library = FaceLibrary(tmp_path / "faces", tmp_path / "appearance.json")
    window = MainWindow(lambda method, params: sent.append((method, params)), faces=library)
    window.show()
    qapp.processEvents()
    yield window, sent
    window.close()
    window.deleteLater()
    qapp.processEvents()


def _menus(window):
    return {action.text(): action.menu() for action in window.menuBar().actions()}


def _actions(menu):
    return {action.text(): action for action in menu.actions() if not action.isSeparator()}


def _state(**changes):
    state = {
        "bindingToken": "binding-1",
        "track": {"occurrenceId": "occ-1", "title": "Song", "artists": ["Artist"]},
        "status": "paused",
        "positionSeconds": 10,
        "durationSeconds": 200,
        "capabilities": ["play", "pause", "previous", "next", "setLiked"],
        "liked": False,
    }
    state.update(changes)
    return state


def test_player_native_menu_shares_existing_popup_actions(player):
    window, sent = player
    menus = _menus(window)
    assert list(menus) == ["&File", "&Playback", "&View", "&Window"]
    file_actions = _actions(menus["&File"])
    view_actions = _actions(menus["&View"])
    popup = _actions(window._menu)
    for label in ("Faces…", "Face editor…", "Close Amberfader"):
        assert file_actions[label] is popup[label]
    for label in ("Search", "Cover view"):
        assert view_actions[label] is popup[label]
    assert sent == []


def test_native_menu_does_not_reserve_space_inside_any_face(player, qapp):
    from amberfader.ui.face_surface import prepare_face

    window, _ = player
    assert window.menuBar().isHidden()
    for info in window._faces.faces:
        window.select_face(info.id)
        qapp.processEvents()
        assert window._surface.geometry() == window.rect(), info.id
        artwork = prepare_face(window._faces.load(info.id))
        assert window.mask() == artwork.scaled_mask(
            (window.width(), window.height()),
        ), info.id


def test_playback_menu_uses_observed_state_and_pending_guard(player):
    window, sent = player
    menu = _menus(window)["&Playback"]
    assert all(not action.isEnabled() for action in menu.actions())
    window.apply_state(_state())
    play = _actions(menu)["Play"]
    play.trigger()
    play.trigger()
    assert sent == [("player.play", {})]
    assert not play.isEnabled()

    window.apply_state(_state(status="playing"))
    assert play.text() == "Pause"
    assert not play.isEnabled()
    window.route_response("player.play", True, {})
    assert play.isEnabled()
    play.trigger()
    play.trigger()
    assert sent == [("player.play", {}), ("player.pause", {})]
    assert not play.isEnabled()


def test_previous_and_next_menu_use_existing_button_commands(player):
    window, sent = player
    window.apply_state(_state())
    actions = _actions(_menus(window)["&Playback"])
    actions["Previous track"].trigger()
    actions["Next track"].trigger()
    assert sent == [("player.previous", {}), ("player.next", {})]


def test_like_menu_waits_for_reported_state_and_command_settlement(player):
    window, sent = player
    menu = _menus(window)["&Playback"]
    window.apply_state(_state(liked=None))
    like = _actions(menu)["Like song"]
    assert not like.isEnabled()
    like.trigger()
    assert sent == []

    window.apply_state(_state())
    assert like.isEnabled()
    like.trigger()
    assert like.text() == "Like song"
    assert not like.isEnabled()
    assert sent == [("player.setLiked", {"occurrenceId": "occ-1", "liked": True})]
    window.apply_state(_state(liked=True))
    assert like.text() == "Unlike song"
    assert not like.isEnabled()
    window.route_response("player.setLiked", True, {})
    assert like.isEnabled()
    like.trigger()
    assert sent[-1] == ("player.setLiked", {"occurrenceId": "occ-1", "liked": False})


@pytest.mark.parametrize("lost", ["binding", "connection"])
def test_menu_commands_disable_when_target_is_lost(player, lost):
    window, sent = player
    window.apply_state(_state())
    menu = _menus(window)["&Playback"]
    if lost == "binding":
        window.binding_changed()
    else:
        window.set_connection("gui", "disconnected")
    for action in menu.actions():
        assert not action.isEnabled()
        action.trigger()
    assert sent == []


def test_menu_respects_capability_changes(player):
    window, sent = player
    window.apply_state(_state(capabilities=[]))
    for action in _menus(window)["&Playback"].actions():
        assert not action.isEnabled()
        action.trigger()
    assert sent == []


def test_browser_menu_uses_existing_commands(player):
    window, sent = player
    actions = _actions(_menus(window)["&View"])
    actions["Show YouTube Music"].trigger()
    actions["Hide YouTube Music"].trigger()
    assert sent == [("browser.showPlayer", {}), ("browser.hidePlayer", {})]


def test_close_menu_only_closes_presentation(player):
    window, sent = player
    closed = []
    window.closed.connect(lambda: closed.append(True))
    _actions(_menus(window)["&File"])["Close Amberfader"].trigger()
    assert not window.isVisible()
    assert closed == [True]
    assert sent == []
