"""Separate search window: Enter submits, results list, Enter/double-click
plays a validated selection. No per-keystroke network activity."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)


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

        lay = QVBoxLayout(self)
        lay.addWidget(self._q)
        lay.addWidget(self._list, 1)
        lay.addWidget(self._status)

        self._q.returnPressed.connect(self._submit)
        self._list.itemActivated.connect(self._play_item)

    def _submit(self) -> None:
        query = self._q.text().strip()
        if not query or self._busy:
            return
        self._busy = True
        self._list.clear()
        self._status.setText("Searching…")
        self._request("search.songs", {"query": query})

    def apply_response(self, method: str, ok: bool, payload: dict) -> None:
        if method == "search.songs":
            self._busy = False
            if not ok:
                self._status.setText(payload.get("message", "search failed"))
                return
            self._token = payload.get("searchToken")
            self._render(payload.get("results") or [], payload.get("complete", False))
        elif method == "search.playResult":
            self._busy = False
            if not ok:
                self._status.setText(payload.get("message", "could not play result"))
            else:
                self._status.setText("Playing")

    def _render(self, rows: list[dict], complete: bool) -> None:
        self._list.clear()
        if not rows:
            self._status.setText("No songs found")
            return
        for row in rows:
            title = str(row.get("title", ""))
            artists = ", ".join(row.get("artists") or [])
            album = row.get("album")
            sub = artists + (f" · {album}" if album else "") + _fmt_dur(row.get("durationSeconds"))
            item = QListWidgetItem(f"{title}\n{sub}")
            supported = bool(row.get("supported"))
            item.setData(Qt.ItemDataRole.UserRole, row.get("resultId"))
            if not supported:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                item.setToolTip(f"{row.get('kind', 'other')} results are not supported yet")
            else:
                item.setToolTip("Play this song")
            self._list.addItem(item)
        self._status.setText("" if complete else "Showing first results — more may exist")

    def _play_item(self, item: QListWidgetItem) -> None:
        rid = item.data(Qt.ItemDataRole.UserRole)
        if not self._token or not isinstance(rid, str) or self._busy:
            return
        self._busy = True
        self._request(
            "search.playResult",
            {"searchToken": self._token, "resultId": rid},
        )

    def mark_stale(self) -> None:
        self._token = None
        self._status.setText("Playback target changed — results are stale; search again")
