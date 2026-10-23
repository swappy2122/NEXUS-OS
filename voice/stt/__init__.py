"""Speech-to-Text provider abstraction package for NEXUS OS."""

from voice.stt.base import STTProvider
from voice.stt.dev_provider import DevSTTProvider
from voice.stt.http_provider import HTTPSTTProvider
from voice.stt.registry import STTRegistry, default_stt_registry

__all__ = [
    "STTProvider",
    "DevSTTProvider",
    "HTTPSTTProvider",
    "STTRegistry",
    "default_stt_registry",
]
