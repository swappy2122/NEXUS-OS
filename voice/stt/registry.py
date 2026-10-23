"""Registry and factory for Speech-to-Text providers in NEXUS OS."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from voice.exceptions import STTProviderNotFoundError
from voice.stt.base import STTProvider
from voice.stt.dev_provider import DevSTTProvider
from voice.stt.http_provider import HTTPSTTProvider

if TYPE_CHECKING:
    from voice.config import VoiceConfig


class STTRegistry:
    """Registry managing active Speech-to-Text providers and factories."""

    def __init__(self) -> None:
        self._providers: dict[str, STTProvider] = {}
        self._factories: dict[str, Callable[[VoiceConfig], STTProvider]] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Register built-in providers and factories."""
        dev_inst = DevSTTProvider()
        self.register_instance("dev", dev_inst)
        self.register_instance("mock", dev_inst)

        self.register_factory(
            "dev",
            lambda cfg: DevSTTProvider(),
        )
        self.register_factory(
            "mock",
            lambda cfg: DevSTTProvider(),
        )
        self.register_factory(
            "http",
            lambda cfg: HTTPSTTProvider(
                endpoint=cfg.stt_endpoint,
                model=cfg.stt_model,
                api_key=cfg.api_key,
            ),
        )
        self.register_factory(
            "whisper",
            lambda cfg: HTTPSTTProvider(
                endpoint=cfg.stt_endpoint,
                model=cfg.stt_model,
                api_key=cfg.api_key,
            ),
        )
        self.register_factory(
            "openai",
            lambda cfg: HTTPSTTProvider(
                endpoint=cfg.stt_endpoint,
                model=cfg.stt_model,
                api_key=cfg.api_key,
            ),
        )

    def register_instance(self, name: str, provider: STTProvider) -> None:
        """Register a specific STT provider instance."""
        self._providers[name.lower()] = provider

    def register_factory(
        self,
        name: str,
        factory: Callable[[VoiceConfig], STTProvider],
    ) -> None:
        """Register a constructor factory for a provider name."""
        self._factories[name.lower()] = factory

    def get_provider(self, name: str) -> STTProvider | None:
        """Retrieve an already-instantiated provider by name."""
        return self._providers.get(name.lower())

    def list_providers(self) -> list[str]:
        """Return all registered provider names."""
        names = set(self._providers.keys()) | set(self._factories.keys())
        return sorted(names)

    def create_provider(self, config: VoiceConfig) -> STTProvider:
        """Create or retrieve the provider specified in VoiceConfig."""
        provider_name = (config.provider or "dev").lower()

        # Check existing instance
        if provider_name in self._providers:
            return self._providers[provider_name]

        # Use registered factory
        if provider_name in self._factories:
            provider = self._factories[provider_name](config)
            self._providers[provider_name] = provider
            return provider

        raise STTProviderNotFoundError(provider_name)


# Global default registry instance
default_stt_registry = STTRegistry()
