"""Amazon Transcribe Streaming wrapper."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from amazon_transcribe.client import TranscribeStreamingClient

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from amazon_transcribe.model import StartStreamTranscriptionEventStream, TranscriptEvent


async def open_stream(
    *,
    language_code: str,
    sample_rate_hz: int = 16000,
) -> StartStreamTranscriptionEventStream:
    """Open a Transcribe Streaming stream for PCM 16-bit input.

    Args:
        language_code: BCP-47 source language, e.g. "it-IT".
        sample_rate_hz: PCM sample rate in Hz, default 16000.

    Returns:
        The streaming session (with input_stream and output_stream attributes).
    """
    client = TranscribeStreamingClient(region=os.environ.get("AWS_REGION", "eu-west-1"))
    # amazon-transcribe annotates a few rarely-used params (pii_entity_types,
    # content_redaction_type, content_identification_type) without types, so the
    # method signature is "partially unknown" under pyright strict. The return
    # type and our keyword args are typed correctly.
    return await client.start_stream_transcription(  # pyright: ignore[reportUnknownMemberType]
        language_code=language_code,
        media_sample_rate_hz=sample_rate_hz,
        media_encoding="pcm",
    )


async def iter_finalized(handler: AsyncIterator[TranscriptEvent]) -> AsyncIterator[str]:
    """Yield only finalized transcript texts (skip partials).

    Args:
        handler: async iterator of Transcribe events.

    Yields:
        The transcript string for each event with is_partial=False.
    """
    async for event in handler:
        for result in event.transcript.results:
            if result.is_partial:
                continue
            if result.alternatives:
                yield result.alternatives[0].transcript
