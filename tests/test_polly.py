"""Test the Polly synthesis wrapper."""

from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from app.polly import PollyError, synthesize_stream


@pytest.mark.asyncio
@patch("app.polly.boto3.client")
async def test_synthesize_stream_yields_chunks(mock_client: MagicMock) -> None:
    """`synthesize_stream` calls synthesize_speech and yields the audio in chunks."""
    full_audio = b"x" * 8000  # ~2.5 chunks of 3200 bytes
    mock_client.return_value.synthesize_speech.return_value = {
        "AudioStream": BytesIO(full_audio),
    }

    received = [chunk async for chunk in synthesize_stream(text="hello world", voice_id="Matthew")]

    assert b"".join(received) == full_audio
    mock_client.return_value.synthesize_speech.assert_called_once_with(
        Text="hello world",
        VoiceId="Matthew",
        Engine="generative",
        OutputFormat="pcm",
        SampleRate="16000",
    )


@pytest.mark.asyncio
@patch("app.polly.boto3.client")
async def test_synthesize_stream_raises_on_error(mock_client: MagicMock) -> None:
    """`synthesize_stream` raises PollyError when the AWS call fails."""
    mock_client.return_value.synthesize_speech.side_effect = RuntimeError("polly boom")

    with pytest.raises(PollyError):
        async for _ in synthesize_stream(text="hello", voice_id="Matthew"):
            pass


@pytest.mark.asyncio
@patch("app.polly.boto3.client")
async def test_synthesize_stream_raises_when_no_audio_stream(mock_client: MagicMock) -> None:
    """`synthesize_stream` raises PollyError when AudioStream is missing."""
    mock_client.return_value.synthesize_speech.return_value = {}

    with pytest.raises(PollyError):
        async for _ in synthesize_stream(text="hello", voice_id="Matthew"):
            pass
