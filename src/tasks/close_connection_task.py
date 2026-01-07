"""Close connection task for closing serial connections."""

from typing import Any, Dict, Optional

from .base_task import BaseTask, TaskStatus
from ..serial_manager import get_serial_manager
from ..logging_config import get_logger

logger = get_logger(__name__)


class CloseConnectionTask(BaseTask):
    """Task for closing an active serial connection."""

    def __init__(
        self,
        task_id: str,
        port_id: str,
        priority: int = 1,
        params: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize close connection task.

        Args:
            task_id: Task identifier
            port_id: Port ID to close
            priority: Task priority (lower = higher priority)
            params: Additional parameters
        """
        super().__init__(
            task_id=task_id,
            command_type="close_connection",
            port_id=port_id,
            priority=priority,
            params=params or {},
        )

    async def execute(self) -> None:
        """
        Execute connection close.

        Raises:
            RuntimeError: If close fails
        """
        serial_manager = get_serial_manager()

        logger.info(
            "Closing connection",
            extra={
                "task_id": self.task_id,
                "port_id": self.port_id,
            }
        )

        # Close the connection
        success = await serial_manager.close_connection(self.port_id)

        if not success:
            error_msg = f"Failed to close connection on port {self.port_id}"
            logger.error(error_msg, extra={"port_id": self.port_id})
            raise RuntimeError(error_msg)

        logger.info(
            "Connection closed successfully",
            extra={
                "task_id": self.task_id,
                "port_id": self.port_id,
            }
        )

        # Store result
        self.result = {
            "port_id": self.port_id,
            "status": "closed",
        }
