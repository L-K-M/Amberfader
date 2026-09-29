"""Main player window — compact classic skin, ~360x150 logical px at 1x.

Renders PlayerState and never decides what is playing on its own. Slider
gestures preview locally and commit one command on release; the gesture is
cancelled when the track changes (spec §9).
"""
from __future__ import annotations

import base64
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QByteArray, QElapsedTimer, Qt, QTimer
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .placeholder import placeholder_png
from .search_window import SearchWindow

AMBER_QSS = """
QWidget { background: #241a10; color: #e8ddc8; font-size: 12px; }
QLabel#title { font-weight: 600; }
QLabel#dim, QLabel#status { color: #a89984; }
QLabel#status[error="true"] { color: #e86a5a; }
QLabel#art { background: #2f2314; border: 1px solid #8a5a20; }
QPushButton {
  background: #2f2314; border: 1px solid #8a5a20; border-radius: 3px;
  padding: 3px 10px; min-width: 34px;
}
QPushButton:hover:!disabled { border-color: #e8a33d; color: #f5cf8a; }
QPushButton:pressed, QPushButton[pending="true"] { background: #e8a33d; color: #241a10; }
QPushButton:disabled { opacity: 0.45; }
QSlider::groove:horizontal { height: 4px; background: #3a2c18; }
QSlider::handle:horizontal { width: 12px; margin: -5px 0; background: #e8a33d; border-radius: 6px; }
QSlider::sub-page:horizontal { background: #8a5a20; }
QLineEdit, QListWidget {
  background: #2f2314; color: #e8ddc8; border: 1px solid #8a5a20;
}
QListWidget::item { padding: 4px; border-bottom: 1px solid #3a2c18; }
QListWidget::item:selected { background: #4a3a20; }
QToolTip { background: #2f2314; color: #e8ddc8; border: 1px solid #8a5a20; }
"""


def _fmt(sec: Any) -> str:
    if not isinstance(sec, int | float):
        return "–:––"
    s = max(0, int(sec))
    return f"{s // 60}:{s % 60:02d}"


class MainWindow(QMainWindow):
    def __init__(
        self,
        request: Callable[[str, dict], None],
        scale: float = 1.0,
    ) -> None:
        super().__init__()
        self._request = request
        self._state: dict | None = None
        self._state_at = QElapsedTimer()
        self._seeking = False
        self._seek_occ: str | None = None
        self._pending_transport = False
        self._search: SearchWindow | None = None

        self.setWindowTitle("Amberfader")
        self.setStyleSheet(AMBER_QSS)
        self.setMinimumSize(int(360 * scale), int(150 * scale))

        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 8, 10, 6)
        root.setSpacing(6)

        top = QHBoxLayout()
        self._art = QLabel()
        self._art.setObjectName("art")
        self._art.setFixedSize(int(64 * scale), int(64 * scale))
        self._placeholder = QPixmap()
        self._placeholder.loadFromData(QByteArray(placeholder_png()))
        self._art.setPixmap(self._placeholder)
        top.addWidget(self._art)

        meta = QVBoxLayout()
        meta.setSpacing(1)
        self._title = QLabel("Nothing selected")
        self._title.setObjectName("title")
        self._artists = QLabel("Waiting for Firefox…")
        self._artists.setObjectName("dim")
        self._time = QLabel("–:–– / –:––")
        self._time.setObjectName("dim")
        for w in (self._title, self._artists, self._time):
            meta.addWidget(w)

        transport = QHBoxLayout()
        transport.setSpacing(6)
        self._prev = QPushButton("⏮")
        self._prev.setToolTip("Previous")
        self._play = QPushButton("▶")
        self._play.setToolTip("Play/Pause (Space)")
        self._next = QPushButton("⏭")
        self._next.setToolTip("Next")
        for w in (self._prev, self._play, self._next):
            transport.addWidget(w)
        transport.addStretch(1)
        meta.addLayout(transport)
        top.addLayout(meta, 1)
        root.addLayout(top)

        self._seek = QSlider(Qt.Orientation.Horizontal)
        self._seek.setRange(0, 1000)
        self._seek.setToolTip("Seek")
        root.addWidget(self._seek)

        bottom = QHBoxLayout()
        self._vol = QSlider(Qt.Orientation.Horizontal)
        self._vol.setRange(0, 100)
        self._vol.setValue(80)
        self._vol.setToolTip("Volume")
        bottom.addWidget(self._vol, 1)
        self._btn_search = QPushButton("Search")
        self._btn_search.setToolTip("Search songs (Ctrl+F)")
        self._btn_show = QPushButton("Show YT")
        self._btn_show.setToolTip("Show the YouTube Music tab")
        self._btn_hide = QPushButton("Hide")
        self._btn_hide.setToolTip("Hide the playback tab (opt-in)")
        self._btn_menu = QPushButton("☰")
        self._btn_menu.setToolTip("Menu")
        for w in (self._btn_search, self._btn_show, self._btn_hide, self._btn_menu):
            bottom.addWidget(w)
        root.addLayout(bottom)

        self._status = QLabel("")
        self._status.setObjectName("status")
        root.addWidget(self._status)

        # wiring
        self._play.clicked.connect(self._toggle_play)
        self._prev.clicked.connect(lambda: self._request("player.previous", {}))
        self._next.clicked.connect(lambda: self._request("player.next", {}))
        self._btn_show.clicked.connect(lambda: self._request("browser.showPlayer", {}))
        self._btn_hide.clicked.connect(lambda: self._request("browser.hidePlayer", {}))
        self._btn_search.clicked.connect(self.open_search)
        self._seek.sliderPressed.connect(self._seek_press)
        self._seek.sliderReleased.connect(self._seek_release)
        self._seek.sliderMoved.connect(self._seek_preview)
        self._vol.sliderReleased.connect(self._vol_release)

        QShortcut(QKeySequence(Qt.Key.Key_Space), self, self._toggle_play)
        QShortcut(QKeySequence("Ctrl+F"), self, self.open_search)

        self._tick = QTimer(self)
        self._tick.setInterval(500)
        self._tick.timeout.connect(self._render_time)
        self._tick.start()

        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.setInterval(4000)
        self._status_timer.timeout.connect(lambda: self._status.setText(""))

    # ---- state -----------------------------------------------------------

    def apply_state(self, state: dict) -> None:
        self._state = state
        self._state_at.start()
        track = state.get("track")
        caps = state.get("capabilities") or []

        if track:
            title = track.get("title") or "Unknown track"
            self._title.setText(title)
            self._title.setToolTip(title)
            sub = " — ".join(
                p for p in [", ".join(track.get("artists") or []), track.get("album")] if p
            )
            self._artists.setText(sub or "")
            self._artists.setToolTip(sub)
        else:
            self._title.setText("Nothing selected")
            self._artists.setText("Waiting for Firefox…")
            self._artists.setToolTip("")
        if not track or not track.get("artworkId"):
            self._art.setPixmap(self._placeholder)

        playing = state.get("status") == "playing"
        self._play.setText("⏸" if playing else "▶")
        self._play.setProperty("pending", self._pending_transport)
        self._play.style().unpolish(self._play)
        self._play.style().polish(self._play)

        self._play.setEnabled(
            not self._pending_transport and (("pause" if playing else "play") in caps)
        )
        self._prev.setEnabled("previous" in caps)
        self._next.setEnabled("next" in caps)
        self._seek.setEnabled("seek" in caps and bool(state.get("durationSeconds")))
        self._vol.setEnabled("volume" in caps)
        self._btn_show.setEnabled(True)
        self._btn_hide.setEnabled(True)
        self._render_time()

    def _interpolated(self) -> float | None:
        st = self._state
        if not st:
            return None
        pos = st.get("positionSeconds")
        if not isinstance(pos, int | float):
            return None
        if st.get("status") != "playing" or self._seeking:
            return float(pos)
        rate = st.get("playbackRate")
        est = float(pos) + (self._state_at.elapsed() / 1000.0) * (
            rate if isinstance(rate, int | float) else 1.0
        )
        dur = st.get("durationSeconds")
        return min(est, float(dur)) if isinstance(dur, int | float) else est

    def _render_time(self) -> None:
        st = self._state or {}
        pos = self._interpolated()
        self._time.setText(f"{_fmt(pos)} / {_fmt(st.get('durationSeconds'))}")
        dur = st.get("durationSeconds")
        if not self._seeking and isinstance(dur, int | float) and dur > 0 and pos is not None:
            self._seek.setValue(int(min(max(pos / dur, 0), 1) * 1000))

    def apply_asset(self, data: dict) -> None:
        raw = data.get("dataBase64")
        if not isinstance(raw, str):
            return
        try:
            pix = QPixmap()
            pix.loadFromData(QByteArray(base64.b64decode(raw)))
        except Exception:
            return
        if pix.isNull():
            return
        self._art.setPixmap(
            pix.scaled(
                self._art.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def set_connection(self, component: str, status: str, reason: str = "") -> None:
        if component == "gui" and status == "disconnected":
            self.show_status("Disconnected from Firefox bridge", error=True)
        elif component == "target" and status != "connected":
            self.show_status(reason or "Playback tab disconnected", error=True)
            if self._search:
                self._search.mark_stale()

    def raise_requested(self) -> None:
        """Second-instance activation: surface the existing window."""
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def show_status(self, text: str, error: bool = False) -> None:
        self._status.setText(text)
        self._status.setProperty("error", "true" if error else "false")
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)
        if text and not error:
            self._status_timer.start()

    # ---- commands ---------------------------------------------------------

    def _toggle_play(self) -> None:
        if self._pending_transport:
            return
        playing = (self._state or {}).get("status") == "playing"
        self._pending_transport = True
        self._render_transport_pending()
        self._request("player.pause" if playing else "player.play", {})

    def _render_transport_pending(self) -> None:
        self._play.setProperty("pending", self._pending_transport)
        self._play.style().unpolish(self._play)
        self._play.style().polish(self._play)
        self._play.setEnabled(False)

    def command_settled(self) -> None:
        self._pending_transport = False
        if self._state:
            self.apply_state(self._state)

    def _seek_press(self) -> None:
        self._seeking = True
        self._seek_occ = ((self._state or {}).get("track") or {}).get("occurrenceId")

    def _seek_preview(self, value: int) -> None:
        dur = (self._state or {}).get("durationSeconds")
        if isinstance(dur, int | float):
            self._time.setText(f"{_fmt(dur * value / 1000)} / {_fmt(dur)}")

    def _seek_release(self) -> None:
        self._seeking = False
        occ = self._seek_occ
        self._seek_occ = None
        dur = (self._state or {}).get("durationSeconds")
        current = ((self._state or {}).get("track") or {}).get("occurrenceId")
        if not occ or occ != current or not isinstance(dur, int | float) or dur <= 0:
            self._render_time()
            return
        self._request(
            "player.seek",
            {"occurrenceId": occ, "positionSeconds": dur * self._seek.value() / 1000},
        )

    def _vol_release(self) -> None:
        self._request("player.setVolume", {"volume": self._vol.value() / 100})

    def open_search(self) -> None:
        if self._search is None:
            self._search = SearchWindow(self._request, self)
        self._search.show()
        self._search.raise_()
        self._search.activateWindow()
        self._search._q.setFocus()

    def route_response(self, method: str, ok: bool, payload: dict) -> None:
        self.command_settled()
        if method.startswith("search.") and self._search is not None:
            self._search.apply_response(method, ok, payload)
        if not ok:
            self.show_status(payload.get("message", "command failed"), error=True)
