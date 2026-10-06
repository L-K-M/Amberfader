"""Separate search window: Enter submits, results list, Enter/double-click
plays a validated selection. No per-keystroke network activity."""
from __future__ import annotations

from collections.abc import Callable
from enum import Enum, auto
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

_RADIO_ROLE = Qt.ItemDataRole.UserRole + 1
_HISTORY_CAP = 20


class _SearchActivity(Enum):
    IDLE = auto()
    PENDING = auto()


def _fmt_dur(sec: Any) -> str:
    if not isinstance(sec, int | float):
        return ""
    s = int(sec)
    return f" · {s // 60}:{s % 60:02d}"


class SearchWindow(QDialog):
    def __init__(
        self,
        request: Callable[[str, dict], None],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Amberfader — Search")
        self.resize(420, 480)
        self._request = request
        self._token: str | None = None
        self._busy = False

        self._q = QLineEdit()
        self._q.setPlaceholderText("Search songs — Enter submits")
        self._q.setMaxLength(500)
        self._list = QListWidget()
        self._status = QLabel("")
        self._status.setWordWrap(True)

        # Recent queries/artists, reloaded from the router on every open and
        # after each successful search.
        self._history_box = QWidget(self)
        hb = QVBoxLayout(self._history_box)
        hb.setContentsMargins(0, 0, 0, 0)
        hb.setSpacing(2)
        head = QHBoxLayout()
        label = QLabel("Recent")
        label.setObjectName("dim")
        head.addWidget(label, 1)
        self._btn_clear_history = QPushButton("Clear recents")
        head.addWidget(self._btn_clear_history)
        hb.addLayout(head)
        self._history = QListWidget()
        self._history.setMaximumHeight(140)
        hb.addWidget(self._history)
        self._history_box.setVisible(False)

        self._btn_radio = QPushButton("Start mix")
        self._btn_radio.setToolTip("Start a radio station from the selected result")
        self._btn_radio.setEnabled(False)

        lay = QVBoxLayout(self)
        lay.addWidget(self._q)
        lay.addWidget(self._history_box)
        lay.addWidget(self._list, 1)
        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(self._btn_radio)
        lay.addLayout(actions)
        lay.addWidget(self._status)

        self._q.returnPressed.connect(self._submit)
        self._list.itemActivated.connect(self._play_item)
        self._list.currentItemChanged.connect(lambda *_: self._refresh_actions())
        self._history.itemClicked.connect(self._use_history_item)
        self._btn_clear_history.clicked.connect(
            lambda: self._request("search.clearHistory", {})
        )
        self._btn_radio.clicked.connect(self._start_radio)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._load_history()

    def _load_history(self) -> None:
        self._request("search.history", {})

    def _set_activity(self, activity: _SearchActivity) -> None:
        self._busy = activity is _SearchActivity.PENDING
        self._refresh_actions()

    def _refresh_actions(self) -> None:
        item = self._list.currentItem()
        radioable = (
            item is not None
            and self._token is not None
            and bool(item.data(_RADIO_ROLE))
        )
        self._btn_radio.setEnabled(radioable and not self._busy)

    def _submit(self) -> None:
        query = self._q.text().strip()
        if not query or self._busy:
            return
        self._set_activity(_SearchActivity.PENDING)
        self._list.clear()
        self._status.setText("Searching…")
        self._request("search.songs", {"query": query})

    def apply_response(self, method: str, ok: bool, payload: dict) -> None:
        # search.history/clearHistory are unbound reads; they do not touch
        # the search-action busy flag.
        if method == "search.songs":
            self._set_activity(_SearchActivity.IDLE)
            if not ok:
                self._status.setText(payload.get("message", "search failed"))
                return
            self._token = payload.get("searchToken")
            self._render(payload.get("results") or [], payload.get("complete", False))
            self._load_history()
        elif method in ("search.playResult", "search.startRadio"):
            self._set_activity(_SearchActivity.IDLE)
            if ok:
                self._status.setText(
                    "Playing" if method == "search.playResult" else "Mix started"
                )
            else:
                self._status.setText(payload.get("message", "action failed"))
        elif method == "search.history":
            if ok:
                queries = payload.get("queries")
                artists = payload.get("artists")
                self._render_history(
                    queries if isinstance(queries, list) else [],
                    artists if isinstance(artists, list) else [],
                )
        elif method == "search.clearHistory":
            if ok:
                self._render_history([], [])
            else:
                self._status.setText(payload.get("message", "could not clear history"))

    def _render_history(self, queries: list, artists: list) -> None:
        self._history.clear()
        for label, values in (
            ("Recent searches", queries),
            ("Recent artists", artists),
        ):
            entries = [
                v for v in values if isinstance(v, str) and v.strip()
            ][:_HISTORY_CAP]
            if not entries:
                continue
            header = QListWidgetItem(label)
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            self._history.addItem(header)
            for value in entries:
                item = QListWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, value)
                item.setToolTip("Search again")
                self._history.addItem(item)
        self._history_box.setVisible(self._history.count() > 0)

    def _use_history_item(self, item: QListWidgetItem) -> None:
        if self._busy:
            return

        text = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(text, str):
            return
        self._q.setText(text)
        self._submit()

    def _render(self, rows: list[dict], complete: bool) -> None:
        self._list.clear()
        if not rows:
            self._status.setText("No songs found")
            self._refresh_actions()
            return
        for row in rows:
            title = str(row.get("title", ""))
            artists = ", ".join(row.get("artists") or [])
            album = row.get("album")
            sub = artists + (f" · {album}" if album else "") + _fmt_dur(row.get("durationSeconds"))
            item = QListWidgetItem(f"{title}\n{sub}")
            supported = bool(row.get("supported"))
            item.setData(Qt.ItemDataRole.UserRole, row.get("resultId"))
            item.setData(_RADIO_ROLE, bool(row.get("radioSupported")))
            if not supported:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                item.setToolTip(f"{row.get('kind', 'other')} results are not supported yet")
            else:
                item.setToolTip("Play this song")
            self._list.addItem(item)
        self._status.setText("" if complete else "Showing first results — more may exist")
        self._refresh_actions()

    def _play_item(self, item: QListWidgetItem) -> None:
        rid = item.data(Qt.ItemDataRole.UserRole)
        if not self._token or not isinstance(rid, str) or self._busy:
            return
        self._set_activity(_SearchActivity.PENDING)
        self._request(
            "search.playResult",
            {"searchToken": self._token, "resultId": rid},
        )

    def _start_radio(self) -> None:
        item = self._list.currentItem()
        if self._busy or not self._token or item is None:
            return
        rid = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(rid, str) or not item.data(_RADIO_ROLE):
            return
        self._set_activity(_SearchActivity.PENDING)
        self._request(
            "search.startRadio",
            {"searchToken": self._token, "resultId": rid},
        )

    def mark_stale(self) -> None:
        self._token = None
        self._set_activity(_SearchActivity.IDLE)
        for i in range(self._list.count()):
            item = self._list.item(i)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
        self._status.setText("Playback target changed — results are stale; search again")
