"""
Command handler for processing server commands and creating tasks.

Validates incoming command envelopes, creates appropriate task instances,
and manages task execution queue with priority scheduling.
"""

import asyncio
import uuid
from typing import Any, Callable, Dict, List, Optional
from datetime import datetime

from .config import get_settings
from .logging_config import get_logger
from .tasks import BaseTask, SerialWriteTask, FlashTask, RestartTask, CloseConnectionTask, TaskStatus

logger = get_logger(__name__)


class CommandHandler:
    """
    Handles command envelopes from server and dispatches tasks.
    
    Validates command structure, creates task instances, manages priority queue,
    and reports task status back to server via Hub Agent callbacks.
    """
    
    def __init__(
        self,
        task_status_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        max_concurrent_tasks: int = 5
    ):
        """
        Initialize command handler.
        
        Args:
            task_status_callback: Callback for reporting task status updates
            max_concurrent_tasks: Maximum concurrent task execution limit
        """
        self.task_status_callback = task_status_callback
        self.max_concurrent_tasks = max_concurrent_tasks
        
        # Task storage
        self._tasks: Dict[str, BaseTask] = {}
        self._task_queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._running_tasks: Dict[str, asyncio.Task] = {}
        
        # Worker control
        self._workers: List[asyncio.Task] = []
        self._running = False
        self._shutdown_event = asyncio.Event()
        
        logger.info(
            "CommandHandler initialized",
            extra={"max_concurrent_tasks": max_concurrent_tasks}
        )
    
    async def start(self) -> None:
        """Start task worker threads."""
        if self._running:
            logger.warning("CommandHandler already running")
            return
        
        self._running = True
        self._shutdown_event.clear()
        
        # Start worker tasks
        for i in range(self.max_concurrent_tasks):
            worker = asyncio.create_task(self._task_worker(worker_id=i))
            self._workers.append(worker)
        
        logger.info(
            "CommandHandler started",
            extra={"worker_count": len(self._workers)}
        )
    
    async def stop(self) -> None:
        """Stop task workers and wait for completion."""
        if not self._running:
            return
        
        self._running = False
        self._shutdown_event.set()
        
        # Wait for workers to finish
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        
        # Cancel any remaining running tasks
        for task_id, task in self._running_tasks.items():
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        self._running_tasks.clear()
        
        logger.info("CommandHandler stopped")
    
    async def handle_command(self, command_envelope: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process command envelope and create task.
        
        Args:
            command_envelope: Command data from server
                {
                    "commandId": str,
                    "commandType": "serial_write" | "flash" | "restart",
                    "portId": str (optional),
                    "params": dict (optional),
                    "priority": int (optional)
                }
        
        Returns:
            Dict containing task_id and status
            
        Raises:
            ValueError: If command envelope is invalid
        """
        try:
            # Validate command structure
            command_id = command_envelope.get("commandId")
            command_type = command_envelope.get("commandType")
            port_id = command_envelope.get("portId")
            params = command_envelope.get("params", {})
            priority = command_envelope.get("priority", 5)
            
            if not command_id:
                raise ValueError("Missing commandId in command envelope")
            
            if not command_type:
                raise ValueError("Missing commandType in command envelope")
            
            logger.info(
                "Handling command",
                extra={
                    "command_id": command_id,
                    "command_type": command_type,
                    "port_id": port_id,
                    "priority": priority
                }
            )
            
            # Create task from command
            task = self._create_task(
                command_id=command_id,
                command_type=command_type,
                port_id=port_id,
                params=params,
                priority=priority
            )
            
            # Store task
            self._tasks[task.task_id] = task
            
            # Queue task for execution
            await self._task_queue.put((task.priority, task.task_id))
            
            # Report task created
            await self._report_task_status(task)
            
            return {
                "task_id": task.task_id,
                "command_id": command_id,
                "status": task.status.value,
                "queued": True
            }
            
        except Exception as e:
            logger.error(
                f"Failed to handle command: {e}",
                extra={"command_envelope": command_envelope},
                exc_info=True
            )
            raise ValueError(f"Invalid command envelope: {e}")
    
    def _create_task(
        self,
        command_id: str,
        command_type: str,
        port_id: Optional[str],
        params: Dict[str, Any],
        priority: int
    ) -> BaseTask:
        """
        Create task instance from command parameters.
        
        Args:
            command_id: Command identifier (used as task_id)
            command_type: Type of task to create
            port_id: Target port ID
            params: Task parameters
            priority: Task priority
            
        Returns:
            Created task instance
            
        Raises:
            ValueError: If command type is unsupported or parameters are invalid
        """
        task_id = command_id
        
        if command_type == "serial_write":
            # Validate serial write parameters
            data = params.get("data")
            if not data:
                raise ValueError("Missing 'data' parameter for serial_write")
            
            if not port_id:
                raise ValueError("Missing portId for serial_write")
            
            encoding = params.get("encoding", "utf-8")
            
            return SerialWriteTask(
                task_id=task_id,
                port_id=port_id,
                data=data,
                encoding=encoding,
                priority=priority,
                params=params
            )
        
        elif command_type == "flash":
            # Validate flash parameters
            firmware_data = params.get("firmwareData")
            if not firmware_data:
                raise ValueError("Missing 'firmwareData' parameter for flash")
            
            if not port_id:
                raise ValueError("Missing portId for flash")
            
            board_fqbn = params.get("boardFqbn")
            
            return FlashTask(
                task_id=task_id,
                port_id=port_id,
                firmware_data=firmware_data,
                board_fqbn=board_fqbn,
                priority=priority,
                params=params
            )
        
        elif command_type == "restart":
            # Validate restart parameters
            if not port_id:
                raise ValueError("Missing portId for restart")
            
            return RestartTask(
                task_id=task_id,
                port_id=port_id,
                priority=priority,
                params=params
            )
        
        elif command_type == "close_connection":
            # Validate close connection parameters
            if not port_id:
                raise ValueError("Missing portId for close_connection")
            
            return CloseConnectionTask(
                task_id=task_id,
                port_id=port_id,
                priority=priority,
                params=params
            )
        
        else:
            raise ValueError(f"Unsupported command type: {command_type}")
    
    async def _task_worker(self, worker_id: int) -> None:
        """
        Worker coroutine for executing tasks from queue.
        
        Args:
            worker_id: Worker identifier for logging
        """
        logger.info(f"Task worker {worker_id} started")
        
        while self._running:
            try:
                # Wait for task with timeout to check shutdown
                try:
                    priority, task_id = await asyncio.wait_for(
                        self._task_queue.get(),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue
                
                # Get task
                task = self._tasks.get(task_id)
                if not task:
                    logger.warning(
                        f"Task not found in storage",
                        extra={"task_id": task_id}
                    )
                    continue
                
                logger.debug(
                    f"Worker {worker_id} executing task",
                    extra={"task_id": task_id, "command_type": task.command_type}
                )
                
                # Execute task
                task_coroutine = asyncio.create_task(task.run())
                self._running_tasks[task_id] = task_coroutine
                
                try:
                    await task_coroutine
                finally:
                    # Clean up
                    self._running_tasks.pop(task_id, None)
                
                # Report task completion
                await self._report_task_status(task)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    f"Worker {worker_id} error: {e}",
                    exc_info=True
                )
        
        logger.info(f"Task worker {worker_id} stopped")
    
    async def _report_task_status(self, task: BaseTask) -> None:
        """
        Report task status to Hub Agent via callback.
        
        Args:
            task: Task to report
        """
        if not self.task_status_callback:
            return
        
        try:
            status_data = {
                "type": "task_status",
                "task_id": task.task_id,
                "command_type": task.command_type,
                "port_id": task.port_id,
                "status": task.status.value,
                "result": task.result,
                "error": task.error,
                "timestamp": datetime.utcnow().isoformat()
            }
            
            self.task_status_callback(status_data)
            
            logger.debug(
                "Task status reported",
                extra={
                    "task_id": task.task_id,
                    "status": task.status.value
                }
            )
            
        except Exception as e:
            logger.error(
                f"Failed to report task status: {e}",
                extra={"task_id": task.task_id},
                exc_info=True
            )
    
    def get_task(self, task_id: str) -> Optional[BaseTask]:
        """
        Get task by ID.
        
        Args:
            task_id: Task identifier
            
        Returns:
            Task instance or None if not found
        """
        return self._tasks.get(task_id)
    
    def get_all_tasks(self) -> List[Dict[str, Any]]:
        """
        Get all tasks as dictionaries.
        
        Returns:
            List of task dictionaries
        """
        return [task.to_dict() for task in self._tasks.values()]
    
    def get_queue_size(self) -> int:
        """
        Get current task queue size.
        
        Returns:
            Number of tasks in queue
        """
        return self._task_queue.qsize()
    
    def get_running_task_count(self) -> int:
        """
        Get number of currently running tasks.
        
        Returns:
            Number of running tasks
        """
        return len(self._running_tasks)


# Global command handler instance
_command_handler: Optional[CommandHandler] = None


def get_command_handler() -> CommandHandler:
    """
    Get global CommandHandler instance.
    
    Returns:
        Global CommandHandler instance
        
    Raises:
        RuntimeError: If command handler not initialized
    """
    if _command_handler is None:
        raise RuntimeError(
            "CommandHandler not initialized. Call initialize_command_handler() first."
        )
    return _command_handler


def initialize_command_handler(
    task_status_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    max_concurrent_tasks: int = 5
) -> CommandHandler:
    """
    Initialize global CommandHandler instance.
    
    Args:
        task_status_callback: Callback for task status updates
        max_concurrent_tasks: Maximum concurrent tasks
        
    Returns:
        Initialized CommandHandler instance
    """
    global _command_handler
    
    if _command_handler is not None:
        logger.warning("CommandHandler already initialized")
        return _command_handler
    
    _command_handler = CommandHandler(
        task_status_callback=task_status_callback,
        max_concurrent_tasks=max_concurrent_tasks
    )
    
    return _command_handler
