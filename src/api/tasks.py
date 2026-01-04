"""Task management endpoints."""

import uuid

from fastapi import APIRouter, HTTPException

from ..command_handler import get_command_handler
from ..logging_config import get_logger
from .models import (
    SerialWriteRequest,
    FlashFirmwareRequest,
    RestartDeviceRequest,
    TaskResponse,
    TaskStatusResponse,
    TaskListResponse
)

logger = get_logger(__name__)
router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("/write", response_model=TaskResponse)
async def write_to_serial(request: SerialWriteRequest):
    """
    Write data to serial port.
    
    Args:
        request: Write parameters
        
    Returns:
        Task information
    """
    try:
        command_handler = get_command_handler()
        
        # Create command envelope
        command_id = f"cmd-{uuid.uuid4().hex[:12]}"
        command_envelope = {
            "commandId": command_id,
            "commandType": "serial_write",
            "portId": request.port_id,
            "params": {
                "data": request.data,
                "encoding": request.encoding
            },
            "priority": request.priority
        }
        
        # Submit command
        result = await command_handler.handle_command(command_envelope)
        
        return TaskResponse(**result)
        
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )
    except Exception as e:
        logger.error(
            f"Failed to submit write task: {e}",
            extra={"port_id": request.port_id},
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to submit write task: {str(e)}"
        )


@router.post("/flash", response_model=TaskResponse)
async def flash_firmware(request: FlashFirmwareRequest):
    """
    Flash firmware to device.
    
    Args:
        request: Flash parameters
        
    Returns:
        Task information
    """
    try:
        command_handler = get_command_handler()
        
        # Create command envelope
        command_id = f"cmd-{uuid.uuid4().hex[:12]}"
        command_envelope = {
            "commandId": command_id,
            "commandType": "flash",
            "portId": request.port_id,
            "params": {
                "firmwareData": request.firmware_data,
                "boardFqbn": request.board_fqbn
            },
            "priority": request.priority
        }
        
        # Submit command
        result = await command_handler.handle_command(command_envelope)
        
        return TaskResponse(**result)
        
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )
    except Exception as e:
        logger.error(
            f"Failed to submit flash task: {e}",
            extra={"port_id": request.port_id},
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to submit flash task: {str(e)}"
        )


@router.post("/restart", response_model=TaskResponse)
async def restart_device(request: RestartDeviceRequest):
    """
    Restart device via DTR toggle.
    
    Args:
        request: Restart parameters
        
    Returns:
        Task information
    """
    try:
        command_handler = get_command_handler()
        
        # Create command envelope
        command_id = f"cmd-{uuid.uuid4().hex[:12]}"
        command_envelope = {
            "commandId": command_id,
            "commandType": "restart",
            "portId": request.port_id,
            "params": {},
            "priority": request.priority
        }
        
        # Submit command
        result = await command_handler.handle_command(command_envelope)
        
        return TaskResponse(**result)
        
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )
    except Exception as e:
        logger.error(
            f"Failed to submit restart task: {e}",
            extra={"port_id": request.port_id},
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to submit restart task: {str(e)}"
        )


@router.get("/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """
    Get task status and details.
    
    Args:
        task_id: Task identifier
        
    Returns:
        Task status information
    """
    try:
        command_handler = get_command_handler()
        
        task = command_handler.get_task(task_id)
        if not task:
            raise HTTPException(
                status_code=404,
                detail=f"Task not found: {task_id}"
            )
        
        task_dict = task.to_dict()
        return TaskStatusResponse(**task_dict)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Failed to get task status: {e}",
            extra={"task_id": task_id},
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get task status: {str(e)}"
        )


@router.get("", response_model=TaskListResponse)
async def list_tasks():
    """
    List all tasks.
    
    Returns:
        List of all tasks with their status
    """
    try:
        command_handler = get_command_handler()
        
        all_tasks = command_handler.get_all_tasks()
        
        tasks = [TaskStatusResponse(**task) for task in all_tasks]
        
        return TaskListResponse(
            tasks=tasks,
            count=len(tasks)
        )
        
    except Exception as e:
        logger.error(
            f"Failed to list tasks: {e}",
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list tasks: {str(e)}"
        )
