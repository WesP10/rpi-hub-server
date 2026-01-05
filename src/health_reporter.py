"""
Health Reporter for system and service metrics.

Collects and reports comprehensive health metrics including:
- System metrics (CPU, memory, disk, temperature)
- Service metrics (connections, tasks, buffer)
- Per-port error tracking
- Uptime tracking
"""

import asyncio
import time
from datetime import datetime
from typing import Any, Callable, Dict, Optional

import psutil

from .config import get_settings
from .logging_config import get_logger

logger = get_logger(__name__)


class HealthReporter:
    """
    Collects and reports system and service health metrics.
    
    Monitors system resources, active connections, task queue status,
    buffer utilization, and per-port error counts. Reports metrics
    periodically to Hub Agent.
    """
    
    def __init__(
        self,
        report_interval: int = 30,
        health_callback: Optional[Callable[[Dict[str, Any]], None]] = None
    ):
        """
        Initialize health reporter.
        
        Args:
            report_interval: Reporting interval in seconds (default: 30)
            health_callback: Callback for health reports
        """
        self.report_interval = report_interval
        self.health_callback = health_callback
        
        # Service start time
        self._start_time = time.time()
        
        # Per-port error tracking
        self._port_errors: Dict[str, int] = {}
        self._port_read_errors: Dict[str, int] = {}
        self._port_write_errors: Dict[str, int] = {}
        
        # Reporting task
        self._reporter_task: Optional[asyncio.Task] = None
        self._running = False
        
        logger.info(
            "HealthReporter initialized",
            extra={"report_interval": report_interval}
        )
    
    async def start(self) -> None:
        """Start periodic health reporting."""
        if self._running:
            logger.warning("HealthReporter already running")
            return
        
        self._running = True
        self._reporter_task = asyncio.create_task(self._report_loop())
        
        logger.info("HealthReporter started")
    
    async def stop(self) -> None:
        """Stop health reporting."""
        if not self._running:
            return
        
        self._running = False
        
        if self._reporter_task:
            self._reporter_task.cancel()
            try:
                await self._reporter_task
            except asyncio.CancelledError:
                pass
            self._reporter_task = None
        
        logger.info("HealthReporter stopped")
    
    async def _report_loop(self) -> None:
        """Periodic health reporting loop."""
        logger.debug("Health reporter loop started")
        
        while self._running:
            try:
                # Collect and report metrics
                health_data = await self.collect_health_metrics()
                await self._send_health_report(health_data)
                
                # Wait for next interval
                await asyncio.sleep(self.report_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    f"Error in health reporter loop: {e}",
                    exc_info=True
                )
                await asyncio.sleep(self.report_interval)
        
        logger.debug("Health reporter loop stopped")
    
    async def collect_health_metrics(self) -> Dict[str, Any]:
        """
        Collect comprehensive health metrics.
        
        Returns:
            Dictionary containing all health metrics
        """
        metrics = {
            "timestamp": datetime.utcnow().isoformat(),
            "uptime_seconds": int(time.time() - self._start_time),
            "system": await self._collect_system_metrics(),
            "service": await self._collect_service_metrics(),
            "errors": self._collect_error_metrics(),
        }
        
        return metrics
    
    async def _collect_system_metrics(self) -> Dict[str, Any]:
        """
        Collect system-level metrics using psutil.
        
        Returns:
            Dictionary containing system metrics
        """
        try:
            # CPU metrics
            cpu_percent = psutil.cpu_percent(interval=0.1)
            cpu_count = psutil.cpu_count()
            
            # Memory metrics
            memory = psutil.virtual_memory()
            
            # Disk metrics
            disk = psutil.disk_usage('/')
            
            system_metrics = {
                "cpu": {
                    "percent": cpu_percent,
                    "count": cpu_count,
                },
                "memory": {
                    "total_mb": memory.total / (1024 * 1024),
                    "available_mb": memory.available / (1024 * 1024),
                    "used_mb": memory.used / (1024 * 1024),
                    "percent": memory.percent,
                },
                "disk": {
                    "total_gb": disk.total / (1024 ** 3),
                    "used_gb": disk.used / (1024 ** 3),
                    "free_gb": disk.free / (1024 ** 3),
                    "percent": disk.percent,
                },
            }
            
            # Try to get temperature (RPi specific)
            try:
                temps = psutil.sensors_temperatures()
                if temps:
                    # Get CPU temperature (common on RPi)
                    cpu_temp = None
                    if 'cpu_thermal' in temps:
                        cpu_temp = temps['cpu_thermal'][0].current
                    elif 'coretemp' in temps:
                        cpu_temp = temps['coretemp'][0].current
                    
                    if cpu_temp is not None:
                        system_metrics["temperature"] = {
                            "cpu_celsius": cpu_temp
                        }
            except (AttributeError, OSError):
                # Temperature sensors not available
                pass
            
            return system_metrics
            
        except Exception as e:
            logger.error(
                f"Error collecting system metrics: {e}",
                exc_info=True
            )
            return {}
    
    async def _collect_service_metrics(self) -> Dict[str, Any]:
        """
        Collect service-level metrics.
        
        Returns:
            Dictionary containing service metrics
        """
        try:
            service_metrics = {}
            
            # Serial Manager metrics
            try:
                from .serial_manager import get_serial_manager
                serial_manager = get_serial_manager()
                
                active_connections = serial_manager.get_active_connections()
                service_metrics["serial"] = {
                    "active_connections": len(active_connections),
                    "ports": [
                        {
                            "port_id": conn.port_id,
                            "status": conn.status.value if hasattr(conn.status, 'value') else str(conn.status),
                            "baud_rate": conn.baud_rate,
                            "bytes_read": getattr(conn, 'bytes_read', 0),
                            "bytes_written": getattr(conn, 'bytes_written', 0),
                        }
                        for conn in active_connections.values()
                    ],
                }
            except RuntimeError:
                # Serial manager not initialized
                service_metrics["serial"] = {
                    "active_connections": 0,
                    "ports": [],
                }
            
            # USB Port Mapper metrics
            try:
                from .usb_port_mapper import get_usb_port_mapper
                usb_mapper = get_usb_port_mapper()
                
                # Get count of detected devices from port_id_to_device_info
                devices_count = len(usb_mapper.port_id_to_device_info)
                service_metrics["usb"] = {
                    "detected_devices": devices_count,
                }
            except RuntimeError:
                service_metrics["usb"] = {
                    "detected_devices": 0,
                }
            
            # Command Handler metrics
            try:
                from .command_handler import get_command_handler
                command_handler = get_command_handler()
                
                service_metrics["tasks"] = {
                    "queue_size": command_handler.get_queue_size(),
                    "running_count": command_handler.get_running_task_count(),
                    "total_tasks": len(command_handler.get_all_tasks()),
                }
            except RuntimeError:
                # Command handler not initialized
                service_metrics["tasks"] = {
                    "queue_size": 0,
                    "running_count": 0,
                    "total_tasks": 0,
                }
            
            # Buffer Manager metrics
            try:
                from .buffer_manager import get_buffer_manager
                buffer_manager = get_buffer_manager()
                
                buffer_stats = buffer_manager.get_stats()
                service_metrics["buffer"] = buffer_stats
            except RuntimeError:
                # Buffer manager not initialized
                service_metrics["buffer"] = {
                    "utilization_percent": 0,
                    "message_count": 0,
                }
            
            return service_metrics
            
        except Exception as e:
            logger.error(
                f"Error collecting service metrics: {e}",
                exc_info=True
            )
            return {}
    
    def _collect_error_metrics(self) -> Dict[str, Any]:
        """
        Collect error tracking metrics.
        
        Returns:
            Dictionary containing error counts
        """
        return {
            "total_errors": sum(self._port_errors.values()),
            "port_errors": dict(self._port_errors),
            "port_read_errors": dict(self._port_read_errors),
            "port_write_errors": dict(self._port_write_errors),
        }
    
    def record_port_error(
        self,
        port_id: str,
        error_type: str = "general"
    ) -> None:
        """
        Record error for specific port.
        
        Args:
            port_id: Port identifier
            error_type: Type of error (general, read, write)
        """
        if error_type == "read":
            self._port_read_errors[port_id] = self._port_read_errors.get(port_id, 0) + 1
        elif error_type == "write":
            self._port_write_errors[port_id] = self._port_write_errors.get(port_id, 0) + 1
        
        self._port_errors[port_id] = self._port_errors.get(port_id, 0) + 1
        
        logger.debug(
            f"Error recorded for port {port_id}",
            extra={
                "port_id": port_id,
                "error_type": error_type,
                "total_errors": self._port_errors[port_id]
            }
        )
    
    def reset_port_errors(self, port_id: Optional[str] = None) -> None:
        """
        Reset error counts for port(s).
        
        Args:
            port_id: Port identifier, or None to reset all
        """
        if port_id:
            self._port_errors.pop(port_id, None)
            self._port_read_errors.pop(port_id, None)
            self._port_write_errors.pop(port_id, None)
        else:
            self._port_errors.clear()
            self._port_read_errors.clear()
            self._port_write_errors.clear()
        
        logger.debug(
            "Error counts reset",
            extra={"port_id": port_id or "all"}
        )
    
    async def _send_health_report(self, health_data: Dict[str, Any]) -> None:
        """
        Send health report via callback.
        
        Args:
            health_data: Health metrics data
        """
        if not self.health_callback:
            return
        
        try:
            if asyncio.iscoroutinefunction(self.health_callback):
                await self.health_callback(health_data)
            else:
                self.health_callback(health_data)
            
            logger.debug(
                "Health report sent",
                extra={
                    "uptime_seconds": health_data.get("uptime_seconds"),
                    "cpu_percent": health_data.get("system", {}).get("cpu", {}).get("percent"),
                    "memory_percent": health_data.get("system", {}).get("memory", {}).get("percent"),
                }
            )
            
        except Exception as e:
            logger.error(
                f"Failed to send health report: {e}",
                exc_info=True
            )
    
    def get_uptime_seconds(self) -> int:
        """
        Get service uptime in seconds.
        
        Returns:
            Uptime in seconds
        """
        return int(time.time() - self._start_time)
    
    def get_error_count(self, port_id: Optional[str] = None) -> int:
        """
        Get error count for port or total.
        
        Args:
            port_id: Port identifier, or None for total
            
        Returns:
            Error count
        """
        if port_id:
            return self._port_errors.get(port_id, 0)
        return sum(self._port_errors.values())


# Global health reporter instance
_health_reporter: Optional[HealthReporter] = None


def get_health_reporter() -> HealthReporter:
    """
    Get global HealthReporter instance.
    
    Returns:
        Global HealthReporter instance
        
    Raises:
        RuntimeError: If health reporter not initialized
    """
    if _health_reporter is None:
        raise RuntimeError(
            "HealthReporter not initialized. Call initialize_health_reporter() first."
        )
    return _health_reporter


def initialize_health_reporter(
    report_interval: int = 30,
    health_callback: Optional[Callable[[Dict[str, Any]], None]] = None
) -> HealthReporter:
    """
    Initialize global HealthReporter instance.
    
    Args:
        report_interval: Reporting interval in seconds
        health_callback: Callback for health reports
        
    Returns:
        Initialized HealthReporter instance
    """
    global _health_reporter
    
    if _health_reporter is not None:
        logger.warning("HealthReporter already initialized")
        return _health_reporter
    
    _health_reporter = HealthReporter(
        report_interval=report_interval,
        health_callback=health_callback
    )
    
    return _health_reporter
