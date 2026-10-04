"""Embedded QtWebEngine prototype.

Amberfader loads music.youtube.com in its own QtWebEngine profile instead of
attaching to Firefox. The page runs the extension's site adapter unchanged;
this package replaces the Firefox router, controller page, native-messaging
helper and socket hop with an in-process host that speaks the same public
protocol to the existing desktop client.

Modules that need QtWebEngine (`page`, `app`) import it lazily, so the
Qt-free parts (`router`, `history`, `navigation`) stay testable without the
`embedded` extra.
"""
