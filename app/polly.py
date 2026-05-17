"""Amazon Polly synthesis wrapper.

Delegates to the `amazon-polly-streaming` package, which talks to Polly's
HTTP/2 bidirectional streaming endpoint (`StartSpeechSynthesisStream`) via
SigV4 plus rolling chunk-signature. Exposes an async-iterator interface so
`app.pipeline` can yield audio bytes as they arrive from Polly.
"""

from __future__ import annotations

import os
from functools import cache
from typing import TYPE_CHECKING

from amazon_polly_streaming import PollyStreamingClient, ServiceException
from loguru import logger

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class PollyError(RuntimeError):
    """Raised when Polly synthesis fails."""


_USE_POOL_FALSY = frozenset({"false", "0", "no"})


def _parse_use_pool() -> bool:
    """Read the ``POLLY_USE_POOL`` env var.

    Returns:
        ``False`` when the variable is set to ``"false"``, ``"0"``, or
        ``"no"`` (case-insensitive). ``True`` when unset or set to anything
        else. Default ``True`` matches the amazon-polly-streaming library
        default and the production target (pool reduces TLS / HTTP/2 setup cost).
    """
    raw = os.environ.get("POLLY_USE_POOL")
    if raw is None:
        return True
    return raw.strip().lower() not in _USE_POOL_FALSY


@cache
def _get_client() -> PollyStreamingClient:
    """Return a cached ``PollyStreamingClient`` bound to the configured region.

    Module-level cache mirrors the boto3 client caching pattern used elsewhere
    in this package (see ``app.transcribe``, ``app.translate``). Region is read
    once from ``AWS_REGION``; changes at runtime require a process restart.
    """
    return PollyStreamingClient(region=os.environ.get("AWS_REGION", "us-west-2"))


async def synthesize_stream(
    *,
    text: str,
    voice_id: str,
    engine: str = "generative",
    output_format: str = "pcm",
    sample_rate: str = "16000",
) -> AsyncIterator[bytes]:
    """Synthesize text and yield audio bytes as Polly emits them.

    Reads ``POLLY_USE_POOL`` from the environment to enable or disable the
    amazon-polly-streaming HTTP/2 connection pool per call. Default ``True``;
    ``"false"``, ``"0"``, or ``"no"`` disable it (case-insensitive). Useful
    for A/B latency comparisons against the no-pool baseline at the same
    code path.

    Args:
        text: Input text to synthesize.
        voice_id: Polly voice ID (must be a generative voice supporting
            bidirectional streaming, e.g. ``"Matthew"``).
        engine: Polly engine; default ``"generative"`` (only supported value
            for the bidirectional streaming API).
        output_format: ``"pcm"``, ``"mp3"``, ``"ogg_vorbis"``, ...; default
            ``"pcm"``.
        sample_rate: Sample rate in Hz as string; default ``"16000"``.

    Yields:
        Bytes from each ``AudioEvent`` Polly returns, in order. With PCM the
        chunks are 16-bit signed little-endian samples at the configured
        sample rate.

    Raises:
        PollyError: If the AWS call fails (transport error, server-side
            exception, missing credentials).
    """
    try:
        async for chunk in _get_client().start_speech_synthesis_stream(
            text=text,
            voice_id=voice_id,
            engine=engine,
            language_code=os.environ.get("POLLY_LANGUAGE_CODE", "en-US"),
            output_format=output_format,
            sample_rate=sample_rate,
            use_pool=_parse_use_pool(),
        ):
            yield chunk
    except ServiceException as exc:
        logger.warning("Polly bidirectional streaming returned an error event: {}", exc)
        raise PollyError(str(exc)) from exc
    except RuntimeError as exc:
        logger.warning("Polly bidirectional streaming transport failure: {}", exc)
        raise PollyError(str(exc)) from exc
