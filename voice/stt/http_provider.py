"""HTTP-based Speech-to-Text provider for OpenAI-compatible Whisper endpoints."""

from __future__ import annotations

import logging
from typing import Any

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore

from voice.exceptions import EmptyAudioError, TranscriptionError
from voice.stt.base import STTProvider
from voice.types import AudioData, TranscriptionResult

logger = logging.getLogger("nexus.voice.stt.http")


class HTTPSTTProvider(STTProvider):
    """Speech-to-Text provider connecting to an HTTP transcription endpoint.

    Compatible with OpenAI Whisper, local whisper.cpp server, faster-whisper server,
    and Ollama audio proxies exposing a `/v1/audio/transcriptions` endpoint.

    Parameters:
        endpoint: HTTP URL of the transcription service.
        model: Model name to request (default: 'whisper-1').
        api_key: Optional Bearer token or API key for authentication.
        timeout_seconds: Request timeout in seconds.
    """

    name: str = "http"

    def __init__(
        self,
        endpoint: str = "http://localhost:8000/v1/audio/transcriptions",
        model: str = "whisper-1",
        api_key: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.endpoint = endpoint
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    async def is_ready(self) -> bool:
        """Verify endpoint connectivity."""
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                res = await client.get(self.endpoint)
                return res.status_code in (200, 405)  # 405 Method Not Allowed is expected for POST endpoint
        except Exception:
            return False

    async def transcribe(
        self,
        audio: AudioData,
        language: str | None = None,
        **kwargs: Any,
    ) -> TranscriptionResult:
        """Send audio to the HTTP endpoint and return transcribed text."""
        if audio.is_empty:
            raise EmptyAudioError("Cannot transcribe empty audio buffer.")

        wav_bytes = audio.to_wav_bytes()

        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        form_data: dict[str, Any] = {
            "model": kwargs.get("model", self.model),
        }
        if language:
            form_data["language"] = language

        files = {
            "file": ("audio.wav", wav_bytes, "audio/wav"),
        }

        logger.debug(
            "Sending %d bytes of audio to STT endpoint: %s (model=%s)",
            len(wav_bytes),
            self.endpoint,
            self.model,
        )

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    self.endpoint,
                    data=form_data,
                    files=files,
                    headers=headers,
                )

                if response.status_code != 200:
                    err_msg = (
                        f"Server returned HTTP {response.status_code}: {response.text[:200]}"
                    )
                    raise TranscriptionError(err_msg, provider=self.name, status_code=response.status_code)

                payload = response.json()
                text = (
                    payload.get("text")
                    or payload.get("transcription")
                    or payload.get("result", "")
                )

                if not isinstance(text, str):
                    raise TranscriptionError(
                        f"Unexpected response payload format: {payload}",
                        provider=self.name,
                    )

                return TranscriptionResult(
                    text=text.strip(),
                    language=payload.get("language", language),
                    duration_seconds=audio.duration_seconds,
                    provider=self.name,
                    model=self.model,
                    raw_response=payload,
                )

        except (EmptyAudioError, TranscriptionError):
            raise
        except httpx.TimeoutException as exc:
            raise TranscriptionError(
                f"STT request timed out after {self.timeout_seconds}s",
                provider=self.name,
            ) from exc
        except Exception as exc:
            raise TranscriptionError(
                f"Network or request error: {exc}",
                provider=self.name,
            ) from exc
