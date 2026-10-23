"""Deterministic developer and testing Speech-to-Text provider."""

from __future__ import annotations

import time
from collections import deque
from typing import Any

from voice.exceptions import EmptyAudioError, TranscriptionError
from voice.stt.base import STTProvider
from voice.types import AudioData, TranscriptionResult


class DevSTTProvider(STTProvider):
    """Zero-dependency deterministic STT provider for development, tests, and CI/CD.

    Parameters:
        default_text: Default transcription returned when no queued text is set.
    """

    name: str = "dev"

    def __init__(self, default_text: str = "show system status") -> None:
        self.default_text = default_text
        self._queue: deque[str] = deque()
        self._recorded_calls: list[AudioData] = []
        self._should_fail_with: Exception | None = None

    def queue_transcription(self, text: str) -> None:
        """Enqueue a specific transcription string for the next call."""
        self._queue.append(text)

    def queue_transcriptions(self, texts: list[str]) -> None:
        """Enqueue multiple transcription strings."""
        self._queue.extend(texts)

    def set_error_for_next_call(self, exception: Exception) -> None:
        """Simulate an error on the subsequent call for testing error handling."""
        self._should_fail_with = exception

    def clear(self) -> None:
        """Reset internal queue and history."""
        self._queue.clear()
        self._recorded_calls.clear()
        self._should_fail_with = None

    @property
    def call_count(self) -> int:
        """Return total number of transcribe invocations."""
        return len(self._recorded_calls)

    @property
    def last_audio(self) -> AudioData | None:
        """Return the last AudioData object received."""
        return self._recorded_calls[-1] if self._recorded_calls else None

    async def transcribe(
        self,
        audio: AudioData,
        language: str | None = None,
        **kwargs: Any,
    ) -> TranscriptionResult:
        """Simulate speech recognition."""
        if self._should_fail_with:
            err = self._should_fail_with
            self._should_fail_with = None
            if isinstance(err, Exception):
                raise err
            raise TranscriptionError(str(err), provider=self.name)

        if audio.is_empty:
            raise EmptyAudioError("Cannot transcribe empty audio buffer.")

        self._recorded_calls.append(audio)

        # Retrieve text from queue or default
        if self._queue:
            text = self._queue.popleft()
        else:
            text = self.default_text

        return TranscriptionResult(
            text=text,
            confidence=0.99,
            language=language or "en",
            duration_seconds=audio.duration_seconds,
            provider=self.name,
            model="dev-stt-v1",
            raw_response={"mock": True, "samples": len(audio.raw_bytes)},
        )
