"""Per-utterance timing log for latency measurement.

Stateless API: callers manage the correlation_id lifecycle (one per utterance) and
pass it explicitly to `log()` for each stage event. This avoids the bug of a single
shared "current correlation_id" being overwritten on every PCM frame.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from pathlib import Path


class UtteranceTiming:
    """Helper that appends JSON-line timing entries to a file.

    Stages typically logged by the caller:
    transcribe_finalized, translate_done, polly_first_chunk, listener_first_chunk.
    """

    def __init__(self, log_path: Path) -> None:
        """Initialize with a log file path; ensures the parent directory exists."""
        self._log_path = log_path
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

    def new_id(self) -> str:
        """Return a fresh correlation id (UUID string) for a new utterance."""
        return str(uuid4())

    def log(self, correlation_id: str, event: str) -> None:
        """Append a JSON line with correlation_id, event, and current monotonic time."""
        entry = {
            "correlation_id": correlation_id,
            "event": event,
            "t": time.monotonic(),
        }
        with self._log_path.open("a") as fh:
            fh.write(json.dumps(entry) + "\n")
