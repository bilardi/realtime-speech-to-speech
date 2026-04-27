"""Polly voice discovery and filter for bidirectional streaming compatibility."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, cast

import boto3

if TYPE_CHECKING:
    from mypy_boto3_polly.client import PollyClient
    from mypy_boto3_polly.literals import LanguageCodeType
    from mypy_boto3_polly.type_defs import VoiceTypeDef


def _client() -> PollyClient:
    """Return a Polly boto3 client using AWS_REGION from env."""
    # boto3.client has ~400 overloads; only polly/translate are typed via stubs,
    # the rest return Unknown which pyright strict flags as partially unknown.
    # Our literal "polly" call matches the typed overload, so the returned client
    # is correctly typed even though the function symbol itself is partial.
    return boto3.client(  # pyright: ignore[reportUnknownMemberType]
        "polly",
        region_name=os.environ.get("AWS_REGION", "eu-west-1"),
    )


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


def voice_for(language_code: str) -> str | None:
    """Return the ID of the first generative voice for a language, or None.

    Args:
        language_code: BCP-47 code.

    Returns:
        Voice ID string, or None if no generative voice is available.
    """
    voices = list_voices(language_code)
    return voices[0].get("Id") if voices else None
