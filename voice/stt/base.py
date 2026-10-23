"""Abstract Base Class for Speech-to-Text (STT) providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from voice.types import AudioData, TranscriptionResult


class STTProvider(ABC):
    """Abstract interface that every speech-to-text provider must implement.

    Keeps the voice layer completely vendor-agnostic (local Whisper, Whisper HTTP,
    Ollama voice, cloud STT, or offline dev mock).
    """

    name: str = "base"

    @abstractmethod
    async def transcribe(
        self,
        audio: AudioData,
        language: str | None = None,
        **kwargs: Any,
    ) -> TranscriptionResult:
        """Convert speech audio data into plain text.

        Parameters:
            audio: Captured audio samples and format metadata.
            language: Optional language hint (e.g. 'en').
            **kwargs: Extra vendor-specific parameters.

        Returns:
            A :class:`~voice.types.TranscriptionResult` containing the transcribed text.

        Raises:
            TranscriptionError: If speech recognition fails.
        """
        ...

    async def is_ready(self) -> bool:
        """Check if provider backend is initialized and reachable."""
        return True

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r}>"
