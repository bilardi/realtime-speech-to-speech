"""WebSocket session lifecycle manager.

Exactly one speaker and one listener are allowed at any time. Subsequent
registrations raise SessionConflictError; the caller is expected to close
the WebSocket with code 4409.
"""

from __future__ import annotations

import asyncio
import json
from typing import Protocol
from uuid import uuid4

from loguru import logger

_DISPATCH_TIMEOUT_S = 2.0


class WebSocketLike(Protocol):
    """Minimal WebSocket interface used by the manager."""

    async def send_text(self, data: str) -> None:
        """Send a text frame over the WebSocket."""

    async def send_bytes(self, data: bytes) -> None:
        """Send a binary frame over the WebSocket."""


class SessionConflictError(RuntimeError):
    """Raised when a slot (speaker or listener) is already taken."""


class SessionManager:
    """Hold the active speaker and listener WebSockets and their ids."""

    def __init__(self) -> None:
        """Initialize empty slots."""
        self._speaker_id: str | None = None
        self._speaker_ws: WebSocketLike | None = None
        self._listener_id: str | None = None
        self._listener_ws: WebSocketLike | None = None

    def register_speaker(self, ws: WebSocketLike) -> str:
        """Register a speaker and return its id.

        Args:
            ws: The speaker WebSocket.

        Returns:
            The newly assigned speaker id.

        Raises:
            SessionConflictError: If a speaker is already registered.
        """
        if self._speaker_ws is not None:
            msg = "speaker_busy"
            raise SessionConflictError(msg)
        self._speaker_id = str(uuid4())
        self._speaker_ws = ws
        return self._speaker_id

    def unregister_speaker(self, speaker_id: str) -> None:
        """Clear the speaker slot if the id matches."""
        if self._speaker_id == speaker_id:
            self._speaker_id = None
            self._speaker_ws = None

    def has_speaker(self) -> bool:
        """Return True if a speaker is currently registered."""
        return self._speaker_ws is not None

    def register_listener(self, ws: WebSocketLike) -> str:
        """Register a listener and return its id.

        Args:
            ws: The listener WebSocket.

        Returns:
            The newly assigned listener id.

        Raises:
            SessionConflictError: If a listener is already registered.
        """
        if self._listener_ws is not None:
            msg = "listener_busy"
            raise SessionConflictError(msg)
        self._listener_id = str(uuid4())
        self._listener_ws = ws
        return self._listener_id

    def unregister_listener(self, listener_id: str) -> None:
        """Clear the listener slot if the id matches."""
        if self._listener_id == listener_id:
            self._listener_id = None
            self._listener_ws = None

    def has_listener(self) -> bool:
        """Return True if a listener is currently registered."""
        return self._listener_ws is not None

    @property
    def listener_ws(self) -> WebSocketLike | None:
        """Return the active listener WebSocket, or None if not registered."""
        return self._listener_ws

    async def dispatch_text(self, *, text: str, lang: str, error: str | None) -> None:
        """Send a JSON text payload to the listener if one is registered.

        Wraps the WebSocket send in a timeout plus broad except so that a
        half-broken listener (browser closed, network blip) does not bubble
        up the speaker pipeline and tear down the speaker session. On
        failure the listener slot is cleared, leaving the speaker free to
        keep processing utterances; the next listener can register fresh.

        Args:
            text: Translated text (or "..." on translate failure).
            lang: BCP-47 target language code, e.g. "en-US".
            error: Error tag ("translate_failed", "polly_failed") or None.
        """
        ws = self._listener_ws
        if ws is None:
            return
        payload = json.dumps({"text": text, "lang": lang, "error": error})
        try:
            await asyncio.wait_for(ws.send_text(payload), timeout=_DISPATCH_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001
            logger.warning("listener text dispatch failed, dropping listener: {}", exc)
            if self._listener_ws is ws:
                self._listener_ws = None
                self._listener_id = None

    async def dispatch_audio(self, audio: bytes) -> None:
        """Send a raw audio binary frame to the listener if one is registered.

        Same hardening as ``dispatch_text``: timeout plus broad except plus
        clear-on-failure, to keep the speaker pipeline running when the
        listener disappears mid-stream.
        """
        ws = self._listener_ws
        if ws is None:
            return
        try:
            await asyncio.wait_for(ws.send_bytes(audio), timeout=_DISPATCH_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001
            logger.warning("listener audio dispatch failed, dropping listener: {}", exc)
            if self._listener_ws is ws:
                self._listener_ws = None
                self._listener_id = None
