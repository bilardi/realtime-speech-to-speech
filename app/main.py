"""FastAPI server for speech-to-speech: WebSocket routes plus static plus REST helpers."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.pipeline import Pipeline
from app.rooms import RoomRegistry, SessionConflictError
from app.timing import UtteranceTiming
from app.transcribe import iter_finalized, open_stream
from app.voices import supported_target_languages

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from amazon_transcribe.model import StartStreamTranscriptionEventStream

load_dotenv()

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
TIMING_LOG = Path(__file__).resolve().parent.parent / "logs" / "timings.jsonl"

# Optional per-utterance trace at logger.debug level: enabled when
# ``DEBUG_LOG_PIPELINE_TRACE=1`` is set in the environment. Disabled by
# default so production logs only carry uvicorn access lines plus warnings
# / errors. The timing JSON is always written to ``logs/timings.jsonl``
# regardless of this flag.
_PIPELINE_TRACE = os.environ.get("DEBUG_LOG_PIPELINE_TRACE") == "1"

# Source langs are validated lazily by AWS Transcribe Streaming itself.
# Target langs are discovered at startup from Polly generative voices.
_SUPPORTED_TARGET_LANGS: set[str] = set()

# Defaults from .env when the WS query string does not carry an explicit lang.
# Speakers (audio_client) and listeners (browser via QR) normally pass
# ``?lang=...`` explicitly; these defaults cover the bare connect case.
_DEFAULT_SOURCE_LANG = os.environ.get("SOURCE_LANG", "it-IT")
_DEFAULT_TARGET_LANG = os.environ.get("TARGET_LANG", "en-US")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    """Discover supported target languages once at startup."""
    _SUPPORTED_TARGET_LANGS.clear()
    _SUPPORTED_TARGET_LANGS.update(supported_target_languages())
    logger.info("Discovered {} supported target languages", len(_SUPPORTED_TARGET_LANGS))
    yield


app = FastAPI(title="Speech-to-Speech", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
registry = RoomRegistry()


@app.get("/")
async def root() -> FileResponse:
    """Serve the browser display index page."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/languages")
async def api_languages() -> JSONResponse:
    """Return the discovered set of supported target languages."""
    return JSONResponse({"languages": sorted(_SUPPORTED_TARGET_LANGS)})


@app.get("/api/rooms")
async def api_rooms() -> JSONResponse:
    """Return room ids with at least one registered speaker."""
    return JSONResponse({"rooms": registry.list_rooms_with_speaker()})


@app.get("/rooms")
async def rooms_index() -> HTMLResponse:
    """HTML thin-wrapper over /api/rooms: list active rooms as clickable anchors."""
    rooms = registry.list_rooms_with_speaker()
    items = "".join(f'<li><a href="/?room={r}&lang=en-US">room {r}</a></li>' for r in rooms)
    body = (
        "<!doctype html><meta charset='utf-8'>"
        "<title>active rooms</title>"
        f"<h1>active rooms ({len(rooms)})</h1>"
        f"<ul>{items}</ul>"
    )
    return HTMLResponse(body)


async def _feed_audio(
    websocket: WebSocket,
    stream: StartStreamTranscriptionEventStream,
) -> None:
    """Forward incoming PCM frames from the speaker WS to Transcribe Streaming."""
    try:
        while True:
            frame = await websocket.receive_bytes()
            await stream.input_stream.send_audio_event(audio_chunk=frame)
    except WebSocketDisconnect:
        await stream.input_stream.end_stream()


async def _dispatch_for_target(  # noqa: PLR0913
    *,
    room: str,
    source: str,
    target: str,
    text: str,
    timing: UtteranceTiming,
    cid: str,
) -> None:
    """Run Translate plus Polly for one (room, target) and broadcast to listeners."""
    pipeline = Pipeline(source=source, target=target)
    first_audio_logged = False
    async for ev in pipeline.process_finalized(text):
        if ev.kind == "text":
            timing.log(cid, "translate_done")
            if _PIPELINE_TRACE:
                logger.debug("Translate done [{}]: {!r}", target, ev.text)
            await registry.dispatch_text(
                room=room,
                target_lang=ev.lang or target,
                text=ev.text or "",
                error=ev.error,
            )
        elif ev.kind == "audio":
            if not first_audio_logged:
                timing.log(cid, "polly_first_chunk")
                if _PIPELINE_TRACE:
                    logger.debug(
                        "Polly first audio chunk [{}]: {} bytes", target, len(ev.audio or b"")
                    )
            await registry.dispatch_audio(
                room=room, target_lang=ev.lang or target, audio=ev.audio or b""
            )
            if not first_audio_logged:
                timing.log(cid, "listener_first_chunk")
                first_audio_logged = True


async def _consume_transcripts(
    stream: StartStreamTranscriptionEventStream,
    room: str,
    source_short: str,
    timing: UtteranceTiming,
) -> None:
    """Drain finalized transcripts; fan-out per active target as parallel tasks."""
    # amazon-transcribe types output_stream as TranscriptResultStream, but it satisfies
    # the AsyncIterator[TranscriptEvent] protocol at runtime; pyright cannot see __anext__.
    async for finalized in iter_finalized(stream.output_stream):  # pyright: ignore[reportArgumentType]
        if _PIPELINE_TRACE:
            logger.debug("Transcribe finalized: {!r}", finalized)
        targets = registry.active_targets(room)
        if not targets:
            logger.debug("no active targets for room {}, skipping fan-out", room)
            continue
        # One correlation_id per (utterance, target): each cid carries the full
        # set of stage events the latency analyzer needs, and analyze_timings.py
        # produces one row per (utterance, target) without changes.
        for target in targets:
            cid = timing.new_id()
            timing.log(cid, "transcribe_finalized")
            asyncio.create_task(  # noqa: RUF006
                _dispatch_for_target(
                    room=room,
                    source=source_short,
                    target=target,
                    text=finalized,
                    timing=timing,
                    cid=cid,
                )
            )


@app.websocket("/ws/speak")
async def ws_speak(websocket: WebSocket, room: str = "1", lang: str = _DEFAULT_SOURCE_LANG) -> None:
    """Receive PCM frames from a speaker, stream to Transcribe, fan-out per active target."""
    await websocket.accept()
    try:
        registry.register_speaker(room, websocket, source_lang=lang)
    except SessionConflictError:
        await websocket.close(code=4409, reason="speaker_busy")
        return

    timing = UtteranceTiming(log_path=TIMING_LOG)
    source_short = lang.split("-", 1)[0]

    try:
        stream = await open_stream(language_code=lang)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"transcribe open failed for room={room} lang={lang}: {exc}")
        await websocket.close(code=4400, reason="transcribe_open_failed")
        registry.unregister_speaker(room, websocket)
        return

    try:
        await asyncio.gather(
            _feed_audio(websocket, stream),
            _consume_transcripts(stream, room=room, source_short=source_short, timing=timing),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(f"speak ws error: {exc}")
        await websocket.close(code=4500, reason="transcribe_lost")
    finally:
        registry.unregister_speaker(room, websocket)


@app.websocket("/ws/listen")
async def ws_listen(
    websocket: WebSocket, room: str = "1", lang: str = _DEFAULT_TARGET_LANG
) -> None:
    """Receive translated text (JSON) and audio chunks (binary) from the fan-out."""
    if lang not in _SUPPORTED_TARGET_LANGS:
        await websocket.close(code=4400, reason="lang not supported")
        return

    await websocket.accept()
    registry.register_listener(room, websocket, target_lang=lang)

    try:
        # Keep the connection open; dispatch happens from the speaker side via
        # registry.dispatch_text / dispatch_audio. We just block until the
        # client disconnects.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        registry.unregister_listener(room, websocket, target_lang=lang)
