"""Serial Manager with connection pooling and task queue."""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, Optional

import serial

from src.logging_config import StructuredLogger


class ConnectionStatus(Enum):
    """Connection status enumeration."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class Connection:
    """Serial connection information."""

    hub_id: str
    session_id: str
    port_id: str
    device_path: str
    baud_rate: int
    data_bits: int = 8
    stop_bits: int = 1
    parity: str = "N"  # N, E, O, M, S
    timeout: float = 1.0
    set_port_script_path: Optional[str] = None
    serial_port: Optional[serial.Serial] = None
    created_at: datetime = field(default_factory=datetime.now)
    last_activity_at: datetime = field(default_factory=datetime.now)
    status: ConnectionStatus = ConnectionStatus.DISCONNECTED
    error_count: int = 0

    def get_device_path(self) -> str:
        """Get device path."""
        return self.device_path

    def get_baud_rate(self) -> int:
        """Get baud rate."""
        return self.baud_rate

    def is_open(self) -> bool:
        """Check if connection is open."""
        return (
            self.serial_port is not None
            and self.serial_port.is_open
            and self.status == ConnectionStatus.CONNECTED
        )

    def update_activity(self) -> None:
        """Update last activity timestamp."""
        self.last_activity_at = datetime.now()


@dataclass
class Task:
    """Base task for serial operations."""

    task_id: str
    task_type: str
    port_id: str
    priority: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    status: str = "pending"

    def get_id(self) -> str:
        """Get task ID."""
        return self.task_id


class SerialManager:
    """Manages serial port connections and operations."""

    def __init__(
        self,
        max_connections: int = 10,
        task_queue_size: int = 100,
        connection_retry_attempts: int = 3,
        default_timeout: float = 1.0,
    ):
        """Initialize Serial Manager.

        Args:
            max_connections: Maximum simultaneous connections
            task_queue_size: Maximum task queue size
            connection_retry_attempts: Number of retry attempts
            default_timeout: Default serial timeout
        """
        self.logger = StructuredLogger(__name__)
        self.max_connections = max_connections
        self.connection_retry_attempts = connection_retry_attempts
        self.default_timeout = default_timeout

        # Connection pool
        self.active_connections: Dict[str, Connection] = {}

        # Task queue
        self.task_queue: asyncio.Queue = asyncio.Queue(maxsize=task_queue_size)
        self.is_busy = False

        # Reader tasks
        self._reader_tasks: Dict[str, asyncio.Task] = {}
        self._queue_processor_task: Optional[asyncio.Task] = None
        self._running = False

        # Data callback for routing serial data
        self._data_callback: Optional[Callable] = None

        self.logger.info(
            "serial_manager_initialized",
            "Serial Manager initialized",
            max_connections=max_connections,
            task_queue_size=task_queue_size,
        )

    async def start(self) -> None:
        """Start serial manager and task processing."""
        self._running = True
        self._queue_processor_task = asyncio.create_task(self._process_task_queue())
        self.logger.info("serial_manager_started", "Serial Manager started")

    async def stop(self) -> None:
        """Stop serial manager and close all connections."""
        self._running = False

        # Stop queue processor
        if self._queue_processor_task:
            self._queue_processor_task.cancel()
            try:
                await self._queue_processor_task
            except asyncio.CancelledError:
                pass

        # Close all connections
        for port_id in list(self.active_connections.keys()):
            await self.close_connection(port_id)

        self.logger.info("serial_manager_stopped", "Serial Manager stopped")

    def set_data_callback(self, callback: Callable) -> None:
        """Set callback for received serial data.

        Args:
            callback: Async function(port_id: str, session_id: str, data: bytes)
        """
        self._data_callback = callback

    async def open_connection(
        self,
        session_id: str,
        port_id: str,
        device_path: str,
        baud_rate: int,
        hub_id: str = "",
        **kwargs: Any,
    ) -> bool:
        """Open serial connection with retry logic.

        Args:
            session_id: Session identifier
            port_id: Port identifier
            device_path: Device path (e.g., /dev/ttyUSB0)
            baud_rate: Baud rate
            hub_id: Hub identifier
            **kwargs: Additional serial parameters

        Returns:
            True if connection opened successfully
        """
        # Check if already connected
        if port_id in self.active_connections:
            existing = self.active_connections[port_id]
            if existing.is_open():
                self.logger.warning(
                    "connection_already_open",
                    f"Connection already open on {port_id}",
                    port_id=port_id,
                    session_id=session_id,
                )
                return True

        # Check max connections
        if len(self.active_connections) >= self.max_connections:
            self.logger.error(
                "max_connections_reached",
                f"Maximum connections ({self.max_connections}) reached",
                max_connections=self.max_connections,
            )
            return False

        # Create connection object
        connection = Connection(
            hub_id=hub_id,
            session_id=session_id,
            port_id=port_id,
            device_path=device_path,
            baud_rate=baud_rate,
            data_bits=kwargs.get("data_bits", 8),
            stop_bits=kwargs.get("stop_bits", 1),
            parity=kwargs.get("parity", "N"),
            timeout=kwargs.get("timeout", self.default_timeout),
            set_port_script_path=kwargs.get("set_port_script_path"),
        )

        self.logger.info(
            "connection_requested",
            f"Opening connection on {port_id}",
            session_id=session_id,
            port_id=port_id,
            device_path=device_path,
            baud_rate=baud_rate,
        )

        # Attempt connection with retry logic
        for attempt in range(1, self.connection_retry_attempts + 1):
            try:
                connection.status = ConnectionStatus.CONNECTING

                # Open serial port
                ser = serial.Serial(
                    port=device_path,
                    baudrate=baud_rate,
                    bytesize=connection.data_bits,
                    stopbits=connection.stop_bits,
                    parity=connection.parity,
                    timeout=connection.timeout,
                )

                # Reset Arduino by toggling DTR (required for auto-start on RPi)
                # This mimics Windows behavior and resets the Arduino
                ser.dtr = False
                await asyncio.sleep(0.1)  # Brief delay
                ser.dtr = True
                await asyncio.sleep(2)  # Wait for Arduino to reset and start sketch

                connection.serial_port = ser
                connection.status = ConnectionStatus.CONNECTED
                self.active_connections[port_id] = connection

                # Start reader task
                reader_task = asyncio.create_task(
                    self._read_continuously(port_id)
                )
                self._reader_tasks[port_id] = reader_task

                self.logger.connection_opened(
                    session_id,
                    port_id,
                    device_path=device_path,
                    baud_rate=baud_rate,
                    attempt=attempt,
                )

                return True

            except serial.SerialException as e:
                connection.status = ConnectionStatus.ERROR
                connection.error_count += 1

                if attempt < self.connection_retry_attempts:
                    # Exponential backoff: 1s, 2s, 4s
                    delay = 2 ** (attempt - 1)
                    self.logger.info(
                        "connection_retry",
                        f"Connection failed on {port_id}, retrying in {delay}s",
                        port_id=port_id,
                        attempt=attempt,
                        next_delay_s=delay,
                        error=str(e),
                    )
                    await asyncio.sleep(delay)
                else:
                    # Final attempt failed
                    self.logger.connection_failed(
                        port_id,
                        attempt,
                        str(e),
                        device_path=device_path,
                    )

            except Exception as e:
                connection.status = ConnectionStatus.ERROR
                self.logger.error(
                    "connection_error",
                    f"Unexpected error opening {port_id}: {e}",
                    port_id=port_id,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                break

        # All attempts failed
        self.logger.error(
            "connection_abandoned",
            f"Abandoned connection attempts on {port_id}",
            port_id=port_id,
            attempts=self.connection_retry_attempts,
        )

        return False

    async def close_connection(self, port_id: str) -> bool:
        """Close serial connection.

        Args:
            port_id: Port identifier

        Returns:
            True if closed successfully
        """
        connection = self.active_connections.get(port_id)
        if not connection:
            self.logger.warning(
                "connection_not_found",
                f"Connection {port_id} not found",
                port_id=port_id,
            )
            return False

        try:
            # Stop reader task
            if port_id in self._reader_tasks:
                self._reader_tasks[port_id].cancel()
                try:
                    await self._reader_tasks[port_id]
                except asyncio.CancelledError:
                    pass
                del self._reader_tasks[port_id]

            # Close serial port
            if connection.serial_port and connection.serial_port.is_open:
                connection.serial_port.close()

            connection.status = ConnectionStatus.DISCONNECTED
            del self.active_connections[port_id]

            self.logger.info(
                "connection_closed",
                f"Connection {port_id} closed",
                port_id=port_id,
                session_id=connection.session_id,
            )

            return True

        except Exception as e:
            self.logger.error(
                "connection_close_error",
                f"Error closing {port_id}: {e}",
                port_id=port_id,
                error=str(e),
            )
            return False

    async def _read_continuously(self, port_id: str) -> None:
        """Continuously read from serial port.

        Args:
            port_id: Port identifier
        """
        connection = self.active_connections.get(port_id)
        if not connection or not connection.serial_port:
            return

        self.logger.debug(
            "reader_started",
            f"Started reading from {port_id}",
            port_id=port_id,
        )

        loop = asyncio.get_event_loop()

        while self._running and connection.is_open():
            try:
                # Read in executor to avoid blocking
                data = await loop.run_in_executor(
                    None, connection.serial_port.read, 1024
                )

                if data:
                    connection.update_activity()
                    data_hex = data.hex()

                    self.logger.serial_read(
                        port_id,
                        len(data),
                        data_hex,
                    )

                    # Send to callback if registered
                    if self._data_callback:
                        try:
                            if asyncio.iscoroutinefunction(self._data_callback):
                                await self._data_callback(port_id, connection.session_id, data)
                            else:
                                self._data_callback(port_id, connection.session_id, data)
                        except Exception as e:
                            self.logger.error(
                                "data_callback_error",
                                f"Error in data callback: {e}",
                                port_id=port_id,
                                error=str(e),
                            )

                else:
                    # Small delay when no data
                    await asyncio.sleep(0.01)

            except serial.SerialException as e:
                self.logger.error(
                    "serial_read_error",
                    f"Serial read error on {port_id}: {e}",
                    port_id=port_id,
                    error=str(e),
                )
                connection.status = ConnectionStatus.ERROR
                connection.error_count += 1
                break

            except asyncio.CancelledError:
                break

            except Exception as e:
                self.logger.error(
                    "reader_error",
                    f"Unexpected error reading {port_id}: {e}",
                    port_id=port_id,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                break

        self.logger.debug(
            "reader_stopped",
            f"Stopped reading from {port_id}",
            port_id=port_id,
        )

    async def write_to_port(self, port_id: str, data: bytes) -> bool:
        """Write data to serial port.

        Args:
            port_id: Port identifier
            data: Data to write

        Returns:
            True if write successful
        """
        connection = self.active_connections.get(port_id)
        if not connection or not connection.is_open():
            self.logger.error(
                "write_connection_not_open",
                f"Connection {port_id} not open",
                port_id=port_id,
            )
            return False

        try:
            loop = asyncio.get_event_loop()
            bytes_written = await loop.run_in_executor(
                None, connection.serial_port.write, data
            )

            connection.update_activity()
            self.logger.serial_write(port_id, bytes_written)

            return True

        except serial.SerialException as e:
            connection.status = ConnectionStatus.ERROR
            connection.error_count += 1
            self.logger.error(
                "serial_write_error",
                f"Serial write error on {port_id}: {e}",
                port_id=port_id,
                error=str(e),
            )
            return False

        except Exception as e:
            self.logger.error(
                "write_error",
                f"Unexpected write error on {port_id}: {e}",
                port_id=port_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            return False

    async def read_from_port(
        self, port_id: str, size: int = 1024, timeout: Optional[float] = None
    ) -> Optional[bytes]:
        """Read data from serial port.

        Args:
            port_id: Port identifier
            size: Maximum bytes to read
            timeout: Read timeout (uses connection default if None)

        Returns:
            Data read or None on error
        """
        connection = self.active_connections.get(port_id)
        if not connection or not connection.is_open():
            self.logger.error(
                "read_connection_not_open",
                f"Connection {port_id} not open",
                port_id=port_id,
            )
            return None

        try:
            # Set timeout if specified
            if timeout is not None:
                original_timeout = connection.serial_port.timeout
                connection.serial_port.timeout = timeout

            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(
                None, connection.serial_port.read, size
            )

            # Restore original timeout
            if timeout is not None:
                connection.serial_port.timeout = original_timeout

            if data:
                connection.update_activity()
                self.logger.serial_read(port_id, len(data), data.hex())

            return data

        except Exception as e:
            self.logger.error(
                "read_error",
                f"Error reading from {port_id}: {e}",
                port_id=port_id,
                error=str(e),
            )
            return None

    async def flush_port(self, port_id: str) -> bool:
        """Flush serial port buffers.

        Args:
            port_id: Port identifier

        Returns:
            True if successful
        """
        connection = self.active_connections.get(port_id)
        if not connection or not connection.is_open():
            return False

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, connection.serial_port.reset_input_buffer)
            await loop.run_in_executor(None, connection.serial_port.reset_output_buffer)

            self.logger.debug(
                "port_flushed",
                f"Flushed buffers on {port_id}",
                port_id=port_id,
            )

            return True

        except Exception as e:
            self.logger.error(
                "flush_error",
                f"Error flushing {port_id}: {e}",
                port_id=port_id,
                error=str(e),
            )
            return False

    async def add_task(self, task: Task) -> str:
        """Add task to queue.

        Args:
            task: Task to add

        Returns:
            Task ID
        """
        try:
            await self.task_queue.put(task)
            self.logger.info(
                "task_queued",
                f"Task {task.task_id} queued",
                task_id=task.task_id,
                task_type=task.task_type,
                port_id=task.port_id,
                queue_size=self.task_queue.qsize(),
            )
            return task.task_id

        except asyncio.QueueFull:
            self.logger.error(
                "task_queue_full",
                "Task queue is full",
                task_id=task.task_id,
            )
            raise

    async def _process_task_queue(self) -> None:
        """Process tasks from queue."""
        self.logger.info("task_processor_started", "Task queue processor started")

        while self._running:
            try:
                # Get task with timeout
                task = await asyncio.wait_for(
                    self.task_queue.get(), timeout=1.0
                )

                self.is_busy = True
                self.logger.info(
                    "task_processing",
                    f"Processing task {task.task_id}",
                    task_id=task.task_id,
                    task_type=task.task_type,
                )

                # Process task (basic implementation, extended by task types)
                # Task execution is handled by task objects themselves
                task.status = "completed"

                self.is_busy = False
                self.task_queue.task_done()

            except asyncio.TimeoutError:
                # No tasks available, continue
                continue

            except asyncio.CancelledError:
                break

            except Exception as e:
                self.logger.error(
                    "task_processing_error",
                    f"Error processing task: {e}",
                    error=str(e),
                )
                self.is_busy = False

        self.logger.info("task_processor_stopped", "Task queue processor stopped")

    def get_active_connections(self) -> Dict[str, Connection]:
        """Get all active connections.

        Returns:
            Dictionary of active connections
        """
        return self.active_connections.copy()

    def get_connection_status(self, port_id: str) -> Optional[ConnectionStatus]:
        """Get connection status.

        Args:
            port_id: Port identifier

        Returns:
            Connection status or None
        """
        connection = self.active_connections.get(port_id)
        return connection.status if connection else None

    def get_connection(self, port_id: str) -> Optional[Connection]:
        """Get connection by port ID.

        Args:
            port_id: Port identifier

        Returns:
            Connection or None
        """
        return self.active_connections.get(port_id)

    def get_port_error_count(self, port_id: str) -> int:
        """Get error count for a port.

        Args:
            port_id: Port identifier

        Returns:
            Error count
        """
        connection = self.active_connections.get(port_id)
        return connection.error_count if connection else 0


# Global serial manager instance
_serial_manager: Optional[SerialManager] = None


def get_serial_manager() -> SerialManager:
    """Get global Serial Manager instance.

    Returns:
        SerialManager instance

    Raises:
        RuntimeError: If serial manager not initialized
    """
    if _serial_manager is None:
        raise RuntimeError(
            "SerialManager not initialized. Call initialize_serial_manager() first."
        )
    return _serial_manager


def initialize_serial_manager(
    max_connections: int = 10,
    task_queue_size: int = 100,
    connection_retry_attempts: int = 3,
    default_timeout: float = 1.0,
) -> SerialManager:
    """Initialize Serial Manager instance.

    Args:
        max_connections: Maximum simultaneous connections
        task_queue_size: Maximum task queue size
        connection_retry_attempts: Number of retry attempts
        default_timeout: Default serial timeout

    Returns:
        SerialManager instance
    """
    global _serial_manager
    
    if _serial_manager is not None:
        return _serial_manager
    
    from src.config import get_settings

    settings = get_settings()
    _serial_manager = SerialManager(
        max_connections=max_connections or settings.serial.max_connections,
        task_queue_size=task_queue_size or settings.serial.task_queue_size,
        connection_retry_attempts=connection_retry_attempts or settings.serial.connection_retry_attempts,
        default_timeout=default_timeout or settings.serial.default_timeout,
    )
    
    return _serial_manager
