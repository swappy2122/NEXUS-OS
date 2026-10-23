"""Central Voice Input service for NEXUS OS.

Orchestrates microphone recording, speech-to-text transcription, and
returns plain text to the existing NEXUS Supervisor.

Strictly handles audio capture and transcription — contains NO AI reasoning.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from voice.capture import AudioCapture, create_audio_capture
from voice.config import VoiceConfig
from voice.exceptions import (
    AudioCaptureError,
    TranscriptionError,
    VoiceDisabledError,
    VoiceError,
)
from voice.stt.base import STTProvider
from voice.stt.registry import default_stt_registry
from voice.types import AudioData, TranscriptionResult, VoiceCommandResult

if TYPE_CHECKING:
    from agents.supervisor import SupervisorAgent
    from core.event_bus import EventBus
    from core.nexus import NexusCore

logger = logging.getLogger("nexus.voice.service")


class VoiceInputService:
    """Coordinates microphone capture and speech-to-text processing for NEXUS OS.

    Parameters:
        config: Voice configuration object.
        audio_capture: AudioCapture instance for microphone recording (optional).
        stt_provider: STTProvider instance for transcription (optional).
        supervisor: Existing SupervisorAgent instance to receive plain text commands (optional).
        core: NexusCore kernel instance for end-to-end command execution (optional).
        event_bus: Optional event bus for publishing voice activity events.
    """

    def __init__(
        self,
        config: VoiceConfig | None = None,
        audio_capture: AudioCapture | None = None,
        stt_provider: STTProvider | None = None,
        supervisor: SupervisorAgent | None = None,
        core: NexusCore | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.config = config or VoiceConfig()
        self._capture = audio_capture or create_audio_capture(
            backend=self.config.capture_backend,
            device=self.config.capture_device,
        )
        self._stt = stt_provider or default_stt_registry.create_provider(self.config)
        self._supervisor = supervisor
        self._core = core
        self._event_bus = event_bus

    # ── Activation & Configuration ───────────────────────────────────────

    @property
    def is_enabled(self) -> bool:
        """Check whether voice input is currently enabled."""
        return self.config.enabled

    def enable(self) -> None:
        """Enable voice input at runtime."""
        self.config.enabled = True
        logger.info("Voice input service enabled")

    def disable(self) -> None:
        """Disable voice input at runtime."""
        self.config.enabled = False
        logger.info("Voice input service disabled")

    def set_supervisor(self, supervisor: SupervisorAgent) -> None:
        """Connect or swap the SupervisorAgent."""
        self._supervisor = supervisor

    def set_core(self, core: NexusCore) -> None:
        """Connect or swap the NexusCore kernel."""
        self._core = core

    def set_audio_capture(self, capture: AudioCapture) -> None:
        """Inject a custom audio capture backend (e.g. for testing or VR audio streams)."""
        self._capture = capture

    def set_stt_provider(self, provider: STTProvider) -> None:
        """Inject a custom Speech-to-Text provider."""
        self._stt = provider

    def _ensure_active(self) -> None:
        """Verify the service is enabled before performing voice capture."""
        if not self.config.enabled:
            raise VoiceDisabledError()

    # ── Audio Recording ──────────────────────────────────────────────────

    async def record_audio(
        self,
        duration_seconds: float | None = None,
    ) -> AudioData:
        """Capture audio from the microphone.

        Parameters:
            duration_seconds: Maximum length to record (defaults to config).

        Raises:
            VoiceDisabledError: If voice module is disabled.
            AudioCaptureError: If recording fails.
        """
        self._ensure_active()

        duration = duration_seconds or self.config.max_record_seconds

        logger.info("Listening for audio input (duration=%.1fs)...", duration)
        if self._event_bus:
            await self._event_bus.publish(
                "voice.listening",
                {"duration_seconds": duration, "mode": self.config.activation_mode.value},
            )

        audio = await self._capture.record(
            duration_seconds=duration,
            sample_rate=self.config.sample_rate,
            channels=self.config.channels,
            sample_width=self.config.sample_width,
        )

        logger.debug(
            "Captured %d bytes of audio (%.2fs)",
            len(audio.raw_bytes),
            audio.duration_seconds,
        )

        if self._event_bus:
            await self._event_bus.publish(
                "voice.captured",
                {
                    "bytes": len(audio.raw_bytes),
                    "duration_seconds": audio.duration_seconds,
                },
            )

        return audio

    # ── Speech-to-Text Transcription ─────────────────────────────────────

    async def transcribe(
        self,
        audio: AudioData,
        language: str | None = None,
    ) -> TranscriptionResult:
        """Transcribe speech audio data into a TranscriptionResult.

        Raises:
            VoiceDisabledError: If voice module is disabled.
            TranscriptionError: If STT fails.
        """
        self._ensure_active()

        lang = language or self.config.language
        result = await self._stt.transcribe(audio, language=lang)

        logger.info(
            "Transcribed speech -> '%s' (provider=%s)",
            result.plain_text,
            result.provider,
        )

        if self._event_bus:
            await self._event_bus.publish(
                "voice.transcribed",
                {
                    "text": result.plain_text,
                    "confidence": result.confidence,
                    "provider": result.provider,
                },
            )

        return result

    async def transcribe_file(
        self,
        wav_file: str | Path,
        language: str | None = None,
    ) -> str:
        """Load a WAV audio file and return its plain text transcription."""
        self._ensure_active()
        p = Path(wav_file)
        audio = AudioData.from_wav_bytes(p.read_bytes())
        res = await self.transcribe(audio, language=language)
        return res.plain_text

    async def listen_and_transcribe(
        self,
        duration_seconds: float | None = None,
        language: str | None = None,
    ) -> str:
        """Record from microphone and return plain text transcription.

        Returns clean plain text string suitable for the Supervisor.
        """
        audio = await self.record_audio(duration_seconds=duration_seconds)
        res = await self.transcribe(audio, language=language)
        return res.plain_text

    # ── Supervisor Handoff Pipeline ──────────────────────────────────────

    async def process_voice_command(
        self,
        duration_seconds: float | None = None,
        session_id: str = "voice_session",
    ) -> VoiceCommandResult:
        """Execute the full voice pipeline:

            Microphone Audio → STT → Plain Text → Supervisor

        Returns a :class:`~voice.types.VoiceCommandResult` with the plain text
        command and the Supervisor's execution result.
        """
        start = time.monotonic()

        # Check configuration
        if not self.config.enabled:
            return VoiceCommandResult(
                success=False,
                error="[VOICE_DISABLED] Voice input module is disabled in configuration.",
                duration_ms=0.0,
            )

        try:
            # 1. Capture microphone audio
            audio = await self.record_audio(duration_seconds=duration_seconds)

            # 2. Transcribe audio to plain text
            transcription = await self.transcribe(audio)
            plain_text = transcription.plain_text

            if not plain_text:
                return VoiceCommandResult(
                    success=False,
                    text="",
                    audio=audio,
                    transcription=transcription,
                    error="[EMPTY_TRANSCRIPTION] No speech detected in recorded audio.",
                    duration_ms=(time.monotonic() - start) * 1000,
                )

            # 3. Return plain text to Supervisor (or NexusCore)
            supervisor_result = None
            if self.config.auto_dispatch:
                if self._core is not None:
                    # Execute via central NexusCore kernel
                    logger.debug("Dispatching voice plain text to NexusCore: '%s'", plain_text)
                    supervisor_result = await self._core.execute(
                        intent=plain_text,
                        session_id=session_id,
                    )
                elif self._supervisor is not None:
                    # Execute directly on SupervisorAgent
                    from agents.types import AgentContext
                    logger.debug("Dispatching voice plain text to Supervisor: '%s'", plain_text)
                    ctx = AgentContext(
                        session_id=session_id,
                        intent=plain_text,
                    )
                    supervisor_result = await self._supervisor.run(ctx)

            duration_ms = (time.monotonic() - start) * 1000
            return VoiceCommandResult(
                success=True,
                text=plain_text,
                audio=audio,
                transcription=transcription,
                supervisor_result=supervisor_result,
                duration_ms=duration_ms,
            )

        except VoiceError as exc:
            duration_ms = (time.monotonic() - start) * 1000
            logger.warning("Voice pipeline failed: %s", exc)
            if self._event_bus:
                await self._event_bus.publish(
                    "voice.error",
                    {"error": str(exc), "code": exc.code},
                )
            return VoiceCommandResult(
                success=False,
                error=str(exc),
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = (time.monotonic() - start) * 1000
            logger.exception("Unexpected error in voice pipeline: %s", exc)
            return VoiceCommandResult(
                success=False,
                error=f"Unexpected voice pipeline error: {exc}",
                duration_ms=duration_ms,
            )
