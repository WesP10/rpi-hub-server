"""Pytest configuration and shared fixtures."""

import pytest


@pytest.fixture
def mock_serial_port():
    """Mock pyserial Serial object."""
    from unittest.mock import MagicMock

    port = MagicMock()
    port.is_open = True
    port.read.return_value = b"test data"
    port.write.return_value = 9
    return port


@pytest.fixture
def mock_arduino_cli_output():
    """Mock arduino-cli board list output."""
    return {
        "detected_ports": [
            {
                "matching_boards": [{"name": "Arduino Uno", "fqbn": "arduino:avr:uno"}],
                "port": {
                    "address": "/dev/ttyUSB0",
                    "label": "/dev/ttyUSB0",
                    "protocol": "serial",
                    "protocol_label": "Serial Port (USB)",
                    "properties": {
                        "pid": "0043",
                        "vid": "2341",
                        "serialNumber": "12345",
                    },
                },
            }
        ]
    }


@pytest.fixture
def sample_config():
    """Sample configuration dictionary."""
    return {
        "hub": {
            "hub_id": "test-hub-01",
            "server_endpoint": "ws://test:8080/hub",
            "device_token": "test-token",
        },
        "serial": {
            "default_baud_rate": 9600,
            "scan_interval": 2,
        },
        "buffer": {
            "size_mb": 10,
            "warn_threshold": 0.8,
        },
    }
