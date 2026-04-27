"""Test the FastAPI app routes."""

from http import HTTPStatus
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app


def test_get_root_returns_index_html() -> None:
    """`GET /` serves index.html with status 200."""
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == HTTPStatus.OK
    assert "html" in response.text.lower()


def test_ws_speak_rejects_unsupported_language() -> None:
    """`/ws/speak` with an unsupported language closes the connection (does not accept it)."""
    client = TestClient(app)
    # When the endpoint closes before accepting, TestClient raises WebSocketDisconnect on connect.
    # We just assert that the connect attempt does not yield a usable connection by trying
    # to receive within the with-block context manager.
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/ws/speak?lang=xx-XX") as ws,
    ):
        ws.receive_bytes()


@patch("app.main.open_stream")
def test_ws_speak_accepts_supported_language(mock_open_stream: AsyncMock) -> None:
    """`/ws/speak` accepts a supported source language."""
    # Stub open_stream so it never hits AWS. The streams have whatever the endpoint
    # touches; for this acceptance test, the client closes before any frame is read.
    fake_stream = AsyncMock()
    fake_stream.input_stream = AsyncMock()
    fake_stream.output_stream = AsyncMock()
    fake_stream.output_stream.__aiter__.return_value = iter([])
    mock_open_stream.return_value = fake_stream

    client = TestClient(app)
    with client.websocket_connect("/ws/speak?lang=it-IT") as ws:
        ws.close()


def test_ws_listen_rejects_unsupported_language() -> None:
    """`/ws/listen` with an unsupported language closes the connection (does not accept it)."""
    client = TestClient(app)
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/ws/listen?lang=xx-XX") as ws,
    ):
        ws.receive_bytes()


def test_ws_listen_accepts_supported_language() -> None:
    """`/ws/listen` accepts a supported target language."""
    client = TestClient(app)
    with client.websocket_connect("/ws/listen?lang=en-US") as ws:
        ws.close()
