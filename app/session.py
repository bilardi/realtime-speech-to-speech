"""WebSocket session lifecycle manager.

In M1, exactly one speaker and one listener are allowed (decision 7).
Subsequent registrations raise SessionConflictError; the caller is expected to
close the WebSocket with code 4409.
"""

from __future__ import annotations

from typing import Protocol
from uuid import uuid4


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
