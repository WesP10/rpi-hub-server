"""Port management endpoints."""

from fastapi import APIRouter, HTTPException

from ..usb_port_mapper import get_usb_port_mapper
from ..serial_manager import get_serial_manager
from ..logging_config import get_logger
from .models import PortListResponse, PortInfo, PortDetailResponse

logger = get_logger(__name__)
router = APIRouter(prefix="/ports", tags=["ports"])


@router.get("", response_model=PortListResponse)
async def list_ports():
    """
    List all detected serial ports.
    
    Returns:
        List of available serial ports with device information
    """
    try:
        usb_mapper = get_usb_port_mapper()
        devices = usb_mapper.get_all_devices()
        
        ports = [
            PortInfo(
                port_id=device["port_id"],
                port=device["port"],
                description=device.get("description", ""),
                manufacturer=device.get("manufacturer"),
                serial_number=device.get("serial_number"),
                vendor_id=device.get("vendor_id"),
                product_id=device.get("product_id")
            )
            for device in devices
        ]
        
        return PortListResponse(
            ports=ports,
            count=len(ports)
        )
        
    except Exception as e:
        logger.error(
            f"Failed to list ports: {e}",
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list ports: {str(e)}"
        )


@router.post("/scan")
async def scan_ports():
    """
    Trigger manual port scan.
    
    Returns:
        Updated list of detected ports
    """
    try:
        usb_mapper = get_usb_port_mapper()
        
        # Trigger scan (USB mapper already scans continuously, but this forces immediate update)
        devices = usb_mapper.get_all_devices()
        
        return {
            "message": "Port scan completed",
            "detected_count": len(devices)
        }
        
    except Exception as e:
        logger.error(
            f"Failed to scan ports: {e}",
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to scan ports: {str(e)}"
        )


@router.get("/{port_id}", response_model=PortDetailResponse)
async def get_port_details(port_id: str):
    """
    Get detailed information about specific port.
    
    Args:
        port_id: Port identifier
        
    Returns:
        Detailed port information including connection status
    """
    try:
        usb_mapper = get_usb_port_mapper()
        serial_manager = get_serial_manager()
        
        # Get device info
        device = usb_mapper.get_device_by_id(port_id)
        if not device:
            raise HTTPException(
                status_code=404,
                detail=f"Port not found: {port_id}"
            )
        
        port_info = PortInfo(
            port_id=device["port_id"],
            port=device["port"],
            description=device.get("description", ""),
            manufacturer=device.get("manufacturer"),
            serial_number=device.get("serial_number"),
            vendor_id=device.get("vendor_id"),
            product_id=device.get("product_id")
        )
        
        # Get connection status
        connection = serial_manager.get_connection(port_id)
        
        if connection:
            return PortDetailResponse(
                port_info=port_info,
                connection_status=connection.status,
                baud_rate=connection.baud_rate,
                bytes_read=connection.bytes_read,
                bytes_written=connection.bytes_written
            )
        else:
            return PortDetailResponse(
                port_info=port_info,
                connection_status="disconnected"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Failed to get port details: {e}",
            extra={"port_id": port_id},
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get port details: {str(e)}"
        )
