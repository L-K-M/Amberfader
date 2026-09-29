"""Framing edge cases: exact-length reads, multiple frames per read,
truncated frames, multibyte UTF-8, oversized and malformed payloads."""
import struct

import pytest

from amberfader.protocol import (
    TRANSPORT_MAX_BYTES,
    BadJSON,
    BadUTF8,
    FrameFeed,
    OversizedMessage,
    encode_frame,
)


def test_roundtrip():
    msg = {"kind": "request", "method": "player.play", "params": {}}
    feed = FrameFeed()
    assert list(feed.feed(encode_frame(msg))) == [msg]


def test_multiple_frames_one_read():
    a = {"n": 1}
    b = {"n": 2}
    feed = FrameFeed()
    out = list(feed.feed(encode_frame(a) + encode_frame(b)))
    assert out == [a, b]


def test_split_across_reads():
    frame = encode_frame({"x": "y" * 100})
    feed = FrameFeed()
    out = []
    for i in range(0, len(frame), 7):
        out.extend(feed.feed(frame[i : i + 7]))
    assert out == [{"x": "y" * 100}]


def test_truncated_waits_for_rest():
    frame = encode_frame({"a": 1})
    feed = FrameFeed()
    assert list(feed.feed(frame[:-2])) == []
    assert feed.pending() == len(frame) - 2


def test_multibyte_utf8_length_is_bytes_not_chars():
    # € is 3 bytes in UTF-8 — the length prefix must count bytes.
    msg = {"s": "€" * 50}
    body = encode_frame(msg)[4:]
    assert len(body) > 50 + 20  # proves bytes were measured
    feed = FrameFeed()
    assert next(iter(feed.feed(encode_frame(msg))))["s"] == "€" * 50


def test_oversized_declared_length():
    feed = FrameFeed()
    with pytest.raises(OversizedMessage):
        list(feed.feed(struct.pack("=I", TRANSPORT_MAX_BYTES + 1) + b"{}"))


def test_bad_utf8():
    frame = struct.pack("=I", 2) + b"\xff\xfe"
    with pytest.raises(BadUTF8):
        list(FrameFeed().feed(frame))


def test_bad_json():
    body = b"{not json"
    frame = struct.pack("=I", len(body)) + body
    with pytest.raises(BadJSON):
        list(FrameFeed().feed(frame))


def test_non_object_json_rejected():
    body = b"[1,2,3]"
    frame = struct.pack("=I", len(body)) + body
    with pytest.raises(BadJSON):
        list(FrameFeed().feed(frame))


def test_encode_rejects_nan_and_inf():
    import math

    # allow_nan=False: json raises ValueError; nothing is ever written.
    with pytest.raises(ValueError):
        encode_frame({"v": math.nan})
    with pytest.raises(ValueError):
        encode_frame({"v": math.inf})
