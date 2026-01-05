"""
Flash task for uploading firmware to Arduino devices.
"""

import asyncio
import os
import tempfile
from typing import Any, Dict, Optional

from .base_task import BaseTask
from ..logging_config import get_logger

logger = get_logger(__name__)


class FlashTask(BaseTask):
    """
    Task for flashing Arduino firmware.
    
    Uses arduino-cli to upload .hex files to Arduino devices.
    Handles temporary file creation, board detection, and upload process.
    """
    
    def __init__(
        self,
        task_id: str,
        port_id: str,
        firmware_data: str,
        board_fqbn: Optional[str] = None,
        priority: int = 3,
        params: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize flash task.
        
        Args:
            task_id: Unique task identifier
            port_id: Target port ID to flash
            firmware_data: Base64 encoded firmware hex file
            board_fqbn: Board FQBN (e.g., "arduino:avr:uno"), auto-detect if None
            priority: Task priority (default: 3, higher priority than serial_write)
            params: Additional task parameters
        """
        super().__init__(
            task_id=task_id,
            command_type="flash",
            port_id=port_id,
            params=params,
            priority=priority
        )
        
        self.firmware_data = firmware_data
        self.board_fqbn = board_fqbn
        
        logger.debug(
            f"FlashTask created",
            extra={
                "task_id": task_id,
                "port_id": port_id,
                "board_fqbn": board_fqbn,
                "firmware_size": len(firmware_data)
            }
        )
    
    async def execute(self) -> Dict[str, Any]:
        """
        Execute firmware flash operation.
        
        Returns:
            Dict containing flash result (board_fqbn, flash_duration_ms)
            
        Raises:
            RuntimeError: If flash operation fails
            ValueError: If port or board detection fails
        """
        # Import here to avoid circular dependency
        from ..serial_manager import get_serial_manager
        from ..usb_port_mapper import get_usb_port_mapper
        
        serial_manager = get_serial_manager()
        usb_mapper = get_usb_port_mapper()
        
        # Get port path from USB mapper
        device_info = await usb_mapper.get_device_info(self.port_id)
        if not device_info:
            raise ValueError(f"Port ID not found: {self.port_id}")
        
        port_path = device_info.device_path
        
        logger.info(
            f"Starting firmware flash",
            extra={
                "task_id": self.task_id,
                "port_id": self.port_id,
                "port_path": port_path,
                "board_fqbn": self.board_fqbn
            }
        )
        
        # Close serial connection if open
        await serial_manager.close_connection(self.port_id)
        
        # Wait for port to settle
        await asyncio.sleep(0.5)
        
        # Decode firmware data
        import base64
        firmware_bytes = base64.b64decode(self.firmware_data)
        
        # Write firmware to temporary file
        with tempfile.NamedTemporaryFile(
            mode='wb',
            suffix='.hex',
            delete=False
        ) as temp_file:
            temp_file.write(firmware_bytes)
            temp_file_path = temp_file.name
        
        try:
            # Auto-detect board if FQBN not provided
            board_fqbn = self.board_fqbn
            if not board_fqbn:
                logger.info(
                    f"Auto-detecting board FQBN",
                    extra={"task_id": self.task_id, "port_path": port_path}
                )
                board_fqbn = await self._detect_board_fqbn(port_path)
                logger.info(
                    f"Detected board FQBN: {board_fqbn}",
                    extra={"task_id": self.task_id, "board_fqbn": board_fqbn}
                )
            
            # Flash firmware using arduino-cli
            flash_result = await self._flash_firmware(
                port_path=port_path,
                firmware_path=temp_file_path,
                board_fqbn=board_fqbn
            )
            
            logger.info(
                f"Firmware flash completed",
                extra={
                    "task_id": self.task_id,
                    "port_id": self.port_id,
                    "board_fqbn": board_fqbn,
                    **flash_result
                }
            )
            
            return {
                "port_id": self.port_id,
                "board_fqbn": board_fqbn,
                **flash_result
            }
            
        finally:
            # Clean up temporary file
            try:
                os.unlink(temp_file_path)
            except Exception as e:
                logger.warning(
                    f"Failed to delete temp file: {e}",
                    extra={"temp_file": temp_file_path}
                )
    
    async def _detect_board_fqbn(self, port_path: str) -> str:
        """
        Auto-detect board FQBN using arduino-cli.
        
        Args:
            port_path: Serial port path
            
        Returns:
            Detected board FQBN
            
        Raises:
            RuntimeError: If board detection fails
        """
        try:
            process = await asyncio.create_subprocess_exec(
                "arduino-cli",
                "board",
                "list",
                "--format",
                "json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                raise RuntimeError(f"arduino-cli board list failed: {error_msg}")
            
            import json
            boards = json.loads(stdout.decode())
            
            # Find matching port
            for board in boards:
                if board.get("port", {}).get("address") == port_path:
                    matching_boards = board.get("matching_boards", [])
                    if matching_boards:
                        return matching_boards[0].get("fqbn")
            
            raise RuntimeError(f"No board detected on port {port_path}")
            
        except Exception as e:
            logger.error(
                f"Board detection failed: {e}",
                extra={"port_path": port_path},
                exc_info=True
            )
            raise RuntimeError(f"Failed to detect board FQBN: {e}")
    
    async def _flash_firmware(
        self,
        port_path: str,
        firmware_path: str,
        board_fqbn: str
    ) -> Dict[str, Any]:
        """
        Flash firmware using arduino-cli upload.
        
        Args:
            port_path: Serial port path
            firmware_path: Path to .hex firmware file
            board_fqbn: Board FQBN
            
        Returns:
            Dict containing flash duration and output
            
        Raises:
            RuntimeError: If flash fails
        """
        import time
        start_time = time.time()
        
        try:
            process = await asyncio.create_subprocess_exec(
                "arduino-cli",
                "upload",
                "-p", port_path,
                "-b", board_fqbn,
                "-i", firmware_path,
                "--verify",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=120.0  # 2 minute timeout for flash
            )
            
            duration_ms = int((time.time() - start_time) * 1000)
            
            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                raise RuntimeError(f"arduino-cli upload failed: {error_msg}")
            
            output = stdout.decode() if stdout else ""
            
            return {
                "flash_duration_ms": duration_ms,
                "output": output.strip()
            }
            
        except asyncio.TimeoutError:
            raise RuntimeError("Firmware flash timeout (120s exceeded)")
        except Exception as e:
            logger.error(
                f"Firmware flash failed: {e}",
                extra={
                    "port_path": port_path,
                    "board_fqbn": board_fqbn
                },
                exc_info=True
            )
            raise RuntimeError(f"Failed to flash firmware: {e}")
