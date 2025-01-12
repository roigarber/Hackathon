import socket
import struct
import threading
import time

class SpeedTestClient:
    def __init__(self, file_size=2048):
        """
        Client that:
          - Waits for server offer on UDP port 13117
          - Connects over TCP to request a file
          - Receives data over TCP
          - Also receives data over UDP to the same ephemeral port
        """
        self.file_size = file_size
        self.server_ip = None
        self.server_port = None

        # For UDP listening
        self.udp_socket = None
        self.keep_listening = True
        self.udp_listen_thread = None

        # Stats
        self.udp_segments_received = 0
        self.udp_received_bytes = 0
        self.udp_start_time = 0.0

    def discover_server(self):
        """
        Wait for the broadcast offer on port 13117.
        Once received, parse out the server's IP & port.
        """
        print("[Client] Client started, listening for offer requests on UDP port 13117...")
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('', 13117))

        while True:
            data, addr = s.recvfrom(1024)  # blocking
            if len(data) >= 7:
                magic_cookie, message_type, tcp_port = struct.unpack('>IBH', data)
                if magic_cookie == 0xabcddcba and message_type == 0x2:
                    self.server_ip = addr[0]
                    self.server_port = tcp_port
                    print(f"[Client] Received offer from {self.server_ip}, TCP port {tcp_port}")
                    break

        s.close()

    def connect_and_run(self):
        """
        1) Connect to the server via TCP
        2) Bind a UDP socket to the same ephemeral port
        3) Request the file (TCP)
        4) Receive the file (TCP)
        5) Listen for the UDP transfer
        """
        if not self.server_ip or not self.server_port:
            print("[Client] No server info. Please run discover_server() first.")
            return

        print(f"[Client] Attempting to connect to server at {self.server_ip}:{self.server_port} ...")
        tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_socket.bind(('', 0))  # ephemeral port
        tcp_socket.connect((self.server_ip, self.server_port))

        local_ip, local_port = tcp_socket.getsockname()
        print(f"[Client] Connected to {self.server_ip}:{self.server_port} from local port {local_port}")

        # Create a UDP socket on the same port
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.udp_socket.bind(('', local_port))

        # Start listening thread for UDP packets
        self.keep_listening = True
        self.udp_listen_thread = threading.Thread(target=self.listen_for_udp, daemon=True)
        self.udp_listen_thread.start()

        # TCP transfer
        self.send_file_size_request(tcp_socket)
        self.receive_tcp_data(tcp_socket)

        # Wait a moment for UDP to finish
        time.sleep(2)
        self.stop_udp()

    def send_file_size_request(self, tcp_socket):
        """
        Send the request to the server in the form "FileSize:<N>"
        """
        msg = f"FileSize:{self.file_size}"
        tcp_socket.sendall(msg.encode())
        print(f"[Client] Sent file size request: {msg}")

    def receive_tcp_data(self, tcp_socket):
        """
        Receive 'self.file_size' bytes of data via TCP, measure time & print stats.
        """
        start_time = time.time()

        total_received = 0
        buffer = b''

        while total_received < self.file_size:
            data = tcp_socket.recv(4096)
            if not data:
                break
            buffer += data
            total_received = len(buffer)

        end_time = time.time()
        tcp_socket.close()

        duration = max(end_time - start_time, 1e-6)
        speed_bps = total_received / duration

        print(f"[Client] TCP transfer #1 finished, total time: {duration:.3f} seconds, "
              f"total speed: {speed_bps:.2f} bytes/second")

    def listen_for_udp(self):
        """
        Continuously receive UDP packets from the server to measure stats.
        We'll parse the header (magic cookie, msg type, total segs, current seg),
        then read the payload data. We'll track how many segments arrive.
        """
        self.udp_start_time = time.time()
        print(f"[Client] Listening for UDP data on port {self.udp_socket.getsockname()[1]}...")

        while self.keep_listening:
            try:
                data, addr = self.udp_socket.recvfrom(65535)
                if data:
                    self.udp_segments_received += 1
                    self.udp_received_bytes += len(data)
            except:
                break

    def stop_udp(self):
        """
        Stop the UDP listening thread & print stats.
        """
        self.keep_listening = False
        if self.udp_socket:
            self.udp_socket.close()
        if self.udp_listen_thread:
            self.udp_listen_thread.join()

        end_time = time.time()
        total_time = max(end_time - self.udp_start_time, 1e-6)
        speed_bps = self.udp_received_bytes / total_time

        print(f"[Client] UDP transfer #1 finished, total time: {total_time:.3f} seconds, "
              f"total speed: {speed_bps:.2f} bytes/second")
        # If you wanted to compute packet loss, you'd parse segment headers & compare.

def main():
    client = SpeedTestClient(file_size=2048)  # Adjust the requested size as you wish
    client.discover_server()
    client.connect_and_run()

    print("[Client] All transfers complete, listening for offer requests...")

if __name__ == "__main__":
    main()
