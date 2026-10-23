"""Comprehensive tests for the NEXUS Voice Input subsystem.

Covers:
1. Audio Data & WAV conversions (AudioData, to_wav_bytes, from_wav_bytes, error handling)
2. Audio Capture Abstractions (LinuxAudioCapture, BufferAudioCapture, MockAudioCapture, create_audio_capture)
3. Speech-to-Text Providers & Model Abstraction (DevSTTProvider, HTTPSTTProvider, STTRegistry)
4. Configurable Activation (VoiceConfig, enable/disable, VoiceDisabledError)
5. Plain Text Return & Handoff to existing Supervisor
6. Robust Error Handling (empty audio, timeouts, capture failures, provider errors)
7. End-to-End Integration with NexusCore
"""

from __future__ import annotations

import asyncio
import io
import tempfile
import wave
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.registry import AgentRegistry
from agents.supervisor import SupervisorAgent
from agents.system_agent import SystemAgent
from context.manager import ContextManager
from core.nexus import NexusCore
from tools.system_tools import SystemCpuTool
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
from voice.stt.base import STTProvider
from voice.stt.dev_provider import DevSTTProvider
from voice.stt.http_provider import HTTPSTTProvider
from voice.stt.registry import STTRegistry
from voice.types import (
    ActivationMode,
    AudioData,
    TranscriptionResult,
    VoiceCommandResult,
)


# ===========================================================================
# 1. Audio Data & WAV Conversions
# ===========================================================================

def test_audio_data_duration_and_properties():
    """Verify AudioData calculates duration and flags empty state."""
    # 1 second of 16kHz, 16-bit mono = 32000 bytes
    raw_1s = b"\x00" * 32000
    audio = AudioData(raw_bytes=raw_1s, sample_rate=16000, channels=1, sample_width=2)
    assert pytest.approx(audio.duration_seconds, 0.01) == 1.0
    assert not audio.is_empty

    empty = AudioData(raw_bytes=b"")
    assert empty.duration_seconds == 0.0
    assert empty.is_empty


def test_audio_data_wav_roundtrip():
    """Verify converting AudioData to WAV bytes and back retains raw samples."""
    raw_pcm = b"\x01\x02\x03\x04" * 1000
    audio = AudioData(raw_bytes=raw_pcm, sample_rate=16000, channels=1, sample_width=2)

    wav_bytes = audio.to_wav_bytes()
    assert wav_bytes.startswith(b"RIFF")
    assert b"WAVE" in wav_bytes[:16]

    parsed = AudioData.from_wav_bytes(wav_bytes)
    assert parsed.sample_rate == 16000
    assert parsed.channels == 1
    assert parsed.sample_width == 2
    assert parsed.raw_bytes == raw_pcm


def test_audio_data_corrupt_wav_raises_audio_format_error():
    """Parsing malformed bytes as WAV raises AudioFormatError."""
    with pytest.raises(AudioFormatError):
        AudioData.from_wav_bytes(b"NOT_A_VALID_WAV_HEADER_DATA")


# ===========================================================================
# 2. Audio Capture Abstractions
# ===========================================================================

@pytest.mark.asyncio
async def test_mock_audio_capture():
    """MockAudioCapture generates synthetic PCM audio."""
    capture = MockAudioCapture()
    assert await capture.is_available()

    audio = await capture.record(duration_seconds=0.5, sample_rate=16000)
    assert isinstance(audio, AudioData)
    assert pytest.approx(audio.duration_seconds, 0.01) == 0.5
    assert len(audio.raw_bytes) == 16000  # 0.5s * 16000 samples * 2 bytes


@pytest.mark.asyncio
async def test_buffer_audio_capture():
    """BufferAudioCapture queues and yields AudioData objects."""
    buffer = BufferAudioCapture()
    assert await buffer.is_available()

    # Empty buffer raises EmptyAudioError
    with pytest.raises(EmptyAudioError):
        await buffer.record()

    # Feed AudioData
    pcm = b"\x05\x05" * 1600
    data = AudioData(raw_bytes=pcm, sample_rate=16000)
    buffer.feed(data)
    assert buffer.pending_count == 1

    rec = await buffer.record()
    assert rec.raw_bytes == pcm
    assert buffer.pending_count == 0


@pytest.mark.asyncio
async def test_buffer_audio_capture_feed_wav_bytes():
    """BufferAudioCapture can be fed WAV bytes directly."""
    buffer = BufferAudioCapture()
    sample = AudioData(raw_bytes=b"\x12\x34" * 800, sample_rate=16000)
    wav_bytes = sample.to_wav_bytes()

    buffer.feed(wav_bytes)
    rec = await buffer.record()
    assert rec.raw_bytes == sample.raw_bytes


@pytest.mark.asyncio
async def test_linux_audio_capture_missing_tool():
    """LinuxAudioCapture raises DeviceNotFoundError if recording tool is missing."""
    capture = LinuxAudioCapture(preferred_tool="non_existent_record_tool_xyz")
    assert not await capture.is_available()

    with pytest.raises(DeviceNotFoundError):
        await capture.record()


@pytest.mark.asyncio
async def test_linux_audio_capture_simulated_process():
    """Test LinuxAudioCapture with simulated subprocess success."""
    capture = LinuxAudioCapture()
    fake_pcm = b"\x00\x01" * 8000

    # Mock subprocess creation
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (fake_pcm, b"")
    mock_proc.returncode = 0

    with patch("voice.capture.shutil.which", return_value="/usr/bin/arecord"), \
         patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        audio = await capture.record(duration_seconds=0.5, sample_rate=16000)
        assert len(audio.raw_bytes) == len(fake_pcm)


@pytest.mark.asyncio
async def test_linux_audio_capture_process_error():
    """LinuxAudioCapture raises AudioCaptureError on non-zero return code."""
    capture = LinuxAudioCapture()
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"", b"arecord: audio open error: Device or resource busy")
    mock_proc.returncode = 1

    with patch("voice.capture.shutil.which", return_value="/usr/bin/arecord"), \
         patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(DeviceNotFoundError) as exc_info:
            await capture.record(duration_seconds=1.0)
        assert "busy" in str(exc_info.value).lower()


def test_create_audio_capture_factory():
    """Factory selects correct capture implementation based on backend parameter."""
    mock_cap = create_audio_capture("mock")
    assert isinstance(mock_cap, MockAudioCapture)

    buf_cap = create_audio_capture("buffer")
    assert isinstance(buf_cap, BufferAudioCapture)

    auto_cap = create_audio_capture("auto")
    assert isinstance(auto_cap, LinuxAudioCapture)


# ===========================================================================
# 3. Speech-to-Text Providers & Model Abstraction
# ===========================================================================

@pytest.mark.asyncio
async def test_dev_stt_provider_transcription():
    """DevSTTProvider returns deterministic plain text."""
    provider = DevSTTProvider(default_text="open browser")
    audio = AudioData(raw_bytes=b"\x00" * 3200)

    res = await provider.transcribe(audio)
    assert isinstance(res, TranscriptionResult)
    assert res.plain_text == "open browser"
    assert res.provider == "dev"
    assert provider.call_count == 1
    assert provider.last_audio == audio


@pytest.mark.asyncio
async def test_dev_stt_provider_queued_transcriptions():
    """DevSTTProvider returns queued transcriptions in FIFO order."""
    provider = DevSTTProvider()
    provider.queue_transcriptions(["check cpu", "list files", "close window"])
    audio = AudioData(raw_bytes=b"\x00" * 3200)

    res1 = await provider.transcribe(audio)
    res2 = await provider.transcribe(audio)
    res3 = await provider.transcribe(audio)

    assert res1.plain_text == "check cpu"
    assert res2.plain_text == "list files"
    assert res3.plain_text == "close window"


@pytest.mark.asyncio
async def test_dev_stt_provider_empty_audio_raises():
    """Transcribing empty audio raises EmptyAudioError."""
    provider = DevSTTProvider()
    with pytest.raises(EmptyAudioError):
        await provider.transcribe(AudioData(raw_bytes=b""))


@pytest.mark.asyncio
async def test_dev_stt_provider_simulated_error():
    """DevSTTProvider can simulate errors for test coverage."""
    provider = DevSTTProvider()
    provider.set_error_for_next_call(TranscriptionError("Simulated neural model crash", provider="dev"))

    audio = AudioData(raw_bytes=b"\x00" * 3200)
    with pytest.raises(TranscriptionError) as exc_info:
        await provider.transcribe(audio)
    assert "Simulated neural model crash" in str(exc_info.value)


@pytest.mark.asyncio
async def test_http_stt_provider_successful_transcription():
    """HTTPSTTProvider posts WAV audio and parses response JSON."""
    provider = HTTPSTTProvider(endpoint="http://mock-stt/v1/audio/transcriptions")
    audio = AudioData(raw_bytes=b"\x00" * 3200)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"text": "read file notes.txt", "language": "en"}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp) as mock_post:
        res = await provider.transcribe(audio)
        assert res.plain_text == "read file notes.txt"
        assert res.provider == "http"
        mock_post.assert_called_once()


@pytest.mark.asyncio
async def test_http_stt_provider_http_error():
    """HTTPSTTProvider raises TranscriptionError on HTTP 4xx/5xx responses."""
    provider = HTTPSTTProvider(endpoint="http://mock-stt/v1/audio/transcriptions")
    audio = AudioData(raw_bytes=b"\x00" * 3200)

    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "Internal Model Error"

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
        with pytest.raises(TranscriptionError) as exc_info:
            await provider.transcribe(audio)
        assert "HTTP 500" in str(exc_info.value)


def test_stt_registry_lookup_and_custom_provider():
    """STTRegistry creates and manages provider instances."""
    registry = STTRegistry()

    # Built-in 'dev'
    cfg_dev = VoiceConfig(provider="dev")
    prov_dev = registry.create_provider(cfg_dev)
    assert isinstance(prov_dev, DevSTTProvider)

    # Built-in 'http'
    cfg_http = VoiceConfig(provider="http", stt_endpoint="http://localhost:9999/stt")
    prov_http = registry.create_provider(cfg_http)
    assert isinstance(prov_http, HTTPSTTProvider)
    assert prov_http.endpoint == "http://localhost:9999/stt"

    # Unknown provider
    cfg_bad = VoiceConfig(provider="unsupported_quantum_stt")
    with pytest.raises(STTProviderNotFoundError):
        registry.create_provider(cfg_bad)


# ===========================================================================
# 4. Configurable Activation
# ===========================================================================

def test_voice_config_defaults_and_env():
    """VoiceConfig defaults to disabled and parses activation mode."""
    cfg = VoiceConfig()
    assert cfg.enabled is False
    assert cfg.provider == "dev"
    assert cfg.activation_mode == ActivationMode.MANUAL

    cfg_dict = VoiceConfig.from_dict({
        "enabled": True,
        "provider": "whisper",
        "activation_mode": "push_to_talk",
        "sample_rate": 44100,
    })
    assert cfg_dict.enabled is True
    assert cfg_dict.provider == "whisper"
    assert cfg_dict.activation_mode == ActivationMode.PUSH_TO_TALK
    assert cfg_dict.sample_rate == 44100


@pytest.mark.asyncio
async def test_voice_service_disabled_raises_voice_disabled_error():
    """When disabled, recording or transcribing directly raises VoiceDisabledError."""
    service = VoiceInputService(config=VoiceConfig(enabled=False))
    assert not service.is_enabled

    with pytest.raises(VoiceDisabledError):
        await service.record_audio()

    with pytest.raises(VoiceDisabledError):
        await service.transcribe(AudioData(raw_bytes=b"\x00" * 100))


@pytest.mark.asyncio
async def test_voice_service_runtime_enable_disable():
    """VoiceInputService can be toggled at runtime."""
    service = VoiceInputService(
        config=VoiceConfig(enabled=False),
        audio_capture=MockAudioCapture(),
        stt_provider=DevSTTProvider(),
    )
    assert not service.is_enabled

    # Enable at runtime
    service.enable()
    assert service.is_enabled
    audio = await service.record_audio(duration_seconds=0.1)
    assert not audio.is_empty

    # Disable again
    service.disable()
    assert not service.is_enabled
    with pytest.raises(VoiceDisabledError):
        await service.record_audio()


# ===========================================================================
# 5. Plain Text Return & Handoff to existing Supervisor
# ===========================================================================

@pytest.mark.asyncio
async def test_listen_and_transcribe_returns_plain_text():
    """listen_and_transcribe returns pure plain text without AI reasoning."""
    stt = DevSTTProvider(default_text="show memory usage")
    capture = MockAudioCapture()
    service = VoiceInputService(
        config=VoiceConfig(enabled=True),
        audio_capture=capture,
        stt_provider=stt,
    )

    plain_text = await service.listen_and_transcribe()
    assert plain_text == "show memory usage"
    assert isinstance(plain_text, str)


@pytest.mark.asyncio
async def test_process_voice_command_hands_plain_text_to_supervisor():
    """process_voice_command captures audio, gets plain text, and passes it to Supervisor."""
    from models.dev_backend import DevModelBackend

    dev_model = DevModelBackend()
    sys_agent = SystemAgent()
    sys_agent.register_tool(SystemCpuTool())
    sys_agent.set_llm(dev_model)

    registry = AgentRegistry()
    registry.register(sys_agent)

    context = ContextManager()
    supervisor = SupervisorAgent(registry, context)
    supervisor.set_llm(dev_model)

    # Setup Voice service
    stt = DevSTTProvider(default_text="cpu")
    capture = MockAudioCapture()

    service = VoiceInputService(
        config=VoiceConfig(enabled=True, auto_dispatch=True),
        audio_capture=capture,
        stt_provider=stt,
        supervisor=supervisor,
    )

    result = await service.process_voice_command()
    assert isinstance(result, VoiceCommandResult)
    assert result.success is True
    assert result.text == "cpu"
    assert result.supervisor_result is not None
    assert result.supervisor_result.success is True
    # The output from system_cpu executed via Supervisor
    assert "cpu_model" in result.supervisor_result.output or "cpu" in result.supervisor_result.output.lower()


# ===========================================================================
# 6. Robust Error Handling
# ===========================================================================

@pytest.mark.asyncio
async def test_process_voice_command_empty_transcription_returns_error():
    """Empty transcription returns a structured failure without crashing."""
    stt = DevSTTProvider(default_text="")  # returns blank string
    capture = MockAudioCapture()

    service = VoiceInputService(
        config=VoiceConfig(enabled=True),
        audio_capture=capture,
        stt_provider=stt,
    )

    res = await service.process_voice_command()
    assert res.success is False
    assert "EMPTY_TRANSCRIPTION" in res.error


@pytest.mark.asyncio
async def test_process_voice_command_when_disabled_returns_structured_error():
    """process_voice_command returns structured error when disabled rather than crashing."""
    service = VoiceInputService(config=VoiceConfig(enabled=False))

    res = await service.process_voice_command()
    assert res.success is False
    assert "[VOICE_DISABLED]" in res.error


@pytest.mark.asyncio
async def test_process_voice_command_catches_audio_capture_error():
    """Audio capture failures return structured error in VoiceCommandResult."""
    capture = BufferAudioCapture()  # empty buffer -> raises EmptyAudioError
    service = VoiceInputService(
        config=VoiceConfig(enabled=True),
        audio_capture=capture,
        stt_provider=DevSTTProvider(),
    )

    res = await service.process_voice_command()
    assert res.success is False
    assert "EMPTY_AUDIO" in res.error or "empty" in res.error.lower()


# ===========================================================================
# 7. End-to-End Integration with NexusCore
# ===========================================================================

@pytest.mark.asyncio
async def test_nexus_core_execute_voice_pipeline():
    """NexusCore integrates with voice module to process voice commands end-to-end."""
    core = NexusCore.bootstrap(use_dev_model=True, log_level="WARNING")

    # Inject mock capture & dev STT into the core's voice service and enable it
    core.voice_service.set_audio_capture(MockAudioCapture())
    dev_stt = DevSTTProvider(default_text="cpu")
    core.voice_service.set_stt_provider(dev_stt)
    core.voice_service.enable()

    assert core.get_system_status()["voice_enabled"] is True

    # Execute voice command through NexusCore
    voice_res = await core.execute_voice()
    assert isinstance(voice_res, VoiceCommandResult)
    assert voice_res.success is True
    assert voice_res.text == "cpu"
    assert voice_res.supervisor_result is not None
    assert voice_res.supervisor_result.success is True
    assert "system_cpu" in voice_res.supervisor_result.route_display
