import logging
import queue
import socket
import struct
import threading
import time
import math

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ANSI color codes for enhanced output readability
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

# Constants
MAGIC_COOKIE = 0xabcddcba
OFFER_MESSAGE_TYPE = 0x2
REQUEST_MESSAGE_TYPE = 0x3
PAYLOAD_MESSAGE_TYPE = 0x4
OFFER_LISTEN_PORT = 13117
# Increase BUFFER_SIZE to accommodate larger UDP packets.
BUFFER_SIZE = 8192
UDP_TIMEOUT = 1.0
COOLDOWN_PERIOD = 5

# Increase UDP_PAYLOAD_SIZE to match the server (4096 bytes)
UDP_PAYLOAD_SIZE = 4096

print_lock = threading.Lock()

def colored_print(message, color=Colors.ENDC):
    """
    Prints a message with the specified ANSI color.
    """
    with print_lock:
        print(f"{color}{message}{Colors.ENDC}")

def get_user_parameters():
    """
    Gets user parameters.
    Returns a tuple of (file_size, num_tcp, num_udp).
    """
    while True:
        try:
            file_size_input = input("Enter the file size to download (in bytes): ")
            file_size = int(file_size_input)
            if file_size <= 0:
                raise ValueError("File size must be positive.")

            num_tcp_input = input("Enter the number of TCP connections: ")
            num_tcp = int(num_tcp_input)
            if num_tcp < 0:
                raise ValueError("Number of TCP connections cannot be negative.")

            num_udp_input = input("Enter the number of UDP connections: ")
            num_udp = int(num_udp_input)
            if num_udp < 0:
                raise ValueError("Number of UDP connections cannot be negative.")

            return file_size, num_tcp, num_udp
        except ValueError as ve:
            colored_print(f"Invalid input: {ve}. Please try again.", Colors.WARNING)

def perform_tcp_transfer(server_ip, server_tcp_port, file_size, transfer_id):
    """
    Performs a TCP transfer to the specified server.
    Measures transfer time and calculates speed.
    """
    try:
        start_time = time.time()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp_sock:
            tcp_sock.settimeout(10.0)
            tcp_sock.connect((server_ip, server_tcp_port))
            request = f"{file_size}\n".encode()
            tcp_sock.sendall(request)
            bytes_received = 0
            while bytes_received < file_size:
                chunk = tcp_sock.recv(BUFFER_SIZE)
                if not chunk:
                    break
                bytes_received += len(chunk)
        end_time = time.time()
        duration = end_time - start_time
        speed = (bytes_received * 8) / duration  # bits per second
        colored_print(
            f"TCP transfer #{transfer_id} finished, total time: {duration:.2f} seconds, total speed: {speed:.2f} bits/second",
            Colors.OKCYAN)
    except Exception as e:
        colored_print(f"TCP transfer #{transfer_id} failed: {e}", Colors.FAIL)

def perform_udp_transfer(server_ip, server_udp_port, file_size, transfer_id, stats_lock, stats):
    """
    Performs a UDP transfer to the specified server.
    Now the file_size is interpreted as the total number of bytes to receive.
    The client receives packets (each with a 9-byte header plus payload),
    counts the number of packets received, and stops when the total bytes received
    reaches or exceeds the requested file size.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_sock:
            udp_sock.settimeout(UDP_TIMEOUT)
            request_message = struct.pack('!IBQ', MAGIC_COOKIE, REQUEST_MESSAGE_TYPE, file_size)
            start_time = time.time()
            udp_sock.sendto(request_message, (server_ip, server_udp_port))
            total_received_bytes = 0
            packets_received = 0
            # Calculate expected number of packets
            expected_packets = file_size // UDP_PAYLOAD_SIZE
            if file_size % UDP_PAYLOAD_SIZE != 0:
                expected_packets += 1
            last_receive_time = time.time()
            while total_received_bytes < file_size:
                try:
                    data, addr = udp_sock.recvfrom(BUFFER_SIZE)
                    current_time = time.time()
                    if len(data) < 9:
                        continue  # The header is 9 bytes long
                    header = data[:9]
                    payload = data[9:]
                    magic_cookie_recv, message_type_recv, data_size = struct.unpack('!IBI', header)
                    if magic_cookie_recv != MAGIC_COOKIE or message_type_recv != PAYLOAD_MESSAGE_TYPE:
                        continue
                    packets_received += 1
                    total_received_bytes += len(payload)
                    last_receive_time = current_time
                except socket.timeout:
                    if time.time() - last_receive_time >= UDP_TIMEOUT:
                        break
            end_time = time.time()
            duration = end_time - start_time
            speed = (total_received_bytes * 8) / duration  # bits per second
            received_percentage = (packets_received / expected_packets) * 100 if expected_packets > 0 else 0
            colored_print(
                f"UDP transfer #{transfer_id} finished, total time: {duration:.2f} seconds, total speed: {speed:.2f} bits/second, "
                f"percentage of packets received successfully: {received_percentage:.2f}%",
                Colors.OKCYAN)
            with stats_lock:
                stats['udp_total_time'] += duration
                stats['udp_total_speed'] += speed
                stats['udp_total_bytes'] += file_size
                stats['udp_received_bytes'] += total_received_bytes
    except Exception as e:
        colored_print(f"UDP transfer #{transfer_id} failed: {e}", Colors.FAIL)

def start_speed_test(server_info, file_size, num_tcp, num_udp):
    """
    Initiates the speed test by launching TCP and UDP transfers concurrently.
    Waits until all transfers are complete and then prints aggregated UDP statistics.
    """
    server_ip, server_udp_port, server_tcp_port = server_info
    threads = []
    stats = {
        'udp_total_time': 0.0,
        'udp_total_speed': 0.0,
        'udp_total_bytes': 0,
        'udp_received_bytes': 0
    }
    stats_lock = threading.Lock()
    # Start TCP transfers
    for i in range(1, num_tcp + 1):
        tcp_thread = threading.Thread(
            target=perform_tcp_transfer,
            args=(server_ip, server_tcp_port, file_size, i),
            daemon=True
        )
        threads.append(tcp_thread)
        tcp_thread.start()
    # Start UDP transfers
    for i in range(1, num_udp + 1):
        udp_thread = threading.Thread(
            target=perform_udp_transfer,
            args=(server_ip, server_udp_port, file_size, i, stats_lock, stats),
            daemon=True
        )
        threads.append(udp_thread)
        udp_thread.start()
    for thread in threads:
        thread.join()
    if num_udp > 0:
        avg_udp_time = stats['udp_total_time'] / num_udp
        avg_udp_speed = stats['udp_total_speed'] / num_udp
        total_requested = stats['udp_total_bytes']
        total_received = stats['udp_received_bytes']
        loss_percent = ((total_requested - total_received) / total_requested * 100) if total_requested > 0 else 0
        colored_print(f"Average UDP transfer time: {avg_udp_time:.2f} seconds", Colors.OKCYAN)
        colored_print(f"Average UDP transfer speed: {avg_udp_speed:.2f} bits/second", Colors.OKCYAN)
        colored_print(f"Total UDP data loss: {loss_percent:.2f}%", Colors.OKCYAN)

def listen_for_offers(stop_event, offer_queue):
    """
    Listens for UDP offer messages from servers.
    """
    colored_print("Client started, listening for offer requests...", Colors.OKBLUE)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_sock:
        udp_sock.bind(('', OFFER_LISTEN_PORT))
        udp_sock.settimeout(1.0)
        while not stop_event.is_set():
            try:
                offer_message, server_address = udp_sock.recvfrom(BUFFER_SIZE)
                magic_cookie, message_type, server_udp_port, server_tcp_port = struct.unpack('!IBHH', offer_message)
                if magic_cookie == MAGIC_COOKIE and message_type == OFFER_MESSAGE_TYPE:
                    server_info = (server_address[0], server_udp_port, server_tcp_port)
                    offer_queue.put(server_info)
            except socket.timeout:
                continue
            except Exception as e:
                colored_print(f"Error in offer listener: {e}", Colors.FAIL)

def main():
    """
    Main function for the client:
    1. Starts the offer listener.
    2. Loops forever:
       a. Asks the user to enter the file size (and connection counts).
       b. Waits for an offer from a server.
       c. Launches the speed test.
       d. Prints “All transfers complete, listening to offer requests”
          and then returns to (a).
    """
    stop_event = threading.Event()
    offer_queue = queue.Queue()
    offer_listener_thread = threading.Thread(
        target=listen_for_offers,
        args=(stop_event, offer_queue),
        daemon=True
    )
    offer_listener_thread.start()
    while True:
        file_size, num_tcp, num_udp = get_user_parameters()
        colored_print("Waiting for an offer...", Colors.OKBLUE)
        server_info = offer_queue.get()  # Blocking call until an offer arrives
        # Clear any extra pending offers
        while not offer_queue.empty():
            try:
                offer_queue.get_nowait()
            except queue.Empty:
                break
        start_speed_test(server_info, file_size, num_tcp, num_udp)
        colored_print("All transfers complete, listening to offer requests", Colors.OKBLUE)
        # Loop back to ask for user parameters again.

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        colored_print("Shutting down...", Colors.WARNING)
