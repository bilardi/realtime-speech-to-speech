"""Test the timing log module."""

import json
from pathlib import Path
from uuid import UUID

from app.timing import UtteranceTiming

EXPECTED_LINES = 3


def test_new_id_returns_unique_uuids(tmp_path: Path) -> None:
    """`new_id` returns distinct UUID strings."""
    timing = UtteranceTiming(log_path=tmp_path / "timings.jsonl")
    a = timing.new_id()
    b = timing.new_id()
    assert a != b
    UUID(a)
    UUID(b)


def test_log_appends_jsonl(tmp_path: Path) -> None:
    """`log` appends a JSON line with correlation_id, event, monotonic time."""
    log_path = tmp_path / "timings.jsonl"
    timing = UtteranceTiming(log_path=log_path)

    cid_a = timing.new_id()
    cid_b = timing.new_id()
    timing.log(cid_a, "transcribe_finalized")
    timing.log(cid_a, "translate_done")
    timing.log(cid_b, "transcribe_finalized")

    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == EXPECTED_LINES

    parsed = [json.loads(line) for line in lines]
    assert parsed[0]["correlation_id"] == cid_a
    assert parsed[0]["event"] == "transcribe_finalized"
    assert parsed[1]["correlation_id"] == cid_a
    assert parsed[1]["event"] == "translate_done"
    assert parsed[2]["correlation_id"] == cid_b
    for p in parsed:
        assert isinstance(p["t"], float)
