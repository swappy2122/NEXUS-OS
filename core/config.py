"""Configuration loader for NEXUS OS."""

from dataclasses import dataclass, field
import os
from pathlib import Path
import sys
if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomllib  # type: ignore

from core.constants import DEFAULT_DATA_DIR, DEFAULT_ENV, DEFAULT_LOG_LEVEL
from voice.config import VoiceConfig


@dataclass
class Config:
    """NEXUS OS Configuration holding environment and system settings."""

    env: str = field(default_factory=lambda: os.getenv("NEXUS_ENV", DEFAULT_ENV))
    log_level: str = field(default_factory=lambda: os.getenv("NEXUS_LOG_LEVEL", DEFAULT_LOG_LEVEL))
    data_dir: Path = field(
        default_factory=lambda: Path(os.getenv("NEXUS_DATA_DIR", DEFAULT_DATA_DIR))
    )
    enable_security: bool = field(
        default_factory=lambda: os.getenv("NEXUS_ENABLE_SECURITY", "true").lower() == "true"
    )
    session_lifetime_seconds: int = field(
        default_factory=lambda: int(os.getenv("NEXUS_SESSION_LIFETIME_SECONDS", "3600"))
    )
    default_model: str = field(
        default_factory=lambda: os.getenv("NEXUS_DEFAULT_MODEL", "llama3.2")
    )
    ollama_base_url: str = field(
        default_factory=lambda: os.getenv("NEXUS_OLLAMA_BASE_URL", "http://localhost:11434")
    )

    # -- Model routing config ----------------------------------------------
    routing_strategy: str = field(
        default_factory=lambda: os.getenv("NEXUS_ROUTING_STRATEGY", "rule_based")
    )
    routing_tiers: dict[str, str] = field(default_factory=lambda: {
        "bypass": os.getenv("NEXUS_ROUTING_TIER_BYPASS", "dev_backend"),
        "light": os.getenv("NEXUS_ROUTING_TIER_LIGHT", "default"),
        "standard": os.getenv("NEXUS_ROUTING_TIER_STANDARD", "default"),
        "heavy": os.getenv("NEXUS_ROUTING_TIER_HEAVY", "default"),
    })

    # -- Voice config ------------------------------------------------------
    voice: VoiceConfig = field(default_factory=VoiceConfig)

    @classmethod
    def load_from_toml(cls, config_path: Path) -> "Config":
        """Load configuration from a TOML file with environment overrides."""
        if not config_path.exists():
            return cls()

        with open(config_path, "rb") as f:
            data = tomllib.load(f)

        nexus_data = data.get("nexus", {})
        routing_data = data.get("routing", {})
        tier_data = routing_data.get("tiers", {})
        voice_data = data.get("voice", {})

        return cls(
            env=os.getenv("NEXUS_ENV", nexus_data.get("env", DEFAULT_ENV)),
            log_level=os.getenv("NEXUS_LOG_LEVEL", nexus_data.get("log_level", DEFAULT_LOG_LEVEL)),
            data_dir=Path(os.getenv("NEXUS_DATA_DIR", nexus_data.get("data_dir", DEFAULT_DATA_DIR))),
            enable_security=os.getenv("NEXUS_ENABLE_SECURITY", str(nexus_data.get("enable_security", True))).lower() == "true",
            session_lifetime_seconds=int(os.getenv("NEXUS_SESSION_LIFETIME_SECONDS", nexus_data.get("session_lifetime_seconds", 3600))),
            default_model=os.getenv("NEXUS_DEFAULT_MODEL", nexus_data.get("default_model", "llama3.2")),
            ollama_base_url=os.getenv("NEXUS_OLLAMA_BASE_URL", nexus_data.get("ollama_base_url", "http://localhost:11434")),
            routing_strategy=os.getenv("NEXUS_ROUTING_STRATEGY", routing_data.get("strategy", "rule_based")),
            routing_tiers={
                "bypass": os.getenv("NEXUS_ROUTING_TIER_BYPASS", tier_data.get("bypass", "dev_backend")),
                "light": os.getenv("NEXUS_ROUTING_TIER_LIGHT", tier_data.get("light", "default")),
                "standard": os.getenv("NEXUS_ROUTING_TIER_STANDARD", tier_data.get("standard", "default")),
                "heavy": os.getenv("NEXUS_ROUTING_TIER_HEAVY", tier_data.get("heavy", "default")),
            },
            voice=VoiceConfig.from_dict(voice_data),
        )

