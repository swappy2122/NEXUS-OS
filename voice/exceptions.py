"""Voice input module exceptions for NEXUS OS."""

from __future__ import annotations

from typing import Any


class VoiceError(Exception):
    """Base exception for all voice and audio-related errors."""

    def __init__(self, message: str, code: str = "VOICE_ERROR", **kwargs: Any) -> None:
        self.message = message
        self.code = code
        self.details = kwargs
        super().__init__(f"[{self.code}] {self.message}")

    def to_dict(self) -> dict[str, Any]:
        """Convert error to dictionary for logging and API serialization."""
        return {
            "error_type": self.__class__.__name__,
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


class VoiceDisabledError(VoiceError):
    """Raised when voice input is triggered but the module is disabled in configuration."""

    def __init__(self, message: str = "Voice input module is disabled in configuration.") -> None:
        super().__init__(message=message, code="VOICE_DISABLED")


class AudioCaptureError(VoiceError):
    """Raised when an error occurs during audio recording or hardware capture."""

    def __init__(self, message: str, code: str = "AUDIO_CAPTURE_ERROR", **kwargs: Any) -> None:
        super().__init__(message=message, code=code, **kwargs)


class DeviceNotFoundError(AudioCaptureError):
    """Raised when no audio capture device / microphone is detected or accessible."""

    def __init__(self, message: str = "No audio recording device detected or accessible.") -> None:
        super().__init__(message=message, code="DEVICE_NOT_FOUND")


class RecordingTimeoutError(AudioCaptureError):
    """Raised when audio recording exceeds the configured timeout."""

    def __init__(self, timeout: float) -> None:
        super().__init__(
            message=f"Audio recording timed out after {timeout:.1f} seconds.",
            code="RECORDING_TIMEOUT",
            timeout=timeout,
        )


class EmptyAudioError(AudioCaptureError):
    """Raised when recorded audio is empty or contains zero valid samples."""

    def __init__(self, message: str = "Captured audio buffer is empty or silent.") -> None:
        super().__init__(message=message, code="EMPTY_AUDIO")


class AudioFormatError(VoiceError):
    """Raised when audio data format or encoding is invalid or unsupported."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message=message, code="AUDIO_FORMAT_ERROR", **kwargs)


class TranscriptionError(VoiceError):
    """Raised when speech-to-text transcription fails."""

    def __init__(self, message: str, provider: str = "", code: str = "TRANSCRIPTION_ERROR", **kwargs: Any) -> None:
        super().__init__(
            message=f"Speech-to-text transcription failed: {message}",
            code=code,
            provider=provider,
            **kwargs,
        )


class STTProviderNotFoundError(VoiceError):
    """Raised when the requested STT provider is not registered or supported."""

    def __init__(self, provider_name: str) -> None:
        super().__init__(
            message=f"Speech-to-text provider '{provider_name}' not found.",
            code="STT_PROVIDER_NOT_FOUND",
            provider=provider_name,
        )
