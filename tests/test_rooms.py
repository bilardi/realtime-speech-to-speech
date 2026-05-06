"""Test the rooms registry: multi-room, multi-listener fan-out, dispatch hardening."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from app.rooms import RoomRegistry, SessionConflictError


def test_register_speaker_first_time_succeeds() -> None:
    """First speaker registration in a room succeeds."""
    reg = RoomRegistry()
    reg.register_speaker("1", AsyncMock(), source_lang="it-IT")
    assert reg.has_speaker("1")


def test_register_speaker_conflict_per_room() -> None:
    """A second speaker in the same room raises; another room is allowed."""
    reg = RoomRegistry()
    reg.register_speaker("1", AsyncMock(), source_lang="it-IT")
    with pytest.raises(SessionConflictError):
        reg.register_speaker("1", AsyncMock(), source_lang="it-IT")
    reg.register_speaker("2", AsyncMock(), source_lang="it-IT")
    assert reg.has_speaker("2")


def test_unregister_speaker_clears_slot() -> None:
    """After unregister_speaker, a new registration is allowed."""
    reg = RoomRegistry()
    ws = AsyncMock()
    reg.register_speaker("1", ws, source_lang="it-IT")
    reg.unregister_speaker("1", ws)
    assert not reg.has_speaker("1")
    reg.register_speaker("1", AsyncMock(), source_lang="it-IT")


def test_unregister_speaker_with_different_ws_is_noop() -> None:
    """Unregistering a ws different from the current speaker does not clear the slot."""
    reg = RoomRegistry()
    current = AsyncMock()
    other = AsyncMock()
    reg.register_speaker("1", current, source_lang="it-IT")
    reg.unregister_speaker("1", other)
    assert reg.has_speaker("1")


def test_register_multiple_listeners_same_lang_no_conflict() -> None:
    """N listeners on the same target_lang in the same room are allowed."""
    reg = RoomRegistry()
    reg.register_listener("1", AsyncMock(), target_lang="en-US")
    reg.register_listener("1", AsyncMock(), target_lang="en-US")
    assert reg.active_targets("1") == {"en-US"}


def test_active_targets_collects_distinct_langs() -> None:
    """active_targets returns the set of langs with at least one listener."""
    reg = RoomRegistry()
    reg.register_listener("1", AsyncMock(), target_lang="en-US")
    reg.register_listener("1", AsyncMock(), target_lang="es-ES")
    reg.register_listener("1", AsyncMock(), target_lang="en-US")
    assert reg.active_targets("1") == {"en-US", "es-ES"}


def test_active_targets_empty_for_unknown_room() -> None:
    """Unknown room id returns an empty set."""
    assert RoomRegistry().active_targets("9") == set()


def test_unregister_listener_removes_only_that_ws() -> None:
    """Unregistering one ws keeps the others on the same lang."""
    reg = RoomRegistry()
    a = AsyncMock()
    b = AsyncMock()
    reg.register_listener("1", a, target_lang="en-US")
    reg.register_listener("1", b, target_lang="en-US")
    reg.unregister_listener("1", a, target_lang="en-US")
    assert reg.active_targets("1") == {"en-US"}


def test_unregister_listener_last_removes_lang_from_active() -> None:
    """When the last listener of a lang leaves, the lang exits active_targets."""
    reg = RoomRegistry()
    ws = AsyncMock()
    reg.register_listener("1", ws, target_lang="en-US")
    reg.unregister_listener("1", ws, target_lang="en-US")
    assert reg.active_targets("1") == set()


def test_list_rooms_with_speaker() -> None:
    """list_rooms_with_speaker returns rooms with a registered speaker."""
    reg = RoomRegistry()
    reg.register_speaker("1", AsyncMock(), source_lang="it-IT")
    reg.register_listener("2", AsyncMock(), target_lang="en-US")
    assert reg.list_rooms_with_speaker() == ["1"]


@pytest.mark.asyncio
async def test_dispatch_text_broadcasts_to_all_in_lang() -> None:
    """dispatch_text sends the JSON payload to every listener on (room, lang)."""
    reg = RoomRegistry()
    a = AsyncMock()
    b = AsyncMock()
    other_lang = AsyncMock()
    reg.register_listener("1", a, target_lang="en-US")
    reg.register_listener("1", b, target_lang="en-US")
    reg.register_listener("1", other_lang, target_lang="es-ES")

    await reg.dispatch_text(room="1", target_lang="en-US", text="hi", error=None)

    a.send_text.assert_awaited_once()
    b.send_text.assert_awaited_once()
    other_lang.send_text.assert_not_awaited()
    payload = json.loads(a.send_text.await_args.args[0])
    assert payload == {"text": "hi", "lang": "en-US", "error": None}


@pytest.mark.asyncio
async def test_dispatch_audio_broadcasts_to_all_in_lang() -> None:
    """dispatch_audio sends the bytes to every listener on (room, lang)."""
    reg = RoomRegistry()
    a = AsyncMock()
    b = AsyncMock()
    reg.register_listener("1", a, target_lang="en-US")
    reg.register_listener("1", b, target_lang="en-US")
    await reg.dispatch_audio(room="1", target_lang="en-US", audio=b"chunk")
    a.send_bytes.assert_awaited_once_with(b"chunk")
    b.send_bytes.assert_awaited_once_with(b"chunk")


@pytest.mark.asyncio
async def test_dispatch_text_drops_failing_listener() -> None:
    """If a single send_text raises, only that listener is dropped from the bucket."""
    reg = RoomRegistry()
    bad = AsyncMock()
    bad.send_text.side_effect = ConnectionResetError("gone")
    good = AsyncMock()
    reg.register_listener("1", bad, target_lang="en-US")
    reg.register_listener("1", good, target_lang="en-US")

    await reg.dispatch_text(room="1", target_lang="en-US", text="x", error=None)

    good.send_text.assert_awaited_once()
    await reg.dispatch_text(room="1", target_lang="en-US", text="y", error=None)
    bad.send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_audio_drops_failing_listener() -> None:
    """If a single send_bytes raises, only that listener is dropped."""
    reg = RoomRegistry()
    bad = AsyncMock()
    bad.send_bytes.side_effect = ConnectionResetError("gone")
    good = AsyncMock()
    reg.register_listener("1", bad, target_lang="en-US")
    reg.register_listener("1", good, target_lang="en-US")

    await reg.dispatch_audio(room="1", target_lang="en-US", audio=b"chunk")

    good.send_bytes.assert_awaited_once_with(b"chunk")
    assert reg.active_targets("1") == {"en-US"}
    await reg.dispatch_audio(room="1", target_lang="en-US", audio=b"chunk2")
    expected_good_calls = 2
    assert good.send_bytes.await_count == expected_good_calls
    assert bad.send_bytes.await_count == 1


@pytest.mark.asyncio
async def test_dispatch_audio_timeout_drops_listener() -> None:
    """A hanging send_bytes triggers the timeout branch and the listener is dropped."""
    reg = RoomRegistry()
    ws = AsyncMock()

    async def hang(_: bytes) -> None:
        await asyncio.sleep(60)

    ws.send_bytes.side_effect = hang
    reg.register_listener("1", ws, target_lang="en-US")

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("app.rooms._DISPATCH_TIMEOUT_S", 0.05)
        await reg.dispatch_audio(room="1", target_lang="en-US", audio=b"chunk")

    assert reg.active_targets("1") == set()


@pytest.mark.asyncio
async def test_dispatch_no_listener_is_noop() -> None:
    """Dispatch on empty / non-existent room is a noop and does not raise."""
    reg = RoomRegistry()
    await reg.dispatch_text(room="9", target_lang="en-US", text="x", error=None)
    await reg.dispatch_audio(room="9", target_lang="en-US", audio=b"x")
