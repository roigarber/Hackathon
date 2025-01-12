import random
import threading
import struct
import time
from socket import *
from scapy.arch import get_if_addr


class SpeedTestServer:
    def __init__(self):
        """
        Initialize the server:
         - Create UDP and TCP sockets
         - Prepare broadcast message
         - Pick a random TCP port
         - Detect IP address
        """
        # Networking setup
        self.udp_socket = socket(AF_INET, SOCK_DGRAM)
        self.tcp_socket = socket(AF_INET, SOCK_STREAM)

        # Socket options
        self.udp_socket.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
        self.udp_socket.setsockopt(SOL_SOCKET, SO_BROADCAST, 1)
        self.tcp_socket.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)

        # Server IP and ports
        self.UDP_IP = '255.255.255.255' 
        self.UDP_PORT = 13117
        self.server_port = random.randint(1024, 65535)

        # Broadcast message: magic cookie (4 bytes) + type (1 byte=0x2) + port (2 bytes)
        magic_cookie = 0xabcddcba
        message_type = 0x2
        self.broadcast_message = struct.pack('>IBH', magic_cookie, message_type, self.server_port)

        # Attempt to detect server IP automatically
        self.server_ip = gethostbyname(gethostname())

        # Control flag
        self.is_running = True
        print(f"[Server] Server started, listening on IP address {self.server_ip}")

    def broadcast_offers(self):
        """
        1) Bind and listen on TCP
        2) Spawn a thread to accept clients
        3) Broadcast UDP offers once per second
        """
        # Bind + Listen on random TCP port
        self.tcp_socket.bind(('', self.server_port))
        self.tcp_socket.listen(5)
        print(f"[Server] TCP listening on port {self.server_port}")

        # Single thread for handling clients
        threading.Thread(target=self.handle_clients, daemon=True).start()

        print("[Server] Starting to broadcast offer messages every second...")
        while self.is_running:
            try:
                self.udp_socket.sendto(self.broadcast_message, (self.UDP_IP, self.UDP_PORT))
                print("[Server] Sent offer broadcast via UDP")
                time.sleep(1)
            except Exception as e:
                print(f"[Server] Error broadcasting: {e}")
                break

    def handle_clients(self):
        """
        Continuously accept new client connections on TCP and process them.
        """
        print("[Server] Ready to accept client connections.")
        while self.is_running:
            try:
                client_socket, client_address = self.tcp_socket.accept()
                print(f"[Server] New client connected from {client_address}")
                threading.Thread(
                    target=self.process_client,
                    args=(client_socket, client_address),
                    daemon=True
                ).start()
            except Exception as e:
                print(f"[Server] Error accepting client: {e}")
                break

    def process_client(self, client_socket, client_address):
        """
        For each client:
         1) Receive the file size request over TCP
         2) Simulate the TCP transfer
         3) Simulate the UDP transfer to that client's ephemeral TCP port
        """
        print(f"[Server] Processing client {client_address}...")
        try:
            data = client_socket.recv(1024).decode().strip()
            print(f"[Server] Received from {client_address}: {data}")

            # Expect "FileSize:<number>"
            if data.startswith("FileSize:"):
                file_size = int(data.split(":")[1])
                print(f"[Server] -> Client wants a file of {file_size} bytes")

                # 1) TCP Transfer
                self.simulate_tcp_transfer(client_socket, file_size)

                # 2) UDP Transfer (to the same ephemeral TCP port)
                self.simulate_udp_transfer(client_address, file_size)
        except Exception as e:
            print(f"[Server] Error processing {client_address}: {e}")
        finally:
            client_socket.close()

    def simulate_tcp_transfer(self, client_socket, file_size):
        """
        Send 'file_size' bytes to the client via TCP in 1KB chunks.
        """
        print(f"[Server] Starting TCP transfer of {file_size} bytes...")
        start_time = time.time()

        chunk_size = 1024
        chunk_data = b'T' * chunk_size  # Mock data
        bytes_sent = 0

        while bytes_sent < file_size:
            remaining = file_size - bytes_sent
            to_send = chunk_data[:min(chunk_size, remaining)]
            client_socket.send(to_send)
            bytes_sent += len(to_send)

        elapsed = max(time.time() - start_time, 1e-6)
        speed_bps = file_size / elapsed

        print(f"[Server] TCP transfer complete: {bytes_sent} bytes in {elapsed:.3f} s "
              f"({speed_bps:.2f} bytes/s)")

    def simulate_udp_transfer(self, client_address, file_size):
        """
        Send 'file_size' bytes to the client via UDP, in 1KB segments.
        We'll add the standard assignment payload header:
          - magic cookie (4 bytes)
          - message_type=0x4 (1 byte)
          - total_segments (8 bytes)
          - current_segment (8 bytes)
          - data
        """
        print(f"[Server] Starting UDP transfer of {file_size} bytes to {client_address}...")
        start_time = time.time()

        chunk_size = 1024
        total_segments = (file_size + chunk_size - 1) // chunk_size
        data_chunk = b'U' * chunk_size

        for seg_num in range(total_segments):
            magic_cookie = 0xabcddcba
            message_type = 0x4
            header = struct.pack('>IBQQ',
                                 magic_cookie,
                                 message_type,
                                 total_segments,
                                 seg_num)

            payload_size = min(chunk_size, file_size - seg_num * chunk_size)
            payload = data_chunk[:payload_size]
            packet = header + payload

            self.udp_socket.sendto(packet, client_address)

        elapsed = max(time.time() - start_time, 1e-6)
        speed_bps = file_size / elapsed
        print(f"[Server] UDP transfer complete: {total_segments} segments in {elapsed:.3f} s "
              f"({speed_bps:.2f} bytes/s)")

    def stop_server(self):
        """
        Gracefully stop server operations.
        """
        self.is_running = False
        try:
            self.tcp_socket.close()
            self.udp_socket.close()
        except Exception as e:
            print(f"[Server] Error closing sockets: {e}")

        print("[Server] All transfers complete, listening for offer requests... (Server stopping)")


if __name__ == "__main__":
    server = SpeedTestServer()
    try:
        server.broadcast_offers()
    except KeyboardInterrupt:
        print("[Server] KeyboardInterrupt received.")
    finally:
        server.stop_server()
