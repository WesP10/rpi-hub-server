"""
FastAPI main application for RPi Hub Service.

Manages lifespan of all service components and provides HTTP API endpoints.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .logging_config import setup_logging, get_logger
from .usb_port_mapper import initialize_usb_port_mapper
from .serial_manager import initialize_serial_manager
from .buffer_manager import initialize_buffer_manager
from .hub_agent import HubAgent
from .command_handler import initialize_command_handler
from .health_reporter import initialize_health_reporter

# Import API routers
from .api import health_router, ports_router, connections_router, tasks_router

# Setup logging
setup_logging()
logger = get_logger(__name__)

# Global component instances
hub_agent = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application lifespan.
    
    Initializes all service components on startup and gracefully shuts down on exit.
    """
    global hub_agent
    
    settings = get_settings()
    
    # Log environment variables being used
    import os
    logger.info(
        "Environment variables check",
        extra={
            "HUB_ID_env": os.getenv("HUB_ID", "NOT SET"),
            "SERVER_ENDPOINT_env": os.getenv("SERVER_ENDPOINT", "NOT SET"),
            "DEVICE_TOKEN_env": "SET" if os.getenv("DEVICE_TOKEN") else "NOT SET",
        }
    )
    
    logger.info(
        "Starting RPi Hub Service",
        extra={
            "hub_id": settings.hub.hub_id,
            "server_endpoint": settings.hub.server_endpoint,
            "device_token_set": bool(settings.hub.device_token),
            "device_token_length": len(settings.hub.device_token) if settings.hub.device_token else 0,
        }
    )
    
    # Log critical connection parameters for debugging
    if settings.hub.server_endpoint == "ws://localhost:8080/hub":
        logger.warning(
            "Using default localhost endpoint - ensure cloud service is accessible",
            extra={
                "server_endpoint": settings.hub.server_endpoint,
                "hint": "Set SERVER_ENDPOINT environment variable or update config/config.yaml"
            }
        )
    
    if not settings.hub.device_token:
        logger.warning(
            "DEVICE_TOKEN is not set - authentication will fail",
            extra={"hub_id": settings.hub.hub_id}
        )
    
    # Initialize variables to None to prevent UnboundLocalError in finally block
    usb_mapper = None
    serial_manager = None
    buffer_manager = None
    command_handler = None
    health_reporter = None
    hub_connection_manager = None
    
    try:
        # Initialize USB Port Mapper
        logger.info("Initializing USB Port Mapper")
        usb_mapper = initialize_usb_port_mapper(
            scan_interval=settings.serial.scan_interval
        )
        
        # Initialize Serial Manager
        logger.info("Initializing Serial Manager")
        serial_manager = initialize_serial_manager(
            max_connections=settings.serial.max_connections,
            task_queue_size=settings.serial.task_queue_size,
            connection_retry_attempts=settings.serial.connection_retry_attempts,
            default_timeout=settings.serial.default_timeout
        )
        
        # Set data callback for forwarding serial data to Hub Agent
        def serial_data_callback(port_id: str, session_id: str, data: bytes):
            """Callback for serial data - forwards to Hub Agent."""
            if hub_agent and hub_agent.is_connected:
                asyncio.create_task(
                    hub_agent.send_telemetry(
                        port_id=port_id,
                        session_id=session_id,
                        data=data
                    )
                )
        
        serial_manager.set_data_callback(serial_data_callback)
        await serial_manager.start()
        
        # Set up auto-connection callback for USB devices
        if settings.serial.auto_connect:
            async def auto_connect_device(device_info):
                """Automatically connect to detected devices."""
                try:
                    import time
                    session_id = f"auto-session-{int(time.time())}-{device_info.port_id[:8]}"
                    
                    # Use detected baud rate or default
                    baud_rate = device_info.detected_baud or settings.serial.default_baud_rate
                    
                    logger.info(
                        "auto_connect_triggered",
                        f"Auto-connecting to {device_info.port_id}",
                        extra={
                            "port_id": device_info.port_id,
                            "device_path": device_info.device_path,
                            "baud_rate": baud_rate,
                            "vendor_id": device_info.vendor_id,
                            "product_id": device_info.product_id,
                        }
                    )
                    
                    success = await serial_manager.open_connection(
                        session_id=session_id,
                        port_id=device_info.port_id,
                        device_path=device_info.device_path,
                        baud_rate=baud_rate,
                        hub_id=settings.hub.hub_id,
                    )
                    
                    if success:
                        logger.info(
                            "auto_connect_success",
                            f"Auto-connected to {device_info.port_id}",
                            extra={
                                "port_id": device_info.port_id,
                                "session_id": session_id,
                                "baud_rate": baud_rate,
                            }
                        )
                        
                        # Send device event to server
                        if hub_agent and hub_agent.is_connected:
                            await hub_agent.send_device_event(
                                event_type="connected",
                                port_id=device_info.port_id,
                                device_info={
                                    "port": device_info.device_path,
                                    "vendor_id": device_info.vendor_id,
                                    "product_id": device_info.product_id,
                                    "serial_number": device_info.serial_number,
                                    "manufacturer": device_info.manufacturer,
                                    "product": device_info.product,
                                    "baud_rate": baud_rate,
                                    "auto_connected": True,
                                }
                            )
                    else:
                        logger.warning(
                            "auto_connect_failed",
                            f"Failed to auto-connect to {device_info.port_id}",
                            extra={"port_id": device_info.port_id}
                        )
                        
                except Exception as e:
                    logger.error(
                        "auto_connect_error",
                        f"Error auto-connecting to {device_info.port_id}: {e}",
                        extra={
                            "port_id": device_info.port_id,
                            "error": str(e),
                        },
                        exc_info=True
                    )
            
            async def auto_disconnect_device(device_info):
                """Automatically disconnect removed devices."""
                try:
                    logger.info(
                        "auto_disconnect_triggered",
                        f"Device removed: {device_info.port_id}",
                        extra={"port_id": device_info.port_id}
                    )
                    
                    # Close the connection
                    await serial_manager.close_connection(device_info.port_id)
                    
                    # Send device event to server
                    if hub_agent and hub_agent.is_connected:
                        await hub_agent.send_device_event(
                            event_type="disconnected",
                            port_id=device_info.port_id,
                            device_info={
                                "port": device_info.device_path,
                                "vendor_id": device_info.vendor_id,
                                "product_id": device_info.product_id,
                            }
                        )
                        
                except Exception as e:
                    logger.error(
                        "auto_disconnect_error",
                        f"Error auto-disconnecting {device_info.port_id}: {e}",
                        extra={
                            "port_id": device_info.port_id,
                            "error": str(e),
                        },
                        exc_info=True
                    )
            
            usb_mapper.on_device_connected(auto_connect_device)
            usb_mapper.on_device_disconnected(auto_disconnect_device)
            
            logger.info(
                "auto_connect_enabled",
                "Auto-connection enabled for detected devices"
            )
        
        # Start USB port mapper scanning
        await usb_mapper.start(scan_interval=settings.serial.scan_interval)
        
        # Initialize Buffer Manager
        logger.info("Initializing Buffer Manager")
        buffer_manager = initialize_buffer_manager(
            size_mb=settings.buffer.size_mb,
            warn_threshold=settings.buffer.warn_threshold
        )
        
        # Initialize Hub Agent
        logger.info("Initializing Hub Agent")
        hub_agent = HubAgent(
            hub_id=settings.hub.hub_id,
            server_endpoint=settings.hub.server_endpoint,
            device_token=settings.hub.device_token,
            buffer_manager=buffer_manager,
            reconnect_interval=settings.hub.reconnect_interval,
            max_reconnect_attempts=settings.hub.max_reconnect_attempts
        )
        
        # Initialize Command Handler with task status callback
        logger.info("Initializing Command Handler")
        command_handler = initialize_command_handler(
            task_status_callback=hub_agent.send_task_status_update,
            max_concurrent_tasks=5
        )
        await command_handler.start()
        
        # Set Hub Agent command callback
        async def handle_command(command_envelope):
            """Handle incoming commands from server."""
            try:
                await command_handler.handle_command(command_envelope)
            except Exception as e:
                logger.error(
                    f"Failed to handle command: {e}",
                    extra={"command": command_envelope},
                    exc_info=True
                )
        
        hub_agent.set_command_callback(handle_command)
        
        # Initialize Health Reporter with callback
        logger.info("Initializing Health Reporter")
        health_reporter = initialize_health_reporter(
            report_interval=settings.health.report_interval,
            health_callback=lambda health_data: asyncio.create_task(
                hub_agent.send_health_status(health_data)
            )
        )
        await health_reporter.start()
        
        # Connect Hub Agent to server
        logger.info("Connecting to server")
        await hub_agent.connect_to_server()
        
        logger.info(
            "RPi Hub Service started successfully",
            extra={
                "hub_id": settings.hub.hub_id,
                "api_port": settings.api.port
            }
        )
        
        yield
        
    finally:
        # Shutdown sequence
        logger.info("Shutting down RPi Hub Service")
        
        try:
            # Stop Health Reporter
            if health_reporter:
                logger.info("Stopping Health Reporter")
                await health_reporter.stop()
            
            # Stop Command Handler
            if command_handler:
                logger.info("Stopping Command Handler")
                await command_handler.stop()
            
            # Disconnect Hub Agent
            if hub_agent:
                logger.info("Disconnecting Hub Agent")
                await hub_agent.disconnect_from_server()
                await hub_agent.stop()
            
            # Stop Serial Manager
            if serial_manager:
                logger.info("Stopping Serial Manager")
                await serial_manager.stop()
            
            # Stop USB Port Mapper
            if usb_mapper:
                logger.info("Stopping USB Port Mapper")
                await usb_mapper.stop()
            
            logger.info("RPi Hub Service shutdown complete")
            
        except Exception as e:
            logger.error(
                f"Error during shutdown: {e}",
                exc_info=True
            )


# Create FastAPI application
app = FastAPI(
    title="RPi Hub Service",
    description="Raspberry Pi hub service for Arduino serial communication",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all HTTP requests."""
    start_time = asyncio.get_event_loop().time()
    
    logger.info(
        f"Request started",
        extra={
            "method": request.method,
            "url": str(request.url),
            "client": request.client.host if request.client else None
        }
    )
    
    try:
        response = await call_next(request)
        
        duration_ms = (asyncio.get_event_loop().time() - start_time) * 1000
        
        logger.info(
            f"Request completed",
            extra={
                "method": request.method,
                "url": str(request.url),
                "status_code": response.status_code,
                "duration_ms": duration_ms
            }
        )
        
        return response
        
    except Exception as e:
        duration_ms = (asyncio.get_event_loop().time() - start_time) * 1000
        
        logger.error(
            f"Request failed: {e}",
            extra={
                "method": request.method,
                "url": str(request.url),
                "duration_ms": duration_ms
            },
            exc_info=True
        )
        raise


# Exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle uncaught exceptions."""
    logger.error(
        f"Unhandled exception: {exc}",
        extra={
            "method": request.method,
            "url": str(request.url)
        },
        exc_info=True
    )
    
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc),
            "timestamp": datetime.utcnow().isoformat()
        }
    )


# Include routers
app.include_router(health_router)
app.include_router(ports_router)
app.include_router(connections_router)
app.include_router(tasks_router)


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint with service information."""
    settings = get_settings()
    
    return {
        "service": "RPi Hub Service",
        "version": "1.0.0",
        "hub_id": settings.hub.hub_id,
        "status": "running",
        "timestamp": datetime.utcnow().isoformat()
    }


if __name__ == "__main__":
    import uvicorn
    
    settings = get_settings()
    
    uvicorn.run(
        "src.main:app",
        host=settings.api.host,
        port=settings.api.port,
        reload=settings.api.reload,
        log_level=settings.logging.level.lower()
    )
