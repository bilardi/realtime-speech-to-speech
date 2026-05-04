"""Amazon Polly synthesis wrapper.

Delegates to the `polly-streaming` package, which talks to Polly's HTTP/2
bidirectional streaming endpoint (`StartSpeechSynthesisStream`) via SigV4
plus rolling chunk-signature. Exposes an async-iterator interface so
`app.pipeline` can yield audio bytes as they arrive from Polly.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from loguru import logger
from polly_streaming import PollyStreamError
from polly_streaming import synthesize_stream as _synthesize_stream

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
        else. Default ``True`` matches the polly-streaming library default
        and the production target (pool reduces TLS / HTTP/2 setup cost).
    """
    raw = os.environ.get("POLLY_USE_POOL")
    if raw is None:
        return True
    return raw.strip().lower() not in _USE_POOL_FALSY


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
    polly-streaming HTTP/2 connection pool per call. Default ``True``;
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
        async for chunk in _synthesize_stream(
            text=text,
            voice_id=voice_id,
            region=os.environ.get("AWS_REGION", "us-west-2"),
            engine=engine,
            language_code=os.environ.get("POLLY_LANGUAGE_CODE", "en-US"),
            output_format=output_format,
            sample_rate=sample_rate,
            use_pool=_parse_use_pool(),
        ):
            yield chunk
    except PollyStreamError as exc:
        logger.warning("Polly bidirectional streaming returned an error event: {}", exc)
        raise PollyError(str(exc)) from exc
    except RuntimeError as exc:
        logger.warning("Polly bidirectional streaming transport failure: {}", exc)
        raise PollyError(str(exc)) from exc
