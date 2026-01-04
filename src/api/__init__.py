"""API routes for RPi Hub Service."""

__all__ = [
    "health_router",
    "ports_router",
    "connections_router",
    "tasks_router",
]

from .health import router as health_router
from .ports import router as ports_router
from .connections import router as connections_router
from .tasks import router as tasks_router
