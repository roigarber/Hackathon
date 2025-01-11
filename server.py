import random
import threading
import struct
import time
from socket import *
from scapy.arch import get_if_addr


class SpeedTestServer:
    def __init__(self):
        """
        Initialize the server.
        Sets up UDP and TCP sockets, prepares the broadcast message, and initializes server settings.
        """
        # Networking setup
        self.udp_socket = socket(AF_INET, SOCK_DGRAM)
        self.tcp_socket = socket(AF_INET, SOCK_STREAM)

        # Socket options
        self.udp_socket.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
        self.udp_socket.setsockopt(SOL_SOCKET, SO_BROADCAST, 1)
        self.tcp_socket.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)

        # Server IP and ports
        self.UDP_IP = '255.255.255.255'  # Broadcast to all available networks
        self.UDP_PORT = 13117            # Well-known assignment port for broadcasts
        self.server_port = random.randint(1024, 65535)  # Random TCP port for connections

        # Broadcast message: magic cookie (0xabcddcba), message type (0x2), server TCP port
        magic_cookie = 0xabcddcba
        message_type = 0x2
        self.broadcast_message = struct.pack('>IBH', magic_cookie, message_type, self.server_port)

        # Server IP address (auto-detect interface IP)
        self.server_ip = gethostbyname(gethostname())

        # Flag to keep server running
        self.is_running = True

        print(f"[Server] Initialized on {self.server_ip}:{self.server_port}")

    def broadcast_offers(self):
        """
        Broadcast UDP offer messages periodically and start accepting client connections (once).
        """
        # Bind and listen on the chosen TCP port
        self.tcp_socket.bind(('', self.server_port))
        self.tcp_socket.listen(5)
        print(f"[Server] Listening on TCP port {self.server_port}...")

        # Spawn a single thread to handle clients
        threading.Thread(target=self.handle_clients, daemon=True).start()

        # Continuously send UDP broadcast offers
        while self.is_running:
            try:
                self.udp_socket.sendto(self.broadcast_message, (self.UDP_IP, self.UDP_PORT))
                print("[Server] Broadcasting offer message...")
                time.sleep(1)
            except Exception as e:
                print(f"[Server] Error broadcasting offers: {e}")
                break

    def handle_clients(self):
        """
        Accept and handle incoming TCP client connections in a loop.
        """
        print("[Server] Ready to accept TCP clients...")
        while self.is_running:
            try:
                client_socket, client_address = self.tcp_socket.accept()
                print(f"[Server] Client connected from {client_address}")
                threading.Thread(target=self.process_client, args=(client_socket, client_address), daemon=True).start()
            except Exception as e:
                print(f"[Server] Error accepting clients: {e}")
                break

    def process_client(self, client_socket, client_address):
        """
        Process client requests for speed testing. 
        1. Receives file size via TCP.
        2. Simulates TCP file transfer to the client.
        3. Simulates UDP file transfer to the client's ephemeral TCP port.
        """
        try:
            print(f"[Server] Processing client {client_address}...")
            request_data = client_socket.recv(1024).decode().strip()
            print(f"[Server] Request from {client_address}: {request_data}")

            # Expecting something like: "FileSize:2048"
            if request_data.startswith("FileSize:"):
                file_size = int(request_data.split(":")[1])
                print(f"[Server] Client requests file size: {file_size} bytes")

                # 1) Simulate TCP transfer
                self.simulate_tcp_transfer(client_socket, file_size)

                # 2) Simulate UDP transfer (send to same IP and same ephemeral TCP port)
                client_ip, client_port = client_address[0], client_address[1]
                self.simulate_udp_transfer((client_ip, client_port), file_size)

            client_socket.close()
        except Exception as e:
            print(f"[Server] Error processing client {client_address}: {e}")

    def simulate_tcp_transfer(self, client_socket, file_size):
        """
        Simulate sending a file of the requested size over TCP.
        """
        print(f"[Server] Starting TCP transfer of {file_size} bytes...")
        start_time = time.time()

        chunk_size = 1024
        data_chunk = b'X' * chunk_size  # Simulated data

        bytes_sent = 0
        while bytes_sent < file_size:
            remaining = file_size - bytes_sent
            client_socket.send(data_chunk[:min(chunk_size, remaining)])
            bytes_sent += min(chunk_size, remaining)

        end_time = time.time()
        duration = max(end_time - start_time, 1e-6)
        transfer_speed = file_size / duration

        print(f"[Server] TCP transfer complete: {bytes_sent} bytes in {duration:.2f} sec "
              f"({transfer_speed:.2f} bytes/s)")

    def simulate_udp_transfer(self, client_address, file_size):
        """
        Simulate sending a file of the requested size over UDP.
        Sends multiple segments to the client's ephemeral TCP port (same as client_address[1]).
        """
        print(f"[Server] Starting UDP transfer of {file_size} bytes to {client_address}...")
        chunk_size = 1024
        total_segments = (file_size + chunk_size - 1) // chunk_size  # round up
        data_chunk = b'U' * chunk_size  # Simulated data

        for segment_number in range(total_segments):
            # Prepare a payload packet:
            #   [magic_cookie (4 bytes), message_type (1 byte=0x4), total_segments (8 bytes), current_segment (8 bytes), data...]
            magic_cookie = 0xabcddcba
            message_type = 0x4
            packet_header = struct.pack('>IBQQ',
                                        magic_cookie,
                                        message_type,
                                        total_segments,
                                        segment_number)
            payload = data_chunk[:min(chunk_size, file_size - segment_number * chunk_size)]
            packet = packet_header + payload

            self.udp_socket.sendto(packet, client_address)

        print(f"[Server] UDP transfer to {client_address} completed.")

    def stop_server(self):
        """
        Gracefully stop the server and release resources.
        """
        self.is_running = False
        try:
            self.tcp_socket.close()
            self.udp_socket.close()
        except Exception as e:
            print(f"[Server] Error closing sockets: {e}")
        print("[Server] Stopped.")


if __name__ == "__main__":
    server = SpeedTestServer()
    try:
        # Start broadcasting offers in the main thread
        print("[Server] Starting broadcast_offers()...")
        server.broadcast_offers()
    except KeyboardInterrupt:
        print("[Server] KeyboardInterrupt received.")
    finally:
        server.stop_server()
