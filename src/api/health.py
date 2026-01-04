"""Health check endpoints."""

from datetime import datetime

from fastapi import APIRouter, HTTPException

from ..health_reporter import get_health_reporter
from ..logging_config import get_logger
from .models import HealthResponse, DetailedStatusResponse

logger = get_logger(__name__)
router = APIRouter(prefix="", tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Basic health check endpoint.
    
    Returns:
        Basic health status
    """
    return HealthResponse(
        status="healthy",
        timestamp=datetime.utcnow()
    )


@router.get("/status", response_model=DetailedStatusResponse)
async def detailed_status():
    """
    Detailed status with comprehensive metrics.
    
    Returns:
        Detailed health and service metrics
    """
    try:
        health_reporter = get_health_reporter()
        metrics = await health_reporter.collect_health_metrics()
        
        return DetailedStatusResponse(**metrics)
        
    except Exception as e:
        logger.error(
            f"Failed to collect status metrics: {e}",
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to collect status: {str(e)}"
        )
