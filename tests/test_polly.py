"""Test the Polly synthesis wrapper."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from amazon_polly_streaming import PollyStreamingClient, ServiceException

from app.polly import PollyError, synthesize_stream

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def _async_iter(chunks: list[bytes]) -> AsyncIterator[bytes]:
    """Wrap a list of bytes into an async iterator."""

    async def gen() -> AsyncIterator[bytes]:
        for chunk in chunks:
            yield chunk

    return gen()


@pytest.fixture(autouse=True)
def _clear_polly_client_cache() -> None:
    """Reset `_get_client()` cache before each test (region env may vary per test)."""
    from app.polly import _get_client  # noqa: PLC0415

    _get_client.cache_clear()


@pytest.mark.asyncio
async def test_synthesize_stream_passes_through_polly_chunks() -> None:
    """Each `AudioEvent` chunk emitted by amazon-polly-streaming is yielded as-is."""
    polly_chunks = [b"alpha", b"beta", b"gamma"]

    def fake_synth(**_: object) -> AsyncIterator[bytes]:
        return _async_iter(polly_chunks)

    with patch.object(
        PollyStreamingClient, "start_speech_synthesis_stream", side_effect=fake_synth
    ):
        received = [chunk async for chunk in synthesize_stream(text="hi", voice_id="Matthew")]

    assert received == polly_chunks


@pytest.mark.asyncio
async def test_synthesize_stream_forwards_voice_and_format_parameters() -> None:
    """Voice id, engine, output format, sample rate, and language flow through to the method."""
    captured: dict[str, object] = {}

    def fake_synth(**kwargs: object) -> AsyncIterator[bytes]:
        captured.update(kwargs)
        return _async_iter([b"audio"])

    env = {"AWS_REGION": "us-west-2", "POLLY_LANGUAGE_CODE": "en-US"}
    with (
        patch.dict("os.environ", env, clear=False),
        patch.object(PollyStreamingClient, "start_speech_synthesis_stream", side_effect=fake_synth),
    ):
        async for _ in synthesize_stream(
            text="ciao",
            voice_id="Matthew",
            engine="generative",
            output_format="pcm",
            sample_rate="16000",
        ):
            pass

    assert captured["text"] == "ciao"
    assert captured["voice_id"] == "Matthew"
    assert captured["engine"] == "generative"
    assert captured["output_format"] == "pcm"
    assert captured["sample_rate"] == "16000"
    assert captured["language_code"] == "en-US"


def test_get_client_uses_aws_region_from_env() -> None:
    """The cached client is constructed with the AWS_REGION env value."""
    from app.polly import _get_client  # noqa: PLC0415

    with patch.dict("os.environ", {"AWS_REGION": "ap-southeast-1"}, clear=False):
        client = _get_client()

    assert client.region == "ap-southeast-1"


@pytest.mark.asyncio
async def test_synthesize_stream_maps_service_exception_to_polly_error() -> None:
    """`ServiceException` from the library surfaces as `PollyError` to callers."""

    async def fake_synth(**_: object) -> AsyncIterator[bytes]:
        msg = "framed exception from Polly"
        raise ServiceException(msg)
        yield  # pragma: no cover - unreachable, keeps function an async generator

    with (
        patch.object(PollyStreamingClient, "start_speech_synthesis_stream", side_effect=fake_synth),
        pytest.raises(PollyError, match="framed exception"),
    ):
        async for _ in synthesize_stream(text="x", voice_id="Matthew"):
            pass


@pytest.mark.asyncio
async def test_synthesize_stream_maps_transport_runtime_error_to_polly_error() -> None:
    """A transport-layer `RuntimeError` (HTTP/2, TLS, credentials) maps to `PollyError`."""

    async def fake_synth(**_: object) -> AsyncIterator[bytes]:
        msg = "connection refused"
        raise RuntimeError(msg)
        yield  # pragma: no cover - unreachable, keeps function an async generator

    with (
        patch.object(PollyStreamingClient, "start_speech_synthesis_stream", side_effect=fake_synth),
        pytest.raises(PollyError, match="connection refused"),
    ):
        async for _ in synthesize_stream(text="x", voice_id="Matthew"):
            pass


@pytest.mark.asyncio
async def test_synthesize_stream_default_use_pool_is_true_when_env_unset() -> None:
    """Without `POLLY_USE_POOL` set, the wrapper passes `use_pool=True`."""
    captured: dict[str, object] = {}

    def fake_synth(**kwargs: object) -> AsyncIterator[bytes]:
        captured.update(kwargs)
        return _async_iter([b"audio"])

    with (
        patch.dict("os.environ", {}, clear=False),
        patch.object(PollyStreamingClient, "start_speech_synthesis_stream", side_effect=fake_synth),
    ):
        import os  # noqa: PLC0415

        os.environ.pop("POLLY_USE_POOL", None)
        async for _ in synthesize_stream(text="x", voice_id="Matthew"):
            pass

    assert captured["use_pool"] is True


@pytest.mark.asyncio
async def test_synthesize_stream_use_pool_false_when_env_disables_pool() -> None:
    """`POLLY_USE_POOL=false` propagates `use_pool=False` to amazon-polly-streaming."""
    captured: dict[str, object] = {}

    def fake_synth(**kwargs: object) -> AsyncIterator[bytes]:
        captured.update(kwargs)
        return _async_iter([b"audio"])

    with (
        patch.dict("os.environ", {"POLLY_USE_POOL": "false"}, clear=False),
        patch.object(PollyStreamingClient, "start_speech_synthesis_stream", side_effect=fake_synth),
    ):
        async for _ in synthesize_stream(text="x", voice_id="Matthew"):
            pass

    assert captured["use_pool"] is False


@pytest.mark.asyncio
async def test_synthesize_stream_use_pool_true_when_env_explicitly_enables_pool() -> None:
    """`POLLY_USE_POOL=true` propagates `use_pool=True`."""
    captured: dict[str, object] = {}

    def fake_synth(**kwargs: object) -> AsyncIterator[bytes]:
        captured.update(kwargs)
        return _async_iter([b"audio"])

    with (
        patch.dict("os.environ", {"POLLY_USE_POOL": "true"}, clear=False),
        patch.object(PollyStreamingClient, "start_speech_synthesis_stream", side_effect=fake_synth),
    ):
        async for _ in synthesize_stream(text="x", voice_id="Matthew"):
            pass

    assert captured["use_pool"] is True


@pytest.mark.asyncio
async def test_synthesize_stream_use_pool_env_parse_is_case_insensitive() -> None:
    """`POLLY_USE_POOL=FALSE` (uppercase) is parsed as disabled."""
    captured: dict[str, object] = {}

    def fake_synth(**kwargs: object) -> AsyncIterator[bytes]:
        captured.update(kwargs)
        return _async_iter([b"audio"])

    with (
        patch.dict("os.environ", {"POLLY_USE_POOL": "FALSE"}, clear=False),
        patch.object(PollyStreamingClient, "start_speech_synthesis_stream", side_effect=fake_synth),
    ):
        async for _ in synthesize_stream(text="x", voice_id="Matthew"):
            pass

    assert captured["use_pool"] is False
