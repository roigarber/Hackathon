import socket
import struct
import threading
import time

class SpeedTestClient:
    def __init__(self, file_size=2048):
        """
        Initializes the client.
        :param file_size: Number of bytes to request from the server.
        """
        self.file_size = file_size
        self.server_ip = None
        self.server_port = None  # This will be discovered from broadcast
        self.udp_socket = None
        self.udp_received_bytes = 0
        self.udp_segments_received = 0
        self.udp_listen_thread = None
        self.keep_listening = True

    def discover_server(self):
        """
        Listens for a server broadcast on UDP port 13117,
        then parses the incoming data to retrieve the server IP and TCP port.
        """
        print("[Client] Listening for broadcast offers on UDP port 13117...")

        # Create a UDP socket to receive broadcast
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('', 13117))

        while True:
            data, addr = sock.recvfrom(1024)  # Block until data arrives
            if len(data) >= 7:  # Enough bytes to parse magic_cookie + message_type + port
                # Packet format: >IBH => 4 bytes (cookie), 1 byte (type), 2 bytes (TCP port)
                magic_cookie, message_type, server_port = struct.unpack('>IBH', data)
                if magic_cookie == 0xabcddcba and message_type == 0x2:
                    self.server_ip = addr[0]
                    self.server_port = server_port
                    print(f"[Client] Received offer from {self.server_ip} on TCP port {self.server_port}")
                    break

        sock.close()

    def connect_and_run(self):
        """
        Connects to the server via TCP, sends the file size request,
        spawns a UDP listening thread on the same ephemeral port, and measures performance.
        """
        if not self.server_ip or not self.server_port:
            print("[Client] No server information. Call discover_server() first.")
            return

        # 1) Create TCP socket
        tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_socket.bind(('', 0))  # Let OS pick ephemeral port

        # 2) Connect to the server
        tcp_socket.connect((self.server_ip, self.server_port))
        local_ip, local_tcp_port = tcp_socket.getsockname()
        print(f"[Client] Connected to server at {self.server_ip}:{self.server_port}")
        print(f"[Client] Local ephemeral TCP port: {local_tcp_port}")

        # 3) Create a UDP socket bound to the same port
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.udp_socket.bind(('', local_tcp_port))

        # Start thread to listen for UDP data
        self.keep_listening = True
        self.udp_listen_thread = threading.Thread(target=self.listen_udp, daemon=True)
        self.udp_listen_thread.start()

        # 4) Send the file size request (e.g., "FileSize:2048") over TCP
        request_str = f"FileSize:{self.file_size}"
        tcp_socket.sendall(request_str.encode())
        print(f"[Client] Sent file size request: {request_str}")

        # 5) Receive file data over TCP
        start_time = time.time()
        bytes_received = 0
        buffer = b''

        while bytes_received < self.file_size:
            data = tcp_socket.recv(4096)
            if not data:
                break
            buffer += data
            bytes_received = len(buffer)

        end_time = time.time()
        tcp_socket.close()

        # Compute TCP stats
        tcp_duration = max(end_time - start_time, 1e-6)
        tcp_throughput = bytes_received / tcp_duration  # bytes/s

        print(f"\n[Client] TCP Transfer complete!")
        print(f"         Requested/Received: {self.file_size}/{bytes_received} bytes")
        print(f"         Duration: {tcp_duration:.3f} sec")
        print(f"         Throughput: {tcp_throughput:.2f} bytes/s")

        # 6) Give the server some time to send UDP packets
        time.sleep(2)

        # Stop UDP listening
        self.keep_listening = False
        if self.udp_socket:
            self.udp_socket.close()
        if self.udp_listen_thread:
            self.udp_listen_thread.join()

        # Print UDP stats
        print(f"\n[Client] UDP Transfer stats:")
        print(f"         Total packets received: {self.udp_segments_received}")
        print(f"         Total UDP bytes received: {self.udp_received_bytes}")

    def listen_udp(self):
        """
        Continuously receives UDP packets on our ephemeral TCP port.
        For each packet, increments counters for total packets and bytes.
        """
        print(f"[Client] Listening for UDP data on port {self.udp_socket.getsockname()[1]}...")

        while self.keep_listening:
            try:
                data, addr = self.udp_socket.recvfrom(65535)
                if data:
                    self.udp_segments_received += 1
                    self.udp_received_bytes += len(data)
            except socket.error:
                # Socket likely closed
                break

def main():
    client = SpeedTestClient(file_size=2048)  # or any file size you want
    client.discover_server()
    client.connect_and_run()

if __name__ == "__main__":
    main()
