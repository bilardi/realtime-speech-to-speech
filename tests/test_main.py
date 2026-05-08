"""Test the FastAPI app routes: room query, lazy source validation, fan-out, lifespan."""

import asyncio
import importlib
from http import HTTPStatus
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


def _make_app() -> ModuleType:
    """Reload app.main so the lifespan picks up the patched describe_voices on each test."""
    import app.main  # noqa: PLC0415

    return importlib.reload(app.main)


@patch("app.voices.boto3.client")
def test_get_root_returns_index_html(mock_boto: MagicMock) -> None:
    """`GET /` serves index.html with status 200."""
    mock_boto.return_value.describe_voices.return_value = {
        "Voices": [{"Id": "X", "LanguageCode": "en-US", "SupportedEngines": ["generative"]}]
    }
    main = _make_app()
    with TestClient(main.app) as client:
        response = client.get("/")
    assert response.status_code == HTTPStatus.OK
    assert "html" in response.text.lower()


@patch("app.voices.boto3.client")
def test_api_languages_returns_discovered_set(mock_boto: MagicMock) -> None:
    """`GET /api/languages` returns the set discovered at startup, sorted."""
    mock_boto.return_value.describe_voices.return_value = {
        "Voices": [
            {"Id": "X", "LanguageCode": "en-US", "SupportedEngines": ["generative"]},
            {"Id": "Y", "LanguageCode": "es-ES", "SupportedEngines": ["generative"]},
        ]
    }
    main = _make_app()
    with TestClient(main.app) as client:
        response = client.get("/api/languages")
    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"languages": ["en-US", "es-ES"]}


@patch("app.voices.boto3.client")
def test_api_rooms_returns_rooms_with_speaker(mock_boto: MagicMock) -> None:
    """`GET /api/rooms` returns room ids that have a registered speaker."""
    mock_boto.return_value.describe_voices.return_value = {
        "Voices": [{"Id": "X", "LanguageCode": "en-US", "SupportedEngines": ["generative"]}]
    }
    main = _make_app()
    with TestClient(main.app) as client:
        assert client.get("/api/rooms").json() == {"rooms": []}
        main.registry.register_speaker("1", AsyncMock(), source_lang="it-IT")
        assert client.get("/api/rooms").json() == {"rooms": ["1"]}


@patch("app.voices.boto3.client")
def test_rooms_html_lists_active_rooms(mock_boto: MagicMock) -> None:
    """`GET /rooms` returns HTML listing active rooms as anchors."""
    mock_boto.return_value.describe_voices.return_value = {
        "Voices": [{"Id": "X", "LanguageCode": "en-US", "SupportedEngines": ["generative"]}]
    }
    main = _make_app()
    with TestClient(main.app) as client:
        main.registry.register_speaker("1", AsyncMock(), source_lang="it-IT")
        main.registry.register_speaker("2", AsyncMock(), source_lang="it-IT")
        response = client.get("/rooms")
    assert response.status_code == HTTPStatus.OK
    assert "?room=1&lang=en-US" in response.text
    assert "?room=2&lang=en-US" in response.text


@patch("app.voices.boto3.client")
def test_ws_listen_rejects_unsupported_target(mock_boto: MagicMock) -> None:
    """`/ws/listen` with a target not in the discovered set closes the connection."""
    mock_boto.return_value.describe_voices.return_value = {
        "Voices": [{"Id": "X", "LanguageCode": "en-US", "SupportedEngines": ["generative"]}]
    }
    main = _make_app()
    with (
        TestClient(main.app) as client,
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/ws/listen?room=1&lang=xx-XX") as ws,
    ):
        ws.receive_bytes()


@patch("app.voices.boto3.client")
def test_ws_listen_accepts_supported_target(mock_boto: MagicMock) -> None:
    """`/ws/listen` accepts a target language present in the discovered set."""
    mock_boto.return_value.describe_voices.return_value = {
        "Voices": [{"Id": "X", "LanguageCode": "en-US", "SupportedEngines": ["generative"]}]
    }
    main = _make_app()
    with (
        TestClient(main.app) as client,
        client.websocket_connect("/ws/listen?room=1&lang=en-US") as ws,
    ):
        ws.close()


@patch("app.voices.boto3.client")
def test_ws_speak_accepts_and_lazy_validates(mock_boto: MagicMock) -> None:
    """`/ws/speak` accepts the connection, AWS Transcribe validates the lang lazily."""
    mock_boto.return_value.describe_voices.return_value = {
        "Voices": [{"Id": "X", "LanguageCode": "en-US", "SupportedEngines": ["generative"]}]
    }
    fake_stream = AsyncMock()
    fake_stream.input_stream = AsyncMock()
    fake_stream.output_stream = AsyncMock()
    fake_stream.output_stream.__aiter__.return_value = iter([])

    # _make_app() reloads `app.main`, so any patch on `app.main.open_stream` set
    # before reload no longer applies (the reloaded module has a fresh import
    # of the real symbol). Patch on the reloaded module via `patch.object` so
    # the mock survives until the WS handler actually runs.
    main = _make_app()
    with (
        patch.object(main, "open_stream", new_callable=AsyncMock) as mock_open_stream,
        TestClient(main.app) as client,
        client.websocket_connect("/ws/speak?room=1&lang=it-IT") as ws,
    ):
        mock_open_stream.return_value = fake_stream
        ws.close()


@patch("app.voices.boto3.client")
def test_ws_speak_closes_4400_on_transcribe_open_failure(mock_boto: MagicMock) -> None:
    """If AWS Transcribe rejects the source lang, the speaker WS is closed with 4400."""
    mock_boto.return_value.describe_voices.return_value = {
        "Voices": [{"Id": "X", "LanguageCode": "en-US", "SupportedEngines": ["generative"]}]
    }

    main = _make_app()
    with (
        patch.object(main, "open_stream", new_callable=AsyncMock) as mock_open_stream,
        TestClient(main.app) as client,
    ):
        mock_open_stream.side_effect = RuntimeError("invalid language code")
        with (
            pytest.raises(WebSocketDisconnect) as exc_info,
            client.websocket_connect("/ws/speak?room=1&lang=zz-ZZ") as ws,
        ):
            ws.receive_bytes()
    assert exc_info.value.code == 4400  # noqa: PLR2004


@patch("app.voices.boto3.client")
def test_ws_speak_conflict_per_room(mock_boto: MagicMock) -> None:
    """A second speaker in the same room is rejected with 4409."""
    mock_boto.return_value.describe_voices.return_value = {
        "Voices": [{"Id": "X", "LanguageCode": "en-US", "SupportedEngines": ["generative"]}]
    }

    async def slow_open(**_kwargs: object) -> AsyncMock:
        await asyncio.sleep(60)
        return AsyncMock()

    main = _make_app()
    with (
        patch.object(main, "open_stream", new_callable=AsyncMock) as mock_open_stream,
        TestClient(main.app) as client,
    ):
        mock_open_stream.side_effect = slow_open
        with client.websocket_connect("/ws/speak?room=1&lang=it-IT") as ws_a:
            with (
                pytest.raises(WebSocketDisconnect) as exc_info,
                client.websocket_connect("/ws/speak?room=1&lang=it-IT") as ws_b,
            ):
                ws_b.receive_bytes()
            assert exc_info.value.code == 4409  # noqa: PLR2004
            ws_a.close()
