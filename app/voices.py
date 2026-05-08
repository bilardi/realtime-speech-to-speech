"""Polly voice discovery and filter for bidirectional streaming compatibility."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import TYPE_CHECKING, cast

import boto3

if TYPE_CHECKING:
    from mypy_boto3_polly.client import PollyClient
    from mypy_boto3_polly.literals import LanguageCodeType
    from mypy_boto3_polly.type_defs import VoiceTypeDef


_voices_client: PollyClient | None = None


def _client() -> PollyClient:
    """Return the module-level Polly boto3 client, creating it on first call.

    Cached for the process lifetime so subsequent ``describe_voices`` calls
    reuse the same TCP/TLS pool maintained by botocore, avoiding the per-call
    cold start that adds 100 to 300 ms to every voice lookup when the client
    is fresh.
    """
    global _voices_client  # noqa: PLW0603
    if _voices_client is None:
        # boto3.client has ~400 overloads; only polly/translate are typed via stubs,
        # the rest return Unknown which pyright strict flags as partially unknown.
        # Our literal "polly" call matches the typed overload, so the returned client
        # is correctly typed even though the function symbol itself is partial.
        _voices_client = boto3.client(  # pyright: ignore[reportUnknownMemberType]
            "polly",
            region_name=os.environ.get("AWS_REGION", "eu-west-1"),
        )
    return _voices_client


def list_voices(language_code: str) -> list[VoiceTypeDef]:
    """Return Polly voices for a language that support the generative engine.

    Args:
        language_code: BCP-47 code, e.g. "en-US" or "it-IT". Runtime config holds
            arbitrary strings; we cast to the typed `Literal` at the AWS boundary.
            Invalid codes are rejected by AWS server-side.

    Returns:
        List of voice descriptors as returned by DescribeVoices, filtered by
        ``LanguageCode`` and ``SupportedEngines`` containing ``generative``.
    """
    response = _client().describe_voices(LanguageCode=cast("LanguageCodeType", language_code))
    return [
        v
        for v in response.get("Voices", [])
        if "generative" in v.get("SupportedEngines", []) and v.get("LanguageCode") == language_code
    ]


@lru_cache(maxsize=64)
def voice_for(language_code: str) -> str | None:
    """Return the ID of the first generative voice for a language, or None.

    The result is cached for the process lifetime: the voice list returned
    by AWS for a given language code does not change at runtime. Restart
    the server to pick up new voices. Cache size 64 covers the full set of
    Polly generative-supported languages with margin.

    Args:
        language_code: BCP-47 code.

    Returns:
        Voice ID string, or None if no generative voice is available.
    """
    voices = list_voices(language_code)
    return voices[0].get("Id") if voices else None


def supported_target_languages() -> set[str]:
    """Return the set of BCP-47 codes that have at least one generative voice.

    Calls Polly DescribeVoices paginated, filters voices supporting the
    `generative` engine, and returns the distinct LanguageCode set. Used at
    server startup to populate the runtime allowlist for `/ws/listen`.

    Returns:
        Set of distinct BCP-47 language codes.
    """
    client = _client()
    langs: set[str] = set()
    next_token: str | None = None
    while True:
        kwargs: dict[str, str] = {}
        if next_token is not None:
            kwargs["NextToken"] = next_token
        response = client.describe_voices(**kwargs)  # pyright: ignore[reportArgumentType]
        for v in response.get("Voices", []):
            if "generative" in v.get("SupportedEngines", []):
                code = v.get("LanguageCode")
                if code:
                    langs.add(code)
        next_token = response.get("NextToken")
        if not next_token:
            break
    return langs
