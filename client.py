import socket
import struct
import time
import threading

# Constants from the assignment
MAGIC_COOKIE = 0xabcddcba
MSG_TYPE_OFFER = 0x2
MSG_TYPE_REQUEST = 0x3
MSG_TYPE_PAYLOAD = 0x4

class SpeedTestClient:
    def __init__(self):
        """
        The client:
          - Prompts for file size, #TCP connections, #UDP connections
          - Listens for an Offer packet (0x2) on port 13117
          - Once found, extracts server_udp_port and server_tcp_port
          - Handles both TCP and UDP connections, including multiple simultaneous connections.
        """
        self.file_size = None
        self.num_tcp = 1
        self.num_udp = 1

        # Server details (populated after listening for an offer)
        self.server_ip = None
        self.server_udp_port = None
        self.server_tcp_port = None

        # Variables for tracking UDP progress
        self.udp_sockets = []  # A list of sockets for UDP transfers (one per connection)
        self.udp_results = {}  # Store results for each UDP connection by index

    def startup_prompt(self):
        """
        Prompts the user to input:
          - The file size to request (in bytes)
          - The number of TCP connections to open
          - The number of UDP connections to open
        """
        print("[Client] Enter file size in bytes: ", end="")
        self.file_size = int(input().strip())

        print("[Client] How many TCP connections? ", end="")
        self.num_tcp = int(input().strip())

        print("[Client] How many UDP connections? ", end="")
        self.num_udp = int(input().strip())

    def listen_for_offer(self):
        """
        Listens for an Offer packet (type=0x2) on UDP port 13117.
        Once received, extracts the server's IP, UDP port, and TCP port.
        """
        print("[Client] Listening for offer on UDP port 13117...")
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('', 13117))
        s.settimeout(10)  # Timeout for waiting on the offer packet

        try:
            while True:
                print("[Client] Waiting for server broadcast...")
                data, addr = s.recvfrom(1024)  # Blocking call
                if len(data) >= 9:
                    magic_cookie, msg_type, udp_port, tcp_port = struct.unpack('>IBHH', data)
                    if magic_cookie == MAGIC_COOKIE and msg_type == MSG_TYPE_OFFER:
                        self.server_ip = addr[0]
                        self.server_udp_port = udp_port
                        self.server_tcp_port = tcp_port
                        print(f"[Client] Offer received from {self.server_ip} - UDP port: {udp_port}, TCP port: {tcp_port}")
                        break
        except socket.timeout:
            print("[Client] No offer received. Exiting.")
            exit(1)  # Exit the program if no offer is received
        finally:
            s.close()

    def run_speed_test(self):
        """
        Executes both TCP and UDP speed tests using multiple connections.
        Each connection runs in a separate thread.
        """
        print("[Client] Preparing to run speed tests...")
        tcp_threads = []
        udp_threads = []

        # Start TCP threads
        print("[Client] Starting TCP connections...")
        for i in range(self.num_tcp):
            thread = threading.Thread(target=self.run_tcp_transfer, args=(i + 1,))
            tcp_threads.append(thread)
            thread.start()

        # Start UDP threads
        print("[Client] Starting UDP connections...")
        for i in range(self.num_udp):
            thread = threading.Thread(target=self.run_udp_transfer, args=(i + 1,))
            udp_threads.append(thread)
            thread.start()

        # Wait for all TCP threads to complete
        for thread in tcp_threads:
            thread.join()

        # Wait for all UDP threads to complete
        for thread in udp_threads:
            thread.join()

        print("[Client] All speed tests completed successfully.")

    def run_tcp_transfer(self, index):
        """
        Executes a TCP transfer:
          - Connects to the server's TCP port
          - Sends the file size request
          - Receives the requested amount of data
          - Calculates and prints the transfer speed
        """
        print(f"[Client] TCP Transfer #{index} starting...")
        tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_socket.connect((self.server_ip, self.server_tcp_port))

        # Send the file size + newline
        request = f"{self.file_size}\n"
        tcp_socket.sendall(request.encode())

        start_time = time.time()
        bytes_received = 0

        while bytes_received < self.file_size:
            chunk = tcp_socket.recv(4096)
            if not chunk:
                break
            bytes_received += len(chunk)

        end_time = time.time()
        tcp_socket.close()

        duration = end_time - start_time
        speed = (bytes_received * 8) / duration  # Bits per second

        print(f"[Client] TCP Transfer #{index} completed: {bytes_received} bytes in {duration:.3f} seconds ({speed:.2f} bps).")

    def run_udp_transfer(self, index):
        """
        Executes a UDP transfer:
          - Sends a request packet to the server
          - Receives payload packets for a fixed duration
          - Calculates throughput and success rate
        """
        print(f"[Client] UDP Transfer #{index} starting...")
        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_socket.settimeout(1)  # Timeout for receiving data
        self.udp_sockets.append(udp_socket)

        # Send the request packet
        request_packet = struct.pack('>IBQ', MAGIC_COOKIE, MSG_TYPE_REQUEST, self.file_size)
        udp_socket.sendto(request_packet, (self.server_ip, self.server_udp_port))

        start_time = time.time()
        bytes_received = 0

        while time.time() - start_time < 2:
            try:
                data, addr = udp_socket.recvfrom(65535)
                if data:
                    bytes_received += len(data)
            except socket.timeout:
                break

        udp_socket.close()
        self.udp_results[index] = bytes_received
        print(f"[Client] UDP Transfer #{index} completed: {bytes_received} bytes received.")

def main():
    client = SpeedTestClient()
    client.startup_prompt()
    client.listen_for_offer()
    client.run_speed_test()

if __name__ == "__main__":
    main()
