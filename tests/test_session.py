"""Test the WebSocket session lifecycle."""

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
