"""Amberfader's launcher: the `amberfader` command and python -m amberfader.

From a checkout: npm start (builds the page bundle first).
"""
from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import signal
import sys
import tempfile
from pathlib import Path

from .. import APP_NAME
from ..paths import migrate_legacy_files
from ..settings import default_settings_path
from ..transport.paths import runtime_socket_dir
from .history import default_history_path

EMBEDDED_SOCKET_NAME = "embedded.sock"
# Python runs signal handlers only between bytecodes; a short timer gives it
# that chance while Qt's event loop blocks in C++.
SIGNAL_POLL_MS = 250


def default_socket_path() -> str:
    """$XDG_RUNTIME_DIR/amberfader/embedded.sock. macOS has no
    XDG_RUNTIME_DIR; its per-user temporary directory ($TMPDIR) takes that
    role there. Linux still refuses to start without XDG_RUNTIME_DIR rather
    than placing the socket somewhere shared."""
    if sys.platform != "darwin" or os.environ.get("XDG_RUNTIME_DIR"):
        return os.path.join(runtime_socket_dir(), EMBEDDED_SOCKET_NAME)

    directory = Path(tempfile.gettempdir()) / APP_NAME
    with contextlib.suppress(FileExistsError):
        directory.mkdir(mode=0o700)
    # gettempdir() falls back to the shared /tmp when $TMPDIR is unset, so
    # only use a real directory that this user owns. Check and tighten it
    # through one descriptor opened without following symlinks, so the path
    # cannot be swapped between the check and the chmod.
    refused = RuntimeError(
        f"{directory} is not a directory owned by you; pass --socket with a private path"
    )
    try:
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        raise refused from exc
    try:
        if os.fstat(fd).st_uid != os.getuid():
            raise refused
        os.fchmod(fd, 0o700)
    finally:
        os.close(fd)
    return str(directory / EMBEDDED_SOCKET_NAME)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="amberfader",
        description="Amberfader: a compact classic-style player for YouTube Music.",
    )
    parser.add_argument("--scale", type=float, default=1.0, choices=(1.0, 1.5, 2.0))
    parser.add_argument(
        "--socket",
        help="single-instance socket (default: $XDG_RUNTIME_DIR/amberfader/embedded.sock, "
        "or $TMPDIR/amberfader/embedded.sock on macOS)",
    )
    parser.add_argument(
        "--background", action="store_true",
        help="start with the YouTube Music window hidden",
    )
    parser.add_argument(
        "--test-page", action="store_true",
        help="drive a scripted local page instead of YouTube Music (no network, no sign-in)",
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help="check that this installation works, on the scripted test page, then exit",
    )
    args = parser.parse_args(argv)
    if args.self_test:
        # Never touches a running instance, the profile or saved settings.
        args.test_page = args.background = True

    # QtWebEngineWidgets must be imported before the QApplication exists.
    try:
        from PySide6 import QtWebEngineWidgets  # noqa: F401
    except ImportError:
        print(
            "amberfader: QtWebEngine is not installed. Run: uv sync",
            file=sys.stderr,
        )
        return 2

    # The scripted test page keeps its recent searches (and the self-test its
    # socket) in a scratch folder, never in your own files.
    scratch = tempfile.mkdtemp(prefix="amberfader-test-page-") if args.test_page else None
    try:
        return _run(args, scratch)
    finally:
        if scratch:
            shutil.rmtree(scratch, ignore_errors=True)


def _run(args: argparse.Namespace, scratch: str | None) -> int:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from ..face_library import FaceError
    from ..transport.local import try_activate_existing
    from .page import BundleMissingError, PageMode, load_ad_filter, load_bundle
    from .runtime import EmbeddedRuntime, RuntimeOptions

    try:
        if args.socket:
            socket_path = args.socket
        elif args.self_test and scratch:
            socket_path = os.path.join(scratch, "self-test.sock")
        else:
            socket_path = default_socket_path()
    except (RuntimeError, OSError) as exc:
        print(f"amberfader: {exc}", file=sys.stderr)
        return 2

    app = QApplication(sys.argv[:1])
    app.setApplicationName("amberfader")
    app.setOrganizationDomain("ch.lkmc")

    # Single instance: two processes must never share one browser profile.
    # Checked before anything else, so a second launch only raises the first.
    if try_activate_existing(socket_path):
        return 0

    # Only now is this the one running instance, so files can move safely.
    if not args.self_test:
        for problem in migrate_legacy_files():
            print(f"amberfader: {problem}", file=sys.stderr)

    try:
        bundle = load_bundle()
        ad_filter = load_ad_filter()
    except BundleMissingError as exc:
        print(f"amberfader: {exc}", file=sys.stderr)
        return 2

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

    mode = PageMode.TEST_PAGE if args.test_page else PageMode.YOUTUBE_MUSIC
    options = RuntimeOptions(
        mode=mode,
        socket_path=socket_path,
        history_path=Path(scratch) / "history.json" if scratch else default_history_path(),
        scale=args.scale,
        # The scripted test page never changes your saved settings.
        settings_path=None if mode is PageMode.TEST_PAGE else default_settings_path(),
    )
    runtime = EmbeddedRuntime(options, bundle, ad_filter=ad_filter)
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

        if args.self_test:
            from .selftest import SelfTest

            return SelfTest(runtime).run()

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
