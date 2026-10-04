"""Shared wire protocol: framing + schema validation.

Two hops use this module:
  * Firefox <-> helper: native messaging, 4-byte length prefix in native byte
    order (little-endian on our platforms) + UTF-8 JSON. Browser cap is 1 MiB
    per helper->browser message; our own cap is stricter.
  * helper <-> GUI: the same framed JSON over a per-user Unix socket.

Measure bytes, never characters: struct.pack("=I", len(encoded_bytes)).
"""
from __future__ import annotations

import functools
import json
import struct
from collections.abc import Iterator
from importlib import resources
from typing import Any

TRANSPORT_MAX_BYTES = 256 * 1024
NATIVE_MAX_BYTES = 1024 * 1024  # hard limit of the native-messaging channel


class FrameError(Exception):
    """Base class for wire-format failures (all caller-visible)."""


class OversizedMessage(FrameError):
    pass


class TruncatedFrame(FrameError):
    pass


class BadUTF8(FrameError):
    pass


class BadJSON(FrameError):
    pass


def encode_frame(obj: dict[str, Any]) -> bytes:
    """Serialize one message: 4-byte LE length + UTF-8 JSON."""
    body = json.dumps(
        obj,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if len(body) > NATIVE_MAX_BYTES:
        raise OversizedMessage(f"message is {len(body)} bytes (max {NATIVE_MAX_BYTES})")
    return struct.pack("=I", len(body)) + body


class FrameFeed:
    """Incremental frame decoder. feed() arbitrary byte chunks; complete
    messages come out of __iter__ as dicts. Raises FrameError subclasses on
    malformed input — callers decide whether that kills the connection.
    """

    def __init__(self, max_bytes: int = TRANSPORT_MAX_BYTES) -> None:
        self.max_bytes = max_bytes
        self._buf = bytearray()

    def feed(self, data: bytes) -> Iterator[dict[str, Any]]:
        self._buf += data
        while True:
            if len(self._buf) < 4:
                return
            (length,) = struct.unpack("=I", self._buf[:4])
            if length > self.max_bytes:
                raise OversizedMessage(f"declared frame {length} > {self.max_bytes}")
            if len(self._buf) < 4 + length:
                return
            body = bytes(self._buf[4 : 4 + length])
            del self._buf[: 4 + length]
            try:
                text = body.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise BadUTF8(str(exc)) from exc
            try:
                msg = json.loads(text)
            except json.JSONDecodeError as exc:
                raise BadJSON(str(exc)) from exc
            if not isinstance(msg, dict):
                raise BadJSON("frame is not a JSON object")
            yield msg

    def pending(self) -> int:
        return len(self._buf)


def load_schema() -> dict[str, Any]:
    """The bundled copy of protocol/schemas/envelope.schema.json (kept in
    sync by scripts/check.sh — the repo copy is canonical)."""
    ref = resources.files("amberfader") / "schema" / "envelope.schema.json"
    return json.loads(ref.read_text("utf-8"))


def validate_message(msg: dict[str, Any]) -> list[str]:
    """Validate against the envelope schema; returns a list of problems
    (empty = valid). Uses jsonschema when available; otherwise a minimal
    structural check so the helper still gates obvious garbage."""
    try:
        import jsonschema
    except ImportError:  # pragma: no cover - dependency is declared
        return _structural_check(msg)
    schema = load_schema()
    validator = jsonschema.validators.validator_for(schema)(schema)
    return [f"{e.json_path or '/'}: {e.message}" for e in validator.iter_errors(msg)]


@functools.cache
def _definition_validator(name: str) -> Any:
    import jsonschema

    schema = load_schema()
    if name not in schema["$defs"]:
        raise KeyError(f"unknown schema definition: {name}")
    reference = {"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": f"#/$defs/{name}"}
    return jsonschema.validators.validator_for(schema)(reference)


def validate_definition(name: str, value: Any) -> list[str]:
    """Validate one value against a named `$defs` entry of the envelope
    schema, e.g. a search.songs result whose shape the envelope leaves open."""
    validator = _definition_validator(name)
    return [f"{e.json_path or '/'}: {e.message}" for e in validator.iter_errors(value)]


def _structural_check(msg: dict[str, Any]) -> list[str]:
    problems = []
    if msg.get("protocolVersion") != 1:
        problems.append("protocolVersion must be 1")
    if msg.get("kind") not in ("hello", "request", "response", "event"):
        problems.append("unknown kind")
    return problems
