"""Main player window with interchangeable, data-only faces.

Renders PlayerState and never decides what is playing on its own. Slider
gestures preview locally and commit one command on release; the gesture is
cancelled when the track changes (spec §9).
"""
from __future__ import annotations

import base64
from collections import OrderedDict
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QBuffer, QByteArray, QElapsedTimer, QIODevice, QPoint, Qt, QTimer
from PySide6.QtGui import QImageReader, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QVBoxLayout,
)

from ..face_library import BUNDLED_FACE_ERROR, DEFAULT_FACE_ID, Face, FaceError, FaceLibrary
from .face_surface import (
    READOUT_CONTROLS,
    CoverLabel,
    ElidedLabel,
    FaceArtwork,
    FaceButton,
    FaceSlider,
    FaceSurface,
    ReadoutLabel,
    face_stylesheet,
    prepare_face,
    readout_font,
    readout_style,
)
from .placeholder import placeholder_png
from .search_window import SearchWindow

if TYPE_CHECKING:
    from .faces_window import FacesWindow

ARTWORK_CACHE_BYTES = 20 * 1024 * 1024
MAX_ARTWORK_DIMENSION = 256
MAX_ARTWORK_CACHE_ENTRIES = 80


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
        faces: FaceLibrary | None = None,
    ) -> None:
        super().__init__()
        self._request = request
        self._state: dict | None = None
        self._state_at = QElapsedTimer()
        self._seeking = False
        self._seek_occ: str | None = None
        self._pending_transport = False
        self._pending_like = False
        self._bound_token: str | None = None
        self._search: SearchWindow | None = None
        self._cover_window: QDialog | None = None
        self._cover_label: QLabel | None = None
        self._faces_window: FacesWindow | None = None
        self._faces = faces or FaceLibrary()
        self._scale = scale

        self.setWindowTitle("Amberfader")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._surface = FaceSurface(self)
        self.setCentralWidget(self._surface)

        self._art = CoverLabel(self._surface)
        self._art.setObjectName("art")
        self._placeholder = QPixmap()
        self._placeholder.loadFromData(QByteArray(placeholder_png()))
        self._cover = self._placeholder
        self._artwork_cache: OrderedDict[tuple[str, str], tuple[QPixmap, int]] = OrderedDict()
        self._artwork_cache_bytes = 0
        self._title = ElidedLabel("Nothing selected", self._surface)
        self._title.setObjectName("title")
        self._artists = ElidedLabel("Waiting for Firefox…", self._surface)
        self._artists.setObjectName("artists")
        self._time = ReadoutLabel("–:–– / –:––", self._surface)
        self._time.setObjectName("time")
        self._playback = ElidedLabel("OFFLINE", self._surface)
        self._playback.setObjectName("playback")

        self._prev = self._button("⏮", "Previous")
        self._play = self._button("▶", "Play/Pause (Space)")
        self._next = self._button("⏭", "Next")
        self._like = self._button("♡?", "Like or unlike this song")
        self._like.setToolTip("Liked state unknown")
        self._like.setEnabled(False)

        self._seek = FaceSlider(Qt.Orientation.Horizontal, self._surface)
        self._seek.setRange(0, 1000)
        self._seek.setToolTip("Seek")
        self._seek.setAccessibleName("Seek")
        self._vol = FaceSlider(Qt.Orientation.Horizontal, self._surface)
        self._vol.setRange(0, 100)
        self._vol.setValue(80)
        self._vol.setToolTip("Volume")
        self._vol.setAccessibleName("Volume")
        self._btn_search = self._button("Search", "Search songs (Ctrl+F)")
        self._btn_show = self._button("Show YT", "Show the YouTube Music tab")
        self._btn_hide = self._button("Hide", "Hide the playback tab (opt-in)")
        self._btn_menu = self._button("☰", "Menu and Faces (Ctrl+,)")
        self._btn_minimize = self._button("\u2212", "Minimize")
        self._btn_close = self._button("\u00d7", "Close Amberfader; music keeps playing")

        self._status = ElidedLabel("", self._surface)
        self._status.setObjectName("status")
        self._controls = {
            "art": self._art, "title": self._title, "artists": self._artists,
            "time": self._time, "playback": self._playback,
            "previous": self._prev, "play": self._play, "next": self._next, "like": self._like,
            "seek": self._seek, "volume": self._vol, "search": self._btn_search,
            "show": self._btn_show, "hide": self._btn_hide, "menu": self._btn_menu,
            "status": self._status, "minimize": self._btn_minimize, "close": self._btn_close,
        }
        for name, widget in self._controls.items():
            widget.setObjectName(name)
            if isinstance(widget, QLabel):
                widget.setTextFormat(Qt.TextFormat.PlainText)
        self._menu = QMenu(self)
        self._menu.addAction("Faces…", self.open_faces)
        self._menu.addAction("Cover view", self.open_cover)
        self._menu.addAction("Search", self.open_search)
        self._menu.addSeparator()
        self._menu.addAction("Close Amberfader", self.close)
        initial_error = ""
        try:
            face = self._faces.load(self._faces.preferred_id())
            artwork = prepare_face(face)
        except FaceError as exc:
            initial_error = f"Saved face could not load: {exc}. Using Amber Classic."
            try:
                face = self._faces.load(DEFAULT_FACE_ID)
                artwork = prepare_face(face)
            except FaceError as default_error:
                raise FaceError(BUNDLED_FACE_ERROR) from default_error
        self._apply_face(face, artwork)

        # wiring
        self._play.clicked.connect(self._toggle_play)
        self._like.clicked.connect(self._toggle_like)
        self._prev.clicked.connect(lambda: self._request("player.previous", {}))
        self._next.clicked.connect(lambda: self._request("player.next", {}))
        self._btn_show.clicked.connect(lambda: self._request("browser.showPlayer", {}))
        self._btn_hide.clicked.connect(lambda: self._request("browser.hidePlayer", {}))
        self._btn_search.clicked.connect(self.open_search)
        self._btn_menu.clicked.connect(lambda: self._menu.popup(
            self._btn_menu.mapToGlobal(QPoint(0, self._btn_menu.height()))
        ))
        self._btn_minimize.clicked.connect(self.showMinimized)
        self._btn_close.clicked.connect(self.close)
        self._art.activated.connect(self.open_cover)
        self._seek.sliderPressed.connect(self._seek_press)
        self._seek.sliderReleased.connect(self._seek_release)
        self._seek.sliderMoved.connect(self._seek_preview)
        self._vol.sliderReleased.connect(self._vol_release)

        QShortcut(QKeySequence(Qt.Key.Key_Space), self, self._toggle_play)
        QShortcut(QKeySequence("Ctrl+F"), self, self.open_search)
        QShortcut(QKeySequence("Ctrl+,"), self, self.open_faces)

        self._tick = QTimer(self)
        self._tick.setInterval(500)
        self._tick.timeout.connect(self._render_time)
        self._tick.start()

        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.setInterval(4000)
        self._status_timer.timeout.connect(lambda: self._status.setText(""))
        if initial_error:
            self.show_status(initial_error, error=True)
        elif self._faces.problems:
            self.show_status("Some faces could not load. Open Faces for details.", error=True)
        else:
            self.show_status("Waiting for Firefox…")

    def _button(self, text: str, description: str) -> FaceButton:
        button = FaceButton(text, self._surface)
        button.setToolTip(description)
        button.setAccessibleName(description)
        return button

    def closeEvent(self, event) -> None:
        # Auxiliary top-level windows would otherwise keep the GUI alive after
        # its player closes. Closing presentation must never send playback work.
        for window in (self._faces_window, self._cover_window, self._search):
            if window is not None:
                window.close()
        super().closeEvent(event)

    # ---- appearance ------------------------------------------------------

    def _apply_face(self, face: Face, artwork: FaceArtwork) -> None:
        effective_scale = self._scale
        if self.screen() is not None:
            available = self.screen().availableGeometry()
            effective_scale = min(
                effective_scale, available.width() / face.size[0], available.height() / face.size[1]
            )
        size = tuple(round(value * effective_scale) for value in face.size)
        self.setStyleSheet(face_stylesheet(face, effective_scale))
        self.setFixedSize(*size)
        self._surface.apply_face(face, artwork, effective_scale)
        self.setMask(artwork.scaled_mask(size))
        # Move the same widgets, preserving focus, pending commands and gestures.
        for name, widget in self._controls.items():
            widget.setGeometry(*(round(value * effective_scale) for value in face.controls[name]))
            if isinstance(widget, FaceButton):
                widget.set_sprites(artwork.buttons.get(name, {}))
                widget.set_shape(
                    face.control_shapes.get(name, "rectangle"), face.radius * effective_scale,
                )
            elif isinstance(widget, FaceSlider):
                widget.set_face(face)
            elif name in READOUT_CONTROLS:
                widget.setAlignment(readout_style(face, name).alignment)
                widget.setFont(readout_font(face, name, effective_scale))
        self._art.set_shape(
            face.control_shapes.get("art", "rectangle"), face.radius * effective_scale,
            face.cover_glass,
        )
        self._face_id = face.info.id
        self._render_cover()
        if self._search is not None:
            self._search.setStyleSheet(self.styleSheet())
        if self._cover_window is not None:
            self._cover_window.setStyleSheet(self.styleSheet())

    def select_face(self, face_id: str) -> None:
        """Apply and persist a face without issuing a player command."""
        # Validate/decode before saving so a broken pack cannot poison startup.
        face = self._faces.load(face_id)
        artwork = prepare_face(face)
        self._faces.remember(face_id)
        self._apply_face(face, artwork)

    def open_faces(self) -> None:
        from .faces_window import FacesWindow

        if self._faces_window is None:
            self._faces_window = FacesWindow(self._faces, self.select_face, self)
        self._faces_window.refresh(self._face_id)
        self._faces_window.show()
        self._faces_window.raise_()
        self._faces_window.activateWindow()

    def open_cover(self) -> None:
        if self._cover_window is None:
            self._cover_window = QDialog(self)
            self._cover_window.setWindowTitle("Amberfader · Cover view")
            self._cover_label = QLabel(self._cover_window)
            self._cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._cover_label.setFixedSize(384, 384)
            layout = QVBoxLayout(self._cover_window)
            layout.addWidget(self._cover_label)
        self._render_cover()
        self._cover_window.show()
        self._cover_window.raise_()
        self._cover_window.activateWindow()

    def _render_cover(self) -> None:
        for label in (self._art, self._cover_label):
            if label is not None:
                mode = (
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding if label is self._art
                    else Qt.AspectRatioMode.KeepAspectRatio
                )
                label.setPixmap(self._cover.scaled(
                    label.size(), mode,
                    Qt.TransformationMode.SmoothTransformation,
                ))

    @staticmethod
    def _artwork_key(data: dict) -> tuple[str, str] | None:
        occurrence = data.get("occurrenceId")
        artwork = data.get("artworkId")
        if not isinstance(occurrence, str) or not occurrence:
            return None
        if not isinstance(artwork, str) or not artwork:
            return None
        return occurrence, artwork

    def _restore_cover(self, track: dict | None) -> None:
        key = self._artwork_key(track or {})
        cached = self._artwork_cache.get(key) if key is not None else None
        if cached is not None:
            self._artwork_cache.move_to_end(key)
        cover = cached[0] if cached is not None else self._placeholder
        if self._cover.cacheKey() != cover.cacheKey():
            self._cover = cover
            self._render_cover()

    # ---- state -----------------------------------------------------------

    def apply_state(self, state: dict) -> None:
        self._state = state
        self._state_at.start()
        track = state.get("track")
        # A new playback target invalidates the open search session.
        binding = state.get("bindingToken")
        if (
            self._bound_token is not None
            and binding != self._bound_token
            and self._search is not None
        ):
            self._search.mark_stale()
        self._bound_token = binding
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
        self._restore_cover(track)

        playing = state.get("status") == "playing"
        status = state.get("status", "unknown")
        self._playback.setText(str(status).upper())
        self._playback.setToolTip(f"Playback: {status}")
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
        self._render_like()
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
        self._time.setToolTip(self._time.text())
        dur = st.get("durationSeconds")
        if not self._seeking and isinstance(dur, int | float) and dur > 0 and pos is not None:
            self._seek.setValue(int(min(max(pos / dur, 0), 1) * 1000))

    def apply_asset(self, data: dict) -> None:
        key = self._artwork_key(data)
        raw = data.get("dataBase64")
        if key is None or not isinstance(raw, str):
            return
        try:
            encoded = QByteArray(base64.b64decode(raw, validate=True))
        except ValueError:
            return
        buffer = QBuffer(encoded)
        buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        reader = QImageReader(buffer)
        size = reader.size()
        # Validate the encoded image, not only the sender's declared dimensions.
        if not (
            0 < size.width() <= MAX_ARTWORK_DIMENSION
            and 0 < size.height() <= MAX_ARTWORK_DIMENSION
        ):
            return
        cost = size.width() * size.height() * 4
        if cost > ARTWORK_CACHE_BYTES:
            return
        image = reader.read()
        if image.isNull():
            return
        pix = QPixmap.fromImage(image)
        previous = self._artwork_cache.pop(key, None)
        if previous is not None:
            self._artwork_cache_bytes -= previous[1]
        while (
            self._artwork_cache_bytes + cost > ARTWORK_CACHE_BYTES
            or len(self._artwork_cache) >= MAX_ARTWORK_CACHE_ENTRIES
        ):
            _, (_, discarded_cost) = self._artwork_cache.popitem(last=False)
            self._artwork_cache_bytes -= discarded_cost
        self._artwork_cache[key] = pix, cost
        self._artwork_cache_bytes += cost
        # Assets may precede state or finish after a different track was selected.
        # Retain bounded bytes for replay, but render only the observed occurrence.
        track = (self._state or {}).get("track")
        if self._artwork_key(track or {}) == key:
            self._cover = pix
            self._render_cover()

    def set_connection(self, component: str, status: str, reason: str = "") -> None:
        if component in ("gui", "target", "adapter") and status != "connected":
            self._state = None
            self._playback.setText("OFFLINE")
            self._render_like()
            if self._search:
                self._search.mark_stale()

        if component == "gui" and status == "disconnected":
            self.show_status("Disconnected from Firefox bridge", error=True)
        elif component == "target" and status != "connected":
            self.show_status(reason or "Playback tab disconnected", error=True)

    def binding_changed(self) -> None:
        """Disable occurrence-bound actions until a fresh target state arrives."""
        self._state = None
        self._render_like()
        if self._search:
            self._search.mark_stale()

    def raise_requested(self) -> None:
        """Second-instance activation: surface the existing window."""
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def show_status(self, text: str, error: bool = False) -> None:
        self._status.setText(text)
        self._status.setToolTip(text)
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

    def _toggle_like(self) -> None:
        st = self._state or {}
        liked = st.get("liked")
        occurrence = (st.get("track") or {}).get("occurrenceId")
        if (
            self._pending_like
            or not isinstance(occurrence, str)
            or not isinstance(liked, bool)
            or "setLiked" not in (st.get("capabilities") or [])
        ):
            return
        self._pending_like = True
        self._render_like()
        # No optimistic flip: the heart follows the next reported state.
        self._request(
            "player.setLiked", {"occurrenceId": occurrence, "liked": not liked}
        )

    def _render_like(self) -> None:
        st = self._state or {}
        liked = st.get("liked")
        known = isinstance(liked, bool)
        self._like.setText(("♥" if liked else "♡") if known else "♡?")
        self._like.setProperty("pending", self._pending_like)
        self._like.style().unpolish(self._like)
        self._like.style().polish(self._like)
        if self._pending_like:
            self._like.setEnabled(False)
            self._like.setToolTip("Updating like…")
            return
        if not st.get("track"):
            self._like.setEnabled(False)
            self._like.setToolTip("No track selected")
            return
        if "setLiked" not in (st.get("capabilities") or []):
            self._like.setEnabled(False)
            self._like.setToolTip("Liking is not available for this track")
            return
        if not known:
            self._like.setEnabled(False)
            self._like.setToolTip("Like state is unknown for this track")
            return
        self._like.setEnabled(True)
        self._like.setToolTip("Unlike this song" if liked else "Like this song")

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
            self._search.setStyleSheet(self.styleSheet())
        self._search.show()
        self._search.raise_()
        self._search.activateWindow()
        self._search._q.setFocus()

    def route_response(self, method: str, ok: bool, payload: dict) -> None:
        if method == "player.setLiked":
            self._pending_like = False
            self._render_like()
        elif method in ("player.play", "player.pause"):
            self.command_settled()
        if method.startswith("search.") and self._search is not None:
            self._search.apply_response(method, ok, payload)
        if not ok:
            self.show_status(payload.get("message", "command failed"), error=True)
