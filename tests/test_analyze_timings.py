"""Test analyze_timings."""

import json
from pathlib import Path

from benchmarks.analyze_timings import analyze

EXPECTED_ROWS = 1
EXPECTED_TRANSLATE_MS = 200
EXPECTED_POLLY_FIRST_BYTE_MS = 300
EXPECTED_FORWARD_MS = 50
TOLERANCE_MS = 1


def test_analyze_aggregates_per_correlation_id(tmp_path: Path) -> None:
    """`analyze` produces a breakdown row per correlation id."""
    log = tmp_path / "timings.jsonl"
    cid = "abc"
    entries = [
        {"correlation_id": cid, "event": "transcribe_finalized", "t": 0.0},
        {"correlation_id": cid, "event": "translate_done", "t": 0.2},
        {"correlation_id": cid, "event": "polly_first_chunk", "t": 0.5},
        {"correlation_id": cid, "event": "listener_first_chunk", "t": 0.55},
    ]
    log.write_text("\n".join(json.dumps(e) for e in entries) + "\n")

    rows = analyze(log)

    assert len(rows) == EXPECTED_ROWS
    row = rows[0]
    assert row["correlation_id"] == cid
    assert abs(row["translate_ms"] - EXPECTED_TRANSLATE_MS) < TOLERANCE_MS
    assert abs(row["polly_first_byte_ms"] - EXPECTED_POLLY_FIRST_BYTE_MS) < TOLERANCE_MS
    assert abs(row["forward_ms"] - EXPECTED_FORWARD_MS) < TOLERANCE_MS
