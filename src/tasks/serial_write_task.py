"""
Serial write task for sending data to Arduino devices.
"""

from typing import Any, Dict, Optional

from .base_task import BaseTask
from ..logging_config import get_logger

logger = get_logger(__name__)


class SerialWriteTask(BaseTask):
    """
    Task for writing data to a serial port.
    
    Sends data to the specified Arduino device via Serial Manager.
    Supports both string and binary data transmission.
    """
    
    def __init__(
        self,
        task_id: str,
        port_id: str,
        data: str,
        encoding: str = "utf-8",
        priority: int = 5,
        params: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize serial write task.
        
        Args:
            task_id: Unique task identifier
            port_id: Target port ID to write to
            data: Data to write (string or base64 encoded binary)
            encoding: Data encoding (utf-8 or base64)
            priority: Task priority
            params: Additional task parameters
        """
        super().__init__(
            task_id=task_id,
            command_type="serial_write",
            port_id=port_id,
            params=params,
            priority=priority
        )
        
        self.data = data
        self.encoding = encoding
        
        # Validate encoding
        if encoding not in ["utf-8", "base64"]:
            raise ValueError(f"Unsupported encoding: {encoding}")
        
        logger.debug(
            f"SerialWriteTask created",
            extra={
                "task_id": task_id,
                "port_id": port_id,
                "data_length": len(data),
                "encoding": encoding
            }
        )
    
    async def execute(self) -> Dict[str, Any]:
        """
        Execute serial write operation.
        
        Returns:
            Dict containing write result (bytes_written)
            
        Raises:
            ValueError: If port_id is invalid or port not connected
            RuntimeError: If write operation fails
        """
        # Import here to avoid circular dependency
        from ..serial_manager import get_serial_manager
        
        serial_manager = get_serial_manager()
        
        # Decode data based on encoding
        if self.encoding == "base64":
            import base64
            data_bytes = base64.b64decode(self.data)
        else:
            data_bytes = self.data.encode(self.encoding)
        
        logger.info(
            f"Writing to serial port",
            extra={
                "task_id": self.task_id,
                "port_id": self.port_id,
                "bytes_to_write": len(data_bytes),
                "encoding": self.encoding
            }
        )
        
        # Write to serial port via Serial Manager
        try:
            bytes_written = await serial_manager.write_to_port(
                port_id=self.port_id,
                data=data_bytes
            )
            
            logger.info(
                f"Serial write completed",
                extra={
                    "task_id": self.task_id,
                    "port_id": self.port_id,
                    "bytes_written": bytes_written
                }
            )
            
            return {
                "port_id": self.port_id,
                "bytes_written": bytes_written,
                "encoding": self.encoding
            }
            
        except Exception as e:
            logger.error(
                f"Serial write failed: {e}",
                extra={
                    "task_id": self.task_id,
                    "port_id": self.port_id,
                    "error": str(e)
                }
            )
            raise RuntimeError(f"Failed to write to port {self.port_id}: {e}")
