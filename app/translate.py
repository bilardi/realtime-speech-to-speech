"""Amazon Translate synchronous wrapper."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import boto3
from loguru import logger

if TYPE_CHECKING:
    from mypy_boto3_translate.client import TranslateClient


class TranslateError(RuntimeError):
    """Raised when the Amazon Translate call fails."""


_translate_client: TranslateClient | None = None


def _client() -> TranslateClient:
    """Return the module-level Translate boto3 client, creating it on first call.

    Cached for the process lifetime so subsequent ``translate()`` calls reuse
    the same TCP/TLS pool maintained by botocore, avoiding the per-call cold
    start (model loading, region routing, TLS handshake) that adds 100 to
    300 ms to every translate operation when the client is fresh.
    """
    global _translate_client  # noqa: PLW0603
    if _translate_client is None:
        # boto3.client has ~400 overloads; only polly/translate are typed via stubs,
        # the rest return Unknown which pyright strict flags as partially unknown.
        # Our literal "translate" call matches the typed overload, so the returned
        # client is correctly typed even though the function symbol itself is partial.
        _translate_client = boto3.client(  # pyright: ignore[reportUnknownMemberType]
            "translate",
            region_name=os.environ.get("AWS_REGION", "eu-west-1"),
        )
    return _translate_client


def translate(text: str, source: str, target: str) -> str:
    """Translate ``text`` from ``source`` to ``target`` using Amazon Translate.

    The Translate boto3 stubs type ``SourceLanguageCode`` and
    ``TargetLanguageCode`` as plain ``str`` (no Literal), so no cast is needed
    at the AWS boundary. Invalid codes are rejected by AWS server-side.

    Args:
        text: Source text to translate.
        source: Source language code (e.g. ``"it"``).
        target: Target language code (e.g. ``"en"``).

    Returns:
        Translated text from the Translate response.

    Raises:
        TranslateError: If the AWS call fails for any reason.
    """
    try:
        response = _client().translate_text(
            Text=text,
            SourceLanguageCode=source,
            TargetLanguageCode=target,
        )
    except Exception as exc:
        logger.warning("Amazon Translate call failed: {}", exc)
        raise TranslateError(str(exc)) from exc
    return response["TranslatedText"]
