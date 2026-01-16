"""
Flash task for uploading firmware to Arduino devices.
"""

import asyncio
import os
import tempfile
import shutil
from typing import Any, Dict, Optional

from .base_task import BaseTask
from ..logging_config import get_logger

logger = get_logger(__name__)


class FlashTask(BaseTask):
    """
    Task for flashing Arduino firmware.
    
    Uses arduino-cli to compile .ino source files and upload to Arduino devices.
    Handles both pre-compiled .hex files and .ino source code compilation.
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
            firmware_data: Base64 encoded .ino source or .hex firmware file
            board_fqbn: Board FQBN (e.g., "arduino:avr:uno"), required for .ino compilation
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
    
    def _validate_intel_hex(self, content: str) -> bool:
        """
        Strictly validate Intel HEX format.
        
        Args:
            content: Decoded file content
            
        Returns:
            True if valid Intel HEX, False otherwise
        """
        lines = [line.strip() for line in content.strip().split('\n') if line.strip()]
        
        if not lines:
            return False
        
        # All non-empty lines must start with ':' and contain only hex chars
        for line in lines:
            if not line.startswith(':'):
                return False
            # Check if rest of line is valid hex (after ':')
            hex_part = line[1:]
            if not hex_part or not all(c in '0123456789ABCDEFabcdef' for c in hex_part):
                return False
            # Basic length check (minimum Intel HEX line is 11 chars: :BBAAAATTCCSS)
            if len(hex_part) < 10:
                return False
        
        # Last line should be EOF record (:00000001FF)
        if lines[-1].upper() != ':00000001FF':
            logger.warning(
                "Intel HEX file missing standard EOF record",
                extra={"task_id": self.task_id}
            )
        
        return True
    
    def _validate_ino_source(self, content: str) -> bool:
        """
        Validate that content looks like Arduino source code.
        
        Args:
            content: Decoded file content
            
        Returns:
            True if valid .ino source, False otherwise
        """
        # Basic checks for Arduino code
        content_lower = content.lower()
        
        # Should contain typical Arduino keywords
        has_arduino_keywords = any(keyword in content_lower for keyword in [
            'void setup', 'void loop', 'digitalwrite', 'digitalread',
            'analogwrite', 'analogread', 'serial.', 'pinmode'
        ])
        
        # Should NOT look like Intel HEX
        lines = [line.strip() for line in content.strip().split('\n')[:5] if line.strip()]
        looks_like_hex = all(line.startswith(':') for line in lines) if lines else False
        
        # Should contain C/C++ code patterns
        has_code_patterns = any(pattern in content for pattern in [
            '{', '}', '(', ')', ';'
        ])
        
        return has_arduino_keywords or (has_code_patterns and not looks_like_hex)
    
    async def _write_hex_to_temp(self, firmware_bytes: bytes) -> str:
        """
        Write .hex firmware to a temporary file.
        
        Args:
            firmware_bytes: Raw firmware bytes
            
        Returns:
            Path to temporary .hex file
        """
        with tempfile.NamedTemporaryFile(
            mode='wb',
            suffix='.hex',
            delete=False
        ) as temp_file:
            temp_file.write(firmware_bytes)
            return temp_file.name
    
    async def _compile_and_prepare_firmware(
        self,
        firmware_bytes: bytes,
        board_fqbn: str
    ) -> str:
        """
        Compile .ino source code to .hex using arduino-cli.
        
        Args:
            firmware_bytes: Raw .ino source code bytes
            board_fqbn: Board FQBN for compilation
            
        Returns:
            Path to compiled .hex file
            
        Raises:
            RuntimeError: If compilation fails
        """
        import time
        
        # Create temporary directory for sketch (minimal lifetime)
        sketch_dir = tempfile.mkdtemp(prefix='arduino_sketch_')
        sketch_file = os.path.join(sketch_dir, 'sketch.ino')
        
        try:
            # Write .ino source to file (only when necessary for compilation)
            with open(sketch_file, 'wb') as f:
                f.write(firmware_bytes)
            
            logger.info(
                f"Compiling Arduino sketch",
                extra={
                    "task_id": self.task_id,
                    "board_fqbn": board_fqbn,
                    "sketch_dir": sketch_dir
                }
            )
            
            start_time = time.time()
            
            # Compile using arduino-cli
            process = await asyncio.create_subprocess_exec(
                "arduino-cli",
                "compile",
                "--fqbn", board_fqbn,
                "--output-dir", sketch_dir,
                sketch_file,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=300.0  # 5 minute timeout for compilation
            )
            
            compile_duration_ms = int((time.time() - start_time) * 1000)
            
            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                logger.error(
                    f"Compilation failed: {error_msg}",
                    extra={
                        "task_id": self.task_id,
                        "board_fqbn": board_fqbn,
                        "compile_output": stdout.decode() if stdout else ""
                    }
                )
                raise RuntimeError(f"arduino-cli compile failed: {error_msg}")
            
            logger.info(
                f"Compilation successful",
                extra={
                    "task_id": self.task_id,
                    "compile_duration_ms": compile_duration_ms
                }
            )
            
            # Find the compiled .hex file
            hex_file = os.path.join(sketch_dir, 'sketch.ino.hex')
            if not os.path.exists(hex_file):
                # Try alternative naming (some boards use different names)
                hex_files = [f for f in os.listdir(sketch_dir) if f.endswith('.hex')]
                if not hex_files:
                    raise RuntimeError("Compiled .hex file not found after compilation")
                hex_file = os.path.join(sketch_dir, hex_files[0])
            
            # Copy to a safe temporary location (sketch_dir will be cleaned up)
            final_hex = tempfile.NamedTemporaryFile(
                mode='wb',
                suffix='.hex',
                delete=False
            )
            with open(hex_file, 'rb') as src:
                shutil.copyfileobj(src, final_hex)
            final_hex.close()
            
            return final_hex.name
            
        except asyncio.TimeoutError:
            raise RuntimeError("Compilation timeout (300s exceeded)")
        except Exception as e:
            logger.error(
                f"Compilation failed: {e}",
                extra={
                    "task_id": self.task_id,
                    "board_fqbn": board_fqbn
                },
                exc_info=True
            )
            raise RuntimeError(f"Failed to compile sketch: {e}")
        finally:
            # Clean up sketch directory
            try:
                shutil.rmtree(sketch_dir)
            except Exception as e:
                logger.warning(
                    f"Failed to clean up sketch directory: {e}",
                    extra={"sketch_dir": sketch_dir}
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
        
        # Close serial connection if one is already open for this port to avoid conflicts
        if serial_manager.get_connection(self.port_id):
            await serial_manager.close_connection(self.port_id)
        else:
            logger.debug(
                "No existing connection to close before flash",
                extra={"task_id": self.task_id, "port_id": self.port_id},
            )
        
        # Wait for port to settle
        await asyncio.sleep(0.5)
        
        # Decode and validate firmware data
        import base64
        try:
            firmware_bytes = base64.b64decode(self.firmware_data)
            firmware_text = firmware_bytes.decode('utf-8', errors='strict')
        except Exception as e:
            raise ValueError(f"Invalid firmware data encoding: {e}")
        
        # Strictly validate format before any file operations
        is_valid_hex = self._validate_intel_hex(firmware_text)
        is_valid_ino = self._validate_ino_source(firmware_text)
        
        if not is_valid_hex and not is_valid_ino:
            logger.error(
                "Invalid firmware format - not valid .hex or .ino",
                extra={"task_id": self.task_id, "content_preview": firmware_text[:200]}
            )
            raise ValueError(
                "Invalid firmware format. Must be valid Intel HEX (.hex) or Arduino source (.ino)"
            )
        
        if is_valid_hex and is_valid_ino:
            # Ambiguous format - prefer .hex since it's more strict
            logger.warning(
                "Ambiguous format detected, treating as Intel HEX",
                extra={"task_id": self.task_id}
            )
            is_valid_ino = False
        
        # Determine board FQBN
        board_fqbn = self.board_fqbn
        is_ino_source = is_valid_ino
        
        if is_ino_source:
            # For .ino source, board FQBN is required for compilation
            if not board_fqbn:
                raise ValueError("Board FQBN is required for compiling .ino source files")
            
            # Compile .ino source to .hex
            logger.info(
                "Validated .ino source, starting compilation",
                extra={"task_id": self.task_id, "board_fqbn": board_fqbn}
            )
            firmware_path = await self._compile_and_prepare_firmware(
                firmware_bytes=firmware_bytes,
                board_fqbn=board_fqbn
            )
        else:
            # For .hex files, auto-detect board if not provided
            logger.info(
                "Validated Intel HEX format",
                extra={"task_id": self.task_id}
            )
            
            if not board_fqbn:
                logger.info(
                    "Auto-detecting board FQBN",
                    extra={"task_id": self.task_id, "port_path": port_path}
                )
                board_fqbn = await self._detect_board_fqbn(port_path)
                logger.info(
                    f"Detected board FQBN: {board_fqbn}",
                    extra={"task_id": self.task_id, "board_fqbn": board_fqbn}
                )
            
            # Write validated .hex file to temp location (only when ready to flash)
            firmware_path = await self._write_hex_to_temp(firmware_bytes)
        
        try:
            # Flash firmware using arduino-cli
            flash_result = await self._flash_firmware(
                port_path=port_path,
                firmware_path=firmware_path,
                board_fqbn=board_fqbn
            )
            
            logger.info(
                f"Firmware flash completed",
                extra={
                    "task_id": self.task_id,
                    "port_id": self.port_id,
                    "board_fqbn": board_fqbn,
                    "is_ino_source": is_ino_source,
                    **flash_result
                }
            )
            
            return {
                "port_id": self.port_id,
                "board_fqbn": board_fqbn,
                "is_ino_source": is_ino_source,
                **flash_result
            }
            
        finally:
            # Clean up temporary file
            try:
                os.unlink(firmware_path)
            except Exception as e:
                logger.warning(
                    f"Failed to delete temp file: {e}",
                    extra={"temp_file": firmware_path}
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
