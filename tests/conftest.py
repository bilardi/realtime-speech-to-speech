"""Pytest fixtures shared across test modules."""

from collections.abc import Iterator

import pytest

import app.translate
import app.voices


@pytest.fixture(autouse=True)
def _reset_aws_client_caches() -> Iterator[None]:
    """Reset module-level boto3 client caches and the `voice_for` lru_cache.

    The translate and voices modules cache their boto3 clients at module
    level for the process lifetime (production optimisation). Tests patch
    `boto3.client` per-test expecting a fresh client, but without this
    reset the client created in test 1 (under the patch) lingers in the
    cache and is returned to test 2 instead of test 2's fresh patch.

    `voice_for.cache_clear()` does the same job for the LRU cache on the
    voice resolution result.
    """
    app.translate._translate_client = None  # noqa: SLF001
    app.voices._voices_client = None  # noqa: SLF001
    app.voices.voice_for.cache_clear()
    yield
    app.translate._translate_client = None  # noqa: SLF001
    app.voices._voices_client = None  # noqa: SLF001
    app.voices.voice_for.cache_clear()
