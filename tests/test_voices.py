"""Test voice discovery."""

from unittest.mock import MagicMock, patch

from app.voices import list_voices, voice_for


@patch("app.voices.boto3.client")
def test_list_voices_filters_generative(mock_client: MagicMock) -> None:
    """list_voices returns only voices supporting generative engine."""
    mock_client.return_value.describe_voices.return_value = {
        "Voices": [
            {
                "Id": "Matthew",
                "LanguageCode": "en-US",
                "SupportedEngines": ["generative", "neural"],
            },
            {"Id": "Joanna", "LanguageCode": "en-US", "SupportedEngines": ["neural", "standard"]},
            {"Id": "Bianca", "LanguageCode": "it-IT", "SupportedEngines": ["generative"]},
        ]
    }

    voices = list_voices(language_code="en-US")

    assert len(voices) == 1
    assert voices[0]["Id"] == "Matthew"


@patch("app.voices.boto3.client")
def test_voice_for_returns_first_generative(mock_client: MagicMock) -> None:
    """voice_for returns the first generative voice for the language."""
    mock_client.return_value.describe_voices.return_value = {
        "Voices": [
            {"Id": "Matthew", "LanguageCode": "en-US", "SupportedEngines": ["generative"]},
            {"Id": "Ruth", "LanguageCode": "en-US", "SupportedEngines": ["generative"]},
        ]
    }

    voice_id = voice_for("en-US")

    assert voice_id == "Matthew"


@patch("app.voices.boto3.client")
def test_voice_for_returns_none_when_no_generative(mock_client: MagicMock) -> None:
    """voice_for returns None when no generative voice exists for the language."""
    mock_client.return_value.describe_voices.return_value = {
        "Voices": [
            {"Id": "Joanna", "LanguageCode": "en-US", "SupportedEngines": ["neural"]},
        ]
    }

    assert voice_for("en-US") is None
