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


@patch("app.voices.boto3.client")
def test_supported_target_languages_returns_distinct_generative_codes(
    mock_client: MagicMock,
) -> None:
    """Return the deduplicated set of LanguageCode with at least one generative voice."""
    mock_client.return_value.describe_voices.return_value = {
        "Voices": [
            {"Id": "Matthew", "LanguageCode": "en-US", "SupportedEngines": ["generative"]},
            {"Id": "Ruth", "LanguageCode": "en-US", "SupportedEngines": ["generative"]},
            {"Id": "Lucia", "LanguageCode": "es-ES", "SupportedEngines": ["generative"]},
            {"Id": "Joanna", "LanguageCode": "en-US", "SupportedEngines": ["neural"]},
        ]
    }

    from app.voices import supported_target_languages  # noqa: PLC0415

    langs = supported_target_languages()

    assert langs == {"en-US", "es-ES"}


@patch("app.voices.boto3.client")
def test_supported_target_languages_paginates(mock_client: MagicMock) -> None:
    """supported_target_languages follows NextToken across pages."""
    mock_client.return_value.describe_voices.side_effect = [
        {
            "Voices": [
                {"Id": "Matthew", "LanguageCode": "en-US", "SupportedEngines": ["generative"]},
            ],
            "NextToken": "page2",
        },
        {
            "Voices": [
                {"Id": "Bianca", "LanguageCode": "it-IT", "SupportedEngines": ["generative"]},
            ],
        },
    ]

    from app.voices import supported_target_languages  # noqa: PLC0415

    langs = supported_target_languages()

    expected_pages = 2
    assert langs == {"en-US", "it-IT"}
    assert mock_client.return_value.describe_voices.call_count == expected_pages


@patch("app.voices.boto3.client")
def test_client_is_cached_across_calls(mock_client: MagicMock) -> None:
    """A second call to `list_voices` reuses the cached boto3 client (no re-instantiation)."""
    mock_client.return_value.describe_voices.return_value = {"Voices": []}

    list_voices(language_code="en-US")
    list_voices(language_code="it-IT")
    list_voices(language_code="es-ES")

    expected_client_inits = 1
    assert mock_client.call_count == expected_client_inits


@patch("app.voices.boto3.client")
def test_voice_for_caches_result_per_language_code(mock_client: MagicMock) -> None:
    """`voice_for` is `lru_cache`d: the second call with the same lang skips DescribeVoices."""
    mock_client.return_value.describe_voices.return_value = {
        "Voices": [
            {"Id": "Matthew", "LanguageCode": "en-US", "SupportedEngines": ["generative"]},
        ],
    }

    voice_for("en-US")
    voice_for("en-US")
    voice_for("en-US")

    expected_describe_calls = 1
    assert mock_client.return_value.describe_voices.call_count == expected_describe_calls


@patch("app.voices.boto3.client")
def test_voice_for_calls_aws_once_per_distinct_language_code(mock_client: MagicMock) -> None:
    """Distinct language codes each trigger a DescribeVoices call; same lang reuses cache."""
    mock_client.return_value.describe_voices.return_value = {
        "Voices": [
            {"Id": "Matthew", "LanguageCode": "en-US", "SupportedEngines": ["generative"]},
            {"Id": "Bianca", "LanguageCode": "it-IT", "SupportedEngines": ["generative"]},
        ],
    }

    voice_for("en-US")
    voice_for("it-IT")
    voice_for("en-US")  # cached
    voice_for("it-IT")  # cached

    expected_describe_calls = 2
    assert mock_client.return_value.describe_voices.call_count == expected_describe_calls
