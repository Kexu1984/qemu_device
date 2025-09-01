#!/usr/bin/env python3
"""
Test script for the MMIO device server
Tests the binary protocol implementation without requiring QEMU
"""

import socket
import struct
import time
import threading
import sys
import os

# Add tools directory to path to import server
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
from mmio_device_server import MMIODeviceServer

def test_protocol():
    """Test the binary protocol with the device server"""
    print("Testing MMIO device server protocol...")
    
    # Start server in background
    server = MMIODeviceServer(port=7891)
    server_thread = threading.Thread(target=server.start_server)
    server_thread.daemon = True
    server_thread.start()
    
    # Wait for server to start
    time.sleep(1)
    
    try:
        # Connect to server
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(('127.0.0.1', 7891))
        
        print("Connected to server")
        
        # Test 1: Read STATUS register (0x04)
        print("Test 1: Reading STATUS register...")
        req = b'R' + struct.pack('<I', 0x04) + struct.pack('<B', 4)
        sock.send(req)
        response = sock.recv(4)
        status = struct.unpack('<I', response)[0]
        print(f"STATUS = 0x{status:08x} (expected: 0x00000001)")
        assert status == 1, f"Expected STATUS=1, got {status}"
        
        # Test 2: Write and read CTRL register (0x08)
        print("Test 2: Writing/reading CTRL register...")
        req = b'W' + struct.pack('<I', 0x08) + struct.pack('<B', 4) + struct.pack('<I', 0x5)
        sock.send(req)
        
        req = b'R' + struct.pack('<I', 0x08) + struct.pack('<B', 4)
        sock.send(req)
        response = sock.recv(4)
        ctrl = struct.unpack('<I', response)[0]
        print(f"CTRL = 0x{ctrl:08x} (expected: 0x00000005)")
        assert ctrl == 5, f"Expected CTRL=5, got {ctrl}"
        
        # Test 3: Write to TXDATA register (should print character)
        print("Test 3: Writing to TXDATA register...")
        print("Expected output: 'A'")
        req = b'W' + struct.pack('<I', 0x00) + struct.pack('<B', 1) + b'A'
        sock.send(req)
        time.sleep(0.1)  # Give time for output
        
        # Test 4: Write test string
        print("Test 4: Writing test string...")
        print("Expected output: 'Hello!'")
        test_string = "Hello!"
        for char in test_string:
            req = b'W' + struct.pack('<I', 0x00) + struct.pack('<B', 1) + char.encode()
            sock.send(req)
            time.sleep(0.01)  # Small delay between characters
        
        print("\nAll protocol tests passed!")
        
    except Exception as e:
        print(f"Test failed: {e}")
        return False
    finally:
        sock.close()
        server.stop_server()
    
    return True

if __name__ == '__main__':
    if test_protocol():
        print("✓ Protocol test successful")
        sys.exit(0)
    else:
        print("✗ Protocol test failed")
        sys.exit(1)