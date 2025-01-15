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
          - Handles multiple TCP and UDP connections simultaneously using threads.
        """
        self.file_size = None
        self.num_tcp = 1
        self.num_udp = 1

        # Server details
        self.server_ip = None
        self.server_udp_port = None
        self.server_tcp_port = None

    def startup_prompt(self):
        """
        Prompts the user to input:
          1) file_size
          2) num_tcp
          3) num_udp
        """
        print("[Client] Enter file size in bytes: ", end="", flush=True)
        self.file_size = int(input().strip())

        print("[Client] How many TCP connections? ", end="", flush=True)
        self.num_tcp = int(input().strip())

        print("[Client] How many UDP connections? ", end="", flush=True)
        self.num_udp = int(input().strip())

    def listen_for_offer(self):
        """
        Listens for an Offer packet on UDP port 13117.
          Offer packet format:
            [magic_cookie=0xabcddcba, type=0x2, server_udp_port (2 bytes), server_tcp_port (2 bytes)]
        """
        print("[Client] Client started, listening for offer on UDP port 13117...")
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('', 13117))
        s.settimeout(5)  # Set a 5-second timeout

        try:
            while True:
                data, addr = s.recvfrom(1024)  # Blocking with a timeout
                if len(data) >= 9:
                    magic_cookie, message_type, udp_port, tcp_port = struct.unpack('>IBHH', data)
                    if magic_cookie == MAGIC_COOKIE and message_type == MSG_TYPE_OFFER:
                        self.server_ip = addr[0]
                        self.server_udp_port = udp_port
                        self.server_tcp_port = tcp_port
                        print(f"[Client] Received offer from {self.server_ip}, UDP port {udp_port}, TCP port {tcp_port}")
                        break
        except socket.timeout:
            print("[Client] Timeout: No offer received.")
        finally:
            s.close()

    def run_speed_test(self):
        """
        Run the specified number of TCP and UDP connections:
          - Each connection runs in its own thread for parallel execution.
        """
        threads = []

        # Start TCP connections
        for i in range(self.num_tcp):
            thread = threading.Thread(target=self.run_tcp_transfer, args=(i + 1,))
            threads.append(thread)
            thread.start()

        # Start UDP connections
        for i in range(self.num_udp):
            thread = threading.Thread(target=self.run_udp_transfer, args=(i + 1,))
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        print("[Client] All transfers complete, listening for offer requests...")

    def run_tcp_transfer(self, index):
        """
        1) Connect to server_tcp_port
        2) Send ASCII file size + newline
        3) Receive exactly 'file_size' bytes
        4) Print stats in bits/second
        """
        print(f"[Client] Starting TCP transfer #{index} with file_size={self.file_size}...")
        tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_socket.connect((self.server_ip, self.server_tcp_port))

        # Send the file size + newline
        request_str = f"{self.file_size}\n"
        tcp_socket.sendall(request_str.encode())

        # Receive data
        start_time = time.time()
        bytes_received = 0

        while bytes_received < self.file_size:
            chunk = tcp_socket.recv(4096)
            if not chunk:
                break
            bytes_received += len(chunk)

        end_time = time.time()
        tcp_socket.close()

        duration = max(end_time - start_time, 1e-9)
        speed_bps = (bytes_received * 8) / duration  # bits/sec

        print(f"[Client] TCP transfer #{index} finished, total time: {duration:.3f} seconds, "
              f"total speed: {speed_bps:.2f} bits/second")

    def run_udp_transfer(self, index):
        """
        1) Send a request packet to server_udp_port
        2) Listen for payload packets for ~2 seconds
        3) Compute throughput, packet success, etc.
        """
        print(f"[Client] Starting UDP transfer #{index} with file_size={self.file_size}...")
        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Construct the request packet
        packet = struct.pack('>IBQ', MAGIC_COOKIE, MSG_TYPE_REQUEST, self.file_size)
        udp_socket.sendto(packet, (self.server_ip, self.server_udp_port))

        start_time = time.time()
        bytes_received = 0

        while time.time() - start_time < 2:  # Listen for 2 seconds
            try:
                data, addr = udp_socket.recvfrom(65535)
                if data:
                    bytes_received += len(data)
            except socket.timeout:
                break

        udp_socket.close()

        duration = max(time.time() - start_time, 1e-9)
        speed_bps = (bytes_received * 8) / duration  # bits/sec

        print(f"[Client] UDP transfer #{index} finished, total time: {duration:.3f} seconds, "
              f"total speed: {speed_bps:.2f} bits/second")

def main():
    client = SpeedTestClient()
    client.startup_prompt()
    client.listen_for_offer()
    client.run_speed_test()

if __name__ == "__main__":
    main()
