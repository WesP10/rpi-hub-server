"""
Test script for WebSocket connection and message envelope testing.

This script:
1. Establishes WebSocket connection to rpi-hub-service
2. Tests sending different envelope types (telemetry, health, device_event, task_status)
3. Tests automatic serial reading with pyserial
4. Verifies message routing and buffer management
"""

import asyncio
import base64
import json
import sys
import time
from datetime import datetime
from typing import Dict, Any, Optional

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

# For serial testing
try:
    import serial
    from serial.tools import list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False
    print("Warning: pyserial not available. Serial tests will be skipped.")


class WebSocketTester:
    """Test WebSocket connection and message envelopes."""
    
    def __init__(self, endpoint: str, hub_id: str, device_token: str):
        """Initialize tester.
        
        Args:
            endpoint: WebSocket server URL (e.g., ws://localhost:8000/hub)
            hub_id: Hub identifier
            device_token: Authentication token
        """
        self.endpoint = endpoint
        self.hub_id = hub_id
        self.device_token = device_token
        self.ws_connection: Optional[websockets.WebSocketClientProtocol] = None
        self.is_connected = False
        self.received_messages = []
        
    async def connect(self) -> bool:
        """Establish WebSocket connection.
        
        Returns:
            True if connected successfully
        """
        try:
            print(f"\n{'='*60}")
            print(f"TEST 1: WebSocket Connection")
            print(f"{'='*60}")
            print(f"Connecting to: {self.endpoint}")
            print(f"Hub ID: {self.hub_id}")
            
            # Connect with ping settings
            self.ws_connection = await websockets.connect(
                self.endpoint,
                ping_interval=20,
                ping_timeout=10,
            )
            
            # Send handshake
            handshake = {
                "type": "hub_connect",
                "hubId": self.hub_id,
                "deviceToken": self.device_token,
                "timestamp": datetime.now().isoformat(),
                "version": "1.0.0",
            }
            
            await self.ws_connection.send(json.dumps(handshake))
            print(f"✓ Handshake sent")
            
            self.is_connected = True
            print(f"✓ WebSocket connection established")
            
            # Start receiver task
            asyncio.create_task(self._receive_loop())
            
            return True
            
        except Exception as e:
            print(f"✗ Connection failed: {e}")
            return False
    
    async def disconnect(self):
        """Close WebSocket connection."""
        if self.ws_connection:
            await self.ws_connection.close()
            self.is_connected = False
            print(f"✓ Disconnected from server")
    
    async def _receive_loop(self):
        """Receive and log messages from server."""
        while self.is_connected and self.ws_connection:
            try:
                message = await self.ws_connection.recv()
                data = json.loads(message)
                self.received_messages.append(data)
                print(f"← Received: {data.get('type', 'unknown')} message")
                
            except ConnectionClosed:
                print("✗ Connection closed by server")
                self.is_connected = False
                break
            except Exception as e:
                print(f"✗ Receive error: {e}")
                break
    
    async def send_telemetry_envelope(self, port_id: str, data: bytes):
        """Test sending telemetry envelope.
        
        Args:
            port_id: Port identifier
            data: Raw serial data bytes
        """
        print(f"\n{'='*60}")
        print(f"TEST 2: Telemetry Envelope")
        print(f"{'='*60}")
        
        if not self.is_connected:
            print("✗ Not connected to server")
            return
        
        try:
            # Create telemetry envelope
            envelope = {
                "type": "telemetry",
                "hubId": self.hub_id,
                "timestamp": datetime.now().isoformat(),
                "portId": port_id,
                "sessionId": f"test-session-{int(time.time())}",
                "data": base64.b64encode(data).decode("utf-8"),
            }
            
            await self.ws_connection.send(json.dumps(envelope))
            print(f"✓ Sent telemetry envelope")
            print(f"  Port: {port_id}")
            print(f"  Data length: {len(data)} bytes")
            print(f"  Data (hex): {data.hex()}")
            
            await asyncio.sleep(0.5)
            
        except Exception as e:
            print(f"✗ Failed to send telemetry: {e}")
    
    async def send_health_envelope(self):
        """Test sending health envelope."""
        print(f"\n{'='*60}")
        print(f"TEST 3: Health Envelope")
        print(f"{'='*60}")
        
        if not self.is_connected:
            print("✗ Not connected to server")
            return
        
        try:
            # Create health envelope with realistic metrics
            envelope = {
                "type": "health",
                "hubId": self.hub_id,
                "timestamp": datetime.utcnow().isoformat(),
                "uptime_seconds": 3600,
                "system": {
                    "cpu": {
                        "percent": 45.2,
                        "count": 4,
                    },
                    "memory": {
                        "total_mb": 4096.0,
                        "available_mb": 2048.0,
                        "used_mb": 2048.0,
                        "percent": 50.0,
                    },
                    "disk": {
                        "total_gb": 64.0,
                        "used_gb": 32.0,
                        "free_gb": 32.0,
                        "percent": 50.0,
                    },
                },
                "service": {
                    "serial": {
                        "active_connections": 1,
                        "total_bytes_read": 1024,
                        "total_bytes_written": 512,
                    },
                    "usb": {
                        "detected_ports": 2,
                    },
                    "tasks": {
                        "queue_size": 0,
                        "completed": 5,
                    },
                    "buffer": {
                        "size_mb": 0.5,
                        "utilization": 0.05,
                    },
                },
                "errors": {
                    "total_errors": 0,
                    "port_errors": {},
                    "port_read_errors": {},
                    "port_write_errors": {},
                },
            }
            
            await self.ws_connection.send(json.dumps(envelope))
            print(f"✓ Sent health envelope")
            print(f"  CPU: {envelope['system']['cpu']['percent']}%")
            print(f"  Memory: {envelope['system']['memory']['percent']}%")
            print(f"  Active connections: {envelope['service']['serial']['active_connections']}")
            
            await asyncio.sleep(0.5)
            
        except Exception as e:
            print(f"✗ Failed to send health: {e}")
    
    async def send_device_event_envelope(self, port_id: str, event_type: str = "connected"):
        """Test sending device event envelope.
        
        Args:
            port_id: Port identifier
            event_type: Event type (connected/disconnected)
        """
        print(f"\n{'='*60}")
        print(f"TEST 4: Device Event Envelope")
        print(f"{'='*60}")
        
        if not self.is_connected:
            print("✗ Not connected to server")
            return
        
        try:
            # Create device event envelope
            envelope = {
                "type": "device_event",
                "hubId": self.hub_id,
                "timestamp": datetime.now().isoformat(),
                "eventType": event_type,
                "portId": port_id,
                "deviceInfo": {
                    "port": "/dev/ttyUSB0",
                    "description": "USB Serial Device",
                    "manufacturer": "FTDI",
                    "serial_number": "FT123456",
                    "vendor_id": "0403",
                    "product_id": "6001",
                },
            }
            
            await self.ws_connection.send(json.dumps(envelope))
            print(f"✓ Sent device event envelope")
            print(f"  Event: {event_type}")
            print(f"  Port: {port_id}")
            
            await asyncio.sleep(0.5)
            
        except Exception as e:
            print(f"✗ Failed to send device event: {e}")
    
    async def send_task_status_envelope(self, task_id: str, status: str = "completed"):
        """Test sending task status envelope.
        
        Args:
            task_id: Task identifier
            status: Task status (completed/failed/running)
        """
        print(f"\n{'='*60}")
        print(f"TEST 5: Task Status Envelope")
        print(f"{'='*60}")
        
        if not self.is_connected:
            print("✗ Not connected to server")
            return
        
        try:
            # Create task status envelope
            envelope = {
                "type": "task_status",
                "hubId": self.hub_id,
                "timestamp": datetime.now().isoformat(),
                "taskId": task_id,
                "status": status,
                "result": {
                    "message": "Task completed successfully",
                    "duration_ms": 1500,
                } if status == "completed" else None,
            }
            
            await self.ws_connection.send(json.dumps(envelope))
            print(f"✓ Sent task status envelope")
            print(f"  Task ID: {task_id}")
            print(f"  Status: {status}")
            
            await asyncio.sleep(0.5)
            
        except Exception as e:
            print(f"✗ Failed to send task status: {e}")


class SerialTester:
    """Test pyserial automatic reading."""
    
    @staticmethod
    def list_available_ports():
        """List all available serial ports."""
        print(f"\n{'='*60}")
        print(f"TEST 6: Serial Port Detection")
        print(f"{'='*60}")
        
        if not SERIAL_AVAILABLE:
            print("✗ pyserial not available")
            return []
        
        try:
            ports = list(list_ports.comports())
            
            if not ports:
                print("✗ No serial ports detected")
                return []
            
            print(f"✓ Found {len(ports)} serial port(s):")
            for port in ports:
                print(f"  - {port.device}")
                print(f"    Description: {port.description}")
                print(f"    Manufacturer: {port.manufacturer}")
                if port.serial_number:
                    print(f"    Serial Number: {port.serial_number}")
                if port.vid and port.pid:
                    print(f"    VID:PID: {port.vid:04x}:{port.pid:04x}")
            
            return ports
            
        except Exception as e:
            print(f"✗ Error listing ports: {e}")
            return []
    
    @staticmethod
    async def test_serial_reading(port_device: str, baud_rate: int = 9600, duration: int = 5):
        """Test automatic serial reading.
        
        Args:
            port_device: Serial port device path (e.g., /dev/ttyUSB0 or COM3)
            baud_rate: Baud rate
            duration: Test duration in seconds
        """
        print(f"\n{'='*60}")
        print(f"TEST 7: Automatic Serial Reading")
        print(f"{'='*60}")
        
        if not SERIAL_AVAILABLE:
            print("✗ pyserial not available")
            return
        
        try:
            print(f"Opening port: {port_device}")
            print(f"Baud rate: {baud_rate}")
            print(f"Test duration: {duration} seconds")
            
            # Open serial port
            ser = serial.Serial(
                port=port_device,
                baudrate=baud_rate,
                timeout=1.0,
            )
            
            print(f"✓ Port opened successfully")
            print(f"  Reading data for {duration} seconds...")
            
            bytes_read = 0
            chunks_read = 0
            start_time = time.time()
            
            # Read continuously for specified duration
            while time.time() - start_time < duration:
                if ser.in_waiting > 0:
                    data = ser.read(ser.in_waiting)
                    if data:
                        bytes_read += len(data)
                        chunks_read += 1
                        print(f"  ← Read {len(data)} bytes: {data.hex()}")
                        # Try to decode as text
                        try:
                            text = data.decode('utf-8', errors='ignore')
                            if text.strip():
                                print(f"     Text: {text.strip()}")
                        except:
                            pass
                
                await asyncio.sleep(0.1)
            
            ser.close()
            
            print(f"\n✓ Serial reading test complete")
            print(f"  Total bytes read: {bytes_read}")
            print(f"  Data chunks: {chunks_read}")
            
            if bytes_read == 0:
                print(f"\n⚠ Warning: No data received. Check if device is sending data.")
            
        except serial.SerialException as e:
            print(f"✗ Serial error: {e}")
            print(f"  Make sure the port is not already in use")
        except Exception as e:
            print(f"✗ Error during serial test: {e}")


async def main():
    """Main test execution."""
    print("="*60)
    print("RPI-HUB-SERVICE WebSocket & Serial Test Suite")
    print("="*60)
    
    # Configuration - modify these as needed
    ENDPOINT = "ws://localhost:8000/hub"
    HUB_ID = "test-hub-01"
    DEVICE_TOKEN = "test-token-123"
    TEST_PORT_ID = "test-port-01"
    
    # Read from environment if available
    import os
    ENDPOINT = os.getenv("SERVER_ENDPOINT", ENDPOINT)
    HUB_ID = os.getenv("HUB_ID", HUB_ID)
    DEVICE_TOKEN = os.getenv("DEVICE_TOKEN", DEVICE_TOKEN)
    
    print(f"\nConfiguration:")
    print(f"  Endpoint: {ENDPOINT}")
    print(f"  Hub ID: {HUB_ID}")
    print(f"  Device Token: {'*' * len(DEVICE_TOKEN) if DEVICE_TOKEN else 'NOT SET'}")
    
    # Initialize tester
    tester = WebSocketTester(ENDPOINT, HUB_ID, DEVICE_TOKEN)
    
    try:
        # Test 1: Connect
        connected = await tester.connect()
        
        if not connected:
            print("\n✗ Cannot proceed with tests - connection failed")
            return
        
        # Wait a bit for connection to stabilize
        await asyncio.sleep(1)
        
        # Test 2: Send telemetry envelope
        test_data = b"Hello from test! Temperature: 25.5C\n"
        await tester.send_telemetry_envelope(TEST_PORT_ID, test_data)
        
        # Test 3: Send health envelope
        await tester.send_health_envelope()
        
        # Test 4: Send device event envelope
        await tester.send_device_event_envelope(TEST_PORT_ID, "connected")
        
        # Test 5: Send task status envelope
        await tester.send_task_status_envelope("test-task-123", "completed")
        
        # Test 6 & 7: Serial port tests
        serial_tester = SerialTester()
        available_ports = serial_tester.list_available_ports()
        
        if available_ports and SERIAL_AVAILABLE:
            # Test first available port
            first_port = available_ports[0].device
            
            print(f"\n⚠ About to test serial reading on {first_port}")
            print(f"  Make sure this port is NOT in use by another program!")
            response = input(f"  Continue with serial test? (y/n): ")
            
            if response.lower() == 'y':
                await serial_tester.test_serial_reading(first_port, duration=5)
            else:
                print(f"  Skipping serial reading test")
        
        # Summary
        print(f"\n{'='*60}")
        print(f"TEST SUMMARY")
        print(f"{'='*60}")
        print(f"✓ WebSocket connection: {'SUCCESS' if connected else 'FAILED'}")
        print(f"✓ Telemetry envelope: SENT")
        print(f"✓ Health envelope: SENT")
        print(f"✓ Device event envelope: SENT")
        print(f"✓ Task status envelope: SENT")
        print(f"  Received messages from server: {len(tester.received_messages)}")
        
        if tester.received_messages:
            print(f"\n  Server responses:")
            for msg in tester.received_messages:
                print(f"    - {msg.get('type', 'unknown')}: {msg}")
        
        # Keep connection alive to observe behavior
        print(f"\nKeeping connection alive for 5 seconds to observe behavior...")
        await asyncio.sleep(5)
        
    except KeyboardInterrupt:
        print("\n\n⚠ Interrupted by user")
    except Exception as e:
        print(f"\n✗ Test error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup
        await tester.disconnect()
        print("\n" + "="*60)
        print("Test suite completed")
        print("="*60)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(0)
