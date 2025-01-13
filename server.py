import random
import threading
import struct
import time
import socket

# Constants for the assignment
MAGIC_COOKIE = 0xabcddcba
MSG_TYPE_OFFER = 0x2    # Offer packet (server -> client)
MSG_TYPE_REQUEST = 0x3  # Request packet (client -> server, over UDP)
MSG_TYPE_PAYLOAD = 0x4  # Payload packet (server -> client, over UDP)

class SpeedTestServer:
    def __init__(self):
        """
        The server:
         - Creates sockets for broadcasting, listening for UDP requests, and listening for TCP connections.
         - Picks random ports for its UDP and TCP services.
         - Prepares the "offer" packet that is periodically broadcast on port 13117.
        """
        # Sockets for:
        #  1) Broadcasting offers (udp_broadcast_socket)
        #  2) Receiving UDP requests (udp_server_socket)
        #  3) Accepting TCP connections (tcp_server_socket)

        self.udp_broadcast_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.udp_broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        self.udp_server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        self.tcp_server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # The well-known broadcast port from the assignment
        self.BROADCAST_PORT = 13117
        self.broadcast_ip = '255.255.255.255'  # Send to all on local subnet

        # We'll pick random ports for the server's UDP and TCP (the assignment often uses ephemeral or random).
        self.server_udp_port = random.randint(10000, 60000)
        self.server_tcp_port = random.randint(10000, 60000)

        # Build the OFFER packet:
        # Format: >IBHH means:
        #  >       : Big-endian
        #  I       : 4 bytes (the magic cookie)
        #  B       : 1 byte (the message type, 0x2 for 'offer')
        #  H       : 2 bytes (the server's UDP port)
        #  H       : 2 bytes (the server's TCP port)
        self.offer_packet = struct.pack('>IBHH',
                                        MAGIC_COOKIE,
                                        MSG_TYPE_OFFER,
                                        self.server_udp_port,
                                        self.server_tcp_port)

        # We'll just detect the local IP via gethostname -> gethostbyname
        self.server_ip = socket.gethostbyname(socket.gethostname())

        # A flag to let us gracefully shut down
        self.is_running = True

        print(f"[Server] Server started, listening on IP address {self.server_ip}")

    def start(self):
        """
        Starts the server operation:
         1) Binds the UDP "server" socket to server_udp_port (where clients send request=0x3).
         2) Binds + listens on the TCP socket to server_tcp_port (where clients connect).
         3) Broadcasts the offer packet every second on port 13117.
        """

        # 1) Bind to UDP server port (for receiving 0x3 request packets)
        self.udp_server_socket.bind(('', self.server_udp_port))
        threading.Thread(target=self.udp_request_listener, daemon=True).start()

        # 2) Bind + listen on TCP
        self.tcp_server_socket.bind(('', self.server_tcp_port))
        self.tcp_server_socket.listen(5)  # allow up to 5 pending connections
        threading.Thread(target=self.tcp_connection_listener, daemon=True).start()

        print(f"[Server] UDP bound on port {self.server_udp_port}")
        print(f"[Server] TCP listening on port {self.server_tcp_port}")

        # 3) Broadcast the offer packet every 1 second
        print("[Server] Starting to send offer broadcasts...")
        while self.is_running:
            try:
                # Send the offer packet to 255.255.255.255:13117
                self.udp_broadcast_socket.sendto(self.offer_packet, (self.broadcast_ip, self.BROADCAST_PORT))
                time.sleep(1)  # Sleep 1 second
            except Exception as e:
                print(f"[Server] Broadcast error: {e}")
                break

        self.stop_server()

    def udp_request_listener(self):
        """
        Continuously listens for "request" packets on self.server_udp_port:
          [magic_cookie=0xabcddcba, type=0x3, file_size=8 bytes]
        Then spawns a thread to do the "payload" transfer.
        """
        print("[Server] Ready to receive UDP requests...")
        while self.is_running:
            try:
                data, client_addr = self.udp_server_socket.recvfrom(1024)
                if len(data) >= 13:  # 4 + 1 + 8
                    cookie, msg_type, file_size = struct.unpack('>IBQ', data)
                    if cookie == MAGIC_COOKIE and msg_type == MSG_TYPE_REQUEST:
                        print(f"[Server] Received UDP request from {client_addr}, file_size={file_size}")
                        # Spawn a thread to handle the UDP payload sending
                        threading.Thread(
                            target=self.simulate_udp_transfer,
                            args=(client_addr, file_size),
                            daemon=True
                        ).start()
            except Exception as e:
                print(f"[Server] UDP listener error: {e}")
                break

    def tcp_connection_listener(self):
        """
        Accepts incoming TCP connections on self.server_tcp_port.
        The client sends an ASCII string (digits) + "\n" for the file size,
        and we send that many bytes.
        """
        print("[Server] Ready to accept TCP connections...")
        while self.is_running:
            try:
                client_socket, client_addr = self.tcp_server_socket.accept()
                print(f"[Server] New TCP client from {client_addr}")
                threading.Thread(
                    target=self.handle_tcp_client,
                    args=(client_socket, client_addr),
                    daemon=True
                ).start()
            except Exception as e:
                print(f"[Server] TCP listener error: {e}")
                break

    def handle_tcp_client(self, client_socket, client_addr):
        """
        Reads the file size from the client (digits + newline),
        then sends that many bytes over TCP (in 1 KB chunks).
        """
        try:
            data = b''
            # Keep reading until we see a newline
            while b'\n' not in data:
                chunk = client_socket.recv(1024)
                if not chunk:
                    break
                data += chunk

            line = data.decode().strip()
            file_size = int(line)  # parse out the file size
            print(f"[Server] TCP client {client_addr} requested file_size={file_size}")

            self.simulate_tcp_transfer(client_socket, file_size)
        except Exception as e:
            print(f"[Server] Error handling TCP client {client_addr}: {e}")
        finally:
            client_socket.close()

    def simulate_tcp_transfer(self, client_socket, file_size):
        """
        Sends 'file_size' bytes over TCP in chunks of 1024 bytes.
        """
        print(f"[Server] Starting TCP transfer of {file_size} bytes to {client_socket.getpeername()}...")
        start_time = time.time()

        bytes_sent = 0
        chunk_size = 1024
        chunk_data = b'T' * chunk_size  # some dummy data to send

        while bytes_sent < file_size:
            remaining = file_size - bytes_sent
            send_size = min(chunk_size, remaining)
            client_socket.sendall(chunk_data[:send_size])
            bytes_sent += send_size

        end_time = time.time()
        duration = max(end_time - start_time, 1e-9)
        speed_bps = (file_size * 8) / duration  # convert bytes -> bits

        print(f"[Server] TCP transfer complete: {bytes_sent} bytes in {duration:.3f} s "
              f"({speed_bps:.2f} bits/s)")

    def simulate_udp_transfer(self, client_addr, file_size):
        """
        Sends 'file_size' bytes over UDP in "payload" packets, each with:
         [magic_cookie=0xabcddcba, type=0x4, total_segments=8 bytes, current_segment=8 bytes, payload...]
        We use 1024 bytes per segment. 
        """
        print(f"[Server] Starting UDP transfer of {file_size} bytes to {client_addr}...")
        start_time = time.time()

        chunk_size = 1024
        total_segments = (file_size + chunk_size - 1) // chunk_size  # round up
        data_chunk = b'U' * chunk_size

        for seg_num in range(total_segments):
            magic_cookie = MAGIC_COOKIE
            message_type = MSG_TYPE_PAYLOAD
            header = struct.pack('>IBQQ',
                                 magic_cookie,
                                 message_type,
                                 total_segments,
                                 seg_num)
            seg_size = min(chunk_size, file_size - seg_num * chunk_size)
            payload = data_chunk[:seg_size]

            packet = header + payload
            self.udp_server_socket.sendto(packet, client_addr)

        end_time = time.time()
        duration = max(end_time - start_time, 1e-9)
        speed_bps = (file_size * 8) / duration

        print(f"[Server] UDP transfer complete: {total_segments} segments in {duration:.3f} s "
              f"({speed_bps:.2f} bits/s)")

    def stop_server(self):
        """
        Gracefully stop everything.
        """
        self.is_running = False
        try:
            self.udp_broadcast_socket.close()
            self.udp_server_socket.close()
            self.tcp_server_socket.close()
        except Exception as e:
            print(f"[Server] Error closing sockets: {e}")

        print("[Server] All transfers complete, listening for offer requests... (Server shutting down)")


if __name__ == "__main__":
    server = SpeedTestServer()
    try:
        server.start()
    except KeyboardInterrupt:
        print("[Server] KeyboardInterrupt")
        server.stop_server()
