"""Aggregate utterance timings into a per-utterance latency breakdown.

The timing log produced by `app.timing.UtteranceTiming` records four events per
utterance: `transcribe_finalized`, `translate_done`, `polly_first_chunk`,
`listener_first_chunk`. ASR latency is not measured server-side; it is derived
implicitly from end-to-end audio cross-correlation (`bench/measure_e2e.py`,
Task 21) minus the sum of the stage deltas computed here.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

_MS_PER_SECOND = 1000
_EXPECTED_ARGV_LEN = 2


def analyze(log_path: Path) -> list[dict[str, object]]:
    """Read a JSONL timing log and produce one row per correlation id.

    Args:
        log_path: path to a JSONL file produced by `app.timing.UtteranceTiming`.

    Returns:
        List of dicts with keys: `correlation_id`, `translate_ms`,
        `polly_first_byte_ms`, `forward_ms`. Stages with missing source events
        are omitted from the row.
    """
    by_cid: dict[str, dict[str, float]] = defaultdict(dict)
    for line in log_path.read_text().splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        by_cid[entry["correlation_id"]][entry["event"]] = float(entry["t"])

    rows: list[dict[str, object]] = []
    for cid, events in by_cid.items():
        if "transcribe_finalized" not in events:
            continue
        row: dict[str, object] = {"correlation_id": cid}
        if "translate_done" in events:
            row["translate_ms"] = (
                events["translate_done"] - events["transcribe_finalized"]
            ) * _MS_PER_SECOND
        if "polly_first_chunk" in events and "translate_done" in events:
            row["polly_first_byte_ms"] = (
                events["polly_first_chunk"] - events["translate_done"]
            ) * _MS_PER_SECOND
        if "listener_first_chunk" in events and "polly_first_chunk" in events:
            row["forward_ms"] = (
                events["listener_first_chunk"] - events["polly_first_chunk"]
            ) * _MS_PER_SECOND
        rows.append(row)
    return rows


def main() -> None:
    """Print per-utterance breakdown as JSON lines (CLI entrypoint)."""
    if len(sys.argv) != _EXPECTED_ARGV_LEN:
        print("usage: analyze_timings.py <path-to-timings.jsonl>", file=sys.stderr)  # noqa: T201
        sys.exit(1)
    rows = analyze(Path(sys.argv[1]))
    for row in rows:
        print(json.dumps(row))  # noqa: T201


if __name__ == "__main__":
    main()
