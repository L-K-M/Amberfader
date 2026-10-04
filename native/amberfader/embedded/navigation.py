"""Which top-level pages the embedded view may load itself.

The embedded window is a YouTube Music player, not a general browser.
Google sign-in crosses accounts.google.com, accounts.youtube.com, consent
pages and regional cookie hops (for example accounts.google.ch), so those
stay inside the view. Every other link opens in the system browser.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

MUSIC_ORIGIN = "https://music.youtube.com"
_GOOGLE_COM_HOST = re.compile(r"^(?:[a-z0-9-]+\.)*google\.com$")
# Regional domains only for the accounts host that sign-in's cookie hops use
# (accounts.google.ch, accounts.google.co.uk, accounts.google.com.au). Google
# is not known to hold google.<suffix> under every registry, so other regional
# hosts open in the system browser. Narrow further once the live gate records
# which hosts sign-in actually visits.
_GOOGLE_REGIONAL_ACCOUNTS_HOST = re.compile(
    r"^accounts\.google\.(?:[a-z]{2}|co\.[a-z]{2}|com\.[a-z]{2})$"
)


def _https_host(url: str) -> str | None:
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme != "https" or port not in (None, 443):
        return None
    return parts.hostname


def origin_of(url: str) -> str | None:
    host = _https_host(url)
    return f"https://{host}" if host else None


def navigation_allowed(url: str, home_origin: str = MUSIC_ORIGIN) -> bool:
    host = _https_host(url)
    if host is None:
        return False
    if f"https://{host}" == home_origin:
        return True
    if host == "youtube.com" or host.endswith(".youtube.com"):
        return True
    return bool(_GOOGLE_COM_HOST.match(host) or _GOOGLE_REGIONAL_ACCOUNTS_HOST.match(host))


def opens_externally(url: str) -> bool:
    """Links the system browser may receive. Never hand it file:, data:,
    javascript: or custom-scheme URLs from page content."""
    try:
        scheme = urlsplit(url).scheme
    except ValueError:
        return False
    return scheme in ("http", "https")
