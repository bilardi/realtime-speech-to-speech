"""Amazon Polly synthesis wrapper.

M1.A baseline uses Polly's synchronous ``synthesize_speech`` because boto3 does not
yet expose ``start_speech_synthesis_stream`` (verified Task 4, decision 17). The
wrapper exposes the same async-iterator interface that M1.B will retain when migrating
to HTTP/2 bidirectional streaming, so the refactor stays local to this file.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, cast

import boto3
from loguru import logger

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from mypy_boto3_polly.client import PollyClient
    from mypy_boto3_polly.literals import EngineType, OutputFormatType, VoiceIdType


class PollyError(RuntimeError):
    """Raised when Polly synthesis fails."""


# Slice the synthesized audio so the listener gets progressive frames.
# Same numeric value as the audio_client capture block (~100 ms at 16 kHz mono PCM).
_CHUNK_SIZE = 3200


def _client() -> PollyClient:
    """Return a Polly boto3 client using AWS_REGION from env."""
    # boto3.client has ~400 overloads; only polly/translate are typed via stubs,
    # the rest return Unknown which pyright strict flags as partially unknown.
    # Our literal "polly" call matches the typed overload, so the returned client
    # is correctly typed even though the function symbol itself is partial.
    return boto3.client(  # pyright: ignore[reportUnknownMemberType]
        "polly",
        region_name=os.environ.get("AWS_REGION", "eu-west-1"),
    )


async def synthesize_stream(
    *,
    text: str,
    voice_id: str,
    engine: str = "generative",
    output_format: str = "pcm",
    sample_rate: str = "16000",
) -> AsyncIterator[bytes]:
    """Synthesize text to PCM audio and yield fixed-size chunks.

    M1.A: calls ``synthesize_speech`` (sync), then yields the resulting AudioStream
    in chunks. The full audio is generated server-side before the first byte is
    yielded. M1.B will swap this for HTTP/2 bidirectional streaming with the same
    interface.

    Runtime config holds arbitrary strings; we cast to the typed ``Literal`` at the
    AWS boundary. Invalid values are rejected by AWS server-side.

    Args:
        text: Input text to synthesize.
        voice_id: Polly voice ID, e.g. ``"Matthew"``.
        engine: Polly engine; default ``"generative"``.
        output_format: ``"pcm"`` or ``"mp3"``; default ``"pcm"``.
        sample_rate: Sample rate in Hz as string; default ``"16000"``.

    Yields:
        PCM 16-bit signed LE chunks of size up to ``_CHUNK_SIZE``.

    Raises:
        PollyError: If the AWS call fails or the response is malformed.
    """
    try:
        response = _client().synthesize_speech(
            Text=text,
            VoiceId=cast("VoiceIdType", voice_id),
            Engine=cast("EngineType", engine),
            OutputFormat=cast("OutputFormatType", output_format),
            SampleRate=sample_rate,
        )
    except Exception as exc:
        logger.warning("Polly synthesize_speech failed: {}", exc)
        raise PollyError(str(exc)) from exc

    # AudioStream is required in the typed response, but we keep a defensive check
    # for malformed responses (e.g. test doubles, future API changes); pyright cannot
    # see this branch as reachable since the TypedDict marks the field non-optional.
    audio_stream = response.get("AudioStream")
    if audio_stream is None:  # pyright: ignore[reportUnnecessaryComparison]
        msg = "Polly response missing AudioStream"
        raise PollyError(msg)

    while True:
        chunk = audio_stream.read(_CHUNK_SIZE)
        if not chunk:
            break
        yield chunk
