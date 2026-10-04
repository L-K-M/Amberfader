"""Where playback runs, and the user-facing copy that depends on it.

Firefox mode attaches to a YouTube Music tab through the extension and the
native-messaging helper; closing Amberfader leaves Firefox playing. The
embedded prototype plays inside this process, so closing it stops the music
and its window controls show or hide the embedded page instead of a tab.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PlaybackHost(Enum):
    FIREFOX = "firefox"
    EMBEDDED = "embedded"


@dataclass(frozen=True)
class HostCopy:
    waiting: str
    connected: str
    not_connected: str
    disconnected: str
    lost_status: str
    unbound: str
    invalid_snapshot: str
    target_lost: str
    show_tip: str
    hide_tip: str
    close_tip: str


HOST_COPY = {
    PlaybackHost.FIREFOX: HostCopy(
        waiting="Waiting for Firefox…",
        connected="Firefox connected",
        not_connected="Firefox bridge is not connected",
        disconnected="Firefox bridge disconnected",
        lost_status="Disconnected from Firefox bridge",
        unbound="Playback tab is not connected. Reconnect in the extension options.",
        invalid_snapshot="Firefox returned an invalid player snapshot.",
        target_lost="Playback tab disconnected",
        show_tip="Show the YouTube Music tab",
        hide_tip="Hide the playback tab (opt-in)",
        close_tip="Close Amberfader; music keeps playing",
    ),
    PlaybackHost.EMBEDDED: HostCopy(
        waiting="Loading YouTube Music…",
        # The in-process router attaches at startup, before the page loads.
        connected="Loading YouTube Music…",
        not_connected="The YouTube Music page is not attached",
        disconnected="The YouTube Music page detached",
        lost_status="Disconnected from the YouTube Music page",
        unbound="YouTube Music is not ready. Use Show YT to check the page or sign in.",
        invalid_snapshot="The YouTube Music page returned an invalid player snapshot.",
        target_lost="YouTube Music page disconnected",
        show_tip="Show the YouTube Music window",
        hide_tip="Hide the YouTube Music window",
        close_tip="Quit Amberfader; music stops",
    ),
}
