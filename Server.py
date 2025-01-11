import random
import threading
import struct
import time
from socket import *
from scapy.arch import get_if_addr
# from scapy.arch import conf

# from scapy.arch import get_windows_if_list
# interfaces = get_windows_if_list()
# print("Available interfaces:")
# for iface in interfaces:
#     print(iface["name"])


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
        self.UDP_PORT = 13117
        self.server_port = random.randint(1024, 65535)  # Random TCP port for connections

        # Broadcast message
        magic_cookie = 0xabcddcba  # Magic cookie for client validation
        message_type = 0x2         # Message type for "offer"
        self.broadcast_message = struct.pack('>IBH', magic_cookie, message_type, self.server_port)

        # Server IP address (e.g., eth0 for primary interface)
        #self.server_ip = get_if_addr("Ethernet")
        #self.server_ip = conf.iface.ip
        self.server_ip = gethostbyname(gethostname())

        # Lock for managing concurrent access
        self.lock = threading.Lock()

        # Clients and transfer stats
        self.clients = []
        self.is_running = True
        print(f"Server initialized on {self.server_ip}:{self.server_port}")

    def broadcast_offers(self):
        """
        Broadcast UDP offer messages periodically and start accepting client connections.
        """
        self.tcp_socket.bind(('', self.server_port))
        self.tcp_socket.listen(5)  # Allow up to 5 pending connections
        print(f"Server started, broadcasting on {self.server_ip}:{self.UDP_PORT}")

        while self.is_running:
            # Send broadcast message
            self.udp_socket.sendto(self.broadcast_message, (self.UDP_IP, self.UDP_PORT))
            print(f"Broadcasting offer message...")
            threading.Thread(target=self.handle_clients).start()  # Handle incoming connections
            time.sleep(1)  # Broadcast every second

    def handle_clients(self):
        """
        Accept and handle incoming TCP client connections.
        """
        try:
            while self.is_running:
                client_socket, client_address = self.tcp_socket.accept()
                print(f"Client connected from {client_address}")
                threading.Thread(target=self.process_client, args=(client_socket, client_address)).start()
        except Exception as e:
            print(f"Error handling clients: {e}")

    def process_client(self, client_socket, client_address):
        """
        Process client requests for speed testing. Handles file size request and data transfer.
        """
        try:
            print(f"Processing client {client_address}")

            # Step 1: Receive file size from client
            request_data = client_socket.recv(1024).decode()
            print(f"Request from client {client_address}: {request_data}")

            # Parse file size (e.g., client sends "FileSize:1024")
            if request_data.startswith("FileSize:"):
                file_size = int(request_data.split(":")[1])  # Extract file size
                print(f"Client requested file size: {file_size} bytes")

                # Step 2: Simulate TCP file transfer
                self.simulate_tcp_transfer(client_socket, file_size)

                # Step 3: Simulate UDP file transfer
                self.simulate_udp_transfer(client_address, file_size)

            client_socket.close()
        except Exception as e:
            print(f"Error processing client {client_address}: {e}")

    def simulate_tcp_transfer(self, client_socket, file_size):
        """
        Simulate sending a file of the requested size over TCP.
        """
        print(f"Starting TCP transfer of {file_size} bytes...")
        start_time = time.time()

        # Send the requested file size in chunks (e.g., 1024 bytes per chunk)
        chunk_size = 1024
        data = b'0' * chunk_size  # Simulated data

        bytes_sent = 0
        while bytes_sent < file_size:
            remaining = file_size - bytes_sent
            client_socket.send(data[:min(chunk_size, remaining)])  # Send a chunk
            bytes_sent += min(chunk_size, remaining)

        end_time = time.time()
        # transfer_time = end_time - start_time
        transfer_time = max(end_time - start_time, 1e-6)  # Prevent zero division
        transfer_speed = file_size / transfer_time  # Bytes per second

        print(f"TCP transfer complete: {bytes_sent} bytes in {transfer_time:.2f} seconds "
              f"({transfer_speed:.2f} bytes/second)")

    def simulate_udp_transfer(self, client_address, file_size):
        """
        Simulate sending a file of the requested size over UDP.
        """
        print(f"Starting UDP transfer of {file_size} bytes to {client_address}...")

        # Calculate total segments
        chunk_size = 1024  # 1 KB per packet
        total_segments = (file_size + chunk_size - 1) // chunk_size  # Round up
        data_chunk = b'0' * chunk_size  # Simulated data

        # Start sending packets
        for segment_number in range(total_segments):
            # Prepare the packet
            magic_cookie = 0xabcddcba
            message_type = 0x4
            packet = struct.pack('>IBQQ', magic_cookie, message_type, total_segments, segment_number)
            payload = data_chunk[:min(chunk_size, file_size - segment_number * chunk_size)]
            packet += payload

            # Send packet to the client
            self.udp_socket.sendto(packet, client_address)

            print(f"Sent UDP packet {segment_number + 1}/{total_segments} to {client_address}")

        print(f"UDP transfer to {client_address} completed.")

    def stop_server(self):
        """
        Gracefully stop the server and release resources.
        """
        self.is_running = False
        self.tcp_socket.close()
        self.udp_socket.close()
        print("Server stopped.")




# server = SpeedTestServer()
# server.broadcast_offers()

# Create an instance of the server
server = SpeedTestServer()

try:
    # Start broadcasting offers in a separate thread
    threading.Thread(target=server.broadcast_offers, daemon=True).start()

    # Allow the server to set up
    print("Server is running. Testing functionality...")

    # Test 1: UDP Broadcast
    print("\n=== TEST 1: UDP BROADCAST ===")
    udp_test_socket = socket(AF_INET, SOCK_DGRAM)
    udp_test_socket.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
    udp_test_socket.bind(('', 13117))  # Listen on the same port as the broadcast
    data, addr = udp_test_socket.recvfrom(1024)
    magic_cookie, message_type, server_port = struct.unpack('>IBH', data)
    print(f"Received UDP broadcast from {addr}:")
    print(f"  Magic Cookie: {hex(magic_cookie)}")
    print(f"  Message Type: {message_type}")
    print(f"  Server Port: {server_port}")
    udp_test_socket.close()

    # Test 2: TCP Connection Handling
    print("\n=== TEST 2: TCP CONNECTION ===")
    tcp_test_socket = socket(AF_INET, SOCK_STREAM)
    tcp_test_socket.connect((server.server_ip, server_port))
    print("Connected to the server over TCP.")

    # Test 3: File Size Request (TCP)
    print("\n=== TEST 3: FILE SIZE REQUEST ===")
    file_size_request = "FileSize:1024"
    tcp_test_socket.send(file_size_request.encode())
    print(f"Sent file size request: {file_size_request}")
    tcp_test_socket.close()

    # Let the server run for a short time
    time.sleep(10)

except Exception as e:
    print(f"Error during testing: {e}")
finally:
    # Stop the server
    server.stop_server()
