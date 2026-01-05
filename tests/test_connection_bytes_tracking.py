"""
Test bytes_read and bytes_written tracking in Connection class.
This test verifies the fix for the AttributeError in health_reporter.
"""

import pytest
from unittest.mock import MagicMock, patch

from src.serial_manager import Connection, ConnectionStatus
from src.health_reporter import HealthReporter


class TestConnectionBytesTracking:
    """Test that Connection properly tracks bytes_read and bytes_written."""
    
    def test_connection_has_bytes_attributes(self):
        """Test that Connection dataclass has bytes_read and bytes_written attributes."""
        conn = Connection(
            hub_id="test-hub",
            session_id="test-session",
            port_id="port-abc",
            device_path="/dev/ttyUSB0",
            baud_rate=9600
        )
        
        # Verify attributes exist and are initialized to 0
        assert hasattr(conn, 'bytes_read')
        assert hasattr(conn, 'bytes_written')
        assert conn.bytes_read == 0
        assert conn.bytes_written == 0
    
    def test_connection_bytes_can_be_incremented(self):
        """Test that bytes_read and bytes_written can be incremented."""
        conn = Connection(
            hub_id="test-hub",
            session_id="test-session",
            port_id="port-abc",
            device_path="/dev/ttyUSB0",
            baud_rate=9600
        )
        
        # Increment bytes
        conn.bytes_read += 100
        conn.bytes_written += 50
        
        assert conn.bytes_read == 100
        assert conn.bytes_written == 50
        
        # Increment again
        conn.bytes_read += 200
        conn.bytes_written += 75
        
        assert conn.bytes_read == 300
        assert conn.bytes_written == 125


class TestHealthReporterDictIteration:
    """Test that health_reporter correctly iterates over connection dict."""
    
    @pytest.mark.asyncio
    async def test_collect_service_metrics_with_dict_connections(self):
        """Test that service metrics collection works with dict of connections."""
        health_reporter = HealthReporter()
        
        # Mock serial manager that returns a dict (like the real implementation)
        with patch('src.serial_manager.get_serial_manager') as mock_get_sm:
            mock_sm = MagicMock()
            
            # Create real Connection objects
            conn1 = Connection(
                hub_id="test-hub",
                session_id="session-1",
                port_id="port-abc",
                device_path="/dev/ttyUSB0",
                baud_rate=9600,
                status=ConnectionStatus.CONNECTED
            )
            conn1.bytes_read = 1024
            conn1.bytes_written = 512
            
            conn2 = Connection(
                hub_id="test-hub",
                session_id="session-2",
                port_id="port-xyz",
                device_path="/dev/ttyUSB1",
                baud_rate=115200,
                status=ConnectionStatus.CONNECTED
            )
            conn2.bytes_read = 2048
            conn2.bytes_written = 1024
            
            # Return a dict (matching real implementation)
            mock_sm.get_active_connections.return_value = {
                "port-abc": conn1,
                "port-xyz": conn2
            }
            mock_get_sm.return_value = mock_sm
            
            # Mock other components
            with patch('src.usb_port_mapper.get_usb_port_mapper', side_effect=RuntimeError), \
                 patch('src.command_handler.get_command_handler', side_effect=RuntimeError), \
                 patch('src.buffer_manager.get_buffer_manager', side_effect=RuntimeError):
                
                # Collect metrics
                metrics = await health_reporter._collect_service_metrics()
                
                # Verify the metrics were collected successfully
                assert "serial" in metrics
                assert metrics["serial"]["active_connections"] == 2
                assert len(metrics["serial"]["ports"]) == 2
                
                # Find each port in the list
                ports_by_id = {p["port_id"]: p for p in metrics["serial"]["ports"]}
                
                # Verify port-abc
                assert "port-abc" in ports_by_id
                assert ports_by_id["port-abc"]["baud_rate"] == 9600
                assert ports_by_id["port-abc"]["bytes_read"] == 1024
                assert ports_by_id["port-abc"]["bytes_written"] == 512
                
                # Verify port-xyz
                assert "port-xyz" in ports_by_id
                assert ports_by_id["port-xyz"]["baud_rate"] == 115200
                assert ports_by_id["port-xyz"]["bytes_read"] == 2048
                assert ports_by_id["port-xyz"]["bytes_written"] == 1024
    
    @pytest.mark.asyncio
    async def test_collect_service_metrics_empty_connections(self):
        """Test that service metrics collection works with no connections."""
        health_reporter = HealthReporter()
        
        with patch('src.serial_manager.get_serial_manager') as mock_get_sm:
            mock_sm = MagicMock()
            # Return empty dict
            mock_sm.get_active_connections.return_value = {}
            mock_get_sm.return_value = mock_sm
            
            # Mock other components
            with patch('src.usb_port_mapper.get_usb_port_mapper', side_effect=RuntimeError), \
                 patch('src.command_handler.get_command_handler', side_effect=RuntimeError), \
                 patch('src.buffer_manager.get_buffer_manager', side_effect=RuntimeError):
                
                metrics = await health_reporter._collect_service_metrics()
                
                assert metrics["serial"]["active_connections"] == 0
                assert len(metrics["serial"]["ports"]) == 0
