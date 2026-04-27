"""Test the Transcribe Streaming wrapper."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.transcribe import iter_finalized


def _make_event(text: str, *, is_partial: bool) -> MagicMock:
    """Build a mock Transcribe event."""
    alt = MagicMock()
    alt.transcript = text
    result = MagicMock()
    result.is_partial = is_partial
    result.alternatives = [alt]
    event = MagicMock()
    event.transcript.results = [result]
    return event


@pytest.mark.asyncio
async def test_iter_finalized_skips_partials() -> None:
    """`iter_finalized` yields only finalized transcripts and skips partials."""
    events = [
        _make_event("ci", is_partial=True),
        _make_event("ciao mo", is_partial=True),
        _make_event("ciao mondo", is_partial=False),
        _make_event("come", is_partial=True),
        _make_event("come stai", is_partial=False),
    ]

    handler = AsyncMock()
    handler.__aiter__.return_value = iter(events)

    finalized = [text async for text in iter_finalized(handler)]

    assert finalized == ["ciao mondo", "come stai"]
