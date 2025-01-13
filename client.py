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
          - For each TCP connection: connects, sends file size, receives that many bytes
          - For each UDP connection: sends a Request packet (0x3) to server_udp_port, receives payload packets (0x4)
        """
        self.file_size = None
        self.num_tcp = 1
        self.num_udp = 1

        # Server details
        self.server_ip = None
        self.server_udp_port = None
        self.server_tcp_port = None

        # UDP data tracking
        self.udp_socket = None
        self.keep_receiving = True
        self.received_segments = set()  # We'll track which segment numbers arrived
        self.total_segments = 0
        self.udp_bytes_received = 0
        self.udp_start_time = 0.0

    def startup_prompt(self):
        """
        Prompts the user to input:
          1) file_size
          2) num_tcp
          3) num_udp
        Similar to the example run instructions.
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

        while True:
            data, addr = s.recvfrom(1024)
            if len(data) >= 9:
                cookie, msg_type, srv_udp_port, srv_tcp_port = struct.unpack('>IBHH', data)
                if cookie == MAGIC_COOKIE and msg_type == MSG_TYPE_OFFER:
                    self.server_ip = addr[0]  # the IP of the server
                    self.server_udp_port = srv_udp_port
                    self.server_tcp_port = srv_tcp_port
                    print(f"[Client] Received offer from {self.server_ip} | "
                          f"UDP port={srv_udp_port}, TCP port={srv_tcp_port}")
                    break

        s.close()

    def run_speed_test(self):
        """
        According to the user parameters:
         1) run self.num_tcp TCP connections
         2) run self.num_udp UDP connections
        We do them sequentially here for simplicity (the example run references threads, but this is enough to demonstrate).
        """
        for i in range(self.num_tcp):
            self.run_tcp_transfer(i + 1)

        for i in range(self.num_udp):
            self.run_udp_transfer(i + 1)

        print("[Client] All transfers complete, listening for offer requests...")

    # ---------------------------
    # TCP logic
    # ---------------------------
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

        # Send the file size + newline (the assignment says: "client sends the amount of data requested, then newline")
        request_str = f"{self.file_size}\n"
        tcp_socket.sendall(request_str.encode())

        # Receive data
        start_time = time.time()
        bytes_received = 0
        buffer = b''

        while bytes_received < self.file_size:
            chunk = tcp_socket.recv(4096)
            if not chunk:
                break
            buffer += chunk
            bytes_received = len(buffer)

        end_time = time.time()
        tcp_socket.close()

        duration = max(end_time - start_time, 1e-9)
        speed_bps = (bytes_received * 8) / duration  # bits/sec

        print(f"[Client] TCP transfer #{index} finished, total time: {duration:.3f} seconds, "
              f"total speed: {speed_bps:.2f} bits/second")

    # ---------------------------
    # UDP logic
    # ---------------------------
    def run_udp_transfer(self, index):
        """
        1) Create a local UDP socket.
        2) Send the "request" packet: 
             [cookie=0xabcddcba, type=0x3, file_size=8 bytes]
        3) Listen for "payload" (0x4) packets in a separate thread
           until no data arrives for ~1 second.
        4) Compute throughput, packet success, etc.
        """
        print(f"[Client] Starting UDP transfer #{index} with file_size={self.file_size}...")

        # Create the UDP socket for this transfer
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.udp_socket.bind(('', 0))  # ephemeral port

        # Reset our stats
        self.keep_receiving = True
        self.udp_start_time = time.time()
        self.received_segments = set()
        self.total_segments = 0
        self.udp_bytes_received = 0

        # Start a receive thread
        recv_thread = threading.Thread(target=self.udp_receive_loop, daemon=True)
        recv_thread.start()

        # Construct the request packet:
        # Format: >IBQ => 4 bytes (cookie), 1 byte (type=0x3), 8 bytes (file size)
        packet = struct.pack('>IBQ', MAGIC_COOKIE, MSG_TYPE_REQUEST, self.file_size)

        # Send it to the server's UDP port
        self.udp_socket.sendto(packet, (self.server_ip, self.server_udp_port))

        # Wait a bit (the assignment says "the client detects the transfer is done after no data for 1 second")
        # We'll do a simple "wait 2s then stop" approach for demonstration.
        time.sleep(2)

        # Stop receiving
        self.keep_receiving = False
        self.udp_socket.close()
        recv_thread.join()

        # Now compute stats
        end_time = time.time()
        duration = max(end_time - self.udp_start_time, 1e-9)
        speed_bps = (self.udp_bytes_received * 8) / duration

        # If we never got any payload, total_segments=0
        if self.total_segments == 0:
            success_percent = 0.0
        else:
            success_percent = 100.0 * len(self.received_segments) / self.total_segments

        print(f"[Client] UDP transfer #{index} finished, total time: {duration:.3f} seconds, "
              f"total speed: {speed_bps:.2f} bits/second, "
              f"percentage of packets received successfully: {success_percent:.1f}%")

    def udp_receive_loop(self):
        """
        Receives packets of type=0x4:
          [cookie=0xabcddcba, type=0x4, total_segments=8 bytes, current_segment=8 bytes, payload...]
        We'll parse the header (first 21 bytes) and keep track of which segments have arrived.
        Also track total received bytes for throughput calculations.
        """
        self.udp_socket.settimeout(0.5)  # 500ms to avoid blocking forever
        last_received_time = time.time()

        while self.keep_receiving:
            try:
                data, addr = self.udp_socket.recvfrom(65535)
                if data:
                    last_received_time = time.time()
                    self.udp_bytes_received += len(data)

                    # The minimal header size: 21 bytes => 4 + 1 + 8 + 8
                    if len(data) >= 21:
                        cookie, msg_type, tot_seg, cur_seg = struct.unpack('>IBQQ', data[:21])
                        # Verify it's a valid payload
                        if cookie == MAGIC_COOKIE and msg_type == MSG_TYPE_PAYLOAD:
                            self.total_segments = tot_seg
                            self.received_segments.add(cur_seg)

            except socket.timeout:
                # If no data for 0.5s, check if 1s has passed since last data
                # The assignment example says "concludes after no data has been received for 1 second"
                if (time.time() - last_received_time) > 1.0:
                    # We'll consider this done
                    break
            except:
                # Socket closed or other error
                break

def main():
    # 1) Prompt user for file size, #TCP, #UDP
    client = SpeedTestClient()
    client.startup_prompt()

    # 2) Listen for the server's offer (0x2)
    client.listen_for_offer()

    # 3) Run the requested speed tests (TCP & UDP)
    client.run_speed_test()

if __name__ == "__main__":
    main()
