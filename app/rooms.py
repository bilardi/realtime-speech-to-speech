"""WebSocket session lifecycle manager: rooms with speaker plus listeners by lang.

Each room holds at most one speaker and a list of listeners per target
language. Multiple listeners on the same target_lang are allowed; the
synthesis is computed once and broadcast to all of them. Conflicts are
per-room: an existing speaker in room X does not block a speaker in room Y.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Protocol

from loguru import logger

_DISPATCH_TIMEOUT_S = 2.0


class WebSocketLike(Protocol):
    """Minimal WebSocket interface used by the registry."""

    async def send_text(self, data: str) -> None:
        """Send a text frame over the WebSocket."""

    async def send_bytes(self, data: bytes) -> None:
        """Send a binary frame over the WebSocket."""


class SessionConflictError(RuntimeError):
    """Raised when a per-room slot (speaker) is already taken."""


@dataclass
class Room:
    """State for a single room: speaker slot plus listeners grouped by target language."""

    speaker_ws: WebSocketLike | None = None
    source_lang: str | None = None
    listeners: dict[str, list[WebSocketLike]] = field(
        default_factory=dict[str, list[WebSocketLike]],
    )


class RoomRegistry:
    """In-memory registry of rooms keyed by room id."""

    def __init__(self) -> None:
        """Initialize with an empty registry."""
        self._rooms: dict[str, Room] = {}

    def _ensure_room(self, room: str) -> Room:
        """Get or create a room."""
        if room not in self._rooms:
            self._rooms[room] = Room()
        return self._rooms[room]

    def register_speaker(self, room: str, ws: WebSocketLike, source_lang: str) -> None:
        """Register a speaker in a room.

        Args:
            room: Room id.
            ws: Speaker WebSocket.
            source_lang: BCP-47 source language code.

        Raises:
            SessionConflictError: If a speaker is already registered in the room.
        """
        r = self._ensure_room(room)
        if r.speaker_ws is not None:
            msg = "speaker_busy"
            raise SessionConflictError(msg)
        r.speaker_ws = ws
        r.source_lang = source_lang

    def unregister_speaker(self, room: str, ws: WebSocketLike) -> None:
        """Clear the speaker slot in the room if the ws matches."""
        r = self._rooms.get(room)
        if r is None:
            return
        if r.speaker_ws is ws:
            r.speaker_ws = None
            r.source_lang = None

    def has_speaker(self, room: str) -> bool:
        """Return True if a speaker is currently registered in the room."""
        r = self._rooms.get(room)
        return r is not None and r.speaker_ws is not None

    def register_listener(self, room: str, ws: WebSocketLike, target_lang: str) -> None:
        """Register a listener under a target language in a room.

        Args:
            room: Room id.
            ws: Listener WebSocket.
            target_lang: BCP-47 target language code.
        """
        r = self._ensure_room(room)
        r.listeners.setdefault(target_lang, []).append(ws)

    def unregister_listener(self, room: str, ws: WebSocketLike, target_lang: str) -> None:
        """Remove a listener from a target language list in a room."""
        r = self._rooms.get(room)
        if r is None:
            return
        bucket = r.listeners.get(target_lang)
        if bucket is None:
            return
        remaining = [w for w in bucket if w is not ws]
        if remaining:
            r.listeners[target_lang] = remaining
        else:
            del r.listeners[target_lang]

    def active_targets(self, room: str) -> set[str]:
        """Return the set of target languages with at least one listener in the room."""
        r = self._rooms.get(room)
        if r is None:
            return set()
        return set(r.listeners.keys())

    def list_rooms_with_speaker(self) -> list[str]:
        """Return room ids that currently have a registered speaker."""
        return [room for room, r in self._rooms.items() if r.speaker_ws is not None]

    async def dispatch_text(
        self, *, room: str, target_lang: str, text: str, error: str | None
    ) -> None:
        """Broadcast a JSON text payload to every listener on (room, target_lang).

        Each send is wrapped in a timeout plus broad except: a half-broken
        listener (browser closed, network blip) is dropped from the bucket
        and does not bubble up the speaker pipeline.
        """
        r = self._rooms.get(room)
        if r is None:
            return
        bucket = list(r.listeners.get(target_lang, []))
        if not bucket:
            return
        payload = json.dumps({"text": text, "lang": target_lang, "error": error})
        for ws in bucket:
            try:
                await asyncio.wait_for(ws.send_text(payload), timeout=_DISPATCH_TIMEOUT_S)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "listener text dispatch failed, dropping: room={} lang={} err={}",
                    room,
                    target_lang,
                    exc,
                )
                self.unregister_listener(room, ws, target_lang)

    async def dispatch_audio(self, *, room: str, target_lang: str, audio: bytes) -> None:
        """Broadcast a raw audio binary chunk to every listener on (room, target_lang).

        Same hardening as ``dispatch_text``: timeout plus broad except plus
        per-listener drop on failure.
        """
        r = self._rooms.get(room)
        if r is None:
            return
        bucket = list(r.listeners.get(target_lang, []))
        if not bucket:
            return
        for ws in bucket:
            try:
                await asyncio.wait_for(ws.send_bytes(audio), timeout=_DISPATCH_TIMEOUT_S)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "listener audio dispatch failed, dropping: room={} lang={} err={}",
                    room,
                    target_lang,
                    exc,
                )
                self.unregister_listener(room, ws, target_lang)
