"""
Restart task for resetting Arduino devices.
"""

import asyncio
from typing import Any, Dict, Optional

from .base_task import BaseTask
from ..logging_config import get_logger

logger = get_logger(__name__)


class RestartTask(BaseTask):
    """
    Task for restarting Arduino devices.
    
    Performs device restart by toggling DTR signal on serial port.
    This triggers the Arduino bootloader reset sequence.
    """
    
    def __init__(
        self,
        task_id: str,
        port_id: str,
        priority: int = 2,
        params: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize restart task.
        
        Args:
            task_id: Unique task identifier
            port_id: Target port ID to restart
            priority: Task priority (default: 2, higher than flash)
            params: Additional task parameters
        """
        super().__init__(
            task_id=task_id,
            command_type="restart",
            port_id=port_id,
            params=params,
            priority=priority
        )
        
        logger.debug(
            f"RestartTask created",
            extra={"task_id": task_id, "port_id": port_id}
        )
    
    async def execute(self) -> Dict[str, Any]:
        """
        Execute device restart operation.
        
        Returns:
            Dict containing restart result
            
        Raises:
            ValueError: If port_id is invalid
            RuntimeError: If restart operation fails
        """
        # Import here to avoid circular dependency
        from ..serial_manager import get_serial_manager
        from ..usb_port_mapper import get_usb_port_mapper
        
        serial_manager = get_serial_manager()
        usb_mapper = get_usb_port_mapper()
        
        # Get port path from USB mapper
        device = usb_mapper.get_device_by_id(self.port_id)
        if not device:
            raise ValueError(f"Port ID not found: {self.port_id}")
        
        port_path = device["port"]
        
        logger.info(
            f"Starting device restart",
            extra={
                "task_id": self.task_id,
                "port_id": self.port_id,
                "port_path": port_path
            }
        )
        
        try:
            # Close existing connection
            await serial_manager.close_connection(self.port_id)
            
            # Wait for port to settle
            await asyncio.sleep(0.2)
            
            # Perform DTR toggle to restart device
            await self._toggle_dtr(port_path)
            
            # Wait for device to restart
            await asyncio.sleep(2.0)
            
            logger.info(
                f"Device restart completed",
                extra={"task_id": self.task_id, "port_id": self.port_id}
            )
            
            return {
                "port_id": self.port_id,
                "restart_method": "dtr_toggle",
                "restart_completed": True
            }
            
        except Exception as e:
            logger.error(
                f"Device restart failed: {e}",
                extra={
                    "task_id": self.task_id,
                    "port_id": self.port_id,
                    "error": str(e)
                },
                exc_info=True
            )
            raise RuntimeError(f"Failed to restart device {self.port_id}: {e}")
    
    async def _toggle_dtr(self, port_path: str) -> None:
        """
        Toggle DTR signal to restart Arduino device.
        
        Args:
            port_path: Serial port path
            
        Raises:
            RuntimeError: If DTR toggle fails
        """
        try:
            import serial
            
            # Open port with DTR control
            ser = serial.Serial(
                port=port_path,
                baudrate=1200,  # Low baud rate for bootloader reset
                timeout=1
            )
            
            try:
                # Toggle DTR: High -> Low -> High
                ser.dtr = True
                await asyncio.sleep(0.1)
                ser.dtr = False
                await asyncio.sleep(0.1)
                ser.dtr = True
                await asyncio.sleep(0.1)
                
                logger.debug(
                    f"DTR toggle completed",
                    extra={"port_path": port_path}
                )
                
            finally:
                ser.close()
                
        except Exception as e:
            logger.error(
                f"DTR toggle failed: {e}",
                extra={"port_path": port_path},
                exc_info=True
            )
            raise RuntimeError(f"Failed to toggle DTR on {port_path}: {e}")
