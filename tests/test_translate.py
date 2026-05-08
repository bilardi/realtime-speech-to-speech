"""Test the Translate wrapper."""

from unittest.mock import MagicMock, patch

import pytest

from app.translate import TranslateError, translate


@patch("app.translate.boto3.client")
def test_translate_returns_translated_text(mock_client: MagicMock) -> None:
    """`translate` returns the translated text from the Translate response."""
    mock_client.return_value.translate_text.return_value = {"TranslatedText": "hello world"}

    result = translate("ciao mondo", source="it", target="en")

    assert result == "hello world"
    mock_client.return_value.translate_text.assert_called_once_with(
        Text="ciao mondo",
        SourceLanguageCode="it",
        TargetLanguageCode="en",
    )


@patch("app.translate.boto3.client")
def test_translate_raises_on_aws_error(mock_client: MagicMock) -> None:
    """`translate` raises TranslateError when the AWS call fails."""
    mock_client.return_value.translate_text.side_effect = RuntimeError("aws boom")

    with pytest.raises(TranslateError):
        translate("ciao", source="it", target="en")


@patch("app.translate.boto3.client")
def test_translate_caches_boto3_client_across_calls(mock_client: MagicMock) -> None:
    """A second call to `translate` reuses the cached boto3 client (no re-instantiation)."""
    mock_client.return_value.translate_text.return_value = {"TranslatedText": "x"}

    translate("a", source="it", target="en")
    translate("b", source="it", target="en")
    translate("c", source="it", target="en")

    expected_client_inits = 1
    assert mock_client.call_count == expected_client_inits
