"""Test Serial Manager."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
import serial

from src.serial_manager import (
    Connection,
    ConnectionStatus,
    SerialManager,
    Task,
)


@pytest.fixture
def serial_manager():
    """Create Serial Manager instance."""
    return SerialManager(
        max_connections=5,
        task_queue_size=10,
        connection_retry_attempts=3,
        default_timeout=1.0,
    )


@pytest.fixture
def mock_serial():
    """Create mock Serial object."""
    mock = MagicMock(spec=serial.Serial)
    mock.is_open = True
    mock.read.return_value = b"test data"
    mock.write.return_value = 9
    mock.timeout = 1.0
    return mock


@pytest.mark.asyncio
async def test_serial_manager_initialization(serial_manager):
    """Test serial manager initialization."""
    assert serial_manager.max_connections == 5
    assert serial_manager.connection_retry_attempts == 3
    assert len(serial_manager.active_connections) == 0
    assert serial_manager.is_busy is False


@pytest.mark.asyncio
async def test_connection_dataclass():
    """Test Connection dataclass."""
    conn = Connection(
        hub_id="hub_01",
        session_id="session_123",
        port_id="port_0",
        device_path="/dev/ttyUSB0",
        baud_rate=115200,
    )

    assert conn.get_device_path() == "/dev/ttyUSB0"
    assert conn.get_baud_rate() == 115200
    assert conn.is_open() is False
    assert conn.status == ConnectionStatus.DISCONNECTED


@pytest.mark.asyncio
async def test_connection_update_activity():
    """Test connection activity update."""
    conn = Connection(
        hub_id="hub_01",
        session_id="session_123",
        port_id="port_0",
        device_path="/dev/ttyUSB0",
        baud_rate=9600,
    )

    initial_time = conn.last_activity_at
    await asyncio.sleep(0.01)
    conn.update_activity()

    assert conn.last_activity_at > initial_time


@pytest.mark.asyncio
async def test_start_and_stop(serial_manager):
    """Test starting and stopping serial manager."""
    await serial_manager.start()
    assert serial_manager._running is True
    assert serial_manager._queue_processor_task is not None

    await serial_manager.stop()
    assert serial_manager._running is False


@pytest.mark.asyncio
async def test_open_connection_success(serial_manager, mock_serial):
    """Test successful connection opening."""
    with patch("serial.Serial", return_value=mock_serial):
        await serial_manager.start()

        result = await serial_manager.open_connection(
            session_id="session_123",
            port_id="port_0",
            device_path="/dev/ttyUSB0",
            baud_rate=115200,
            hub_id="hub_01",
        )

        assert result is True
        assert "port_0" in serial_manager.active_connections
        assert serial_manager.active_connections["port_0"].is_open()

        await serial_manager.stop()


@pytest.mark.asyncio
async def test_open_connection_already_open(serial_manager, mock_serial):
    """Test opening already open connection."""
    with patch("serial.Serial", return_value=mock_serial):
        await serial_manager.start()

        # Open first time
        await serial_manager.open_connection(
            session_id="session_123",
            port_id="port_0",
            device_path="/dev/ttyUSB0",
            baud_rate=115200,
        )

        # Try to open again
        result = await serial_manager.open_connection(
            session_id="session_123",
            port_id="port_0",
            device_path="/dev/ttyUSB0",
            baud_rate=115200,
        )

        assert result is True  # Should succeed (already open)

        await serial_manager.stop()


@pytest.mark.asyncio
async def test_open_connection_max_connections(serial_manager, mock_serial):
    """Test max connections limit."""
    with patch("serial.Serial", return_value=mock_serial):
        await serial_manager.start()

        # Open max connections
        for i in range(5):
            await serial_manager.open_connection(
                session_id=f"session_{i}",
                port_id=f"port_{i}",
                device_path=f"/dev/ttyUSB{i}",
                baud_rate=115200,
            )

        # Try to open one more
        result = await serial_manager.open_connection(
            session_id="session_6",
            port_id="port_6",
            device_path="/dev/ttyUSB6",
            baud_rate=115200,
        )

        assert result is False  # Should fail (max reached)
        assert len(serial_manager.active_connections) == 5

        await serial_manager.stop()


@pytest.mark.asyncio
async def test_open_connection_retry_logic(serial_manager):
    """Test connection retry with exponential backoff."""
    mock_serial = MagicMock(spec=serial.Serial)

    with patch("serial.Serial") as mock_serial_class:
        # First two attempts fail, third succeeds
        mock_serial_class.side_effect = [
            serial.SerialException("Port busy"),
            serial.SerialException("Port busy"),
            mock_serial,
        ]

        await serial_manager.start()

        result = await serial_manager.open_connection(
            session_id="session_123",
            port_id="port_0",
            device_path="/dev/ttyUSB0",
            baud_rate=115200,
        )

        assert result is True
        assert mock_serial_class.call_count == 3

        await serial_manager.stop()


@pytest.mark.asyncio
async def test_open_connection_all_retries_fail(serial_manager):
    """Test connection when all retry attempts fail."""
    with patch("serial.Serial") as mock_serial_class:
        # All attempts fail
        mock_serial_class.side_effect = serial.SerialException("Port not found")

        await serial_manager.start()

        result = await serial_manager.open_connection(
            session_id="session_123",
            port_id="port_0",
            device_path="/dev/ttyUSB0",
            baud_rate=115200,
        )

        assert result is False
        assert mock_serial_class.call_count == 3  # All retry attempts

        await serial_manager.stop()


@pytest.mark.asyncio
async def test_close_connection(serial_manager, mock_serial):
    """Test closing connection."""
    with patch("serial.Serial", return_value=mock_serial):
        await serial_manager.start()

        await serial_manager.open_connection(
            session_id="session_123",
            port_id="port_0",
            device_path="/dev/ttyUSB0",
            baud_rate=115200,
        )

        result = await serial_manager.close_connection("port_0")

        assert result is True
        assert "port_0" not in serial_manager.active_connections
        assert mock_serial.close.called

        await serial_manager.stop()


@pytest.mark.asyncio
async def test_close_connection_not_found(serial_manager):
    """Test closing non-existent connection."""
    await serial_manager.start()

    result = await serial_manager.close_connection("nonexistent")

    assert result is False

    await serial_manager.stop()


@pytest.mark.asyncio
async def test_write_to_port(serial_manager, mock_serial):
    """Test writing to serial port."""
    with patch("serial.Serial", return_value=mock_serial):
        await serial_manager.start()

        await serial_manager.open_connection(
            session_id="session_123",
            port_id="port_0",
            device_path="/dev/ttyUSB0",
            baud_rate=115200,
        )

        data = b"Hello Arduino"
        result = await serial_manager.write_to_port("port_0", data)

        assert result is True
        mock_serial.write.assert_called_once_with(data)

        await serial_manager.stop()


@pytest.mark.asyncio
async def test_write_to_port_not_open(serial_manager):
    """Test writing to unopened port."""
    await serial_manager.start()

    result = await serial_manager.write_to_port("port_0", b"test")

    assert result is False

    await serial_manager.stop()


@pytest.mark.asyncio
async def test_read_from_port(serial_manager, mock_serial):
    """Test reading from serial port."""
    mock_serial.read.return_value = b"Arduino response"

    with patch("serial.Serial", return_value=mock_serial):
        await serial_manager.start()

        await serial_manager.open_connection(
            session_id="session_123",
            port_id="port_0",
            device_path="/dev/ttyUSB0",
            baud_rate=115200,
        )

        data = await serial_manager.read_from_port("port_0", size=100)

        assert data == b"Arduino response"
        mock_serial.read.assert_called_with(100)

        await serial_manager.stop()


@pytest.mark.asyncio
async def test_read_from_port_with_timeout(serial_manager, mock_serial):
    """Test reading with custom timeout."""
    mock_serial.read.return_value = b"data"

    with patch("serial.Serial", return_value=mock_serial):
        await serial_manager.start()

        await serial_manager.open_connection(
            session_id="session_123",
            port_id="port_0",
            device_path="/dev/ttyUSB0",
            baud_rate=115200,
        )

        await serial_manager.read_from_port("port_0", size=100, timeout=2.0)

        assert mock_serial.timeout == 1.0  # Restored to original

        await serial_manager.stop()


@pytest.mark.asyncio
async def test_flush_port(serial_manager, mock_serial):
    """Test flushing port buffers."""
    with patch("serial.Serial", return_value=mock_serial):
        await serial_manager.start()

        await serial_manager.open_connection(
            session_id="session_123",
            port_id="port_0",
            device_path="/dev/ttyUSB0",
            baud_rate=115200,
        )

        result = await serial_manager.flush_port("port_0")

        assert result is True
        assert mock_serial.reset_input_buffer.called
        assert mock_serial.reset_output_buffer.called

        await serial_manager.stop()


@pytest.mark.asyncio
async def test_data_callback(serial_manager, mock_serial):
    """Test data callback invocation."""
    callback_data = []

    async def data_callback(port_id, session_id, data):
        callback_data.append((port_id, session_id, data))

    serial_manager.set_data_callback(data_callback)

    mock_serial.read.return_value = b"callback test"

    with patch("serial.Serial", return_value=mock_serial):
        await serial_manager.start()

        await serial_manager.open_connection(
            session_id="session_123",
            port_id="port_0",
            device_path="/dev/ttyUSB0",
            baud_rate=115200,
        )

        # Let reader task run
        await asyncio.sleep(0.1)

        # Should have received data via callback
        assert len(callback_data) > 0

        await serial_manager.stop()


@pytest.mark.asyncio
async def test_add_task(serial_manager):
    """Test adding task to queue."""
    await serial_manager.start()

    task = Task(
        task_id="task_123",
        task_type="test",
        port_id="port_0",
    )

    task_id = await serial_manager.add_task(task)

    assert task_id == "task_123"
    assert serial_manager.task_queue.qsize() == 1

    await serial_manager.stop()


@pytest.mark.asyncio
async def test_add_task_queue_full(serial_manager):
    """Test adding task when queue is full."""
    await serial_manager.start()

    # Fill queue
    for i in range(10):
        task = Task(task_id=f"task_{i}", task_type="test", port_id="port_0")
        await serial_manager.add_task(task)

    # Try to add one more
    with pytest.raises(asyncio.QueueFull):
        task = Task(task_id="task_overflow", task_type="test", port_id="port_0")
        await serial_manager.add_task(task)

    await serial_manager.stop()


@pytest.mark.asyncio
async def test_get_active_connections(serial_manager, mock_serial):
    """Test getting active connections."""
    with patch("serial.Serial", return_value=mock_serial):
        await serial_manager.start()

        await serial_manager.open_connection(
            session_id="session_1",
            port_id="port_0",
            device_path="/dev/ttyUSB0",
            baud_rate=115200,
        )

        await serial_manager.open_connection(
            session_id="session_2",
            port_id="port_1",
            device_path="/dev/ttyUSB1",
            baud_rate=9600,
        )

        connections = serial_manager.get_active_connections()

        assert len(connections) == 2
        assert "port_0" in connections
        assert "port_1" in connections

        await serial_manager.stop()


@pytest.mark.asyncio
async def test_get_connection_status(serial_manager, mock_serial):
    """Test getting connection status."""
    with patch("serial.Serial", return_value=mock_serial):
        await serial_manager.start()

        await serial_manager.open_connection(
            session_id="session_123",
            port_id="port_0",
            device_path="/dev/ttyUSB0",
            baud_rate=115200,
        )

        status = serial_manager.get_connection_status("port_0")
        assert status == ConnectionStatus.CONNECTED

        status = serial_manager.get_connection_status("nonexistent")
        assert status is None

        await serial_manager.stop()


@pytest.mark.asyncio
async def test_get_connection(serial_manager, mock_serial):
    """Test getting connection object."""
    with patch("serial.Serial", return_value=mock_serial):
        await serial_manager.start()

        await serial_manager.open_connection(
            session_id="session_123",
            port_id="port_0",
            device_path="/dev/ttyUSB0",
            baud_rate=115200,
        )

        conn = serial_manager.get_connection("port_0")
        assert conn is not None
        assert conn.port_id == "port_0"
        assert conn.session_id == "session_123"

        await serial_manager.stop()


@pytest.mark.asyncio
async def test_get_port_error_count(serial_manager, mock_serial):
    """Test getting port error count."""
    with patch("serial.Serial", return_value=mock_serial):
        await serial_manager.start()

        await serial_manager.open_connection(
            session_id="session_123",
            port_id="port_0",
            device_path="/dev/ttyUSB0",
            baud_rate=115200,
        )

        # Initial error count should be 0
        count = serial_manager.get_port_error_count("port_0")
        assert count == 0

        # Simulate an error
        conn = serial_manager.get_connection("port_0")
        conn.error_count = 5

        count = serial_manager.get_port_error_count("port_0")
        assert count == 5

        await serial_manager.stop()


@pytest.mark.asyncio
async def test_task_dataclass():
    """Test Task dataclass."""
    task = Task(
        task_id="task_456",
        task_type="flash",
        port_id="port_0",
        priority=1,
    )

    assert task.get_id() == "task_456"
    assert task.task_type == "flash"
    assert task.status == "pending"
