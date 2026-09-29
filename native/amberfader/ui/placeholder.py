"""Original placeholder artwork (no borrowed assets): a tiny amber-on-dark
PNG generated at import time — used when a track has no artwork or the fetch
failed. Kept deterministic so tests can assert the bytes."""
from __future__ import annotations

import base64

# 16x16 PNG, dark rounded field with an amber bar glyph. Generated once,
# stored inline so the package has zero asset-file dependencies.
PLACEHOLDER_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAK0lEQVR42mPQVxb5TwlmGOYG"
    "fD3fBcdUMeDFYls4xmoAuoJRAwbCgBGaFwDuf8i+RJbkPAAAAABJRU5ErkJggg=="
)


def placeholder_png() -> bytes:
    return base64.b64decode(PLACEHOLDER_PNG_B64)
