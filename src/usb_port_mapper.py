"""USB Port Mapper with hotplug detection and iterative baud rate detection."""

import asyncio
import hashlib
import json
import serial
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set

import serial.tools.list_ports

from src.logging_config import StructuredLogger

# Common baud rates to try (in order of likelihood)
COMMON_BAUD_RATES = [
    115200,  # Most modern Arduino boards
    9600,    # Default for many older boards
    57600,   # Common alternative
    38400,
    19200,
    74880,   # ESP8266 boot messages
    230400,  # High-speed devices
    250000,  # 3D printers (Marlin)
]


@dataclass
class DeviceInfo:
    """USB device information."""

    port_id: str
    device_path: str
    vendor_id: Optional[str] = None
    product_id: Optional[str] = None
    serial_number: Optional[str] = None
    manufacturer: Optional[str] = None
    product: Optional[str] = None
    location: Optional[str] = None
    detected_baud: Optional[int] = None
    description: str = ""
    hwid: str = ""
    source: str = "pyserial"  # Detection source


@dataclass
class MappedConnection:
    """Mapped connection information."""

    port_id: str
    device_path: str
    device_info: DeviceInfo
    is_available: bool = True
    last_seen: datetime = field(default_factory=datetime.now)


class USBPortMapper:
    """Manages USB port detection and stable ID mapping."""

    def __init__(
        self,
        persistence_path: str = "/var/lib/rpi-hub/port_mappings.json",
        default_baud_rate: int = 9600,
    ):
        """Initialize USB Port Mapper.

        Args:
            persistence_path: Path to save port mappings
            default_baud_rate: Default baud rate fallback
        """
        self.logger = StructuredLogger(__name__)
        self.persistence_path = Path(persistence_path)
        self.default_baud_rate = default_baud_rate

        # Mappings
        self.device_path_to_port_id: Dict[str, str] = {}
        self.port_id_to_device_info: Dict[str, DeviceInfo] = {}

        # Tracking
        self.last_scan_time: Optional[datetime] = None
        self._scan_task: Optional[asyncio.Task] = None
        self._running = False

        # Hotplug callbacks
        self._device_connected_callbacks: List = []
        self._device_disconnected_callbacks: List = []

        self.logger.info("usb_mapper_initialized", "USB Port Mapper initialized")

    async def start(self, scan_interval: int = 2) -> None:
        """Start continuous port scanning.

        Args:
            scan_interval: Scan interval in seconds
        """
        self._running = True
        await self.load_mappings()

        # Initial scan
        await self.refresh()

        # Start scanning loop
        self._scan_task = asyncio.create_task(self._scan_loop(scan_interval))
        self.logger.info(
            "usb_mapper_started",
            "USB Port Mapper scanning started",
            scan_interval=scan_interval,
        )

    async def stop(self) -> None:
        """Stop port scanning."""
        self._running = False
        if self._scan_task:
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                pass

        await self.save_mappings()
        self.logger.info("usb_mapper_stopped", "USB Port Mapper stopped")

    async def _scan_loop(self, interval: int) -> None:
        """Continuous scanning loop.

        Args:
            interval: Scan interval in seconds
        """
        while self._running:
            try:
                await asyncio.sleep(interval)
                await self.refresh()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(
                    "scan_loop_error",
                    f"Error in scan loop: {e}",
                    error=str(e),
                )

    async def refresh(self) -> None:
        """Scan for USB devices and update mappings."""
        scan_start = datetime.now()

        # Get current ports
        new_devices = await self.detect_new_devices()
        removed_devices = await self.detect_removed_devices()

        # Process new devices
        for device_info in new_devices:
            port_id = await self.get_port_id(device_info.device_path, device_info)
            device_info.port_id = port_id
            self.port_id_to_device_info[port_id] = device_info
            self.device_path_to_port_id[device_info.device_path] = port_id

            # Trigger callbacks
            for callback in self._device_connected_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(device_info)
                    else:
                        callback(device_info)
                except Exception as e:
                    self.logger.error(
                        "callback_error",
                        f"Error in device connected callback: {e}",
                        error=str(e),
                    )

            self.logger.port_detected(
                port_id,
                device_info.device_path,
                vendor_id=device_info.vendor_id,
                product_id=device_info.product_id,
                detected_baud=device_info.detected_baud,
                source=device_info.source,
            )

        # Process removed devices
        for port_id in removed_devices:
            device_info = self.port_id_to_device_info.get(port_id)
            if device_info:
                # Trigger callbacks
                for callback in self._device_disconnected_callbacks:
                    try:
                        if asyncio.iscoroutinefunction(callback):
                            await callback(device_info)
                        else:
                            callback(device_info)
                    except Exception as e:
                        self.logger.error(
                            "callback_error",
                            f"Error in device disconnected callback: {e}",
                            error=str(e),
                        )

                self.logger.port_removed(port_id, device_path=device_info.device_path)

                # Clean up mappings
                self.device_path_to_port_id.pop(device_info.device_path, None)
                self.port_id_to_device_info.pop(port_id, None)

        self.last_scan_time = datetime.now()
        scan_duration = (self.last_scan_time - scan_start).total_seconds() * 1000

        self.logger.info(
            "port_scan_completed",
            f"Port scan completed in {scan_duration:.0f}ms",
            duration_ms=scan_duration,
            new_devices=len(new_devices),
            removed_devices=len(removed_devices),
            total_ports=len(self.port_id_to_device_info),
        )

    async def detect_new_devices(self) -> List[DeviceInfo]:
        """Detect newly connected devices.

        Returns:
            List of new device info
        """
        current_ports = await self._list_ports_with_baud()
        new_devices = []

        for device_info in current_ports:
            if device_info.device_path not in self.device_path_to_port_id:
                new_devices.append(device_info)

        return new_devices

    async def detect_removed_devices(self) -> List[str]:
        """Detect removed devices.

        Returns:
            List of removed port IDs
        """
        current_paths = {
            info.device_path
            for info in await self._list_ports_with_baud()
        }

        removed_port_ids = []
        for device_path, port_id in list(self.device_path_to_port_id.items()):
            if device_path not in current_paths:
                removed_port_ids.append(port_id)

        return removed_port_ids

    def _find_cached_baud_rate(self, vendor_id: Optional[str], product_id: Optional[str], 
                                serial_number: Optional[str], location: Optional[str]) -> Optional[int]:
        """Find cached baud rate for a device based on stable identifiers.
        
        Args:
            vendor_id: Vendor ID
            product_id: Product ID
            serial_number: Serial number
            location: USB location
            
        Returns:
            Cached baud rate or None if not found
        """
        for device_info in self.port_id_to_device_info.values():
            # Match based on stable identifiers
            if (device_info.vendor_id == vendor_id and 
                device_info.product_id == product_id and
                device_info.serial_number == serial_number and
                device_info.location == location and
                device_info.detected_baud is not None):
                return device_info.detected_baud
        return None

    async def _detect_baud_rate(self, device_path: str) -> int:
        """Detect baud rate by iteratively trying common rates.

        Args:
            device_path: Serial port device path

        Returns:
            Detected baud rate or default
        """
        loop = asyncio.get_event_loop()
        
        for baud_rate in COMMON_BAUD_RATES:
            try:
                # Attempt to open port at this baud rate (in executor to avoid blocking)
                def try_open():
                    try:
                        ser = serial.Serial(
                            port=device_path,
                            baudrate=baud_rate,
                            timeout=1.0,
                            write_timeout=1.0,
                        )
                        
                        # Clear any existing data in buffer first
                        import time
                        ser.reset_input_buffer()
                        
                        # Reset Arduino by toggling DTR (required for auto-start on RPi)
                        ser.dtr = False
                        time.sleep(0.1)
                        ser.dtr = True
                        
                        # Wait for Arduino to reset and start transmitting
                        time.sleep(1.65)
                        
                        # Check if there's data available (indicates active device)
                        has_data = ser.in_waiting > 0
                        
                        if has_data:
                            # Read a sample to verify it's not all nulls
                            sample = ser.read(min(ser.in_waiting, 64))
                            non_null_bytes = sum(1 for b in sample if b != 0)
                            ser.close()
                            return (True, non_null_bytes > 0)
                        
                        ser.close()
                        return (True, False)
                    except (serial.SerialException, OSError):
                        return (False, False)
                    except Exception:
                        return (False, False)
                
                success, has_data = await loop.run_in_executor(None, try_open)
                
                if success:
                    if has_data:
                        self.logger.info(
                            "baud_detected",
                            f"Detected baud rate {baud_rate} for {device_path}",
                            device_path=device_path,
                            baud_rate=baud_rate,
                        )
                    else:
                        self.logger.debug(
                            "baud_assumed",
                            f"Assuming baud rate {baud_rate} for {device_path}",
                            device_path=device_path,
                            baud_rate=baud_rate,
                        )
                    return baud_rate
                    
            except Exception as e:
                # Unexpected error, log and continue
                self.logger.debug(
                    "baud_probe_error",
                    f"Error probing {baud_rate}: {e}",
                    baud_rate=baud_rate,
                    error=str(e),
                )
                continue
        
        # All attempts failed, use default
        self.logger.warning(
            "baud_fallback",
            f"Could not detect baud rate for {device_path}, using default {self.default_baud_rate}",
            device_path=device_path,
            default_baud=self.default_baud_rate,
        )
        return self.default_baud_rate

    async def _list_ports_with_baud(self) -> List[DeviceInfo]:
        """List all serial ports with iterative baud rate detection.

        Returns:
            List of device information
        """
        return await self._detect_with_pyserial()

    async def _detect_with_pyserial(self) -> List[DeviceInfo]:
        """Detect ports using pyserial with iterative baud rate detection.

        Returns:
            List of detected devices
        """
        devices = []

        # Run blocking operation in executor
        loop = asyncio.get_event_loop()
        ports = await loop.run_in_executor(None, serial.tools.list_ports.comports)

        for port in ports:
            # Skip built-in serial ports (not USB devices)
            # Built-in ports typically have no vendor ID and match certain patterns
            if port.vid is None:
                # Check if it's a built-in hardware serial port
                device_lower = port.device.lower()
                if any(pattern in device_lower for pattern in ['/dev/ttys', '/dev/ttyama', 'com1', 'com2']):
                    self.logger.debug(
                        "skipping_builtin_port",
                        f"Skipping built-in serial port {port.device}",
                        device_path=port.device,
                    )
                    continue
            # Format vendor and product IDs
            vendor_id = f"{port.vid:04x}" if port.vid else None
            product_id = f"{port.pid:04x}" if port.pid else None
            
            # Check if we have a cached baud rate for this device
            cached_baud = self._find_cached_baud_rate(
                vendor_id, product_id, port.serial_number, port.location
            )
            
            if cached_baud is not None:
                # Use cached baud rate
                detected_baud = cached_baud
                self.logger.debug(
                    "baud_cached",
                    f"Using cached baud rate {cached_baud} for {port.device}",
                    device_path=port.device,
                    baud_rate=cached_baud,
                )
            else:
                # Probe for baud rate if not cached
                detected_baud = await self._detect_baud_rate(port.device)
            
            device_info = DeviceInfo(
                port_id="",  # Will be set later
                device_path=port.device,
                vendor_id=vendor_id,
                product_id=product_id,
                serial_number=port.serial_number,
                manufacturer=port.manufacturer,
                product=port.product,
                location=port.location,
                description=port.description,
                hwid=port.hwid,
                detected_baud=detected_baud,
                source="pyserial",
            )

            devices.append(device_info)

        return devices

    async def get_port_id(
        self, device_path: str, device_info: Optional[DeviceInfo] = None
    ) -> str:
        """Get stable port ID for a device path.

        Generates consistent ID based on USB location and serial number.

        Args:
            device_path: Device path (e.g., /dev/ttyUSB0)
            device_info: Optional device information

        Returns:
            Stable port ID
        """
        # Check if we already have a mapping
        if device_path in self.device_path_to_port_id:
            return self.device_path_to_port_id[device_path]

        # Generate stable ID from device characteristics
        if device_info:
            # Use location and serial number for stable ID
            id_source = (
                f"{device_info.location or ''}"
                f"{device_info.serial_number or ''}"
                f"{device_info.vendor_id or ''}"
                f"{device_info.product_id or ''}"
            )
        else:
            # Fallback to device path
            id_source = device_path

        # Generate short hash
        hash_obj = hashlib.sha256(id_source.encode())
        port_id = f"port_{hash_obj.hexdigest()[:8]}"

        return port_id

    async def get_device_info(self, port_id: str) -> Optional[DeviceInfo]:
        """Get device information for a port ID.

        Args:
            port_id: Port identifier

        Returns:
            Device information or None if not found
        """
        return self.port_id_to_device_info.get(port_id)

    async def list_mapped_connections(self) -> List[MappedConnection]:
        """List all mapped connections.

        Returns:
            List of mapped connections
        """
        connections = []
        for port_id, device_info in self.port_id_to_device_info.items():
            connection = MappedConnection(
                port_id=port_id,
                device_path=device_info.device_path,
                device_info=device_info,
                is_available=True,
            )
            connections.append(connection)

        return connections

    async def remove_mapping(self, port_id: str) -> bool:
        """Remove a port mapping.

        Args:
            port_id: Port identifier to remove

        Returns:
            True if removed, False if not found
        """
        device_info = self.port_id_to_device_info.get(port_id)
        if not device_info:
            return False

        self.device_path_to_port_id.pop(device_info.device_path, None)
        self.port_id_to_device_info.pop(port_id, None)

        self.logger.info(
            "mapping_removed",
            f"Removed mapping for {port_id}",
            port_id=port_id,
        )

        return True

    async def save_mappings(self) -> None:
        """Save port mappings to disk."""
        try:
            # Create directory if it doesn't exist
            self.persistence_path.parent.mkdir(parents=True, exist_ok=True)

            # Serialize mappings
            data = {
                "mappings": {
                    port_id: {
                        "device_path": info.device_path,
                        "vendor_id": info.vendor_id,
                        "product_id": info.product_id,
                        "serial_number": info.serial_number,
                        "location": info.location,
                        "detected_baud": info.detected_baud,
                    }
                    for port_id, info in self.port_id_to_device_info.items()
                },
                "last_saved": datetime.now().isoformat(),
            }

            # Write to file
            with open(self.persistence_path, "w") as f:
                json.dump(data, f, indent=2)

            self.logger.info(
                "mappings_saved",
                f"Saved {len(self.port_id_to_device_info)} mappings",
                count=len(self.port_id_to_device_info),
                path=str(self.persistence_path),
            )

        except Exception as e:
            self.logger.error(
                "mappings_save_error",
                f"Error saving mappings: {e}",
                error=str(e),
            )

    async def load_mappings(self) -> None:
        """Load port mappings from disk."""
        try:
            if not self.persistence_path.exists():
                self.logger.info(
                    "no_mappings_file",
                    "No existing mappings file found",
                )
                return

            with open(self.persistence_path, "r") as f:
                data = json.load(f)

            # Restore saved device info (especially baud rates) for matching
            mappings = data.get("mappings", {})
            for port_id, saved_info in mappings.items():
                # Create device info from saved data
                device_info = DeviceInfo(
                    port_id=port_id,
                    device_path=saved_info.get("device_path", ""),
                    vendor_id=saved_info.get("vendor_id"),
                    product_id=saved_info.get("product_id"),
                    serial_number=saved_info.get("serial_number"),
                    location=saved_info.get("location"),
                    detected_baud=saved_info.get("detected_baud"),
                )
                self.port_id_to_device_info[port_id] = device_info

            self.logger.info(
                "mappings_loaded",
                f"Loaded {len(mappings)} saved mappings with cached baud rates",
                count=len(mappings),
            )

        except Exception as e:
            self.logger.error(
                "mappings_load_error",
                f"Error loading mappings: {e}",
                error=str(e),
            )

    def on_device_connected(self, callback) -> None:
        """Register callback for device connection events.

        Args:
            callback: Async or sync function(device_info: DeviceInfo)
        """
        self._device_connected_callbacks.append(callback)

    def on_device_disconnected(self, callback) -> None:
        """Register callback for device disconnection events.

        Args:
            callback: Async or sync function(device_info: DeviceInfo)
        """
        self._device_disconnected_callbacks.append(callback)


# Global USB port mapper instance
_usb_port_mapper: Optional[USBPortMapper] = None


def get_usb_port_mapper() -> USBPortMapper:
    """Get global USB Port Mapper instance.

    Returns:
        USBPortMapper instance

    Raises:
        RuntimeError: If USB port mapper not initialized
    """
    if _usb_port_mapper is None:
        raise RuntimeError(
            "USBPortMapper not initialized. Call initialize_usb_port_mapper() first."
        )
    return _usb_port_mapper


def initialize_usb_port_mapper(
    persistence_path: Optional[str] = None,
    default_baud_rate: Optional[int] = None,
    scan_interval: Optional[int] = None,
) -> USBPortMapper:
    """Initialize USB Port Mapper instance.

    Args:
        persistence_path: Path to save port mappings
        default_baud_rate: Default baud rate fallback
        scan_interval: Port scan interval (unused, for API compatibility)

    Returns:
        USBPortMapper instance
    """
    global _usb_port_mapper
    
    if _usb_port_mapper is not None:
        return _usb_port_mapper
    
    from src.config import get_settings

    settings = get_settings()
    _usb_port_mapper = USBPortMapper(
        persistence_path=persistence_path or settings.storage.port_mapping_file,
        default_baud_rate=default_baud_rate or settings.serial.default_baud_rate,
    )
    
    return _usb_port_mapper
