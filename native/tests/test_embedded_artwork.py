"""Embedded artwork: allowlist, normalization limits, and the fetcher's
redirect, size, type and cache rules against a loopback HTTP server."""
import base64
import struct
import threading
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

pytest.importorskip(
    "PySide6.QtWidgets",
    reason="GUI extra not installed or Qt unusable",
    exc_type=ImportError,
)

from conftest import pump

from amberfader.embedded.artwork import (
    MAX_EDGE,
    MAX_INPUT_BYTES,
    MAX_OUTPUT_BYTES,
    ArtworkFetcher,
    allowed_artwork_url,
    normalize_artwork,
)


def png_bytes(qapp, width, height):
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QColor, QImage

    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor("#d08020"))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    return bytes(data.data())


def png_header_claiming(width, height):
    def chunk(kind, body):
        return (struct.pack(">I", len(body)) + kind + body
                + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IEND", b"")


@pytest.mark.parametrize(("url", "expected"), [
    ("https://yt3.googleusercontent.com/abc=w60-h60", True),
    ("https://lh3.googleusercontent.com/abc", True),
    ("https://i9.ytimg.com/vi/x/hq.jpg", True),
    ("http://yt3.googleusercontent.com/abc", False),
    ("https://yt3.googleusercontent.com:8443/abc", False),
    ("https://yt3.googleusercontent.com.example.net/abc", False),
    ("https://example.net/cover.jpg", False),
    ("not a url", False),
])
def test_artwork_allowlist(url, expected):
    assert allowed_artwork_url(url) is expected


def test_normalization_downscales_and_reencodes(qapp):
    result = normalize_artwork(png_bytes(qapp, 600, 300))

    assert result is not None
    assert (result.width, result.height) == (MAX_EDGE, MAX_EDGE // 2)
    assert result.jpeg[:2] == b"\xff\xd8"
    assert len(result.jpeg) <= MAX_OUTPUT_BYTES


@pytest.mark.parametrize("data", [
    b"",
    b"not an image",
    b"x" * (MAX_INPUT_BYTES + 1),
    png_header_claiming(5000, 10),
])
def test_normalization_rejects_bad_input(qapp, data):
    assert normalize_artwork(data) is None


class _Server:
    def __init__(self, image):
        self.hits: dict[str, int] = {}
        hits = self.hits

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                hits[self.path] = hits.get(self.path, 0) + 1
                if self.path == "/ok/cover":
                    self._send(200, "image/png", image)
                elif self.path == "/ok/text":
                    self._send(200, "text/html", b"<html></html>")
                elif self.path == "/ok/huge":
                    self._send(200, "image/png", b"\0" * (MAX_INPUT_BYTES + 1024))
                elif self.path == "/ok/hop":
                    self._redirect("/ok/cover")
                elif self.path == "/ok/escape":
                    self._redirect("/blocked/cover")
                else:
                    self._send(200, "image/png", image)

            def _send(self, status, mime, body):
                self.send_response(status)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _redirect(self, location):
                self.send_response(302)
                self.send_header("Location", location)
                self.send_header("Content-Length", "0")
                self.end_headers()

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture()
def server(qapp):
    srv = _Server(png_bytes(qapp, 400, 400))
    yield srv
    srv.close()


@pytest.fixture()
def fetcher(qapp, server):
    fetcher = ArtworkFetcher(allow=lambda url: url.startswith(f"{server.base}/ok/"))
    assets = []
    fetcher.assetReady.connect(assets.append)
    fetcher.assets = assets
    yield fetcher
    fetcher.deleteLater()


def test_fetches_normalizes_and_caches(qapp, server, fetcher):
    fetcher.request(f"{server.base}/ok/cover", "art-1", "occ-1")
    fetcher.request(f"{server.base}/ok/cover", "art-1", "occ-1")
    assert pump(qapp, lambda: fetcher.assets)

    asset = fetcher.assets[0]
    assert asset["artworkId"] == "art-1"
    assert asset["mime"] == "image/jpeg"
    assert (asset["width"], asset["height"]) == (MAX_EDGE, MAX_EDGE)
    assert len(base64.b64decode(asset["dataBase64"])) <= MAX_OUTPUT_BYTES
    assert server.hits == {"/ok/cover": 1}

    # A repeat is answered from the cache with the caller's occurrence.
    fetcher.request(f"{server.base}/ok/cover", "art-1", "occ-2")
    assert fetcher.assets[-1]["occurrenceId"] == "occ-2"
    assert server.hits == {"/ok/cover": 1}


def test_follows_allowed_redirects_only(qapp, server, fetcher):
    fetcher.request(f"{server.base}/ok/escape", "art-escape", None)
    fetcher.request(f"{server.base}/ok/hop", "art-hop", None)

    assert pump(qapp, lambda: fetcher.assets)
    pump(qapp, lambda: False, timeout_s=0.3)
    assert [a["artworkId"] for a in fetcher.assets] == ["art-hop"]
    assert "/blocked/cover" not in server.hits


@pytest.mark.parametrize("path", ["/ok/text", "/ok/huge", "/blocked/cover"])
def test_rejects_wrong_type_oversize_and_disallowed_urls(qapp, server, fetcher, path):
    fetcher.request(f"{server.base}{path}", "art-x", None)
    pump(qapp, lambda: False, timeout_s=0.5)

    assert fetcher.assets == []
    # A failed cover can be proposed again later.
    if path != "/blocked/cover":
        fetcher.request(f"{server.base}{path}", "art-x", None)
        assert pump(qapp, lambda: server.hits.get(path) == 2)
