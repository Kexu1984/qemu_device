#!/usr/bin/env python3
"""
MMIO Device Server - External device emulation via TCP socket

This server implements the register semantics for the QEMU mmio-sockdev:
- 0x00 TXDATA (W): Print character (low 8 bits) to stdout
- 0x04 STATUS (R): bit0=TXREADY (always 1)
- 0x08 CTRL (R/W): bit0=ENABLE (default 1), persistent

Protocol:
- Read: 'R' + addr(4B LE) + size(1B) -> return data(sizeB LE)
- Write: 'W' + addr(4B LE) + size(1B) + data(sizeB LE) -> no response
"""

import socket
import struct
import sys
import argparse
import threading
import time

class MMIODeviceServer:
    def __init__(self, port=7890):
        self.port = port
        self.registers = bytearray(0x1000)  # 4KB register space
        
        # Initialize default register values
        self.registers[0x08] = 0x01  # CTRL: ENABLE=1
        
        self.server_socket = None
        self.running = False
        
    def handle_read(self, addr, size):
        """Handle read operation from registers"""
        if addr + size > len(self.registers):
            print(f"Warning: Read beyond register space: addr=0x{addr:x}, size={size}")
            return b'\x00' * size
            
        # Special handling for STATUS register (0x04)
        if addr == 0x04:
            # Return TXREADY=1 (bit 0)
            data = bytearray(size)
            data[0] = 0x01
            return bytes(data)
        
        # Return data from register space
        data = self.registers[addr:addr + size]
        return bytes(data)
    
    def handle_write(self, addr, size, data):
        """Handle write operation to registers"""
        if addr + size > len(self.registers):
            print(f"Warning: Write beyond register space: addr=0x{addr:x}, size={size}")
            return
            
        # Special handling for TXDATA register (0x00)
        if addr == 0x00 and size >= 1:
            char_val = data[0] & 0xFF
            if 32 <= char_val <= 126 or char_val == 10:  # Printable ASCII + newline
                print(chr(char_val), end='', flush=True)
            else:
                print(f"[0x{char_val:02x}]", end='', flush=True)
            return
        
        # For other registers, store the value
        for i in range(size):
            if addr + i < len(self.registers):
                self.registers[addr + i] = data[i]
    
    def handle_client(self, client_socket, addr):
        """Handle a client connection"""
        print(f"Client connected from {addr}")
        
        try:
            while self.running:
                # Read operation type
                op_data = client_socket.recv(1)
                if not op_data:
                    break
                    
                op = op_data[0]
                
                if op == ord('R'):  # Read operation
                    # Read addr (4 bytes LE) and size (1 byte)
                    header = client_socket.recv(5)
                    if len(header) != 5:
                        break
                        
                    addr = struct.unpack('<I', header[:4])[0]
                    size = header[4]
                    
                    # Get data and send response
                    data = self.handle_read(addr, size)
                    client_socket.send(data)
                    
                elif op == ord('W'):  # Write operation
                    # Read addr (4 bytes LE) and size (1 byte)
                    header = client_socket.recv(5)
                    if len(header) != 5:
                        break
                        
                    addr = struct.unpack('<I', header[:4])[0]
                    size = header[4]
                    
                    # Read data
                    data = client_socket.recv(size)
                    if len(data) != size:
                        break
                        
                    # Handle the write
                    self.handle_write(addr, size, data)
                    
                else:
                    print(f"Unknown operation: 0x{op:02x}")
                    break
                    
        except Exception as e:
            print(f"Error handling client {addr}: {e}")
        finally:
            client_socket.close()
            print(f"Client {addr} disconnected")
    
    def start_server(self):
        """Start the TCP server"""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        try:
            self.server_socket.bind(('127.0.0.1', self.port))
            self.server_socket.listen(1)
            self.running = True
            
            print(f"MMIO Device Server listening on port {self.port}")
            print("Register map:")
            print("  0x00 TXDATA (W): Print character")
            print("  0x04 STATUS (R): TXREADY=1")
            print("  0x08 CTRL (R/W): ENABLE bit")
            print("Waiting for QEMU connection...")
            
            while self.running:
                try:
                    client_socket, client_addr = self.server_socket.accept()
                    # Handle each client in a separate thread
                    client_thread = threading.Thread(
                        target=self.handle_client,
                        args=(client_socket, client_addr)
                    )
                    client_thread.daemon = True
                    client_thread.start()
                except socket.error:
                    if self.running:
                        print("Socket error occurred")
                    break
                    
        except Exception as e:
            print(f"Server error: {e}")
        finally:
            self.stop_server()
    
    def stop_server(self):
        """Stop the TCP server"""
        self.running = False
        if self.server_socket:
            self.server_socket.close()
            self.server_socket = None

def main():
    parser = argparse.ArgumentParser(description='MMIO Device Server for QEMU')
    parser.add_argument('--port', type=int, default=7890,
                        help='TCP port to listen on (default: 7890)')
    
    args = parser.parse_args()
    
    server = MMIODeviceServer(args.port)
    
    try:
        server.start_server()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server.stop_server()

if __name__ == '__main__':
    main()