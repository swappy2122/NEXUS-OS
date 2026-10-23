"""Microphone and audio capture abstractions for NEXUS OS."""

from __future__ import annotations

import asyncio
import logging
import math
import shutil
from abc import ABC, abstractmethod
from collections import deque
from pathlib import Path
from typing import Any

from voice.exceptions import (
    AudioCaptureError,
    DeviceNotFoundError,
    EmptyAudioError,
    RecordingTimeoutError,
)
from voice.types import AudioData

logger = logging.getLogger("nexus.voice.capture")


class AudioCapture(ABC):
    """Abstract Base Class for microphone and audio input capture."""

    name: str = "base"

    @abstractmethod
    async def record(
        self,
        duration_seconds: float = 5.0,
        sample_rate: int = 16000,
        channels: int = 1,
        sample_width: int = 2,
    ) -> AudioData:
        """Capture audio from the microphone or input source.

        Parameters:
            duration_seconds: Maximum length of audio to record.
            sample_rate: Audio sampling frequency in Hz.
            channels: Number of audio channels (1 = mono).
            sample_width: Bytes per sample (2 = 16-bit PCM).

        Returns:
            An :class:`AudioData` instance with captured raw bytes and format metadata.

        Raises:
            AudioCaptureError: If recording fails or device is inaccessible.
        """
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        """Return True if this audio capture backend is usable on the host system."""
        ...


class LinuxAudioCapture(AudioCapture):
    """Captures microphone audio on Linux using ``arecord`` (ALSA) or ``pw-record`` (PipeWire).

    Parameters:
        preferred_tool: Force 'arecord' or 'pw-record', or None for auto-detection.
        device: Audio input device name (default: 'default').
    """

    name: str = "linux_system"

    def __init__(
        self,
        preferred_tool: str | None = None,
        device: str = "default",
    ) -> None:
        self.device = device
        self._preferred_tool = preferred_tool
        self._tool_path = self._detect_tool()

    def _detect_tool(self) -> str | None:
        if self._preferred_tool:
            return shutil.which(self._preferred_tool)

        # Auto-detect: try arecord first (standard on ALSA/Pulse/Pipewire-alsa systems)
        arecord_path = shutil.which("arecord")
        if arecord_path:
            return arecord_path

        pw_path = shutil.which("pw-record")
        if pw_path:
            return pw_path

        return None

    async def is_available(self) -> bool:
        """Check if an audio recording executable is found on PATH."""
        return self._tool_path is not None

    async def record(
        self,
        duration_seconds: float = 5.0,
        sample_rate: int = 16000,
        channels: int = 1,
        sample_width: int = 2,
    ) -> AudioData:
        """Record audio from the Linux sound subsystem."""
        if not self._tool_path:
            raise DeviceNotFoundError("No audio recording tool ('arecord' or 'pw-record') found on system PATH.")

        if duration_seconds <= 0:
            raise AudioCaptureError("Duration must be a positive number of seconds.")

        # Determine tool binary
        tool_name = Path(self._tool_path).name
        target_bytes = int(duration_seconds * sample_rate * channels * sample_width)
        ceil_duration = max(1, math.ceil(duration_seconds))

        if tool_name == "arecord":
            cmd = [
                self._tool_path,
                "-q",
                "-D", self.device,
                "-f", "S16_LE",
                "-r", str(sample_rate),
                "-c", str(channels),
                "-t", "raw",
                "-d", str(ceil_duration),
            ]
        elif tool_name == "pw-record":
            cmd = [
                self._tool_path,
                "--rate", str(sample_rate),
                "--channels", str(channels),
                "--format", "s16",
                "-",  # output raw to stdout
            ]
        else:
            raise AudioCaptureError(f"Unsupported recording executable: {tool_name}")

        logger.debug("Executing audio capture command: %s", " ".join(cmd))

        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Wait for output up to duration + buffer timeout
            timeout = duration_seconds + 3.0
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                if proc.returncode is None:
                    try:
                        proc.terminate()
                        await proc.wait()
                    except ProcessLookupError:
                        pass
                raise RecordingTimeoutError(timeout=duration_seconds)

            # Check exit code
            if proc.returncode != 0:
                err_msg = stderr_bytes.decode(errors="replace").strip()
                if "no such device" in err_msg.lower() or "device or resource busy" in err_msg.lower():
                    raise DeviceNotFoundError(f"Microphone device error: {err_msg}")
                raise AudioCaptureError(f"Recording process exited with code {proc.returncode}: {err_msg}")

            # Slice to exact duration bytes
            raw_audio = stdout_bytes[:target_bytes] if len(stdout_bytes) >= target_bytes else stdout_bytes

            if not raw_audio:
                raise EmptyAudioError("Recording tool captured 0 bytes of audio data.")

            return AudioData(
                raw_bytes=raw_audio,
                sample_rate=sample_rate,
                channels=channels,
                sample_width=sample_width,
            )

        except (DeviceNotFoundError, RecordingTimeoutError, EmptyAudioError):
            raise
        except Exception as exc:
            if proc and proc.returncode is None:
                try:
                    proc.terminate()
                except ProcessLookupError:
                    pass
            raise AudioCaptureError(f"Unexpected audio capture error: {exc}") from exc


class BufferAudioCapture(AudioCapture):
    """In-memory queue audio capture.

    Allows tests, pipelines, and VR clients to feed audio buffers or WAV files
    directly into the capture layer.
    """

    name: str = "buffer"

    def __init__(self, default_sample_rate: int = 16000) -> None:
        self.default_sample_rate = default_sample_rate
        self._queue: deque[AudioData] = deque()

    async def is_available(self) -> bool:
        return True

    def feed(self, audio: AudioData | bytes | Path | str) -> None:
        """Feed audio into the capture buffer.

        Accepts :class:`AudioData`, raw PCM bytes, WAV bytes, or a filepath.
        """
        if isinstance(audio, AudioData):
            self._queue.append(audio)
        elif isinstance(audio, (str, Path)):
            p = Path(audio)
            data = AudioData.from_wav_bytes(p.read_bytes())
            self._queue.append(data)
        elif isinstance(audio, bytes):
            # Check for WAV RIFF magic
            if audio.startswith(b"RIFF"):
                self._queue.append(AudioData.from_wav_bytes(audio))
            else:
                self._queue.append(AudioData(raw_bytes=audio, sample_rate=self.default_sample_rate))
        else:
            raise ValueError(f"Unsupported audio feed type: {type(audio)}")

    def clear(self) -> None:
        """Clear all buffered audio."""
        self._queue.clear()

    @property
    def pending_count(self) -> int:
        """Return number of queued audio frames."""
        return len(self._queue)

    async def record(
        self,
        duration_seconds: float = 5.0,
        sample_rate: int = 16000,
        channels: int = 1,
        sample_width: int = 2,
    ) -> AudioData:
        """Return the next queued audio buffer or raise EmptyAudioError if empty."""
        if not self._queue:
            raise EmptyAudioError("No audio available in capture buffer.")
        return self._queue.popleft()


class MockAudioCapture(AudioCapture):
    """Generates synthetic audio for development and headless testing."""

    name: str = "mock"

    def __init__(self, synthetic_text: str = "hello nexus") -> None:
        self.synthetic_text = synthetic_text

    async def is_available(self) -> bool:
        return True

    async def record(
        self,
        duration_seconds: float = 1.0,
        sample_rate: int = 16000,
        channels: int = 1,
        sample_width: int = 2,
    ) -> AudioData:
        """Generate a buffer of synthetic PCM samples."""
        total_samples = int(duration_seconds * sample_rate * channels)
        # 16-bit silence / low tone samples
        raw_bytes = b"\x00\x00" * total_samples
        return AudioData(
            raw_bytes=raw_bytes,
            sample_rate=sample_rate,
            channels=channels,
            sample_width=sample_width,
        )


def create_audio_capture(
    backend: str = "auto",
    device: str = "default",
) -> AudioCapture:
    """Factory creating an AudioCapture instance based on configuration.

    Parameters:
        backend: 'auto', 'arecord', 'pw-record', 'buffer', or 'mock'.
        device: ALSA / PipeWire hardware device name.
    """
    clean_backend = (backend or "auto").strip().lower()

    if clean_backend == "mock":
        return MockAudioCapture()
    if clean_backend == "buffer":
        return BufferAudioCapture()

    # Linux native recording
    capture = LinuxAudioCapture(
        preferred_tool=clean_backend if clean_backend in ("arecord", "pw-record") else None,
        device=device,
    )
    return capture
