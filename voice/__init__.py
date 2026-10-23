"""NEXUS OS Voice Input Subsystem.

Provides microphone recording, speech-to-text provider abstraction,
error handling, and plain-text dispatch to the Supervisor.
"""

from voice.capture import (
    AudioCapture,
    BufferAudioCapture,
    LinuxAudioCapture,
    MockAudioCapture,
    create_audio_capture,
)
from voice.config import VoiceConfig
from voice.exceptions import (
    AudioCaptureError,
    AudioFormatError,
    DeviceNotFoundError,
    EmptyAudioError,
    RecordingTimeoutError,
    STTProviderNotFoundError,
    TranscriptionError,
    VoiceDisabledError,
    VoiceError,
)
from voice.service import VoiceInputService
from voice.stt import (
    DevSTTProvider,
    HTTPSTTProvider,
    STTProvider,
    STTRegistry,
    default_stt_registry,
)
from voice.types import (
    ActivationMode,
    AudioData,
    TranscriptionResult,
    VoiceCommandResult,
)

__all__ = [
    # Types & Enums
    "AudioData",
    "TranscriptionResult",
    "VoiceCommandResult",
    "ActivationMode",
    # Configuration
    "VoiceConfig",
    # Capture & Microphone
    "AudioCapture",
    "LinuxAudioCapture",
    "BufferAudioCapture",
    "MockAudioCapture",
    "create_audio_capture",
    # STT Provider Abstraction
    "STTProvider",
    "DevSTTProvider",
    "HTTPSTTProvider",
    "STTRegistry",
    "default_stt_registry",
    # Voice Service
    "VoiceInputService",
    # Exceptions
    "VoiceError",
    "VoiceDisabledError",
    "AudioCaptureError",
    "DeviceNotFoundError",
    "RecordingTimeoutError",
    "EmptyAudioError",
    "AudioFormatError",
    "TranscriptionError",
    "STTProviderNotFoundError",
]
