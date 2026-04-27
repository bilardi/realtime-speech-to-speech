"""Test the FastAPI app routes."""

from http import HTTPStatus

from fastapi.testclient import TestClient

from app.main import app


def test_get_root_returns_index_html() -> None:
    """`GET /` serves index.html with status 200."""
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == HTTPStatus.OK
    assert "html" in response.text.lower()
