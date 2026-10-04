"""In-process stand-in for the helper socket."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal


class EmbeddedUpstream(QObject):
    """AmberfaderApp sends protocol requests here and receives protocol
    messages back, exactly as over the helper socket (same interface as
    FramedSocket). Delivery to the client is queued, like socket reads, so a
    response never re-enters the client while it is still issuing a request.
    """

    messageReceived = Signal(dict)
    # Part of the FramedSocket interface. Never emitted: the page lifecycle
    # is reported through binding and connection events instead.
    disconnected = Signal()
    requested = Signal(dict)

    def send(self, msg: dict[str, Any]) -> bool:
        self.requested.emit(msg)
        return True

    def deliver(self, msg: dict[str, Any]) -> None:
        QTimer.singleShot(0, self, lambda: self.messageReceived.emit(msg))
