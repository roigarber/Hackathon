import socket
import struct
import time
import threading

# Constants from the assignment
MAGIC_COOKIE = 0xabcddcba  # Used to validate incoming packets
MSG_TYPE_OFFER = 0x2       # Indicates an offer message
MSG_TYPE_REQUEST = 0x3     # Indicates a request message
MSG_TYPE_PAYLOAD = 0x4     # Indicates a payload message

# ANSI color codes for colorful output
GREEN = '\033[92m'
YELLOW = '\033[93m'
RED = '\033[91m'
RESET = '\033[0m'

class SpeedTestClient:
    def __init__(self):
        """
        The client:
          - Prompts for file size, #TCP connections, #UDP connections
          - Listens for an Offer packet (0x2) on port 13117
          - Once found, extracts server_udp_port and server_tcp_port
          - For each TCP connection: connects, sends file size, receives that many bytes
          - For each UDP connection: sends a Request packet (0x3) to server_udp_port, receives payload packets (0x4)
        """
        self.file_size = None  # The size of the file to request in bytes
        self.num_tcp = 1       # Number of TCP connections
        self.num_udp = 1       # Number of UDP connections

        # Server details
        self.server_ip = None          # The IP address of the server
        self.server_udp_port = None    # The UDP port of the server
        self.server_tcp_port = None    # The TCP port of the server

    def startup_prompt(self):
        """
        Prompts the user to input:
          1) File size
          2) Number of TCP connections
          3) Number of UDP connections
        Similar to the example run instructions, with added input validation.
        """
        try:
            print("[Client] Enter file size in bytes: ", end="", flush=True)
            self.file_size = int(input().strip())
            if self.file_size <= 0:
                raise ValueError("File size must be a positive integer.")

            print("[Client] How many TCP connections? ", end="", flush=True)
            self.num_tcp = int(input().strip())
            if self.num_tcp <= 0:
                raise ValueError("Number of TCP connections must be a positive integer.")

            print("[Client] How many UDP connections? ", end="", flush=True)
            self.num_udp = int(input().strip())
            if self.num_udp <= 0:
                raise ValueError("Number of UDP connections must be a positive integer.")

        except ValueError as e:
            print(f"{RED}[Error] Invalid input: {e}{RESET}")
            exit(1)

    def listen_for_offer(self):
        """
        Listens for an Offer packet on UDP port 13117.
          Offer packet format:
            [magic_cookie=0xabcddcba, type=0x2, server_udp_port (2 bytes), server_tcp_port (2 bytes)]
        """
        print(f"{YELLOW}[Client] Listening for offer on UDP port 13117...{RESET}")
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) #SO_REUSEADDR
        s.bind(('', 13117))
        s.settimeout(5)  # Timeout for waiting on the offer packet

        try:
            while True:
                print(f"{YELLOW}[Client] Waiting for server broadcast...{RESET}")
                data, addr = s.recvfrom(1024)  # Blocking call
                if len(data) >= 9:
                    # Extract data from the received packet
                    magic_cookie, msg_type, udp_port, tcp_port = struct.unpack('>IBHH', data)
                    if magic_cookie == MAGIC_COOKIE and msg_type == MSG_TYPE_OFFER:
                        self.server_ip = addr[0]
                        #self.server_ip = '192.168.131.148'
                        #print(self.server_ip)
                        self.server_udp_port = udp_port
                        self.server_tcp_port = tcp_port
                        print(f"{GREEN}[Client] Offer received from {self.server_ip} "
                              f"(UDP port: {udp_port}, TCP port: {tcp_port}){RESET}")
                        break
        except socket.timeout:
            print(f"{RED}[Client] Timeout: No offer received. Exiting.{RESET}")
            exit(1)
        except Exception as e:
            print(f"{RED}[Error] Failed to listen for offer: {e}{RESET}")
            exit(1)
        finally:
            s.close()

    def run_speed_test(self):
        """
        According to the user parameters:
         1) Run self.num_tcp TCP connections
         2) Run self.num_udp UDP connections
        Each connection is handled in its own thread to support parallelism.
        """
        tcp_threads = []
        udp_threads = []

        print(f"{YELLOW}[Client] Starting TCP transfers...{RESET}")
        for i in range(self.num_tcp):
            print(f"{YELLOW}[Client] Preparing TCP transfer #{i + 1}...{RESET}")
            thread = threading.Thread(target=self.run_tcp_transfer, args=(i + 1,))
            tcp_threads.append(thread)
            thread.start()

        print(f"{YELLOW}[Client] Starting UDP transfers...{RESET}")
        for i in range(self.num_udp):
            print(f"{YELLOW}[Client] Preparing UDP transfer #{i + 1}...{RESET}")
            thread = threading.Thread(target=self.run_udp_transfer, args=(i + 1,))
            udp_threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in tcp_threads + udp_threads:
            thread.join()

        print(f"{GREEN}[Client] All transfers complete.{RESET}")

    def run_tcp_transfer(self, index):
        """
        Handles a single TCP connection:
          - Connects to the server's TCP port
          - Sends the requested file size
          - Receives data from the server
          - Logs throughput statistics
        """
        print(f"{YELLOW}[Client] Starting TCP transfer #{index}...{RESET}")
        try:
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
            duration = end_time - start_time
            speed_bps = (bytes_received * 8) / duration  # Bits per second

            print(f"{GREEN}[Client] TCP transfer #{index} completed: {bytes_received} bytes in {duration:.3f} seconds "
                  f"({speed_bps:.2f} bps).{RESET}")

        except Exception as e:
            print(f"{RED}[Error] TCP transfer #{index} failed: {e}{RESET}")
        finally:
            tcp_socket.close()

    def run_udp_transfer(self, index):
        """
        Handles a single UDP connection:
          - Sends a request packet to the server
          - Receives payload packets
          - Computes throughput and success rate
        """
        print(f"{YELLOW}[Client] Starting UDP transfer #{index}...{RESET}")
        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_socket.settimeout(1)

        try:
            request_packet = struct.pack('>IBQ', MAGIC_COOKIE, MSG_TYPE_REQUEST, self.file_size)
            udp_socket.sendto(request_packet, (self.server_ip, self.server_udp_port))

            start_time = time.time()
            bytes_received = 0
            received_segments = set()
            total_segments = 0

            while time.time() - start_time < 2:
                try:
                    data, addr = udp_socket.recvfrom(65535)
                    if len(data) >= 21:
                        cookie, msg_type, total_segments, current_segment = struct.unpack('>IBQQ', data[:21])
                        if cookie == MAGIC_COOKIE and msg_type == MSG_TYPE_PAYLOAD:
                            received_segments.add(current_segment)
                            bytes_received += len(data) - 21  # Exclude header size
                except socket.timeout:
                    break

            duration = max(time.time() - start_time, 1e-9)
            success_rate = (len(received_segments) / total_segments * 100) if total_segments > 0 else 0.0
            speed_bps = (bytes_received * 8) / duration

            print(f"{GREEN}[Client] UDP transfer #{index} completed: {bytes_received} bytes in {duration:.3f} seconds "
                  f"({speed_bps:.2f} bps), percentage of packets received successfully: {success_rate:.1f}%{RESET}")

        except Exception as e:
            print(f"{RED}[Error] UDP transfer #{index} failed: {e}{RESET}")
        finally:
            udp_socket.close()


def main():
    client = SpeedTestClient()
    client.startup_prompt()
    client.listen_for_offer()
    client.run_speed_test()


if __name__ == "__main__":
    main()
