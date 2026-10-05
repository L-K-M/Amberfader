"""Amberfader's embedded browser.

Amberfader loads music.youtube.com in its own QtWebEngine profile. The page
runs the site adapter from web/src; this package hosts that page and routes
the public protocol between it and the player client in the same process.

Modules that need QtWebEngine (`page`, `app`) import it lazily, so the
Qt-free parts (`router`, `history`, `navigation`) stay testable without the
`embedded` extra.
"""
