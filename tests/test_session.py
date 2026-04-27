"""Test the WebSocket session lifecycle."""

import json
from unittest.mock import AsyncMock

import pytest

from app.session import SessionConflictError, SessionManager


def test_register_speaker_first_time_returns_id() -> None:
    """First speaker registration succeeds and returns an id."""
    mgr = SessionManager()
    ws = AsyncMock()

    speaker_id = mgr.register_speaker(ws)

    assert speaker_id is not None
    assert mgr.has_speaker()


def test_register_speaker_second_time_raises_conflict() -> None:
    """A second speaker registration raises SessionConflictError."""
    mgr = SessionManager()
    ws_a = AsyncMock()
    ws_b = AsyncMock()

    mgr.register_speaker(ws_a)

    with pytest.raises(SessionConflictError):
        mgr.register_speaker(ws_b)


def test_unregister_speaker_clears_slot() -> None:
    """After `unregister_speaker`, a new registration is allowed."""
    mgr = SessionManager()
    ws_a = AsyncMock()

    speaker_id = mgr.register_speaker(ws_a)
    mgr.unregister_speaker(speaker_id)

    assert not mgr.has_speaker()
    mgr.register_speaker(AsyncMock())  # does not raise


def test_register_listener_first_time_returns_id() -> None:
    """First listener registration succeeds and returns an id."""
    mgr = SessionManager()
    listener_id = mgr.register_listener(AsyncMock())
    assert listener_id is not None
    assert mgr.has_listener()


def test_register_listener_second_time_raises_conflict() -> None:
    """Second listener raises SessionConflictError."""
    mgr = SessionManager()
    mgr.register_listener(AsyncMock())
    with pytest.raises(SessionConflictError):
        mgr.register_listener(AsyncMock())


def test_unregister_listener_clears_slot() -> None:
    """After `unregister_listener`, a new registration is allowed."""
    mgr = SessionManager()
    lid = mgr.register_listener(AsyncMock())
    mgr.unregister_listener(lid)
    assert not mgr.has_listener()


@pytest.mark.asyncio
async def test_dispatch_sends_text_json_to_listener() -> None:
    """`dispatch_text` sends a JSON message to the listener WebSocket."""
    mgr = SessionManager()
    ws = AsyncMock()
    mgr.register_listener(ws)

    await mgr.dispatch_text(text="hello world", lang="en-US", error=None)

    ws.send_text.assert_awaited_once()
    sent = ws.send_text.await_args.args[0]
    parsed = json.loads(sent)
    assert parsed == {"text": "hello world", "lang": "en-US", "error": None}


@pytest.mark.asyncio
async def test_dispatch_sends_audio_binary_to_listener() -> None:
    """`dispatch_audio` sends raw bytes to the listener WebSocket."""
    mgr = SessionManager()
    ws = AsyncMock()
    mgr.register_listener(ws)

    await mgr.dispatch_audio(b"chunk1")

    ws.send_bytes.assert_awaited_once_with(b"chunk1")


@pytest.mark.asyncio
async def test_dispatch_no_listener_is_noop() -> None:
    """When no listener is registered, dispatch is a noop and does not raise."""
    mgr = SessionManager()
    await mgr.dispatch_text(text="x", lang="en-US", error=None)
    await mgr.dispatch_audio(b"y")
