"""Run the embedded prototype: python -m amberfader.embedded

From a checkout: npm run embedded:run (builds the page bundle first).
"""
from __future__ import annotations

import argparse
import os
import signal
import sys

from .history import default_history_path

EMBEDDED_SOCKET_NAME = "embedded.sock"
# Python runs signal handlers only between bytecodes; a short timer gives it
# that chance while Qt's event loop blocks in C++.
SIGNAL_POLL_MS = 250


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m amberfader.embedded",
        description="Amberfader with YouTube Music in its own QtWebEngine window (prototype).",
    )
    parser.add_argument("--scale", type=float, default=1.0, choices=(1.0, 1.5, 2.0))
    parser.add_argument(
        "--socket",
        help="single-instance socket (default: $XDG_RUNTIME_DIR/amberfader/embedded.sock)",
    )
    parser.add_argument(
        "--background", action="store_true",
        help="start with the YouTube Music window hidden",
    )
    parser.add_argument(
        "--test-page", action="store_true",
        help="drive a scripted local page instead of YouTube Music (no network, no sign-in)",
    )
    args = parser.parse_args(argv)

    # QtWebEngineWidgets must be imported before the QApplication exists.
    try:
        from PySide6 import QtWebEngineWidgets  # noqa: F401
    except ImportError:
        print(
            "amberfader: QtWebEngine is not installed. Run: uv sync --extra gui --extra embedded",
            file=sys.stderr,
        )
        return 2
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from ..face_library import FaceError
    from ..transport.local import try_activate_existing
    from ..transport.paths import runtime_socket_dir
    from .page import BundleMissingError, PageMode, load_bundle
    from .runtime import EmbeddedRuntime, RuntimeOptions

    try:
        bundle = load_bundle()
        socket_path = args.socket or os.path.join(runtime_socket_dir(), EMBEDDED_SOCKET_NAME)
    except (BundleMissingError, RuntimeError) as exc:
        print(f"amberfader: {exc}", file=sys.stderr)
        return 2

    app = QApplication(sys.argv[:1])
    app.setApplicationName("amberfader")
    app.setOrganizationDomain("ch.lkmc")

    # Single instance: two processes must never share one browser profile.
    if try_activate_existing(socket_path):
        return 0

    # Ctrl+C or SIGTERM quits through Qt, so Chromium can flush the sign-in
    # cookies instead of being killed mid-write. Installed before startup;
    # quit() is a no-op until exec() runs, so remember an early request.
    quit_requested = False

    def request_quit(*_args: object) -> None:
        nonlocal quit_requested
        quit_requested = True
        app.quit()

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, request_quit)

    options = RuntimeOptions(
        mode=PageMode.TEST_PAGE if args.test_page else PageMode.YOUTUBE_MUSIC,
        socket_path=socket_path,
        history_path=default_history_path(),
        scale=args.scale,
    )
    runtime = EmbeddedRuntime(options, bundle)
    try:
        try:
            started = runtime.start()
        except FaceError as exc:
            print(f"amberfader: {exc}", file=sys.stderr)
            return 2
        if not started:
            print(f"amberfader: cannot listen on {socket_path}", file=sys.stderr)
            return 2
        if quit_requested:
            return 0

        assert runtime.amber.window is not None
        # Playback lives in this process: closing the player quits and stops it.
        runtime.amber.window.closed.connect(app.quit)
        if not args.background:
            runtime.host.set_visible(True)

        poll = QTimer()
        poll.timeout.connect(lambda: None)
        poll.start(SIGNAL_POLL_MS)
        return app.exec()
    finally:
        # QtWebEngine objects must go page first, then profile, and all of
        # them before the QApplication.
        runtime.shutdown()
        del runtime


if __name__ == "__main__":
    raise SystemExit(main())
