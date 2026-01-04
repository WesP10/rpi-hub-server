"""
Tests for task implementations.
"""

import asyncio
import base64
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
from datetime import datetime

from src.tasks import (
    BaseTask,
    TaskStatus,
    SerialWriteTask,
    FlashTask,
    RestartTask
)


class TestBaseTask:
    """Test BaseTask base class."""
    
    class ConcreteTask(BaseTask):
        """Concrete task for testing."""
        
        async def execute(self):
            """Test execution."""
            await asyncio.sleep(0.01)
            return {"result": "success"}
    
    def test_initialization(self):
        """Test task initializes with correct properties."""
        task = self.ConcreteTask(
            task_id="task-123",
            command_type="test",
            port_id="port-abc",
            params={"key": "value"},
            priority=3
        )
        
        assert task.task_id == "task-123"
        assert task.command_type == "test"
        assert task.port_id == "port-abc"
        assert task.params == {"key": "value"}
        assert task.priority == 3
        assert task.status == TaskStatus.PENDING
        assert task.result is None
        assert task.error is None
        assert task.created_at is not None
    
    @pytest.mark.asyncio
    async def test_run_success(self):
        """Test successful task execution."""
        task = self.ConcreteTask(
            task_id="task-123",
            command_type="test"
        )
        
        await task.run()
        
        assert task.status == TaskStatus.COMPLETED
        assert task.result == {"result": "success"}
        assert task.error is None
        assert task.started_at is not None
        assert task.completed_at is not None
    
    @pytest.mark.asyncio
    async def test_run_failure(self):
        """Test task execution failure handling."""
        class FailingTask(BaseTask):
            async def execute(self):
                raise RuntimeError("Test error")
        
        task = FailingTask(task_id="task-fail", command_type="test")
        
        await task.run()
        
        assert task.status == TaskStatus.FAILED
        assert task.error == "Test error"
        assert task.result is None
    
    @pytest.mark.asyncio
    async def test_cancel_during_execution(self):
        """Test task cancellation during execution."""
        class SlowTask(BaseTask):
            async def execute(self):
                await asyncio.sleep(10)  # Long running
                return {"result": "success"}
        
        task = SlowTask(task_id="task-slow", command_type="test")
        
        # Start task
        run_task = asyncio.create_task(task.run())
        
        # Wait for task to start
        await asyncio.sleep(0.05)
        
        # Cancel task
        task.cancel()
        
        # Wait for cancellation
        await run_task
        
        assert task.status == TaskStatus.CANCELLED
        assert task.error == "Task cancelled"
    
    def test_to_dict(self):
        """Test task serialization to dictionary."""
        task = self.ConcreteTask(
            task_id="task-123",
            command_type="test",
            port_id="port-abc",
            params={"key": "value"},
            priority=5
        )
        
        task_dict = task.to_dict()
        
        assert task_dict["task_id"] == "task-123"
        assert task_dict["command_type"] == "test"
        assert task_dict["port_id"] == "port-abc"
        assert task_dict["params"] == {"key": "value"}
        assert task_dict["priority"] == 5
        assert task_dict["status"] == "pending"
    
    def test_priority_comparison(self):
        """Test task comparison for priority queue."""
        task1 = self.ConcreteTask(
            task_id="task-1",
            command_type="test",
            priority=5
        )
        task2 = self.ConcreteTask(
            task_id="task-2",
            command_type="test",
            priority=3
        )
        
        assert task2 < task1  # Lower number = higher priority


class TestSerialWriteTask:
    """Test SerialWriteTask."""
    
    def test_initialization_utf8(self):
        """Test SerialWriteTask initializes with UTF-8 data."""
        task = SerialWriteTask(
            task_id="task-123",
            port_id="port-abc",
            data="Hello Arduino",
            encoding="utf-8",
            priority=5
        )
        
        assert task.task_id == "task-123"
        assert task.command_type == "serial_write"
        assert task.port_id == "port-abc"
        assert task.data == "Hello Arduino"
        assert task.encoding == "utf-8"
    
    def test_initialization_base64(self):
        """Test SerialWriteTask initializes with base64 data."""
        task = SerialWriteTask(
            task_id="task-456",
            port_id="port-xyz",
            data="SGVsbG8=",
            encoding="base64",
            priority=5
        )
        
        assert task.encoding == "base64"
    
    def test_initialization_invalid_encoding(self):
        """Test SerialWriteTask rejects invalid encoding."""
        with pytest.raises(ValueError, match="Unsupported encoding"):
            SerialWriteTask(
                task_id="task-bad",
                port_id="port-abc",
                data="Test",
                encoding="invalid"
            )
    
    @pytest.mark.asyncio
    async def test_execute_utf8(self):
        """Test serial write execution with UTF-8 data."""
        with patch('src.tasks.serial_write_task.get_serial_manager') as mock_get_sm:
            mock_sm = AsyncMock()
            mock_sm.write_to_port = AsyncMock(return_value=13)
            mock_get_sm.return_value = mock_sm
            
            task = SerialWriteTask(
                task_id="task-123",
                port_id="port-abc",
                data="Hello Arduino",
                encoding="utf-8"
            )
            
            result = await task.execute()
            
            assert result["port_id"] == "port-abc"
            assert result["bytes_written"] == 13
            assert result["encoding"] == "utf-8"
            
            # Verify write_to_port was called with encoded data
            mock_sm.write_to_port.assert_called_once()
            call_args = mock_sm.write_to_port.call_args
            assert call_args[1]["port_id"] == "port-abc"
            assert call_args[1]["data"] == b"Hello Arduino"
    
    @pytest.mark.asyncio
    async def test_execute_base64(self):
        """Test serial write execution with base64 data."""
        with patch('src.tasks.serial_write_task.get_serial_manager') as mock_get_sm:
            mock_sm = AsyncMock()
            mock_sm.write_to_port = AsyncMock(return_value=5)
            mock_get_sm.return_value = mock_sm
            
            # "Hello" base64 encoded
            b64_data = base64.b64encode(b"Hello").decode()
            
            task = SerialWriteTask(
                task_id="task-456",
                port_id="port-xyz",
                data=b64_data,
                encoding="base64"
            )
            
            result = await task.execute()
            
            assert result["bytes_written"] == 5
            
            # Verify data was decoded
            call_args = mock_sm.write_to_port.call_args
            assert call_args[1]["data"] == b"Hello"
    
    @pytest.mark.asyncio
    async def test_execute_failure(self):
        """Test serial write execution failure."""
        with patch('src.tasks.serial_write_task.get_serial_manager') as mock_get_sm:
            mock_sm = AsyncMock()
            mock_sm.write_to_port = AsyncMock(
                side_effect=RuntimeError("Port not open")
            )
            mock_get_sm.return_value = mock_sm
            
            task = SerialWriteTask(
                task_id="task-fail",
                port_id="port-abc",
                data="Test"
            )
            
            with pytest.raises(RuntimeError, match="Failed to write to port"):
                await task.execute()


class TestFlashTask:
    """Test FlashTask."""
    
    def test_initialization(self):
        """Test FlashTask initializes correctly."""
        firmware_data = base64.b64encode(b"hex file content").decode()
        
        task = FlashTask(
            task_id="task-789",
            port_id="port-abc",
            firmware_data=firmware_data,
            board_fqbn="arduino:avr:uno",
            priority=3
        )
        
        assert task.task_id == "task-789"
        assert task.command_type == "flash"
        assert task.port_id == "port-abc"
        assert task.firmware_data == firmware_data
        assert task.board_fqbn == "arduino:avr:uno"
        assert task.priority == 3
    
    @pytest.mark.asyncio
    async def test_execute_with_fqbn(self):
        """Test firmware flash with provided FQBN."""
        firmware_data = base64.b64encode(b"hex file content").decode()
        
        with patch('src.tasks.flash_task.get_serial_manager') as mock_get_sm, \
             patch('src.tasks.flash_task.get_usb_port_mapper') as mock_get_mapper, \
             patch('src.tasks.flash_task.asyncio.create_subprocess_exec') as mock_subprocess, \
             patch('builtins.open', mock_open()) as mock_file, \
             patch('os.unlink') as mock_unlink:
            
            # Mock serial manager
            mock_sm = AsyncMock()
            mock_sm.close_connection = AsyncMock()
            mock_get_sm.return_value = mock_sm
            
            # Mock USB mapper
            mock_mapper = MagicMock()
            mock_mapper.get_device_by_id.return_value = {
                "port": "/dev/ttyUSB0"
            }
            mock_get_mapper.return_value = mock_mapper
            
            # Mock arduino-cli upload process
            mock_process = AsyncMock()
            mock_process.returncode = 0
            mock_process.communicate = AsyncMock(
                return_value=(b"Upload successful", b"")
            )
            mock_subprocess.return_value = mock_process
            
            task = FlashTask(
                task_id="task-flash",
                port_id="port-abc",
                firmware_data=firmware_data,
                board_fqbn="arduino:avr:uno"
            )
            
            result = await task.execute()
            
            assert result["port_id"] == "port-abc"
            assert result["board_fqbn"] == "arduino:avr:uno"
            assert "flash_duration_ms" in result
            assert "output" in result
            
            # Verify serial connection was closed
            mock_sm.close_connection.assert_called_once_with("port-abc")
    
    @pytest.mark.asyncio
    async def test_execute_auto_detect_fqbn(self):
        """Test firmware flash with auto-detected FQBN."""
        firmware_data = base64.b64encode(b"hex file content").decode()
        
        with patch('src.tasks.flash_task.get_serial_manager') as mock_get_sm, \
             patch('src.tasks.flash_task.get_usb_port_mapper') as mock_get_mapper, \
             patch('src.tasks.flash_task.asyncio.create_subprocess_exec') as mock_subprocess, \
             patch('builtins.open', mock_open()), \
             patch('os.unlink'):
            
            mock_sm = AsyncMock()
            mock_sm.close_connection = AsyncMock()
            mock_get_sm.return_value = mock_sm
            
            mock_mapper = MagicMock()
            mock_mapper.get_device_by_id.return_value = {
                "port": "/dev/ttyUSB0"
            }
            mock_get_mapper.return_value = mock_mapper
            
            # Mock board detection
            board_list_output = [
                {
                    "port": {"address": "/dev/ttyUSB0"},
                    "matching_boards": [{"fqbn": "arduino:avr:uno"}]
                }
            ]
            
            # Mock processes for board list and upload
            async def create_process(*args, **kwargs):
                mock_proc = AsyncMock()
                mock_proc.returncode = 0
                
                if "board" in args and "list" in args:
                    # Board detection
                    import json
                    mock_proc.communicate = AsyncMock(
                        return_value=(json.dumps(board_list_output).encode(), b"")
                    )
                else:
                    # Upload
                    mock_proc.communicate = AsyncMock(
                        return_value=(b"Upload successful", b"")
                    )
                
                return mock_proc
            
            mock_subprocess.side_effect = create_process
            
            task = FlashTask(
                task_id="task-flash",
                port_id="port-abc",
                firmware_data=firmware_data,
                board_fqbn=None  # Auto-detect
            )
            
            result = await task.execute()
            
            assert result["board_fqbn"] == "arduino:avr:uno"
    
    @pytest.mark.asyncio
    async def test_execute_port_not_found(self):
        """Test flash fails when port not found."""
        firmware_data = base64.b64encode(b"hex content").decode()
        
        with patch('src.tasks.flash_task.get_usb_port_mapper') as mock_get_mapper:
            mock_mapper = MagicMock()
            mock_mapper.get_device_by_id.return_value = None
            mock_get_mapper.return_value = mock_mapper
            
            task = FlashTask(
                task_id="task-flash",
                port_id="invalid-port",
                firmware_data=firmware_data
            )
            
            with pytest.raises(ValueError, match="Port ID not found"):
                await task.execute()
    
    @pytest.mark.asyncio
    async def test_execute_upload_failure(self):
        """Test flash handles upload failure."""
        firmware_data = base64.b64encode(b"hex content").decode()
        
        with patch('src.tasks.flash_task.get_serial_manager') as mock_get_sm, \
             patch('src.tasks.flash_task.get_usb_port_mapper') as mock_get_mapper, \
             patch('src.tasks.flash_task.asyncio.create_subprocess_exec') as mock_subprocess, \
             patch('builtins.open', mock_open()), \
             patch('os.unlink'):
            
            mock_sm = AsyncMock()
            mock_sm.close_connection = AsyncMock()
            mock_get_sm.return_value = mock_sm
            
            mock_mapper = MagicMock()
            mock_mapper.get_device_by_id.return_value = {"port": "/dev/ttyUSB0"}
            mock_get_mapper.return_value = mock_mapper
            
            # Mock failed upload
            mock_process = AsyncMock()
            mock_process.returncode = 1
            mock_process.communicate = AsyncMock(
                return_value=(b"", b"Upload failed: timeout")
            )
            mock_subprocess.return_value = mock_process
            
            task = FlashTask(
                task_id="task-flash",
                port_id="port-abc",
                firmware_data=firmware_data,
                board_fqbn="arduino:avr:uno"
            )
            
            with pytest.raises(RuntimeError, match="Failed to flash firmware"):
                await task.execute()


class TestRestartTask:
    """Test RestartTask."""
    
    def test_initialization(self):
        """Test RestartTask initializes correctly."""
        task = RestartTask(
            task_id="task-restart",
            port_id="port-abc",
            priority=2
        )
        
        assert task.task_id == "task-restart"
        assert task.command_type == "restart"
        assert task.port_id == "port-abc"
        assert task.priority == 2
    
    @pytest.mark.asyncio
    async def test_execute_success(self):
        """Test device restart execution."""
        with patch('src.tasks.restart_task.get_serial_manager') as mock_get_sm, \
             patch('src.tasks.restart_task.get_usb_port_mapper') as mock_get_mapper, \
             patch('src.tasks.restart_task.serial.Serial') as mock_serial:
            
            # Mock serial manager
            mock_sm = AsyncMock()
            mock_sm.close_connection = AsyncMock()
            mock_get_sm.return_value = mock_sm
            
            # Mock USB mapper
            mock_mapper = MagicMock()
            mock_mapper.get_device_by_id.return_value = {
                "port": "/dev/ttyUSB0"
            }
            mock_get_mapper.return_value = mock_mapper
            
            # Mock serial port for DTR toggle
            mock_port = MagicMock()
            mock_serial.return_value = mock_port
            
            task = RestartTask(
                task_id="task-restart",
                port_id="port-abc"
            )
            
            result = await task.execute()
            
            assert result["port_id"] == "port-abc"
            assert result["restart_method"] == "dtr_toggle"
            assert result["restart_completed"] is True
            
            # Verify connection was closed
            mock_sm.close_connection.assert_called_once_with("port-abc")
            
            # Verify DTR was toggled
            assert mock_port.dtr is True  # Final state
            mock_port.close.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_execute_port_not_found(self):
        """Test restart fails when port not found."""
        with patch('src.tasks.restart_task.get_usb_port_mapper') as mock_get_mapper:
            mock_mapper = MagicMock()
            mock_mapper.get_device_by_id.return_value = None
            mock_get_mapper.return_value = mock_mapper
            
            task = RestartTask(
                task_id="task-restart",
                port_id="invalid-port"
            )
            
            with pytest.raises(ValueError, match="Port ID not found"):
                await task.execute()
    
    @pytest.mark.asyncio
    async def test_execute_dtr_toggle_failure(self):
        """Test restart handles DTR toggle failure."""
        with patch('src.tasks.restart_task.get_serial_manager') as mock_get_sm, \
             patch('src.tasks.restart_task.get_usb_port_mapper') as mock_get_mapper, \
             patch('src.tasks.restart_task.serial.Serial') as mock_serial:
            
            mock_sm = AsyncMock()
            mock_sm.close_connection = AsyncMock()
            mock_get_sm.return_value = mock_sm
            
            mock_mapper = MagicMock()
            mock_mapper.get_device_by_id.return_value = {"port": "/dev/ttyUSB0"}
            mock_get_mapper.return_value = mock_mapper
            
            # Mock serial port failure
            mock_serial.side_effect = Exception("Port access denied")
            
            task = RestartTask(
                task_id="task-restart",
                port_id="port-abc"
            )
            
            with pytest.raises(RuntimeError, match="Failed to restart device"):
                await task.execute()
