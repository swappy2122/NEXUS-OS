"""Data models and value types for the NEXUS Voice Input subsystem."""

from __future__ import annotations

import io
import wave
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from voice.exceptions import AudioFormatError


class ActivationMode(str, Enum):
    """Voice module activation behavior mode."""

    MANUAL = "manual"
    """Activated explicitly on demand by user / application command."""

    PUSH_TO_TALK = "push_to_talk"
    """Activated while holding a trigger key or button."""

    ALWAYS_LISTENING = "always_listening"
    """Continuous listening stream."""


@dataclass
class AudioData:
    """Encapsulates captured audio samples and format parameters.

    Default format is 16kHz, 16-bit mono PCM (standard for speech recognition).
    """

    raw_bytes: bytes
    sample_rate: int = 16000
    channels: int = 1
    sample_width: int = 2  # 2 bytes = 16-bit PCM

    @property
    def duration_seconds(self) -> float:
        """Calculate duration of audio in seconds."""
        bytes_per_second = self.sample_rate * self.channels * self.sample_width
        if bytes_per_second <= 0:
            return 0.0
        return len(self.raw_bytes) / bytes_per_second

    @property
    def is_empty(self) -> bool:
        """Check if audio data is empty."""
        return len(self.raw_bytes) == 0

    def to_wav_bytes(self) -> bytes:
        """Package the raw PCM samples into standard RIFF WAV format bytes."""
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(self.channels)
            wav_file.setsampwidth(self.sample_width)
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(self.raw_bytes)
        return buffer.getvalue()

    @classmethod
    def from_wav_bytes(cls, wav_bytes: bytes) -> AudioData:
        """Parse standard WAV format bytes into an AudioData instance."""
        try:
            buffer = io.BytesIO(wav_bytes)
            with wave.open(buffer, "rb") as wav_file:
                channels = wav_file.getnchannels()
                sample_width = wav_file.getsampwidth()
                sample_rate = wav_file.getframerate()
                num_frames = wav_file.getnframes()
                raw_bytes = wav_file.readframes(num_frames)

            return cls(
                raw_bytes=raw_bytes,
                sample_rate=sample_rate,
                channels=channels,
                sample_width=sample_width,
            )
        except Exception as exc:
            raise AudioFormatError(f"Failed to parse WAV audio bytes: {exc}") from exc

    def __repr__(self) -> str:
        return (
            f"<AudioData bytes={len(self.raw_bytes)} "
            f"duration={self.duration_seconds:.2f}s "
            f"rate={self.sample_rate}Hz channels={self.channels}>"
        )


@dataclass
class TranscriptionResult:
    """The result returned by a Speech-to-Text provider."""

    text: str
    confidence: float | None = None
    language: str | None = None
    duration_seconds: float = 0.0
    provider: str = ""
    model: str = ""
    raw_response: dict[str, Any] = field(default_factory=dict)

    @property
    def plain_text(self) -> str:
        """Return clean plain text string."""
        return self.text.strip()


@dataclass
class VoiceCommandResult:
    """Encapsulates the end-to-end outcome of a voice input operation."""

    success: bool
    text: str = ""
    transcription: TranscriptionResult | None = None
    audio: AudioData | None = None
    supervisor_result: Any | None = None
    error: str | None = None
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary representation."""
        return {
            "success": self.success,
            "text": self.text,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "transcription": {
                "text": self.transcription.text,
                "confidence": self.transcription.confidence,
                "language": self.transcription.language,
                "provider": self.transcription.provider,
                "model": self.transcription.model,
            }
            if self.transcription
            else None,
            "audio_duration_s": self.audio.duration_seconds if self.audio else 0.0,
        }
