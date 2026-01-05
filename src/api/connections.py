"""Serial connection management endpoints."""

from fastapi import APIRouter, HTTPException

from ..serial_manager import get_serial_manager
from ..usb_port_mapper import get_usb_port_mapper
from ..logging_config import get_logger
from .models import (
    OpenConnectionRequest,
    OpenConnectionResponse,
    ConnectionListResponse,
    ConnectionInfo,
    CloseConnectionResponse
)

logger = get_logger(__name__)
router = APIRouter(prefix="/connections", tags=["connections"])


@router.post("", response_model=OpenConnectionResponse)
async def open_connection(request: OpenConnectionRequest):
    """
    Open serial connection to device.
    
    Args:
        request: Connection parameters
        
    Returns:
        Connection details including session ID
    """
    try:
        serial_manager = get_serial_manager()
        usb_mapper = get_usb_port_mapper()
        
        # Verify port exists
        device = usb_mapper.get_device_by_id(request.port_id)
        if not device:
            raise HTTPException(
                status_code=404,
                detail=f"Port not found: {request.port_id}"
            )
        
        # Open connection
        connection = await serial_manager.open_connection(
            port_id=request.port_id,
            baud_rate=request.baud_rate
        )
        
        return OpenConnectionResponse(
            port_id=connection.port_id,
            status=connection.status,
            baud_rate=connection.baud_rate,
            session_id=connection.session_id
        )
        
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )
    except Exception as e:
        logger.error(
            f"Failed to open connection: {e}",
            extra={"port_id": request.port_id},
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to open connection: {str(e)}"
        )


@router.delete("/{port_id}", response_model=CloseConnectionResponse)
async def close_connection(port_id: str):
    """
    Close serial connection.
    
    Args:
        port_id: Port identifier
        
    Returns:
        Closure confirmation
    """
    try:
        serial_manager = get_serial_manager()
        
        # Verify connection exists
        connection = serial_manager.get_connection(port_id)
        if not connection:
            raise HTTPException(
                status_code=404,
                detail=f"No active connection for port: {port_id}"
            )
        
        # Close connection
        await serial_manager.close_connection(port_id)
        
        return CloseConnectionResponse(
            port_id=port_id,
            status="closed",
            message="Connection closed successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Failed to close connection: {e}",
            extra={"port_id": port_id},
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to close connection: {str(e)}"
        )


@router.get("", response_model=ConnectionListResponse)
async def list_connections():
    """
    List all active serial connections.
    
    Returns:
        List of active connections with statistics
    """
    try:
        serial_manager = get_serial_manager()
        usb_mapper = get_usb_port_mapper()
        
        active_connections = serial_manager.get_active_connections()
        
        connections = []
        for conn in active_connections.values():
            # Get device info for port path
            device = usb_mapper.get_device_by_id(conn.port_id)
            port_path = device["port"] if device else "unknown"
            
            connections.append(
                ConnectionInfo(
                    port_id=conn.port_id,
                    port=port_path,
                    status=conn.status,
                    baud_rate=conn.baud_rate,
                    session_id=conn.session_id,
                    bytes_read=conn.bytes_read,
                    bytes_written=conn.bytes_written
                )
            )
        
        return ConnectionListResponse(
            connections=connections,
            count=len(connections)
        )
        
    except Exception as e:
        logger.error(
            f"Failed to list connections: {e}",
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list connections: {str(e)}"
        )
