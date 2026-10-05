"""Request rules for the built-in ad blocker.

A small subset of EasyList and EasyPrivacy (fetched 2026-10-05), limited to
what YouTube Music loads: Google's ad hosts and YouTube's ad and ad-tracking
endpoints. Playback, history and recommendation requests are never matched.
The rule each entry mirrors is noted next to it.

Qt-free on purpose, so the rules are unit-tested without QtWebEngine.
"""
from __future__ import annotations

from urllib.parse import urlsplit

# Blocked together with their subdomains.
AD_HOSTS = (
    "ad.doubleclick.net",            # EasyList ||ad.doubleclick.net^
    "fls.doubleclick.net",           # EasyList ||fls.doubleclick.net^
    "g.doubleclick.net",             # EasyList ||g.doubleclick.net^ (googleads.g., stats.g.)
    "static.doubleclick.net",        # EasyList ||static.doubleclick.net^
    "td.doubleclick.net",            # EasyPrivacy ||td.doubleclick.net^
    "pagead2.googlesyndication.com", # EasyList ||pagead2.googlesyndication.com^
    "googleadservices.com",          # EasyPrivacy ||googleadservices.com^$third-party
    "googletagservices.com",         # EasyList ||googletagservices.com^
    "imasdk.googleapis.com",         # EasyList ||imasdk.googleapis.com^
)

# Paths on youtube.com and its subdomains.
YOUTUBE_AD_PATH_PREFIXES = (
    "/pagead/",                      # EasyList ||youtube.com/pagead/
    "/youtubei/v1/player/ad_break",  # EasyList ||youtube.com/youtubei/v1/player/ad_break
)
YOUTUBE_AD_PATHS = (
    "/api/stats/ads",                # EasyPrivacy ||youtube.com/api/stats/ads?
    "/pcs/activeview",               # EasyPrivacy ||youtube.com/pcs/activeview?
)


def _within(host: str, domain: str) -> bool:
    return host == domain or host.endswith(f".{domain}")


def is_ad_request(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https"):
        return False
    host = (parts.hostname or "").lower()
    if any(_within(host, domain) for domain in AD_HOSTS):
        return True
    if not _within(host, "youtube.com"):
        return False
    path = parts.path
    if path.startswith(YOUTUBE_AD_PATH_PREFIXES) or path in YOUTUBE_AD_PATHS:
        return True
    # EasyList ||youtube.com/get_video_info?*adunit$~third-party
    return path == "/get_video_info" and "adunit" in parts.query
