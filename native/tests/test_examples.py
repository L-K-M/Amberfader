"""Shared protocol vectors — the same files the TypeScript suite validates.
Naming convention: valid-* must pass, invalid-* must fail."""
import json
from pathlib import Path

import pytest

from amberfader.protocol import validate_message

EXAMPLES = (
    Path(__file__).resolve().parents[2] / "protocol" / "examples"
)

VALID = sorted(EXAMPLES.glob("valid-*.json"))
INVALID = sorted(EXAMPLES.glob("invalid-*.json"))


def test_corpus_is_nontrivial():
    assert len(VALID) + len(INVALID) >= 20
    assert INVALID, "need negative vectors"


@pytest.mark.parametrize("path", VALID, ids=lambda p: p.name)
def test_valid_examples(path):
    msg = json.loads(path.read_text())
    problems = validate_message(msg)
    assert problems == [], f"{path.name}: {problems}"


@pytest.mark.parametrize("path", INVALID, ids=lambda p: p.name)
def test_invalid_examples(path):
    msg = json.loads(path.read_text())
    problems = validate_message(msg)
    assert problems, f"{path.name} should not validate"
