"""FastAPI server for speech-to-speech: WebSocket routes plus static."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import TYPE_CHECKING

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.pipeline import Pipeline
from app.session import SessionConflictError, SessionManager
from app.timing import UtteranceTiming
from app.transcribe import iter_finalized, open_stream

if TYPE_CHECKING:
    from amazon_transcribe.model import StartStreamTranscriptionEventStream

load_dotenv()

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
TIMING_LOG = Path(__file__).resolve().parent.parent / "logs" / "timings.jsonl"

# Supported source / target languages (extend as needed)
_SUPPORTED_SOURCE_LANGS = {"it-IT", "en-US"}
_SUPPORTED_TARGET_LANGS = {"en-US", "it-IT"}

app = FastAPI(title="Speech-to-Speech")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
session_manager = SessionManager()


@app.get("/")
async def root() -> FileResponse:
    """Serve the browser display index page."""
    return FileResponse(STATIC_DIR / "index.html")


async def _feed_audio(
    websocket: WebSocket,
    stream: StartStreamTranscriptionEventStream,
) -> None:
    """Forward incoming PCM frames from the client WebSocket to Transcribe Streaming."""
    try:
        while True:
            frame = await websocket.receive_bytes()
            await stream.input_stream.send_audio_event(audio_chunk=frame)
    except WebSocketDisconnect:
        await stream.input_stream.end_stream()


async def _consume_transcripts(
    stream: StartStreamTranscriptionEventStream,
    pipeline: Pipeline,
    timing: UtteranceTiming,
    target_lang: str,
) -> None:
    """Drain finalized transcripts, run the pipeline, and dispatch text plus audio."""
    # amazon-transcribe types output_stream as TranscriptResultStream, but it satisfies
    # the AsyncIterator[TranscriptEvent] protocol at runtime; pyright cannot see __anext__.
    async for finalized in iter_finalized(stream.output_stream):  # pyright: ignore[reportArgumentType]
        cid = timing.new_id()
        timing.log(cid, "transcribe_finalized")
        first_audio_logged = False
        async for ev in pipeline.process_finalized(finalized):
            if ev.kind == "text":
                timing.log(cid, "translate_done")
                await session_manager.dispatch_text(
                    text=ev.text or "",
                    lang=ev.lang or target_lang,
                    error=ev.error,
                )
            elif ev.kind == "audio":
                if not first_audio_logged:
                    timing.log(cid, "polly_first_chunk")
                await session_manager.dispatch_audio(ev.audio or b"")
                if not first_audio_logged:
                    timing.log(cid, "listener_first_chunk")
                    first_audio_logged = True


@app.websocket("/ws/speak")
async def ws_speak(websocket: WebSocket, lang: str = "it-IT") -> None:
    """Receive PCM frames from a single speaker, stream to Transcribe, dispatch to listener."""
    if lang not in _SUPPORTED_SOURCE_LANGS:
        await websocket.close(code=4400, reason="lang not supported")
        return

    target_lang = os.environ.get("TARGET_LANG", "en-US")
    if target_lang not in _SUPPORTED_TARGET_LANGS:
        await websocket.close(code=4400, reason="target lang not supported")
        return

    await websocket.accept()
    try:
        speaker_id = session_manager.register_speaker(websocket)
    except SessionConflictError:
        await websocket.close(code=4409, reason="speaker_busy")
        return

    timing = UtteranceTiming(log_path=TIMING_LOG)
    pipeline = Pipeline(source=lang.split("-", 1)[0], target=target_lang)

    try:
        stream = await open_stream(language_code=lang)
        await asyncio.gather(
            _feed_audio(websocket, stream),
            _consume_transcripts(stream, pipeline, timing, target_lang),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(f"speak ws error: {exc}")
        await websocket.close(code=4500, reason="transcribe_lost")
    finally:
        session_manager.unregister_speaker(speaker_id)


@app.websocket("/ws/listen")
async def ws_listen(websocket: WebSocket, lang: str = "en-US") -> None:
    """Receive translated text (JSON) and audio chunks (binary) from the speaker dispatch.

    Args:
        websocket: incoming WebSocket connection from the browser.
        lang: BCP-47 target language. Must be in `_SUPPORTED_TARGET_LANGS`,
            otherwise the connection is closed with code 4400.
    """
    if lang not in _SUPPORTED_TARGET_LANGS:
        await websocket.close(code=4400, reason="lang not supported")
        return

    await websocket.accept()
    try:
        listener_id = session_manager.register_listener(websocket)
    except SessionConflictError:
        await websocket.close(code=4409, reason="listener_busy")
        return

    try:
        # Keep the connection open; dispatch happens from the speaker side via
        # session_manager.dispatch_text / dispatch_audio. We just block until
        # the client disconnects.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        session_manager.unregister_listener(listener_id)
