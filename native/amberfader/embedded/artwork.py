"""Cover artwork for the embedded host.

Same rules as the extension's ArtworkService (spec §6): HTTPS only, a narrow
host allowlist, no cookies or credentials, every redirect re-validated, 2 MiB
input cap, at most 256 px and 64 KiB output, 20 MiB cache, at most three
concurrent downloads. The page proposes a URL; the client only ever receives
the normalized asset.

The fetch runs on a plain QNetworkAccessManager, not the page's QtWebEngine
profile, so the signed-in session's cookies never travel with it.
"""
from __future__ import annotations

import base64
import re
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, Qt, QUrl, Signal
from PySide6.QtGui import QImageReader
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_SOURCE_EDGE = 4096
MAX_EDGE = 256
MAX_OUTPUT_BYTES = 64 * 1024
CACHE_BUDGET_BYTES = 20 * 1024 * 1024
MAX_CONCURRENT = 3
MAX_REDIRECTS = 3
FETCH_TIMEOUT_MS = 10_000
JPEG_QUALITIES = (85, 70, 55)
ACCEPTED_MIME = frozenset(("image/jpeg", "image/png", "image/webp"))
REDIRECT_STATUSES = frozenset((301, 302, 303, 307, 308))

# The live 2026-10-02 probe found the player cover on this origin. The other
# hosts mirror the extension's legacy candidates and remain UNVERIFIED.
OBSERVED_ARTWORK_ORIGIN = "https://yt3.googleusercontent.com"
ARTWORK_HOST_ALLOWLIST = (
    re.compile(r"^lh3\.googleusercontent\.com$"),
    re.compile(r"^i\d*\.ytimg\.com$"),
    re.compile(r"^yt\d\.ggpht\.com$"),
    re.compile(r"^music\.youtube\.com$"),
)


def allowed_artwork_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    host = parts.hostname
    if parts.scheme != "https" or port not in (None, 443) or not host:
        return False
    if f"https://{host}" == OBSERVED_ARTWORK_ORIGIN:
        return True
    return any(pattern.match(host) for pattern in ARTWORK_HOST_ALLOWLIST)


@dataclass(frozen=True)
class NormalizedArtwork:
    jpeg: bytes
    width: int
    height: int


def normalize_artwork(data: bytes) -> NormalizedArtwork | None:
    """Decode, downscale to fit 256 px, and re-encode as JPEG within 64 KiB.
    Returns None for undecodable, oversized or incompressible images."""
    if not data or len(data) > MAX_INPUT_BYTES:
        return None
    source = QBuffer()
    source.setData(QByteArray(data))
    source.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(source)
    # Browsers honor EXIF orientation, so the page shows covers upright.
    reader.setAutoTransform(True)
    size = reader.size()
    # Check the declared size before decoding so a tiny file cannot claim a
    # huge canvas.
    if not (0 < size.width() <= MAX_SOURCE_EDGE and 0 < size.height() <= MAX_SOURCE_EDGE):
        return None
    image = reader.read()
    if image.isNull():
        return None

    if max(image.width(), image.height()) > MAX_EDGE:
        image = image.scaled(
            MAX_EDGE, MAX_EDGE,
            Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
        )
    for quality in JPEG_QUALITIES:
        encoded = QByteArray()
        target = QBuffer(encoded)
        target.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(target, "JPEG", quality):
            return None
        if encoded.size() <= MAX_OUTPUT_BYTES:
            return NormalizedArtwork(bytes(encoded.data()), image.width(), image.height())
    return None


@dataclass
class _Job:
    url: str
    artwork_id: str
    redirects: int = 0
    rejected: bool = False


class ArtworkFetcher(QObject):
    """Downloads and normalizes proposed covers. Emits `assetReady` with
    asset-event data (occurrenceId null: the router stamps the occurrence
    that is current when the bytes arrive)."""

    assetReady = Signal(dict)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        allow: Callable[[str], bool] = allowed_artwork_url,
    ) -> None:
        super().__init__(parent)
        # Tests pass a loopback allowance; production keeps the allowlist.
        self._allow = allow
        self._manager = QNetworkAccessManager(self)
        self._cache: OrderedDict[str, dict] = OrderedDict()
        self._cache_bytes = 0
        self._queue: deque[_Job] = deque()
        self._active: dict[QNetworkReply, _Job] = {}
        self._wanted: set[str] = set()

    def request(self, url: str, artwork_id: str, occurrence_id: str | None) -> None:
        if not self._allow(url):
            return
        cached = self._cache.get(artwork_id)
        if cached is not None:
            self._cache.move_to_end(artwork_id)
            self.assetReady.emit({**cached, "occurrenceId": occurrence_id})
            return
        if artwork_id in self._wanted:
            return  # one download per cover, however often it is proposed
        self._wanted.add(artwork_id)
        self._queue.append(_Job(url, artwork_id))
        self._pump()

    def _pump(self) -> None:
        while self._queue and len(self._active) < MAX_CONCURRENT:
            self._start(self._queue.popleft())

    def _start(self, job: _Job) -> None:
        request = QNetworkRequest(QUrl(job.url))
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.ManualRedirectPolicy,
        )
        manual = QNetworkRequest.LoadControl.Manual
        request.setAttribute(QNetworkRequest.Attribute.CookieLoadControlAttribute, manual)
        request.setAttribute(QNetworkRequest.Attribute.CookieSaveControlAttribute, manual)
        request.setAttribute(QNetworkRequest.Attribute.AuthenticationReuseAttribute, manual)
        request.setTransferTimeout(FETCH_TIMEOUT_MS)

        reply = self._manager.get(request)
        self._active[reply] = job
        reply.downloadProgress.connect(
            lambda received, total, r=reply: self._limit(r, received, total),
        )
        reply.finished.connect(lambda r=reply: self._finished(r))

    def _limit(self, reply: QNetworkReply, received: int, total: int) -> None:
        if received > MAX_INPUT_BYTES or total > MAX_INPUT_BYTES:
            job = self._active.get(reply)
            if job is not None:
                job.rejected = True
            reply.abort()

    def _finished(self, reply: QNetworkReply) -> None:
        job = self._active.pop(reply, None)
        reply.deleteLater()
        if job is None:
            return
        follow: _Job | None = None
        try:
            follow = self._handle(reply, job)
        finally:
            if follow is None:
                self._wanted.discard(job.artwork_id)
        if follow is not None:
            self._queue.appendleft(follow)
        self._pump()

    def _handle(self, reply: QNetworkReply, job: _Job) -> _Job | None:
        """Returns the redirect job to run next, or None when finished."""
        if job.rejected or reply.error() != QNetworkReply.NetworkError.NoError:
            return None
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)

        if status in REDIRECT_STATUSES:
            target = reply.attribute(QNetworkRequest.Attribute.RedirectionTargetAttribute)
            if not isinstance(target, QUrl) or job.redirects >= MAX_REDIRECTS:
                return None
            url = reply.url().resolved(target).toString()
            if not self._allow(url):
                return None
            return _Job(url, job.artwork_id, job.redirects + 1)

        if status != 200:
            return None
        content_type = reply.header(QNetworkRequest.KnownHeaders.ContentTypeHeader)
        mime = str(content_type or "").split(";", 1)[0].strip().lower()
        if mime not in ACCEPTED_MIME:
            return None
        data = bytes(reply.readAll().data())
        normalized = normalize_artwork(data)
        if normalized is None:
            return None

        asset = {
            "artworkId": job.artwork_id,
            "occurrenceId": None,
            "mime": "image/jpeg",
            "width": normalized.width,
            "height": normalized.height,
            "dataBase64": base64.b64encode(normalized.jpeg).decode("ascii"),
        }
        self._store(job.artwork_id, asset)
        self.assetReady.emit(asset)
        return None

    def _store(self, artwork_id: str, asset: dict) -> None:
        cost = len(asset["dataBase64"])
        while self._cache and self._cache_bytes + cost > CACHE_BUDGET_BYTES:
            _, evicted = self._cache.popitem(last=False)
            self._cache_bytes -= len(evicted["dataBase64"])
        self._cache[artwork_id] = asset
        self._cache_bytes += cost
