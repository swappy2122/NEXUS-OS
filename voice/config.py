"""Configuration settings for the NEXUS Voice Input subsystem."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from voice.types import ActivationMode


@dataclass
class VoiceConfig:
    """Configuration holding voice input, microphone capture, and STT settings.

    All settings can be configured via ``nexus.toml`` under ``[voice]``
    or overridden by ``NEXUS_VOICE_*`` environment variables.
    """

    enabled: bool = field(
        default_factory=lambda: os.getenv("NEXUS_VOICE_ENABLED", "false").lower() == "true"
    )
    """Whether voice input is enabled system-wide."""

    provider: str = field(
        default_factory=lambda: os.getenv("NEXUS_VOICE_PROVIDER", "dev")
    )
    """Speech-to-text provider name (e.g. 'dev', 'http', 'whisper')."""

    activation_mode: ActivationMode = field(
        default_factory=lambda: ActivationMode(
            os.getenv("NEXUS_VOICE_ACTIVATION_MODE", "manual").lower()
        )
    )
    """Activation trigger mode ('manual', 'push_to_talk', 'always_listening')."""

    sample_rate: int = field(
        default_factory=lambda: int(os.getenv("NEXUS_VOICE_SAMPLE_RATE", "16000"))
    )
    """Audio sampling rate in Hertz (default: 16000)."""

    channels: int = field(
        default_factory=lambda: int(os.getenv("NEXUS_VOICE_CHANNELS", "1"))
    )
    """Number of audio channels (1 = mono, 2 = stereo)."""

    sample_width: int = field(
        default_factory=lambda: int(os.getenv("NEXUS_VOICE_SAMPLE_WIDTH", "2"))
    )
    """Bytes per sample (2 = 16-bit PCM)."""

    max_record_seconds: float = field(
        default_factory=lambda: float(os.getenv("NEXUS_VOICE_MAX_RECORD_SECONDS", "10.0"))
    )
    """Default maximum recording length in seconds."""

    stt_endpoint: str = field(
        default_factory=lambda: os.getenv(
            "NEXUS_VOICE_STT_ENDPOINT", "http://localhost:8000/v1/audio/transcriptions"
        )
    )
    """HTTP endpoint URL for remote or local speech-to-text service."""

    stt_model: str = field(
        default_factory=lambda: os.getenv("NEXUS_VOICE_STT_MODEL", "whisper-1")
    )
    """Model identifier to request from the STT provider."""

    api_key: str | None = field(
        default_factory=lambda: os.getenv("NEXUS_VOICE_API_KEY")
    )
    """Optional API key for authenticated STT services."""

    language: str | None = field(
        default_factory=lambda: os.getenv("NEXUS_VOICE_LANGUAGE", "en")
    )
    """Target language code for transcription (ISO 639-1, e.g. 'en')."""

    capture_device: str = field(
        default_factory=lambda: os.getenv("NEXUS_VOICE_CAPTURE_DEVICE", "default")
    )
    """Audio input device identifier or hardware name."""

    capture_backend: str = field(
        default_factory=lambda: os.getenv("NEXUS_VOICE_CAPTURE_BACKEND", "auto")
    )
    """Recording backend ('auto', 'arecord', 'pw-record', 'mock')."""

    auto_dispatch: bool = field(
        default_factory=lambda: os.getenv("NEXUS_VOICE_AUTO_DISPATCH", "true").lower() == "true"
    )
    """Whether to automatically route the transcribed text to the Supervisor."""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VoiceConfig:
        """Construct a VoiceConfig from dictionary, giving precedence to env vars."""
        raw_mode = os.getenv(
            "NEXUS_VOICE_ACTIVATION_MODE",
            data.get("activation_mode", "manual"),
        ).lower()
        try:
            mode = ActivationMode(raw_mode)
        except ValueError:
            mode = ActivationMode.MANUAL

        return cls(
            enabled=os.getenv(
                "NEXUS_VOICE_ENABLED", str(data.get("enabled", False))
            ).lower() == "true",
            provider=os.getenv(
                "NEXUS_VOICE_PROVIDER", data.get("provider", "dev")
            ),
            activation_mode=mode,
            sample_rate=int(
                os.getenv("NEXUS_VOICE_SAMPLE_RATE", str(data.get("sample_rate", 16000)))
            ),
            channels=int(
                os.getenv("NEXUS_VOICE_CHANNELS", str(data.get("channels", 1)))
            ),
            sample_width=int(
                os.getenv("NEXUS_VOICE_SAMPLE_WIDTH", str(data.get("sample_width", 2)))
            ),
            max_record_seconds=float(
                os.getenv(
                    "NEXUS_VOICE_MAX_RECORD_SECONDS",
                    str(data.get("max_record_seconds", 10.0)),
                )
            ),
            stt_endpoint=os.getenv(
                "NEXUS_VOICE_STT_ENDPOINT",
                data.get("stt_endpoint", "http://localhost:8000/v1/audio/transcriptions"),
            ),
            stt_model=os.getenv(
                "NEXUS_VOICE_STT_MODEL", data.get("stt_model", "whisper-1")
            ),
            api_key=os.getenv("NEXUS_VOICE_API_KEY", data.get("api_key")),
            language=os.getenv("NEXUS_VOICE_LANGUAGE", data.get("language", "en")),
            capture_device=os.getenv(
                "NEXUS_VOICE_CAPTURE_DEVICE", data.get("capture_device", "default")
            ),
            capture_backend=os.getenv(
                "NEXUS_VOICE_CAPTURE_BACKEND", data.get("capture_backend", "auto")
            ),
            auto_dispatch=os.getenv(
                "NEXUS_VOICE_AUTO_DISPATCH", str(data.get("auto_dispatch", True))
            ).lower() == "true",
        )
