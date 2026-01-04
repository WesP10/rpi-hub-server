"""
Quick startup test to verify all components initialize correctly.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import get_settings
from src.logging_config import setup_logging, get_logger

setup_logging()
logger = get_logger(__name__)


async def test_startup():
    """Test component initialization."""
    
    logger.info("Testing component initialization...")
    
    try:
        # Test Config
        logger.info("Config loading")
        settings = get_settings()
        logger.info(f"  Hub ID: {settings.hub.hub_id}")
        
        # Test USB Port Mapper
        logger.info("USB Port Mapper")
        from src.usb_port_mapper import initialize_usb_port_mapper
        usb_mapper = initialize_usb_port_mapper(scan_interval=2)
        await usb_mapper.start()
        devices = await usb_mapper.list_mapped_connections()
        logger.info(f"  Detected {len(devices)} devices")
        await usb_mapper.stop()
        
        # Test Serial Manager
        logger.info("Serial Manager")
        from src.serial_manager import initialize_serial_manager
        serial_manager = initialize_serial_manager()
        logger.info("  Serial Manager initialized")
        
        # Test Buffer Manager
        logger.info("Buffer Manager")
        from src.buffer_manager import initialize_buffer_manager
        buffer_manager = initialize_buffer_manager()
        stats = buffer_manager.get_stats()
        logger.info(f"  Buffer size: {stats['size_mb']}MB")
        
        # Test Command Handler
        logger.info("Command Handler")
        from src.command_handler import initialize_command_handler
        command_handler = initialize_command_handler()
        await command_handler.start()
        logger.info(f"  Workers: {command_handler.max_concurrent_tasks}")
        await command_handler.stop()
        
        # Test Health Reporter
        logger.info("Health Reporter")
        from src.health_reporter import initialize_health_reporter
        health_reporter = initialize_health_reporter()
        await health_reporter.start()
        metrics = await health_reporter.collect_health_metrics()
        logger.info(f"  Uptime: {metrics['uptime_seconds']}s")
        await health_reporter.stop()
        
        logger.info("\nAll components initialized successfully!")
        logger.info("\nReady to start service with:")
        logger.info("  uvicorn src.main:app --host 0.0.0.0 --port 8000")
        
    except Exception as e:
        logger.error(f"\nInitialization failed: {e}", exc_info=True)
        return False
    
    return True


if __name__ == "__main__":
    success = asyncio.run(test_startup())
    sys.exit(0 if success else 1)
