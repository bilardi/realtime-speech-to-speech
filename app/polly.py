# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportUnknownParameterType=false
# pyright: reportMissingTypeArgument=false, reportMissingImports=false
# Rationale: aws-sdk-polly ships without `py.typed`, so pyright in strict
# mode fails to resolve some submodules and treats the rest as partially
# unknown; suppressions are scoped to this module.
"""Amazon Polly synthesis wrapper.

Delegates to ``aws-sdk-polly`` (awslabs smithy-based SDK). Exposes an
async-iterator interface so ``app.pipeline`` can yield audio bytes as
they arrive from Polly's HTTP/2 bidirectional streaming endpoint.
"""

from __future__ import annotations

import asyncio
import os
from functools import cache
from typing import TYPE_CHECKING

from aws_sdk_polly.client import PollyClient
from aws_sdk_polly.config import Config
from aws_sdk_polly.models import (
    CloseStreamEvent,
    StartSpeechSynthesisStreamActionStreamCloseStreamEvent,
    StartSpeechSynthesisStreamActionStreamTextEvent,
    StartSpeechSynthesisStreamEventStreamAudioEvent,
    StartSpeechSynthesisStreamInput,
    TextEvent,
)
from loguru import logger
from smithy_aws_core.identity import EnvironmentCredentialsResolver
from smithy_http.aio.crt import (
    AWSCRTHTTPClient,
    AWSCRTHTTPClientConfig,
    ConnectionPoolConfig,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class PollyError(RuntimeError):
    """Raised when Polly synthesis fails."""


@cache
def _get_client() -> PollyClient:
    """Return a cached ``PollyClient`` bound to the configured region.

    Module-level cache mirrors the boto3 client caching pattern used elsewhere
    in this package (see ``app.translate``, ``app.voices``). Region is read
    once from ``AWS_REGION``; changes at runtime require a process restart.

    The transport is constructed with an explicit ``ConnectionPoolConfig`` so
    that fan-out bidirectional synthesis (1 speaker -> N listener languages)
    can run on multiple HTTP/2 connections concurrently. The pool lives on
    the shared ``_AWSCRTEventLoop`` and survives the ``deepcopy`` that the
    smithy operation pipeline performs on the config per request, which is
    what makes warm reuse across operations possible (see the smithy-python
    ``add-awscrt-connection-pool`` branch driving this).
    """
    region = os.environ.get("AWS_REGION", "us-west-2")
    transport = AWSCRTHTTPClient(
        client_config=AWSCRTHTTPClientConfig(
            connection_pool=ConnectionPoolConfig(max_connections_per_host=8)
        )
    )
    return PollyClient(
        config=Config(
            endpoint_uri=f"https://polly.{region}.amazonaws.com",
            region=region,
            aws_credentials_identity_resolver=EnvironmentCredentialsResolver(),
            transport=transport,
        )
    )


async def synthesize_stream(
    *,
    text: str,
    voice_id: str,
    engine: str = "generative",
    output_format: str = "pcm",
    sample_rate: str = "16000",
) -> AsyncIterator[bytes]:
    """Synthesize text and yield audio bytes as Polly emits them.

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
        stream = await _get_client().start_speech_synthesis_stream(
            input=StartSpeechSynthesisStreamInput(
                engine=engine,
                language_code=os.environ.get("POLLY_LANGUAGE_CODE", "en-US"),
                output_format=output_format,
                sample_rate=sample_rate,
                voice_id=voice_id,
            )
        )
        _, output_stream = await stream.await_output()
        if output_stream is None:
            msg = "Polly returned no output stream"
            raise PollyError(msg)  # noqa: TRY301

        async def _send_input() -> None:
            """Send the text + close-stream event on the input channel."""
            await stream.input_stream.send(
                StartSpeechSynthesisStreamActionStreamTextEvent(value=TextEvent(text=text))
            )
            await stream.input_stream.send(
                StartSpeechSynthesisStreamActionStreamCloseStreamEvent(CloseStreamEvent())
            )
            await stream.input_stream.close()

        producer_task = asyncio.create_task(_send_input())
        try:
            async for event in output_stream:
                if isinstance(event, StartSpeechSynthesisStreamEventStreamAudioEvent):
                    chunk = event.value.audio_chunk
                    if chunk:
                        yield chunk
        finally:
            if not producer_task.done():
                producer_task.cancel()
            try:
                await producer_task
            except (asyncio.CancelledError, Exception) as exc:  # noqa: BLE001
                # Producer cleanup errors are not propagated; the consumer
                # iteration already either completed or raised the primary
                # error. Log for diagnosis without masking the original cause.
                logger.debug("Polly input-stream cleanup raised: {}", exc)

    except PollyError:
        raise
    except Exception as exc:
        logger.warning("Polly bidirectional streaming failed: {}", exc)
        raise PollyError(str(exc)) from exc
