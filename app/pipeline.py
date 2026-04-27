"""Pipeline orchestrator: Transcribe finalized -> Translate -> Polly synthesis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.polly import PollyError, synthesize_stream
from app.translate import TranslateError, translate
from app.voices import voice_for

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@dataclass
class PipelineEvent:
    """Output event from the pipeline."""

    kind: str  # "text" or "audio"
    text: str | None = None
    audio: bytes | None = None
    error: str | None = None  # "translate_failed" | "polly_failed" | None
    lang: str | None = None


class Pipeline:
    """Orchestrate Translate plus Polly synthesis for a single language pair."""

    def __init__(self, *, source: str, target: str) -> None:
        """Initialize with source and target language codes.

        Args:
            source: Short BCP-47 code, e.g. ``"it"``.
            target: Full BCP-47 code for Polly voice lookup, e.g. ``"en-US"``.
        """
        self._source = source
        self._target = target
        self._target_short = target.split("-", 1)[0]
        self._voice_id: str | None = None

    def _get_voice(self) -> str | None:
        """Resolve and cache the voice id for the target language."""
        if self._voice_id is None:
            self._voice_id = voice_for(self._target)
        return self._voice_id

    async def process_finalized(self, text: str) -> AsyncIterator[PipelineEvent]:
        """Process a finalized transcript and emit text plus audio chunks.

        Args:
            text: Finalized transcript from Transcribe.

        Yields:
            ``PipelineEvent`` with ``kind="text"`` first (translated text or
            ``"..."`` on translate failure), then ``kind="audio"`` for each Polly
            audio chunk. On polly failure (no voice or mid-stream), the audio
            stream stops without further events.
        """
        try:
            translated = translate(text, source=self._source, target=self._target_short)
        except TranslateError:
            yield PipelineEvent(
                kind="text", text="...", error="translate_failed", lang=self._target
            )
            return

        voice = self._get_voice()
        if voice is None:
            yield PipelineEvent(
                kind="text", text=translated, error="polly_failed", lang=self._target
            )
            return

        yield PipelineEvent(kind="text", text=translated, lang=self._target)

        try:
            async for chunk in synthesize_stream(text=translated, voice_id=voice):
                yield PipelineEvent(kind="audio", audio=chunk, lang=self._target)
        except PollyError:
            # Already emitted text; downstream sees no further audio.
            return
