"""Test the pipeline orchestrator."""

from unittest.mock import patch

import pytest

from app.pipeline import Pipeline, PipelineEvent
from app.polly import PollyError
from app.translate import TranslateError


@pytest.mark.asyncio
@patch("app.pipeline.synthesize_stream")
@patch("app.pipeline.translate")
@patch("app.pipeline.voice_for")
async def test_pipeline_happy_path(
    mock_voice_for,
    mock_translate,
    mock_polly,
) -> None:
    """`Pipeline` calls translate then polly on finalized text and emits text+audio."""
    mock_voice_for.return_value = "Matthew"
    mock_translate.return_value = "hello world"

    async def fake_polly_stream(**_: object):
        for chunk in [b"a", b"b"]:
            yield chunk

    mock_polly.return_value = fake_polly_stream()

    pipe = Pipeline(source="it", target="en-US")
    events: list[PipelineEvent] = [ev async for ev in pipe.process_finalized("ciao mondo")]

    assert events[0].kind == "text"
    assert events[0].text == "hello world"
    assert events[0].error is None

    audio_events = [e for e in events if e.kind == "audio"]
    assert [e.audio for e in audio_events] == [b"a", b"b"]


@pytest.mark.asyncio
@patch("app.pipeline.synthesize_stream")
@patch("app.pipeline.translate")
@patch("app.pipeline.voice_for")
async def test_pipeline_translate_failed(
    mock_voice_for,
    mock_translate,
    mock_polly,
) -> None:
    """When translate raises, pipeline emits text='...' with error='translate_failed' and stops."""
    mock_translate.side_effect = TranslateError("translate boom")

    pipe = Pipeline(source="it", target="en-US")
    events = [e async for e in pipe.process_finalized("ciao mondo")]

    assert len(events) == 1
    assert events[0].kind == "text"
    assert events[0].text == "..."
    assert events[0].error == "translate_failed"
    mock_voice_for.assert_not_called()
    mock_polly.assert_not_called()


@pytest.mark.asyncio
@patch("app.pipeline.synthesize_stream")
@patch("app.pipeline.translate")
@patch("app.pipeline.voice_for")
async def test_pipeline_polly_no_voice(
    mock_voice_for,
    mock_translate,
    mock_polly,
) -> None:
    """When no compatible voice is found, pipeline emits text with error='polly_failed'."""
    mock_voice_for.return_value = None
    mock_translate.return_value = "hello world"

    pipe = Pipeline(source="it", target="en-US")
    events = [e async for e in pipe.process_finalized("ciao mondo")]

    assert len(events) == 1
    assert events[0].text == "hello world"
    assert events[0].error == "polly_failed"
    mock_polly.assert_not_called()


@pytest.mark.asyncio
@patch("app.pipeline.synthesize_stream")
@patch("app.pipeline.translate")
@patch("app.pipeline.voice_for")
async def test_pipeline_polly_stream_error(
    mock_voice_for,
    mock_translate,
    mock_polly,
) -> None:
    """When polly stream raises, text was already emitted and no further audio is yielded."""
    mock_voice_for.return_value = "Matthew"
    mock_translate.return_value = "hello world"

    async def fake_polly_stream(**_: object):
        if False:
            yield  # make it an async generator
        msg = "polly boom"
        raise PollyError(msg)

    mock_polly.return_value = fake_polly_stream()

    pipe = Pipeline(source="it", target="en-US")
    events = [e async for e in pipe.process_finalized("ciao mondo")]

    assert events[0].kind == "text"
    assert events[0].text == "hello world"
    assert all(e.kind != "audio" for e in events)
