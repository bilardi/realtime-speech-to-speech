# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportUnknownParameterType=false
# pyright: reportMissingTypeArgument=false, reportMissingImports=false
# Rationale: aws-sdk-transcribe-streaming ships without `py.typed`, so
# pyright in strict mode fails to resolve some submodules and treats the
# rest as partially unknown; suppressions are scoped to this module.
"""Amazon Transcribe Streaming wrapper.

Delegates to ``aws-sdk-transcribe-streaming`` (awslabs smithy-based SDK).
Exposes a stable input/output interface that mirrors the old
``amazon-transcribe`` package so ``app.main`` can stay unchanged:

* ``open_stream()`` returns a ``TranscribeSession`` with ``input_stream``
  (with ``send_audio_event(audio_chunk=...)`` and ``end_stream()`` methods)
  and ``output_stream`` (an async iterable of typed event-stream events).
* ``iter_finalized(stream)`` filters the output stream and yields the
  string of each finalized ``TranscriptEvent``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING, Any

from aws_sdk_transcribe_streaming.client import TranscribeStreamingClient
from aws_sdk_transcribe_streaming.config import Config
from aws_sdk_transcribe_streaming.models import (
    AudioEvent,
    AudioStreamAudioEvent,
    StartStreamTranscriptionInput,
    TranscriptEvent,
)
from smithy_aws_core.identity import EnvironmentCredentialsResolver

if TYPE_CHECKING:
    from collections.abc import AsyncIterable, AsyncIterator


class _InputAdapter:
    """Legacy-compatible wrapper around the smithy ``input_stream``."""

    def __init__(self, smithy_input: Any) -> None:  # noqa: ANN401
        """Bind to the smithy ``EventPublisher`` that backs this adapter."""
        self._inner = smithy_input

    async def send_audio_event(self, *, audio_chunk: bytes) -> None:
        """Send a PCM audio chunk as an ``AudioEvent``."""
        await self._inner.send(AudioStreamAudioEvent(value=AudioEvent(audio_chunk=audio_chunk)))

    async def end_stream(self) -> None:
        """Close the input stream, signaling end of audio."""
        await self._inner.close()


@dataclass
class TranscribeSession:
    """Handle for an active Transcribe streaming session."""

    input_stream: _InputAdapter
    output_stream: Any  # smithy ``EventReceiver[TranscriptResultStream]``


@cache
def _get_client() -> TranscribeStreamingClient:
    """Return a cached ``TranscribeStreamingClient`` bound to the configured region."""
    region = os.environ.get("AWS_REGION", "eu-west-1")
    return TranscribeStreamingClient(
        config=Config(
            endpoint_uri=f"https://transcribestreaming.{region}.amazonaws.com",
            region=region,
            aws_credentials_identity_resolver=EnvironmentCredentialsResolver(),
        )
    )


async def open_stream(*, language_code: str, sample_rate_hz: int = 16000) -> TranscribeSession:
    """Open a Transcribe Streaming session for PCM 16-bit input.

    Args:
        language_code: BCP-47 source language, e.g. ``"it-IT"``.
        sample_rate_hz: PCM sample rate in Hz, default ``16000``.

    Returns:
        A ``TranscribeSession`` with ``input_stream`` (writable) and
        ``output_stream`` (async iterable of typed transcript events).
    """
    client = _get_client()
    duplex = await client.start_stream_transcription(
        input=StartStreamTranscriptionInput(
            language_code=language_code,
            media_sample_rate_hertz=sample_rate_hz,
            media_encoding="pcm",
        )
    )
    _, output_stream = await duplex.await_output()
    if output_stream is None:
        msg = "Transcribe returned no output stream"
        raise RuntimeError(msg)
    return TranscribeSession(
        input_stream=_InputAdapter(duplex.input_stream),
        output_stream=output_stream,
    )


async def iter_finalized(stream: AsyncIterable[Any]) -> AsyncIterator[str]:
    """Yield only finalized transcript texts (skip partials).

    Args:
        stream: async iterable of typed ``TranscriptResultStream`` events
            (each with ``.value`` holding the wrapped shape).

    Yields:
        The transcript string for each event with ``is_partial=False``.
    """
    async for event in stream:
        if not isinstance(event.value, TranscriptEvent):
            continue
        transcript = event.value.transcript
        if not transcript or not transcript.results:
            continue
        for result in transcript.results:
            if result.is_partial:
                continue
            if result.alternatives:
                yield result.alternatives[0].transcript
