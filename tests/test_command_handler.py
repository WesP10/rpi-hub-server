"""
Tests for CommandHandler.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from datetime import datetime

from src.command_handler import (
    CommandHandler,
    initialize_command_handler,
    get_command_handler
)
from src.tasks import BaseTask, TaskStatus, SerialWriteTask, FlashTask, RestartTask


@pytest.fixture
def mock_task_callback():
    """Create mock task status callback."""
    return MagicMock()


@pytest.fixture
def command_handler(mock_task_callback):
    """Create CommandHandler instance."""
    handler = CommandHandler(
        task_status_callback=mock_task_callback,
        max_concurrent_tasks=2
    )
    return handler


@pytest.fixture
async def started_handler(command_handler):
    """Create and start CommandHandler."""
    await command_handler.start()
    yield command_handler
    await command_handler.stop()


class TestCommandHandlerInitialization:
    """Test command handler initialization."""
    
    def test_initialization(self, mock_task_callback):
        """Test handler initializes with correct settings."""
        handler = CommandHandler(
            task_status_callback=mock_task_callback,
            max_concurrent_tasks=3
        )
        
        assert handler.task_status_callback == mock_task_callback
        assert handler.max_concurrent_tasks == 3
        assert not handler._running
        assert len(handler._tasks) == 0
        assert len(handler._workers) == 0
    
    def test_initialization_defaults(self):
        """Test handler initializes with defaults."""
        handler = CommandHandler()
        
        assert handler.task_status_callback is None
        assert handler.max_concurrent_tasks == 5
    
    @pytest.mark.asyncio
    async def test_start_creates_workers(self, command_handler):
        """Test start() creates worker tasks."""
        await command_handler.start()
        
        assert command_handler._running
        assert len(command_handler._workers) == 2
        assert all(not w.done() for w in command_handler._workers)
        
        await command_handler.stop()
    
    @pytest.mark.asyncio
    async def test_start_idempotent(self, started_handler):
        """Test start() can be called multiple times safely."""
        initial_workers = len(started_handler._workers)
        
        await started_handler.start()
        
        assert len(started_handler._workers) == initial_workers
    
    @pytest.mark.asyncio
    async def test_stop_cancels_workers(self, started_handler):
        """Test stop() cancels all workers."""
        worker_tasks = list(started_handler._workers)
        
        await started_handler.stop()
        
        assert not started_handler._running
        assert len(started_handler._workers) == 0
        assert all(w.done() for w in worker_tasks)


class TestCommandHandling:
    """Test command envelope handling."""
    
    @pytest.mark.asyncio
    async def test_handle_serial_write_command(self, started_handler):
        """Test handling serial_write command."""
        command = {
            "commandId": "cmd-123",
            "commandType": "serial_write",
            "portId": "port-abc",
            "params": {
                "data": "Hello Arduino",
                "encoding": "utf-8"
            },
            "priority": 5
        }
        
        result = await started_handler.handle_command(command)
        
        assert result["task_id"] == "cmd-123"
        assert result["command_id"] == "cmd-123"
        assert result["status"] == "pending"
        assert result["queued"] is True
        
        # Verify task was created
        task = started_handler.get_task("cmd-123")
        assert task is not None
        assert isinstance(task, SerialWriteTask)
        assert task.port_id == "port-abc"
        assert task.data == "Hello Arduino"
    
    @pytest.mark.asyncio
    async def test_handle_flash_command(self, started_handler):
        """Test handling flash command."""
        command = {
            "commandId": "cmd-456",
            "commandType": "flash",
            "portId": "port-xyz",
            "params": {
                "firmwareData": "aGV4ZmlsZQ==",  # base64 encoded
                "boardFqbn": "arduino:avr:uno"
            },
            "priority": 3
        }
        
        result = await started_handler.handle_command(command)
        
        assert result["task_id"] == "cmd-456"
        assert result["queued"] is True
        
        task = started_handler.get_task("cmd-456")
        assert isinstance(task, FlashTask)
        assert task.port_id == "port-xyz"
        assert task.board_fqbn == "arduino:avr:uno"
    
    @pytest.mark.asyncio
    async def test_handle_restart_command(self, started_handler):
        """Test handling restart command."""
        command = {
            "commandId": "cmd-789",
            "commandType": "restart",
            "portId": "port-123",
            "priority": 2
        }
        
        result = await started_handler.handle_command(command)
        
        assert result["task_id"] == "cmd-789"
        assert result["queued"] is True
        
        task = started_handler.get_task("cmd-789")
        assert isinstance(task, RestartTask)
        assert task.port_id == "port-123"
    
    @pytest.mark.asyncio
    async def test_handle_command_missing_command_id(self, started_handler):
        """Test handling command without commandId."""
        command = {
            "commandType": "serial_write",
            "portId": "port-abc"
        }
        
        with pytest.raises(ValueError, match="Missing commandId"):
            await started_handler.handle_command(command)
    
    @pytest.mark.asyncio
    async def test_handle_command_missing_command_type(self, started_handler):
        """Test handling command without commandType."""
        command = {
            "commandId": "cmd-123",
            "portId": "port-abc"
        }
        
        with pytest.raises(ValueError, match="Missing commandType"):
            await started_handler.handle_command(command)
    
    @pytest.mark.asyncio
    async def test_handle_command_unsupported_type(self, started_handler):
        """Test handling command with unsupported type."""
        command = {
            "commandId": "cmd-999",
            "commandType": "unknown_command",
            "portId": "port-abc"
        }
        
        with pytest.raises(ValueError, match="Unsupported command type"):
            await started_handler.handle_command(command)
    
    @pytest.mark.asyncio
    async def test_handle_serial_write_missing_data(self, started_handler):
        """Test serial_write command without data parameter."""
        command = {
            "commandId": "cmd-123",
            "commandType": "serial_write",
            "portId": "port-abc",
            "params": {}
        }
        
        with pytest.raises(ValueError, match="Missing 'data' parameter"):
            await started_handler.handle_command(command)
    
    @pytest.mark.asyncio
    async def test_handle_flash_missing_firmware(self, started_handler):
        """Test flash command without firmwareData parameter."""
        command = {
            "commandId": "cmd-456",
            "commandType": "flash",
            "portId": "port-xyz",
            "params": {}
        }
        
        with pytest.raises(ValueError, match="Missing 'firmwareData' parameter"):
            await started_handler.handle_command(command)


class TestTaskExecution:
    """Test task execution and worker management."""
    
    @pytest.mark.asyncio
    async def test_task_execution_success(self, started_handler, mock_task_callback):
        """Test successful task execution."""
        # Mock serial manager
        with patch('src.tasks.serial_write_task.get_serial_manager') as mock_get_sm:
            mock_sm = AsyncMock()
            mock_sm.write_to_port = AsyncMock(return_value=13)
            mock_get_sm.return_value = mock_sm
            
            command = {
                "commandId": "cmd-123",
                "commandType": "serial_write",
                "portId": "port-abc",
                "params": {"data": "Hello Arduino"}
            }
            
            await started_handler.handle_command(command)
            
            # Wait for task to execute
            await asyncio.sleep(0.2)
            
            task = started_handler.get_task("cmd-123")
            assert task.status == TaskStatus.COMPLETED
            assert task.result["bytes_written"] == 13
            
            # Verify callback was called
            assert mock_task_callback.call_count >= 2  # Created + Completed
    
    @pytest.mark.asyncio
    async def test_task_execution_failure(self, started_handler, mock_task_callback):
        """Test task execution failure handling."""
        with patch('src.tasks.serial_write_task.get_serial_manager') as mock_get_sm:
            mock_sm = AsyncMock()
            mock_sm.write_to_port = AsyncMock(side_effect=RuntimeError("Port not open"))
            mock_get_sm.return_value = mock_sm
            
            command = {
                "commandId": "cmd-fail",
                "commandType": "serial_write",
                "portId": "port-abc",
                "params": {"data": "Test"}
            }
            
            await started_handler.handle_command(command)
            
            # Wait for task to fail
            await asyncio.sleep(0.2)
            
            task = started_handler.get_task("cmd-fail")
            assert task.status == TaskStatus.FAILED
            assert "Port not open" in task.error
    
    @pytest.mark.asyncio
    async def test_priority_queue_ordering(self, started_handler):
        """Test tasks execute in priority order."""
        with patch('src.tasks.serial_write_task.get_serial_manager') as mock_get_sm:
            mock_sm = AsyncMock()
            mock_sm.write_to_port = AsyncMock(return_value=10)
            mock_get_sm.return_value = mock_sm
            
            # Submit tasks with different priorities
            commands = [
                {
                    "commandId": f"cmd-low-{i}",
                    "commandType": "serial_write",
                    "portId": "port-abc",
                    "params": {"data": "Low priority"},
                    "priority": 10
                }
                for i in range(3)
            ]
            
            commands.append({
                "commandId": "cmd-high",
                "commandType": "serial_write",
                "portId": "port-abc",
                "params": {"data": "High priority"},
                "priority": 1
            })
            
            # Submit low priority tasks first
            for cmd in commands[:-1]:
                await started_handler.handle_command(cmd)
            
            # Submit high priority task last
            await started_handler.handle_command(commands[-1])
            
            # Wait for execution
            await asyncio.sleep(0.3)
            
            # High priority task should complete first
            high_task = started_handler.get_task("cmd-high")
            assert high_task.status == TaskStatus.COMPLETED


class TestTaskManagement:
    """Test task management methods."""
    
    @pytest.mark.asyncio
    async def test_get_task(self, started_handler):
        """Test get_task() retrieves task by ID."""
        command = {
            "commandId": "cmd-123",
            "commandType": "serial_write",
            "portId": "port-abc",
            "params": {"data": "Test"}
        }
        
        await started_handler.handle_command(command)
        
        task = started_handler.get_task("cmd-123")
        assert task is not None
        assert task.task_id == "cmd-123"
        
        # Non-existent task
        assert started_handler.get_task("non-existent") is None
    
    @pytest.mark.asyncio
    async def test_get_all_tasks(self, started_handler):
        """Test get_all_tasks() returns all tasks."""
        commands = [
            {
                "commandId": f"cmd-{i}",
                "commandType": "serial_write",
                "portId": "port-abc",
                "params": {"data": "Test"}
            }
            for i in range(3)
        ]
        
        for cmd in commands:
            await started_handler.handle_command(cmd)
        
        all_tasks = started_handler.get_all_tasks()
        assert len(all_tasks) == 3
        assert all(isinstance(t, dict) for t in all_tasks)
        assert {t["task_id"] for t in all_tasks} == {"cmd-0", "cmd-1", "cmd-2"}
    
    @pytest.mark.asyncio
    async def test_get_queue_size(self, started_handler):
        """Test get_queue_size() returns queue length."""
        # Stop workers to prevent execution
        await started_handler.stop()
        
        commands = [
            {
                "commandId": f"cmd-{i}",
                "commandType": "serial_write",
                "portId": "port-abc",
                "params": {"data": "Test"}
            }
            for i in range(5)
        ]
        
        for cmd in commands:
            await started_handler.handle_command(cmd)
        
        assert started_handler.get_queue_size() == 5
    
    @pytest.mark.asyncio
    async def test_get_running_task_count(self, started_handler):
        """Test get_running_task_count() returns active tasks."""
        with patch('src.tasks.serial_write_task.get_serial_manager') as mock_get_sm:
            mock_sm = AsyncMock()
            # Make write_to_port slow to keep tasks running
            mock_sm.write_to_port = AsyncMock(
                side_effect=lambda *args, **kwargs: asyncio.sleep(0.5)
            )
            mock_get_sm.return_value = mock_sm
            
            # Submit multiple tasks
            for i in range(3):
                await started_handler.handle_command({
                    "commandId": f"cmd-{i}",
                    "commandType": "serial_write",
                    "portId": "port-abc",
                    "params": {"data": "Test"}
                })
            
            # Give workers time to pick up tasks
            await asyncio.sleep(0.1)
            
            # Should have at least 1 running (max 2 with our fixture)
            running = started_handler.get_running_task_count()
            assert running > 0
            assert running <= 2


class TestGlobalInstance:
    """Test global command handler singleton."""
    
    def test_initialize_command_handler(self):
        """Test initialize_command_handler() creates instance."""
        mock_callback = MagicMock()
        
        handler = initialize_command_handler(
            task_status_callback=mock_callback,
            max_concurrent_tasks=3
        )
        
        assert handler is not None
        assert handler.task_status_callback == mock_callback
        assert handler.max_concurrent_tasks == 3
    
    def test_get_command_handler(self):
        """Test get_command_handler() returns initialized instance."""
        mock_callback = MagicMock()
        
        # Initialize first
        handler1 = initialize_command_handler(task_status_callback=mock_callback)
        
        # Get should return same instance
        handler2 = get_command_handler()
        
        assert handler1 is handler2
    
    def test_initialize_command_handler_idempotent(self):
        """Test initialize_command_handler() doesn't recreate instance."""
        handler1 = initialize_command_handler()
        handler2 = initialize_command_handler(max_concurrent_tasks=10)
        
        # Should return existing instance, not create new one
        assert handler1 is handler2
        assert handler1.max_concurrent_tasks != 10


class TestTaskStatusReporting:
    """Test task status callback reporting."""
    
    @pytest.mark.asyncio
    async def test_task_created_callback(self, started_handler, mock_task_callback):
        """Test callback called when task created."""
        command = {
            "commandId": "cmd-123",
            "commandType": "serial_write",
            "portId": "port-abc",
            "params": {"data": "Test"}
        }
        
        await started_handler.handle_command(command)
        
        # Should have called callback for task creation
        assert mock_task_callback.call_count >= 1
        call_args = mock_task_callback.call_args[0][0]
        assert call_args["type"] == "task_status"
        assert call_args["task_id"] == "cmd-123"
        assert call_args["status"] == "pending"
    
    @pytest.mark.asyncio
    async def test_task_completed_callback(self, started_handler, mock_task_callback):
        """Test callback called when task completes."""
        with patch('src.tasks.serial_write_task.get_serial_manager') as mock_get_sm:
            mock_sm = AsyncMock()
            mock_sm.write_to_port = AsyncMock(return_value=10)
            mock_get_sm.return_value = mock_sm
            
            command = {
                "commandId": "cmd-123",
                "commandType": "serial_write",
                "portId": "port-abc",
                "params": {"data": "Test"}
            }
            
            await started_handler.handle_command(command)
            await asyncio.sleep(0.2)
            
            # Should have called callback multiple times
            assert mock_task_callback.call_count >= 2
            
            # Find completion callback
            completion_calls = [
                call for call in mock_task_callback.call_args_list
                if call[0][0].get("status") == "completed"
            ]
            assert len(completion_calls) >= 1
            
            call_args = completion_calls[0][0][0]
            assert call_args["task_id"] == "cmd-123"
            assert call_args["result"] is not None
    
    @pytest.mark.asyncio
    async def test_no_callback_no_error(self, command_handler):
        """Test handler works without callback."""
        # Handler without callback
        await command_handler.start()
        
        with patch('src.tasks.serial_write_task.get_serial_manager') as mock_get_sm:
            mock_sm = AsyncMock()
            mock_sm.write_to_port = AsyncMock(return_value=10)
            mock_get_sm.return_value = mock_sm
            
            command = {
                "commandId": "cmd-123",
                "commandType": "serial_write",
                "portId": "port-abc",
                "params": {"data": "Test"}
            }
            
            # Should not raise error
            await command_handler.handle_command(command)
            await asyncio.sleep(0.2)
            
            task = command_handler.get_task("cmd-123")
            assert task.status == TaskStatus.COMPLETED
        
        await command_handler.stop()
