"""Test configuration loading."""

import os
from pathlib import Path

import pytest

from src.config import (
    APIConfig,
    BufferConfig,
    HealthConfig,
    HubConfig,
    LoggingConfig,
    SerialConfig,
    Settings,
    StorageConfig,
    get_settings,
    reload_settings,
)


def test_default_hub_config():
    """Test default hub configuration."""
    config = HubConfig()
    assert config.hub_id == "rpi-bridge-01"
    assert config.server_endpoint == "ws://localhost:8080/hub"
    assert config.reconnect_interval == 5
    assert config.max_reconnect_attempts == 10


def test_default_serial_config():
    """Test default serial configuration."""
    config = SerialConfig()
    assert config.default_baud_rate == 9600
    assert config.scan_interval == 2
    assert config.default_timeout == 1.0
    assert config.max_connections == 10
    assert config.connection_retry_attempts == 3


def test_default_buffer_config():
    """Test default buffer configuration."""
    config = BufferConfig()
    assert config.size_mb == 10
    assert config.warn_threshold == 0.8


def test_default_health_config():
    """Test default health configuration."""
    config = HealthConfig()
    assert config.report_interval == 30
    assert config.cpu_threshold == 80.0
    assert config.memory_threshold == 85.0


def test_default_storage_config():
    """Test default storage configuration."""
    config = StorageConfig()
    assert config.artifact_cache_path == "/tmp/rpi-hub-artifacts"
    assert config.artifact_retention_hours == 24
    assert config.port_mapping_file == "/var/lib/rpi-hub/port_mappings.json"


def test_default_api_config():
    """Test default API configuration."""
    config = APIConfig()
    assert config.host == "0.0.0.0"
    assert config.port == 8000
    assert config.cors_origins == ["*"]


def test_default_logging_config():
    """Test default logging configuration."""
    config = LoggingConfig()
    assert config.level == "INFO"
    assert config.format == "json"


def test_settings_from_environment(monkeypatch):
    """Test loading settings from environment variables."""
    monkeypatch.setenv("HUB__HUB_ID", "test-hub")
    monkeypatch.setenv("HUB__SERVER_ENDPOINT", "ws://test:9090/hub")
    monkeypatch.setenv("SERIAL__DEFAULT_BAUD_RATE", "115200")
    monkeypatch.setenv("API__PORT", "9000")

    settings = Settings()
    assert settings.hub.hub_id == "test-hub"
    assert settings.hub.server_endpoint == "ws://test:9090/hub"
    assert settings.serial.default_baud_rate == 115200
    assert settings.api.port == 9000


def test_settings_load_from_yaml(tmp_path):
    """Test loading settings from YAML file."""
    yaml_content = """
hub:
  hub_id: yaml-hub
  server_endpoint: ws://yaml:8080/hub
serial:
  default_baud_rate: 57600
  scan_interval: 5
"""
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text(yaml_content)

    settings = Settings.load_from_yaml(yaml_file)
    assert settings.hub.hub_id == "yaml-hub"
    assert settings.hub.server_endpoint == "ws://yaml:8080/hub"
    assert settings.serial.default_baud_rate == 57600
    assert settings.serial.scan_interval == 5


def test_settings_yaml_with_env_substitution(tmp_path, monkeypatch):
    """Test YAML loading with environment variable substitution."""
    monkeypatch.setenv("TEST_HUB_ID", "env-substituted-hub")
    monkeypatch.setenv("TEST_BAUD_RATE", "38400")

    yaml_content = """
hub:
  hub_id: ${TEST_HUB_ID}
serial:
  default_baud_rate: ${TEST_BAUD_RATE}
"""
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text(yaml_content)

    settings = Settings.load_from_yaml(yaml_file)
    assert settings.hub.hub_id == "env-substituted-hub"
    assert settings.serial.default_baud_rate == 38400


def test_settings_missing_yaml():
    """Test loading settings when YAML file doesn't exist."""
    non_existent = Path("/tmp/does-not-exist.yaml")
    settings = Settings.load_from_yaml(non_existent)
    # Should fall back to defaults
    assert settings.hub.hub_id == "rpi-bridge-01"


def test_get_settings_singleton():
    """Test get_settings returns same instance."""
    settings1 = get_settings()
    settings2 = get_settings()
    assert settings1 is settings2


def test_reload_settings():
    """Test reload_settings creates new instance."""
    settings1 = get_settings()
    settings2 = reload_settings()
    assert settings1 is not settings2
