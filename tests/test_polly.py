"""Test the Polly synthesis wrapper (aws-sdk-polly based)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aws_sdk_polly.client import PollyClient
from aws_sdk_polly.models import (
    AudioEvent,
    StartSpeechSynthesisStreamEventStreamAudioEvent,
)

from app.polly import PollyError, synthesize_stream

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def _audio_event(chunk: bytes) -> StartSpeechSynthesisStreamEventStreamAudioEvent:
    """Build a real Polly audio event wrapping ``chunk``."""
    return StartSpeechSynthesisStreamEventStreamAudioEvent(value=AudioEvent(audio_chunk=chunk))


def _fake_duplex_stream(events: list[Any]) -> MagicMock:
    """Build a fake ``DuplexEventStream`` whose output emits ``events`` in order.

    ``await_output()`` returns ``(output_shape_mock, async_iter_of_events)``.
    ``input_stream.send`` / ``.close`` are awaitable no-ops.
    """
    stream = MagicMock()
    stream.input_stream = AsyncMock()

    async def output_gen() -> AsyncIterator[Any]:
        for event in events:
            yield event

    async def fake_await_output() -> tuple[MagicMock, AsyncIterator[Any]]:
        return MagicMock(), output_gen()

    stream.await_output = fake_await_output
    return stream


@pytest.fixture(autouse=True)
def _clear_polly_client_cache() -> None:
    """Reset ``_get_client()`` cache before each test (env may vary per test)."""
    from app.polly import _get_client  # noqa: PLC0415

    _get_client.cache_clear()


@pytest.mark.asyncio
async def test_synthesize_stream_passes_through_polly_chunks() -> None:
    """Each AudioEvent chunk emitted by aws-sdk-polly is yielded as-is."""
    events = [_audio_event(b"alpha"), _audio_event(b"beta"), _audio_event(b"gamma")]
    fake_stream = _fake_duplex_stream(events)

    async def fake_start(**_: object) -> MagicMock:
        return fake_stream

    with patch.object(PollyClient, "start_speech_synthesis_stream", side_effect=fake_start):
        received = [chunk async for chunk in synthesize_stream(text="hi", voice_id="Matthew")]

    assert received == [b"alpha", b"beta", b"gamma"]


@pytest.mark.asyncio
async def test_synthesize_stream_skips_audio_events_with_empty_chunk() -> None:
    """``audio_chunk`` may be empty; those events are dropped silently."""
    events = [_audio_event(b""), _audio_event(b"only_real")]
    fake_stream = _fake_duplex_stream(events)

    async def fake_start(**_: object) -> MagicMock:
        return fake_stream

    with patch.object(PollyClient, "start_speech_synthesis_stream", side_effect=fake_start):
        received = [chunk async for chunk in synthesize_stream(text="hi", voice_id="Matthew")]

    assert received == [b"only_real"]


@pytest.mark.asyncio
async def test_synthesize_stream_forwards_voice_and_format_parameters() -> None:
    """Voice id, engine, output format, sample rate, and language flow through to the input."""
    captured: dict[str, Any] = {}
    events = [_audio_event(b"audio")]
    fake_stream = _fake_duplex_stream(events)

    async def fake_start(*, input: Any, **_: object) -> MagicMock:  # noqa: A002
        captured["input"] = input
        return fake_stream

    env = {"AWS_REGION": "us-west-2", "POLLY_LANGUAGE_CODE": "en-US"}
    with (
        patch.dict("os.environ", env, clear=False),
        patch.object(PollyClient, "start_speech_synthesis_stream", side_effect=fake_start),
    ):
        async for _ in synthesize_stream(
            text="ciao",
            voice_id="Matthew",
            engine="generative",
            output_format="pcm",
            sample_rate="16000",
        ):
            pass

    inp = captured["input"]
    assert inp.voice_id == "Matthew"
    assert inp.engine == "generative"
    assert inp.output_format == "pcm"
    assert inp.sample_rate == "16000"
    assert inp.language_code == "en-US"


def test_get_client_uses_aws_region_from_env() -> None:
    """The cached client is constructed with the AWS_REGION env value."""
    from app.polly import _get_client  # noqa: PLC0415

    with patch.dict("os.environ", {"AWS_REGION": "ap-southeast-1"}, clear=False):
        client = _get_client()

    assert client._config.region == "ap-southeast-1"  # noqa: SLF001


@pytest.mark.asyncio
async def test_synthesize_stream_maps_smithy_error_to_polly_error() -> None:
    """Any exception from aws-sdk-polly surfaces as ``PollyError`` to callers."""

    async def fake_start(**_: object) -> MagicMock:
        msg = "smithy/awscrt failure"
        raise RuntimeError(msg)

    with (
        patch.object(PollyClient, "start_speech_synthesis_stream", side_effect=fake_start),
        pytest.raises(PollyError, match="smithy/awscrt failure"),
    ):
        async for _ in synthesize_stream(text="x", voice_id="Matthew"):
            pass
