"""User-facing copy for the player's connection states and window controls.

Playback runs inside this process, so closing the player quits Amberfader and
stops the music, and the window controls show or hide the YouTube Music page.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlayerCopy:
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


PLAYER_COPY = PlayerCopy(
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
)
