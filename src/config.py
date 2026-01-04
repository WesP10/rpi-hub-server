"""Configuration management using Pydantic BaseSettings."""

import os
import re
from pathlib import Path
from typing import List, Optional

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class HubConfig(BaseSettings):
    """Hub-specific configuration."""

    hub_id: str = Field(default="rpi-bridge-01", description="Unique hub identifier")
    server_endpoint: str = Field(
        default="ws://localhost:8080/hub", description="WebSocket server endpoint"
    )
    device_token: str = Field(default="", description="Authentication token for hub")
    reconnect_interval: int = Field(
        default=5, description="Reconnection interval in seconds"
    )
    max_reconnect_attempts: int = Field(
        default=10, description="Maximum reconnection attempts"
    )


class SerialConfig(BaseSettings):
    """Serial communication configuration."""

    default_baud_rate: int = Field(default=9600, description="Default baud rate")
    scan_interval: int = Field(
        default=2, description="Port scan interval in seconds"
    )
    default_timeout: float = Field(
        default=1.0, description="Default serial timeout in seconds"
    )
    max_connections: int = Field(
        default=10, description="Maximum simultaneous connections"
    )
    task_queue_size: int = Field(default=100, description="Task queue size")
    connection_retry_attempts: int = Field(
        default=3, description="Connection retry attempts"
    )


class BufferConfig(BaseSettings):
    """Buffer configuration."""

    size_mb: int = Field(default=10, description="Buffer size in megabytes")
    warn_threshold: float = Field(
        default=0.8, description="Warning threshold (0.0-1.0)"
    )


class HealthConfig(BaseSettings):
    """Health reporter configuration."""

    report_interval: int = Field(
        default=30, description="Health report interval in seconds"
    )
    cpu_threshold: float = Field(
        default=80.0, description="CPU usage alert threshold"
    )
    memory_threshold: float = Field(
        default=85.0, description="Memory usage alert threshold"
    )


class StorageConfig(BaseSettings):
    """Storage paths configuration."""

    artifact_cache_path: str = Field(
        default="/tmp/rpi-hub-artifacts", description="Artifact cache directory"
    )
    artifact_retention_hours: int = Field(
        default=24, description="Artifact retention in hours"
    )
    port_mapping_file: str = Field(
        default="/var/lib/rpi-hub/port_mappings.json",
        description="Port mapping persistence file",
    )
    log_directory: str = Field(
        default="/var/log/rpi-hub", description="Log directory"
    )


class APIConfig(BaseSettings):
    """API server configuration."""

    host: str = Field(default="0.0.0.0", description="API server host")
    port: int = Field(default=8000, description="API server port")
    cors_origins: List[str] = Field(
        default=["*"], description="CORS allowed origins"
    )


class LoggingConfig(BaseSettings):
    """Logging configuration."""

    level: str = Field(default="INFO", description="Log level")
    format: str = Field(default="json", description="Log format (json or text)")


class Settings(BaseSettings):
    """Main application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    hub: HubConfig = Field(default_factory=HubConfig)
    serial: SerialConfig = Field(default_factory=SerialConfig)
    buffer: BufferConfig = Field(default_factory=BufferConfig)
    health: HealthConfig = Field(default_factory=HealthConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    api: APIConfig = Field(default_factory=APIConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    @classmethod
    def load_from_yaml(cls, yaml_path: Optional[Path] = None) -> "Settings":
        """Load settings from YAML file with environment variable substitution.

        Args:
            yaml_path: Path to YAML config file. Defaults to config/config.yaml

        Returns:
            Settings instance with merged configuration
        """
        if yaml_path is None:
            yaml_path = Path("config/config.yaml")

        if not yaml_path.exists():
            # Return settings from environment only
            return cls()

        with open(yaml_path, "r") as f:
            yaml_content = f.read()

        # Substitute environment variables with default values
        # Pattern: ${VAR_NAME:default_value}
        def replace_env_var(match):
            var_name = match.group(1)
            default_value = match.group(2)
            env_value = os.getenv(var_name)
            if env_value is not None:
                return env_value
            # Return default value if it's not empty, otherwise empty string
            return default_value if default_value else ""
        
        yaml_content = re.sub(r'\$\{([^:}]+):([^}]*)\}', replace_env_var, yaml_content)
        config_dict = yaml.safe_load(yaml_content)

        # Merge with environment variables (env vars take precedence)
        return cls(**config_dict)


# Global settings instance
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get the global settings instance.

    Returns:
        Settings instance
    """
    global _settings
    if _settings is None:
        _settings = Settings.load_from_yaml()
    return _settings


def reload_settings(yaml_path: Optional[Path] = None) -> Settings:
    """Reload settings from configuration files.

    Args:
        yaml_path: Optional path to YAML config file

    Returns:
        New Settings instance
    """
    global _settings
    _settings = Settings.load_from_yaml(yaml_path)
    return _settings
