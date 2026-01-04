"""Test JSON structured logging."""

import json
import logging
from io import StringIO

import pytest

from src.logging_config import (
    CustomJsonFormatter,
    StructuredLogger,
    setup_logging,
    get_logger,
)


@pytest.fixture
def log_stream():
    """Create a string stream for capturing log output."""
    return StringIO()


@pytest.fixture
def json_handler(log_stream):
    """Create a logging handler with JSON formatter."""
    handler = logging.StreamHandler(log_stream)
    formatter = CustomJsonFormatter()
    handler.setFormatter(formatter)
    return handler


def test_custom_json_formatter(json_handler, log_stream):
    """Test custom JSON formatter output."""
    logger = logging.getLogger("test_logger")
    logger.addHandler(json_handler)
    logger.setLevel(logging.INFO)

    logger.info("Test message", extra={"event": "test_event", "context": {"key": "value"}})

    log_stream.seek(0)
    log_output = log_stream.read()
    log_data = json.loads(log_output)

    assert log_data["level"] == "INFO"
    assert log_data["module"] == "test_logger"
    assert log_data["event"] == "test_event"
    assert log_data["context"]["key"] == "value"
    assert "timestamp" in log_data


def test_setup_logging_json():
    """Test setup_logging with JSON format."""
    setup_logging(level="DEBUG", format_type="json")
    logger = logging.getLogger()
    assert logger.level == logging.DEBUG
    assert len(logger.handlers) > 0


def test_setup_logging_text():
    """Test setup_logging with text format."""
    setup_logging(level="INFO", format_type="text")
    logger = logging.getLogger()
    assert logger.level == logging.INFO


def test_get_logger():
    """Test get_logger returns logger instance."""
    logger = get_logger("test_module")
    assert isinstance(logger, logging.Logger)
    assert logger.name == "test_module"


def test_structured_logger_info():
    """Test StructuredLogger info method."""
    logger = StructuredLogger("test")
    # Just verify it doesn't raise an exception
    logger.info("test_event", "Test message", key="value")


def test_structured_logger_debug():
    """Test StructuredLogger debug method."""
    logger = StructuredLogger("test")
    logger.debug("debug_event", "Debug message", detail="info")


def test_structured_logger_warning():
    """Test StructuredLogger warning method."""
    logger = StructuredLogger("test")
    logger.warning("warn_event", "Warning message")


def test_structured_logger_error():
    """Test StructuredLogger error method."""
    logger = StructuredLogger("test")
    logger.error("error_event", "Error message", error_code=500)


def test_structured_logger_critical():
    """Test StructuredLogger critical method."""
    logger = StructuredLogger("test")
    logger.critical("critical_event", "Critical message")


def test_structured_logger_serial_read():
    """Test convenience method for serial_read."""
    logger = StructuredLogger("test")
    logger.serial_read("port_0", 64, "48656c6c6f")


def test_structured_logger_serial_write():
    """Test convenience method for serial_write."""
    logger = StructuredLogger("test")
    logger.serial_write("port_0", 32)


def test_structured_logger_ws_send():
    """Test convenience method for ws_send."""
    logger = StructuredLogger("test")
    logger.ws_send("telemetry", port_id="port_0", bytes=128)


def test_structured_logger_ws_receive():
    """Test convenience method for ws_receive."""
    logger = StructuredLogger("test")
    logger.ws_receive("command", command_id="cmd_123")


def test_structured_logger_task_created():
    """Test convenience method for task_created."""
    logger = StructuredLogger("test")
    logger.task_created("task_123", "serial_write", port_id="port_0")


def test_structured_logger_task_completed():
    """Test convenience method for task_completed."""
    logger = StructuredLogger("test")
    logger.task_completed("task_123", 45.5, "success")


def test_structured_logger_connection_opened():
    """Test convenience method for connection_opened."""
    logger = StructuredLogger("test")
    logger.connection_opened("session_123", "port_0", baud_rate=115200)


def test_structured_logger_connection_failed():
    """Test convenience method for connection_failed."""
    logger = StructuredLogger("test")
    logger.connection_failed("port_0", 2, "Device busy")


def test_structured_logger_port_detected():
    """Test convenience method for port_detected."""
    logger = StructuredLogger("test")
    logger.port_detected("port_0", "/dev/ttyUSB0", vendor_id="2341")


def test_structured_logger_port_removed():
    """Test convenience method for port_removed."""
    logger = StructuredLogger("test")
    logger.port_removed("port_0")


def test_structured_logger_buffer_warning():
    """Test convenience method for buffer_warning."""
    logger = StructuredLogger("test")
    logger.buffer_warning(8.0, 10.0)


def test_structured_logger_buffer_drop():
    """Test convenience method for buffer_drop."""
    logger = StructuredLogger("test")
    logger.buffer_drop(5, "telemetry")
