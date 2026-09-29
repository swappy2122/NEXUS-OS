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
    default_model: str = field(
        default_factory=lambda: os.getenv("NEXUS_DEFAULT_MODEL", "llama3.2")
    )
    ollama_base_url: str = field(
        default_factory=lambda: os.getenv("NEXUS_OLLAMA_BASE_URL", "http://localhost:11434")
    )

    @classmethod
    def load_from_toml(cls, config_path: Path) -> "Config":
        """Load configuration from a TOML file with environment overrides."""
        if not config_path.exists():
            return cls()

        with open(config_path, "rb") as f:
            data = tomllib.load(f)

        nexus_data = data.get("nexus", {})
        return cls(
            env=os.getenv("NEXUS_ENV", nexus_data.get("env", DEFAULT_ENV)),
            log_level=os.getenv("NEXUS_LOG_LEVEL", nexus_data.get("log_level", DEFAULT_LOG_LEVEL)),
            data_dir=Path(os.getenv("NEXUS_DATA_DIR", nexus_data.get("data_dir", DEFAULT_DATA_DIR))),
            enable_security=os.getenv("NEXUS_ENABLE_SECURITY", str(nexus_data.get("enable_security", True))).lower() == "true",
            default_model=os.getenv("NEXUS_DEFAULT_MODEL", nexus_data.get("default_model", "llama3.2")),
            ollama_base_url=os.getenv("NEXUS_OLLAMA_BASE_URL", nexus_data.get("ollama_base_url", "http://localhost:11434")),
        )
