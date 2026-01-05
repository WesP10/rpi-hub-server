"""Circular buffer manager for telemetry data."""

import asyncio
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Deque, Dict, Optional

from src.logging_config import StructuredLogger


@dataclass
class BufferedMessage:
    """Message stored in buffer."""

    message_type: str
    payload: Dict[str, Any]
    timestamp: datetime
    size_bytes: int


class BufferManager:
    """Manages circular buffer for telemetry messages."""

    def __init__(
        self,
        size_mb: float = 10.0,
        warn_threshold: float = 0.8,
    ):
        """Initialize Buffer Manager.

        Args:
            size_mb: Buffer size in megabytes
            warn_threshold: Warning threshold (0.0-1.0)
        """
        self.logger = StructuredLogger(__name__)
        self.size_bytes = int(size_mb * 1024 * 1024)
        self.warn_threshold = warn_threshold
        self.warn_threshold_bytes = int(self.size_bytes * warn_threshold)

        # Buffer storage (FIFO)
        self.buffer: Deque[BufferedMessage] = deque()
        self.current_size_bytes = 0

        # State tracking
        self._above_threshold = False
        self._drop_count = 0
        self._total_messages = 0
        self._total_drops = 0

        self.logger.info(
            "buffer_manager_initialized",
            "Buffer Manager initialized",
            size_mb=size_mb,
            size_bytes=self.size_bytes,
            warn_threshold=warn_threshold,
        )

    def add_message(
        self,
        message_type: str,
        payload: Dict[str, Any],
    ) -> bool:
        """Add message to buffer.

        Args:
            message_type: Type of message (telemetry, health, etc.)
            payload: Message payload

        Returns:
            True if added successfully
        """
        # Estimate message size (rough approximation)
        import json

        message_str = json.dumps(payload)
        message_size = len(message_str.encode("utf-8"))

        buffered_msg = BufferedMessage(
            message_type=message_type,
            payload=payload,
            timestamp=datetime.now(),
            size_bytes=message_size,
        )

        self._total_messages += 1

        # Check if we need to drop oldest messages
        while (
            self.current_size_bytes + message_size > self.size_bytes
            and len(self.buffer) > 0
        ):
            self._drop_oldest()

        # Add new message
        self.buffer.append(buffered_msg)
        self.current_size_bytes += message_size

        # Check threshold
        self._check_threshold()

        self.logger.info(
            f"Added {message_type} message to buffer",
            extra={
                "event": "message_buffered",
                "message_type": message_type,
                "size_bytes": message_size,
                "buffer_length": len(self.buffer),
                "buffer_utilization": self.current_size_bytes / self.size_bytes,
            }
        )

        return True

    def _drop_oldest(self) -> None:
        """Drop oldest message from buffer."""
        if len(self.buffer) == 0:
            return

        dropped = self.buffer.popleft()
        self.current_size_bytes -= dropped.size_bytes
        self._drop_count += 1
        self._total_drops += 1

        self.logger.buffer_drop(1, dropped.message_type)

    def _check_threshold(self) -> None:
        """Check if buffer has crossed warning threshold."""
        utilization = self.current_size_bytes / self.size_bytes

        # Crossed threshold (going up)
        if not self._above_threshold and self.current_size_bytes >= self.warn_threshold_bytes:
            self._above_threshold = True
            self.logger.buffer_warning(
                self.current_size_bytes / (1024 * 1024),
                self.warn_threshold_bytes / (1024 * 1024),
            )

        # Dropped below threshold (going down)
        elif self._above_threshold and self.current_size_bytes < self.warn_threshold_bytes:
            self._above_threshold = False
            self.logger.info(
                "buffer_below_threshold",
                f"Buffer dropped below threshold: {utilization:.1%}",
                usage_mb=self.current_size_bytes / (1024 * 1024),
                utilization=utilization,
            )

    async def get_messages(self, max_messages: Optional[int] = None) -> list[BufferedMessage]:
        """Get messages from buffer without removing them.

        Args:
            max_messages: Maximum number of messages to return

        Returns:
            List of buffered messages
        """
        if max_messages is None:
            return list(self.buffer)
        return list(self.buffer)[:max_messages]

    async def pop_message(self) -> Optional[BufferedMessage]:
        """Pop oldest message from buffer.

        Returns:
            Oldest message or None if buffer empty
        """
        if len(self.buffer) == 0:
            return None

        message = self.buffer.popleft()
        self.current_size_bytes -= message.size_bytes

        self.logger.debug(
            f"Popped {message.message_type} message from buffer",
            extra={
                "event": "message_popped",
                "message_type": message.message_type,
                "buffer_remaining": len(self.buffer),
            }
        )

        return message

    async def pop_messages(self, count: int) -> list[BufferedMessage]:
        """Pop multiple messages from buffer.

        Args:
            count: Number of messages to pop

        Returns:
            List of popped messages
        """
        messages = []
        for _ in range(min(count, len(self.buffer))):
            msg = await self.pop_message()
            if msg:
                messages.append(msg)

        return messages

    def clear(self) -> None:
        """Clear all messages from buffer."""
        cleared_count = len(self.buffer)
        self.buffer.clear()
        self.current_size_bytes = 0
        self._above_threshold = False

        self.logger.info(
            "buffer_cleared",
            f"Cleared {cleared_count} messages from buffer",
            cleared_count=cleared_count,
        )

    def get_stats(self) -> Dict[str, Any]:
        """Get buffer statistics.

        Returns:
            Dictionary of buffer stats
        """
        utilization = (
            self.current_size_bytes / self.size_bytes if self.size_bytes > 0 else 0
        )

        return {
            "size_mb": self.size_bytes / (1024 * 1024),
            "used_mb": self.current_size_bytes / (1024 * 1024),
            "utilization_percent": utilization * 100,
            "message_count": len(self.buffer),
            "total_messages": self._total_messages,
            "total_drops": self._total_drops,
            "current_drop_count": self._drop_count,
            "above_threshold": self._above_threshold,
        }

    def is_above_threshold(self) -> bool:
        """Check if buffer is above warning threshold.

        Returns:
            True if above threshold
        """
        return self._above_threshold

    def get_utilization(self) -> float:
        """Get buffer utilization percentage.

        Returns:
            Utilization (0.0-1.0)
        """
        return self.current_size_bytes / self.size_bytes if self.size_bytes > 0 else 0

    def get_message_count(self) -> int:
        """Get number of messages in buffer.

        Returns:
            Message count
        """
        return len(self.buffer)

    def reset_drop_count(self) -> int:
        """Reset and return current drop count.

        Returns:
            Drop count since last reset
        """
        count = self._drop_count
        self._drop_count = 0
        return count


# Global buffer manager instance
_buffer_manager: Optional[BufferManager] = None


def get_buffer_manager() -> BufferManager:
    """
    Get global BufferManager instance.
    
    Returns:
        Global BufferManager instance
        
    Raises:
        RuntimeError: If buffer manager not initialized
    """
    if _buffer_manager is None:
        raise RuntimeError(
            "BufferManager not initialized. Call initialize_buffer_manager() first."
        )
    return _buffer_manager


def initialize_buffer_manager(
    size_mb: float = 10.0,
    warn_threshold: float = 0.8
) -> BufferManager:
    """
    Initialize global BufferManager instance.
    
    Args:
        size_mb: Buffer size in megabytes
        warn_threshold: Warning threshold (0.0-1.0)
        
    Returns:
        Initialized BufferManager instance
    """
    global _buffer_manager
    
    if _buffer_manager is not None:
        return _buffer_manager
    
    _buffer_manager = BufferManager(
        size_mb=size_mb,
        warn_threshold=warn_threshold
    )
    
    return _buffer_manager
