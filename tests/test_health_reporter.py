"""
Tests for HealthReporter.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from src.health_reporter import (
    HealthReporter,
    initialize_health_reporter,
    get_health_reporter
)


@pytest.fixture
def mock_health_callback():
    """Create mock health callback."""
    return MagicMock()


@pytest.fixture
def health_reporter(mock_health_callback):
    """Create HealthReporter instance."""
    return HealthReporter(
        report_interval=1,  # Short interval for testing
        health_callback=mock_health_callback
    )


@pytest.fixture
async def started_reporter(health_reporter):
    """Create and start HealthReporter."""
    await health_reporter.start()
    yield health_reporter
    await health_reporter.stop()


class TestHealthReporterInitialization:
    """Test health reporter initialization."""
    
    def test_initialization(self, mock_health_callback):
        """Test reporter initializes with correct settings."""
        reporter = HealthReporter(
            report_interval=30,
            health_callback=mock_health_callback
        )
        
        assert reporter.report_interval == 30
        assert reporter.health_callback == mock_health_callback
        assert not reporter._running
        assert reporter._start_time > 0
    
    def test_initialization_defaults(self):
        """Test reporter initializes with defaults."""
        reporter = HealthReporter()
        
        assert reporter.report_interval == 30
        assert reporter.health_callback is None
    
    @pytest.mark.asyncio
    async def test_start_creates_task(self, health_reporter):
        """Test start() creates reporter task."""
        await health_reporter.start()
        
        assert health_reporter._running
        assert health_reporter._reporter_task is not None
        assert not health_reporter._reporter_task.done()
        
        await health_reporter.stop()
    
    @pytest.mark.asyncio
    async def test_start_idempotent(self, started_reporter):
        """Test start() can be called multiple times safely."""
        initial_task = started_reporter._reporter_task
        
        await started_reporter.start()
        
        assert started_reporter._reporter_task is initial_task
    
    @pytest.mark.asyncio
    async def test_stop_cancels_task(self, started_reporter):
        """Test stop() cancels reporter task."""
        task = started_reporter._reporter_task
        
        await started_reporter.stop()
        
        assert not started_reporter._running
        assert started_reporter._reporter_task is None
        assert task.done()


class TestSystemMetrics:
    """Test system metrics collection."""
    
    @pytest.mark.asyncio
    async def test_collect_system_metrics(self, health_reporter):
        """Test system metrics collection."""
        with patch('src.health_reporter.psutil') as mock_psutil:
            # Mock CPU
            mock_psutil.cpu_percent.return_value = 45.5
            mock_psutil.cpu_count.return_value = 4
            
            # Mock Memory
            mock_memory = MagicMock()
            mock_memory.total = 8 * 1024 * 1024 * 1024  # 8GB
            mock_memory.available = 4 * 1024 * 1024 * 1024  # 4GB
            mock_memory.used = 4 * 1024 * 1024 * 1024  # 4GB
            mock_memory.percent = 50.0
            mock_psutil.virtual_memory.return_value = mock_memory
            
            # Mock Disk
            mock_disk = MagicMock()
            mock_disk.total = 128 * 1024 ** 3  # 128GB
            mock_disk.used = 64 * 1024 ** 3  # 64GB
            mock_disk.free = 64 * 1024 ** 3  # 64GB
            mock_disk.percent = 50.0
            mock_psutil.disk_usage.return_value = mock_disk
            
            # Mock temperature (not available)
            mock_psutil.sensors_temperatures.side_effect = AttributeError
            
            metrics = await health_reporter._collect_system_metrics()
            
            assert metrics["cpu"]["percent"] == 45.5
            assert metrics["cpu"]["count"] == 4
            assert metrics["memory"]["percent"] == 50.0
            assert metrics["disk"]["percent"] == 50.0
            assert "temperature" not in metrics
    
    @pytest.mark.asyncio
    async def test_collect_system_metrics_with_temperature(self, health_reporter):
        """Test system metrics with temperature sensor."""
        with patch('src.health_reporter.psutil') as mock_psutil:
            mock_psutil.cpu_percent.return_value = 50.0
            mock_psutil.cpu_count.return_value = 4
            
            mock_memory = MagicMock()
            mock_memory.total = 8 * 1024 ** 3
            mock_memory.available = 4 * 1024 ** 3
            mock_memory.used = 4 * 1024 ** 3
            mock_memory.percent = 50.0
            mock_psutil.virtual_memory.return_value = mock_memory
            
            mock_disk = MagicMock()
            mock_disk.total = 128 * 1024 ** 3
            mock_disk.used = 64 * 1024 ** 3
            mock_disk.free = 64 * 1024 ** 3
            mock_disk.percent = 50.0
            mock_psutil.disk_usage.return_value = mock_disk
            
            # Mock temperature sensor
            mock_temp = MagicMock()
            mock_temp.current = 65.0
            mock_psutil.sensors_temperatures.return_value = {
                'cpu_thermal': [mock_temp]
            }
            
            metrics = await health_reporter._collect_system_metrics()
            
            assert metrics["temperature"]["cpu_celsius"] == 65.0
    
    @pytest.mark.asyncio
    async def test_collect_system_metrics_error_handling(self, health_reporter):
        """Test system metrics handles errors gracefully."""
        with patch('src.health_reporter.psutil') as mock_psutil:
            mock_psutil.cpu_percent.side_effect = Exception("CPU error")
            
            metrics = await health_reporter._collect_system_metrics()
            
            assert metrics == {}


class TestServiceMetrics:
    """Test service metrics collection."""
    
    @pytest.mark.asyncio
    async def test_collect_service_metrics(self, health_reporter):
        """Test service metrics collection."""
        with patch('src.health_reporter.get_serial_manager') as mock_get_sm, \
             patch('src.health_reporter.get_usb_port_mapper') as mock_get_mapper, \
             patch('src.health_reporter.get_command_handler') as mock_get_ch, \
             patch('src.health_reporter.get_buffer_manager') as mock_get_bm:
            
            # Mock Serial Manager
            mock_sm = MagicMock()
            mock_conn = MagicMock()
            mock_conn.port_id = "port-abc"
            mock_conn.status = "connected"
            mock_conn.baud_rate = 9600
            mock_conn.bytes_read = 1024
            mock_conn.bytes_written = 512
            mock_sm.get_active_connections.return_value = [mock_conn]
            mock_get_sm.return_value = mock_sm
            
            # Mock USB Port Mapper
            mock_mapper = MagicMock()
            mock_mapper.get_all_devices.return_value = [
                {"port_id": "port-abc", "port": "/dev/ttyUSB0"}
            ]
            mock_get_mapper.return_value = mock_mapper
            
            # Mock Command Handler
            mock_ch = MagicMock()
            mock_ch.get_queue_size.return_value = 3
            mock_ch.get_running_task_count.return_value = 2
            mock_ch.get_all_tasks.return_value = [
                {"task_id": "task-1"},
                {"task_id": "task-2"}
            ]
            mock_get_ch.return_value = mock_ch
            
            # Mock Buffer Manager
            mock_bm = MagicMock()
            mock_bm.get_stats.return_value = {
                "utilization_percent": 25.5,
                "message_count": 100
            }
            mock_get_bm.return_value = mock_bm
            
            metrics = await health_reporter._collect_service_metrics()
            
            assert metrics["serial"]["active_connections"] == 1
            assert metrics["serial"]["ports"][0]["port_id"] == "port-abc"
            assert metrics["usb"]["detected_devices"] == 1
            assert metrics["tasks"]["queue_size"] == 3
            assert metrics["tasks"]["running_count"] == 2
            assert metrics["buffer"]["utilization_percent"] == 25.5
    
    @pytest.mark.asyncio
    async def test_collect_service_metrics_not_initialized(self, health_reporter):
        """Test service metrics when components not initialized."""
        with patch('src.health_reporter.get_serial_manager') as mock_get_sm, \
             patch('src.health_reporter.get_usb_port_mapper') as mock_get_mapper, \
             patch('src.health_reporter.get_command_handler') as mock_get_ch, \
             patch('src.health_reporter.get_buffer_manager') as mock_get_bm:
            
            # All raise RuntimeError
            mock_get_sm.side_effect = RuntimeError("Not initialized")
            mock_get_mapper.side_effect = RuntimeError("Not initialized")
            mock_get_ch.side_effect = RuntimeError("Not initialized")
            mock_get_bm.side_effect = RuntimeError("Not initialized")
            
            metrics = await health_reporter._collect_service_metrics()
            
            assert metrics["serial"]["active_connections"] == 0
            assert metrics["usb"]["detected_devices"] == 0
            assert metrics["tasks"]["queue_size"] == 0
            assert metrics["buffer"]["utilization_percent"] == 0


class TestHealthMetricsCollection:
    """Test complete health metrics collection."""
    
    @pytest.mark.asyncio
    async def test_collect_health_metrics(self, health_reporter):
        """Test complete health metrics collection."""
        with patch('src.health_reporter.psutil') as mock_psutil, \
             patch('src.health_reporter.get_serial_manager') as mock_get_sm:
            
            # Mock psutil
            mock_psutil.cpu_percent.return_value = 50.0
            mock_psutil.cpu_count.return_value = 4
            
            mock_memory = MagicMock()
            mock_memory.total = 8 * 1024 ** 3
            mock_memory.available = 4 * 1024 ** 3
            mock_memory.used = 4 * 1024 ** 3
            mock_memory.percent = 50.0
            mock_psutil.virtual_memory.return_value = mock_memory
            
            mock_disk = MagicMock()
            mock_disk.total = 128 * 1024 ** 3
            mock_disk.used = 64 * 1024 ** 3
            mock_disk.free = 64 * 1024 ** 3
            mock_disk.percent = 50.0
            mock_psutil.disk_usage.return_value = mock_disk
            
            mock_psutil.sensors_temperatures.side_effect = AttributeError
            
            # Mock serial manager
            mock_sm = MagicMock()
            mock_sm.get_active_connections.return_value = []
            mock_get_sm.return_value = mock_sm
            
            # Mock other components to raise RuntimeError
            with patch('src.health_reporter.get_usb_port_mapper', side_effect=RuntimeError), \
                 patch('src.health_reporter.get_command_handler', side_effect=RuntimeError), \
                 patch('src.health_reporter.get_buffer_manager', side_effect=RuntimeError):
                
                metrics = await health_reporter.collect_health_metrics()
                
                assert "timestamp" in metrics
                assert "uptime_seconds" in metrics
                assert metrics["system"]["cpu"]["percent"] == 50.0
                assert metrics["service"]["serial"]["active_connections"] == 0
                assert metrics["errors"]["total_errors"] == 0


class TestErrorTracking:
    """Test error tracking functionality."""
    
    def test_record_port_error_general(self, health_reporter):
        """Test recording general port error."""
        health_reporter.record_port_error("port-abc")
        
        assert health_reporter.get_error_count("port-abc") == 1
        assert health_reporter.get_error_count() == 1
    
    def test_record_port_error_read(self, health_reporter):
        """Test recording read error."""
        health_reporter.record_port_error("port-abc", error_type="read")
        
        errors = health_reporter._collect_error_metrics()
        assert errors["port_read_errors"]["port-abc"] == 1
        assert errors["port_errors"]["port-abc"] == 1
    
    def test_record_port_error_write(self, health_reporter):
        """Test recording write error."""
        health_reporter.record_port_error("port-abc", error_type="write")
        
        errors = health_reporter._collect_error_metrics()
        assert errors["port_write_errors"]["port-abc"] == 1
        assert errors["port_errors"]["port-abc"] == 1
    
    def test_record_multiple_errors(self, health_reporter):
        """Test recording multiple errors for same port."""
        health_reporter.record_port_error("port-abc")
        health_reporter.record_port_error("port-abc", error_type="read")
        health_reporter.record_port_error("port-abc", error_type="write")
        
        assert health_reporter.get_error_count("port-abc") == 3
        assert health_reporter.get_error_count() == 3
    
    def test_record_errors_multiple_ports(self, health_reporter):
        """Test recording errors for multiple ports."""
        health_reporter.record_port_error("port-abc")
        health_reporter.record_port_error("port-xyz")
        
        assert health_reporter.get_error_count("port-abc") == 1
        assert health_reporter.get_error_count("port-xyz") == 1
        assert health_reporter.get_error_count() == 2
    
    def test_reset_port_errors_single(self, health_reporter):
        """Test resetting errors for single port."""
        health_reporter.record_port_error("port-abc")
        health_reporter.record_port_error("port-xyz")
        
        health_reporter.reset_port_errors("port-abc")
        
        assert health_reporter.get_error_count("port-abc") == 0
        assert health_reporter.get_error_count("port-xyz") == 1
    
    def test_reset_port_errors_all(self, health_reporter):
        """Test resetting all port errors."""
        health_reporter.record_port_error("port-abc")
        health_reporter.record_port_error("port-xyz")
        
        health_reporter.reset_port_errors()
        
        assert health_reporter.get_error_count() == 0
    
    def test_collect_error_metrics(self, health_reporter):
        """Test error metrics collection."""
        health_reporter.record_port_error("port-abc")
        health_reporter.record_port_error("port-abc", error_type="read")
        health_reporter.record_port_error("port-xyz", error_type="write")
        
        metrics = health_reporter._collect_error_metrics()
        
        assert metrics["total_errors"] == 3
        assert metrics["port_errors"]["port-abc"] == 2
        assert metrics["port_read_errors"]["port-abc"] == 1
        assert metrics["port_write_errors"]["port-xyz"] == 1


class TestPeriodicReporting:
    """Test periodic health reporting."""
    
    @pytest.mark.asyncio
    async def test_report_loop_calls_callback(self, mock_health_callback):
        """Test report loop calls callback periodically."""
        with patch('src.health_reporter.psutil') as mock_psutil:
            # Mock psutil basics
            mock_psutil.cpu_percent.return_value = 50.0
            mock_psutil.cpu_count.return_value = 4
            mock_psutil.virtual_memory.return_value = MagicMock(
                total=8*1024**3, available=4*1024**3, used=4*1024**3, percent=50.0
            )
            mock_psutil.disk_usage.return_value = MagicMock(
                total=128*1024**3, used=64*1024**3, free=64*1024**3, percent=50.0
            )
            mock_psutil.sensors_temperatures.side_effect = AttributeError
            
            with patch('src.health_reporter.get_serial_manager', side_effect=RuntimeError), \
                 patch('src.health_reporter.get_usb_port_mapper', side_effect=RuntimeError), \
                 patch('src.health_reporter.get_command_handler', side_effect=RuntimeError), \
                 patch('src.health_reporter.get_buffer_manager', side_effect=RuntimeError):
                
                reporter = HealthReporter(
                    report_interval=0.1,  # Very short interval
                    health_callback=mock_health_callback
                )
                
                await reporter.start()
                
                # Wait for multiple reports
                await asyncio.sleep(0.3)
                
                await reporter.stop()
                
                # Should have called callback at least 2 times
                assert mock_health_callback.call_count >= 2
                
                # Verify callback received health data
                call_args = mock_health_callback.call_args[0][0]
                assert "timestamp" in call_args
                assert "uptime_seconds" in call_args
                assert "system" in call_args
    
    @pytest.mark.asyncio
    async def test_report_loop_async_callback(self):
        """Test report loop with async callback."""
        async_callback = AsyncMock()
        
        with patch('src.health_reporter.psutil') as mock_psutil:
            mock_psutil.cpu_percent.return_value = 50.0
            mock_psutil.cpu_count.return_value = 4
            mock_psutil.virtual_memory.return_value = MagicMock(
                total=8*1024**3, available=4*1024**3, used=4*1024**3, percent=50.0
            )
            mock_psutil.disk_usage.return_value = MagicMock(
                total=128*1024**3, used=64*1024**3, free=64*1024**3, percent=50.0
            )
            mock_psutil.sensors_temperatures.side_effect = AttributeError
            
            with patch('src.health_reporter.get_serial_manager', side_effect=RuntimeError), \
                 patch('src.health_reporter.get_usb_port_mapper', side_effect=RuntimeError), \
                 patch('src.health_reporter.get_command_handler', side_effect=RuntimeError), \
                 patch('src.health_reporter.get_buffer_manager', side_effect=RuntimeError):
                
                reporter = HealthReporter(
                    report_interval=0.1,
                    health_callback=async_callback
                )
                
                await reporter.start()
                await asyncio.sleep(0.2)
                await reporter.stop()
                
                assert async_callback.call_count >= 1
    
    @pytest.mark.asyncio
    async def test_report_loop_no_callback(self):
        """Test report loop works without callback."""
        with patch('src.health_reporter.psutil') as mock_psutil:
            mock_psutil.cpu_percent.return_value = 50.0
            mock_psutil.cpu_count.return_value = 4
            mock_psutil.virtual_memory.return_value = MagicMock(
                total=8*1024**3, available=4*1024**3, used=4*1024**3, percent=50.0
            )
            mock_psutil.disk_usage.return_value = MagicMock(
                total=128*1024**3, used=64*1024**3, free=64*1024**3, percent=50.0
            )
            mock_psutil.sensors_temperatures.side_effect = AttributeError
            
            with patch('src.health_reporter.get_serial_manager', side_effect=RuntimeError), \
                 patch('src.health_reporter.get_usb_port_mapper', side_effect=RuntimeError), \
                 patch('src.health_reporter.get_command_handler', side_effect=RuntimeError), \
                 patch('src.health_reporter.get_buffer_manager', side_effect=RuntimeError):
                
                reporter = HealthReporter(
                    report_interval=0.1,
                    health_callback=None
                )
                
                # Should not raise error
                await reporter.start()
                await asyncio.sleep(0.2)
                await reporter.stop()


class TestUtilityMethods:
    """Test utility methods."""
    
    def test_get_uptime_seconds(self, health_reporter):
        """Test uptime calculation."""
        import time
        time.sleep(0.1)
        
        uptime = health_reporter.get_uptime_seconds()
        assert uptime >= 0
    
    def test_get_error_count_specific_port(self, health_reporter):
        """Test getting error count for specific port."""
        health_reporter.record_port_error("port-abc")
        health_reporter.record_port_error("port-xyz")
        
        assert health_reporter.get_error_count("port-abc") == 1
        assert health_reporter.get_error_count("port-xyz") == 1
    
    def test_get_error_count_total(self, health_reporter):
        """Test getting total error count."""
        health_reporter.record_port_error("port-abc")
        health_reporter.record_port_error("port-xyz")
        
        assert health_reporter.get_error_count() == 2


class TestGlobalInstance:
    """Test global health reporter singleton."""
    
    def test_initialize_health_reporter(self):
        """Test initialize_health_reporter() creates instance."""
        mock_callback = MagicMock()
        
        reporter = initialize_health_reporter(
            report_interval=60,
            health_callback=mock_callback
        )
        
        assert reporter is not None
        assert reporter.report_interval == 60
        assert reporter.health_callback == mock_callback
    
    def test_get_health_reporter(self):
        """Test get_health_reporter() returns initialized instance."""
        mock_callback = MagicMock()
        
        reporter1 = initialize_health_reporter(health_callback=mock_callback)
        reporter2 = get_health_reporter()
        
        assert reporter1 is reporter2
    
    def test_initialize_health_reporter_idempotent(self):
        """Test initialize_health_reporter() doesn't recreate instance."""
        reporter1 = initialize_health_reporter(report_interval=30)
        reporter2 = initialize_health_reporter(report_interval=60)
        
        # Should return existing instance
        assert reporter1 is reporter2
        assert reporter1.report_interval == 30
