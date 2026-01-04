"""Pydantic models for API requests and responses."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# Health Models
class HealthResponse(BaseModel):
    """Basic health check response."""
    status: str = "healthy"
    timestamp: datetime


class SystemMetrics(BaseModel):
    """System metrics."""
    cpu: Dict[str, Any]
    memory: Dict[str, Any]
    disk: Dict[str, Any]
    temperature: Optional[Dict[str, Any]] = None


class ServiceMetrics(BaseModel):
    """Service metrics."""
    serial: Dict[str, Any]
    usb: Dict[str, Any]
    tasks: Dict[str, Any]
    buffer: Dict[str, Any]


class ErrorMetrics(BaseModel):
    """Error metrics."""
    total_errors: int
    port_errors: Dict[str, int]
    port_read_errors: Dict[str, int]
    port_write_errors: Dict[str, int]


class DetailedStatusResponse(BaseModel):
    """Detailed status response."""
    timestamp: datetime
    uptime_seconds: int
    system: SystemMetrics
    service: ServiceMetrics
    errors: ErrorMetrics


# Port Models
class PortInfo(BaseModel):
    """Serial port information."""
    port_id: str
    port: str
    description: str
    manufacturer: Optional[str] = None
    serial_number: Optional[str] = None
    vendor_id: Optional[str] = None
    product_id: Optional[str] = None


class PortListResponse(BaseModel):
    """List of detected ports."""
    ports: List[PortInfo]
    count: int


class PortDetailResponse(BaseModel):
    """Detailed port information."""
    port_info: PortInfo
    connection_status: str
    baud_rate: Optional[int] = None
    bytes_read: Optional[int] = None
    bytes_written: Optional[int] = None


# Connection Models
class OpenConnectionRequest(BaseModel):
    """Request to open serial connection."""
    port_id: str = Field(..., description="Port ID to connect to")
    baud_rate: Optional[int] = Field(None, description="Baud rate (auto-detect if not provided)")


class OpenConnectionResponse(BaseModel):
    """Response from opening connection."""
    port_id: str
    status: str
    baud_rate: int
    session_id: str


class ConnectionInfo(BaseModel):
    """Active connection information."""
    port_id: str
    port: str
    status: str
    baud_rate: int
    session_id: str
    bytes_read: int
    bytes_written: int


class ConnectionListResponse(BaseModel):
    """List of active connections."""
    connections: List[ConnectionInfo]
    count: int


class CloseConnectionResponse(BaseModel):
    """Response from closing connection."""
    port_id: str
    status: str
    message: str


# Task Models
class SerialWriteRequest(BaseModel):
    """Request to write data to serial port."""
    port_id: str = Field(..., description="Target port ID")
    data: str = Field(..., description="Data to write")
    encoding: str = Field("utf-8", description="Data encoding (utf-8 or base64)")
    priority: int = Field(5, ge=1, le=10, description="Task priority (1=highest)")


class FlashFirmwareRequest(BaseModel):
    """Request to flash firmware to device."""
    port_id: str = Field(..., description="Target port ID")
    firmware_data: str = Field(..., description="Base64 encoded firmware hex file")
    board_fqbn: Optional[str] = Field(None, description="Board FQBN (auto-detect if not provided)")
    priority: int = Field(3, ge=1, le=10, description="Task priority")


class RestartDeviceRequest(BaseModel):
    """Request to restart device."""
    port_id: str = Field(..., description="Target port ID")
    priority: int = Field(2, ge=1, le=10, description="Task priority")


class TaskResponse(BaseModel):
    """Task creation response."""
    task_id: str
    command_id: str
    status: str
    queued: bool


class TaskStatusResponse(BaseModel):
    """Task status information."""
    task_id: str
    command_type: str
    port_id: Optional[str]
    status: str
    priority: int
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class TaskListResponse(BaseModel):
    """List of tasks."""
    tasks: List[TaskStatusResponse]
    count: int


# Error Response
class ErrorResponse(BaseModel):
    """Error response."""
    error: str
    detail: Optional[str] = None
    timestamp: datetime
