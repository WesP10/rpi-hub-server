#!/usr/bin/env python3
"""
Simple serial port read test to diagnose what data is actually being received.

This script opens the serial port and displays raw bytes, hex, and ASCII.
"""

import sys
import time
from datetime import datetime

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    print("ERROR: pyserial not installed")
    print("Install with: pip install pyserial")
    sys.exit(1)


def list_available_ports():
    """List all available serial ports."""
    print("\n" + "="*60)
    print("Available Serial Ports")
    print("="*60)
    
    ports = list(list_ports.comports())
    
    if not ports:
        print("No serial ports found!")
        return None
    
    for i, port in enumerate(ports):
        print(f"\n{i+1}. {port.device}")
        print(f"   Description: {port.description}")
        print(f"   Manufacturer: {port.manufacturer}")
        if port.serial_number:
            print(f"   Serial Number: {port.serial_number}")
        if port.vid and port.pid:
            print(f"   VID:PID: {port.vid:04X}:{port.pid:04X}")
    
    print()
    return ports


def bytes_to_printable(data):
    """Convert bytes to printable ASCII, replacing non-printable with '.'"""
    return ''.join(chr(b) if 32 <= b < 127 else '.' for b in data)


def auto_detect_baud_rate(port_path):
    """
    Auto-detect baud rate by trying common rates with DTR reset.
    
    Args:
        port_path: Serial port path
        
    Returns:
        Detected baud rate or None
    """
    common_baud_rates = [9600, 115200, 57600, 38400, 19200, 4800, 2400, 1200]
    
    print("\n" + "="*60)
    print("Auto-detecting Baud Rate")
    print("="*60)
    print(f"Port: {port_path}")
    print(f"Testing rates: {common_baud_rates}")
    print("="*60 + "\n")
    
    for baud_rate in common_baud_rates:
        try:
            print(f"Trying {baud_rate} baud...", end='', flush=True)
            
            ser = serial.Serial(
                port=port_path,
                baudrate=baud_rate,
                bytesize=8,
                stopbits=1,
                parity='N',
                timeout=0.1,
                write_timeout=0.1,
            )
            
            # Wait briefly for connection to stabilize
            time.sleep(0.05)
            
            # Reset Arduino by toggling DTR (required for auto-start on RPi)
            ser.dtr = False
            time.sleep(0.1)
            ser.dtr = True
            time.sleep(0.3)  # Wait for Arduino to reset and start transmitting
            
            # Clear any existing data in buffer
            ser.reset_input_buffer()
            
            # Wait a moment for any auto-transmitted data
            time.sleep(0.1)
            
            # Check if there's data available (indicates active device)
            has_data = ser.in_waiting > 0
            
            if has_data:
                # Read a sample to verify it's not all nulls
                sample = ser.read(min(ser.in_waiting, 64))
                non_null_bytes = sum(1 for b in sample if b != 0)
                
                ser.close()
                
                if non_null_bytes > 0:
                    print(f" ✓ DETECTED! (found {len(sample)} bytes, {non_null_bytes} non-null)")
                    print(f"   Sample HEX: {sample[:32].hex()}")
                    print(f"   Sample ASCII: {bytes_to_printable(sample[:32])}")
                    return baud_rate
                else:
                    print(f" ✗ Data present but all null bytes")
            else:
                ser.close()
                print(f" ✗ No data")
                
        except serial.SerialException as e:
            print(f" ✗ Error: {e}")
        except Exception as e:
            print(f" ✗ Unexpected error: {e}")
    
    print("\n⚠️  Could not auto-detect baud rate")
    return None


def test_serial_read(port_path, baud_rate=115200, duration=10):
    """
    Read from serial port and display data in multiple formats.
    
    Args:
        port_path: Serial port path (e.g., /dev/ttyACM0 or COM3)
        baud_rate: Baud rate (default: 115200)
        duration: How long to read in seconds (default: 10)
    """
    print("\n" + "="*60)
    print("Serial Port Read Test")
    print("="*60)
    print(f"Port: {port_path}")
    print(f"Baud Rate: {baud_rate}")
    print(f"Duration: {duration} seconds")
    print(f"Press Ctrl+C to stop early")
    print("="*60 + "\n")
    
    try:
        # Open serial port
        ser = serial.Serial(
            port=port_path,
            baudrate=baud_rate,
            bytesize=8,
            stopbits=1,
            parity='N',
            timeout=1.0
        )
        
        print(f"✓ Opened {port_path} successfully")
        
        # Reset Arduino by toggling DTR (required for auto-start on RPi)
        print("Resetting Arduino...")
        ser.dtr = False
        time.sleep(0.1)  # Brief delay
        ser.dtr = True
        time.sleep(2)  # Wait for Arduino to reset and start sketch
        
        print(f"Waiting for data...\n")
        
        start_time = time.time()
        total_bytes = 0
        read_count = 0
        
        while (time.time() - start_time) < duration:
            try:
                # Read available data
                if ser.in_waiting > 0:
                    data = ser.read(ser.in_waiting)
                    if data:
                        read_count += 1
                        total_bytes += len(data)
                        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                        
                        print(f"\n[{timestamp}] Read #{read_count} - {len(data)} bytes")
                        print(f"  HEX:   {data.hex()}")
                        print(f"  ASCII: {bytes_to_printable(data)}")
                        print(f"  RAW:   {data}")
                        
                        # Check if all zeros
                        if all(b == 0 for b in data):
                            print(f"  ⚠️  WARNING: All bytes are 0x00 (null)")
                        
                else:
                    time.sleep(0.1)
                    
            except KeyboardInterrupt:
                print("\n\n⏹️  Stopped by user")
                break
        
        ser.close()
        
        # Summary
        print("\n" + "="*60)
        print("Summary")
        print("="*60)
        print(f"Duration: {time.time() - start_time:.1f} seconds")
        print(f"Total Reads: {read_count}")
        print(f"Total Bytes: {total_bytes}")
        if read_count > 0:
            print(f"Average per Read: {total_bytes / read_count:.1f} bytes")
        print()
        
    except serial.SerialException as e:
        print(f"\n❌ Serial Error: {e}")
        print("\nPossible issues:")
        print("  - Port is already in use by another process")
        print("  - Permission denied (try: sudo usermod -a -G dialout $USER)")
        print("  - Wrong baud rate")
    except Exception as e:
        print(f"\n❌ Unexpected Error: {e}")


def main():
    """Main function."""
    # List available ports
    ports = list_available_ports()
    
    if not ports:
        return
    
    # Get user selection
    print("Select a port to test (or press Enter for port 1): ", end='')
    try:
        selection = input().strip()
        if not selection:
            selection = "1"
        port_index = int(selection) - 1
        
        if port_index < 0 or port_index >= len(ports):
            print(f"Invalid selection. Must be 1-{len(ports)}")
            return
        
        selected_port = ports[port_index].device
    except (ValueError, KeyboardInterrupt):
        print("\nCancelled")
        return
    
    # Get baud rate
    print("\nBaud rate options:")
    print("  1. 9600")
    print("  2. 115200")
    print("  3. 57600")
    print("  4. 38400")
    print("  5. Auto-detect (recommended)")
    print("  6. Custom")
    print("\nSelect baud rate (or press Enter for auto-detect): ", end='')
    
    baud_rate = None
    try:
        baud_choice = input().strip()
        if not baud_choice or baud_choice == "5":
            baud_rate = auto_detect_baud_rate(selected_port)
            if not baud_rate:
                print("Auto-detect failed. Enter baud rate manually: ", end='')
                baud_rate = int(input().strip())
        elif baud_choice == "1":
            baud_rate = 9600
        elif baud_choice == "2":
            baud_rate = 115200
        elif baud_choice == "3":
            baud_rate = 57600
        elif baud_choice == "4":
            baud_rate = 38400
        elif baud_choice == "6":
            print("Enter custom baud rate: ", end='')
            baud_rate = int(input().strip())
        else:
            print("Invalid choice, using auto-detect")
            baud_rate = auto_detect_baud_rate(selected_port)
            if not baud_rate:
                print("Auto-detect failed, using 115200")
                baud_rate = 115200
    except (ValueError, KeyboardInterrupt):
        print("\nUsing auto-detect")
        baud_rate = auto_detect_baud_rate(selected_port)
        if not baud_rate:
            print("Auto-detect failed, using 115200")
            baud_rate = 115200
    
    # Get duration
    print("\nHow long to read (seconds, default 10): ", end='')
    try:
        duration_str = input().strip()
        duration = int(duration_str) if duration_str else 10
    except (ValueError, KeyboardInterrupt):
        print("\nUsing default: 10 seconds")
        duration = 10
    
    # Run the test
    test_serial_read(selected_port, baud_rate, duration)


if __name__ == "__main__":
    main()
