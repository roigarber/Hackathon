import socket
import struct
import threading
import time
import sys

# --------------------------------------------------------------------------------------
# Color codes (you can remove or modify these if you like)
# --------------------------------------------------------------------------------------
COL_RESET   = "\033[0m"
COL_GREEN   = "\033[92m"
COL_RED     = "\033[91m"
COL_YELLOW  = "\033[93m"

# --------------------------------------------------------------------------------------
# Constants & Global Settings
# --------------------------------------------------------------------------------------
MAGIC_COOKIE    = 0xabcddcba
MSG_OFFER       = 0x2   # Offer message type
MSG_REQUEST     = 0x3   # Request message type
MSG_PAYLOAD     = 0x4   # Payload message type

SERVER_HOST     = "0.0.0.0"  # Listen on all interfaces
SERVER_UDP_PORT = 20001
SERVER_TCP_PORT = 20002
      # Chosen TCP port

BROADCAST_DELAY = 1.0        # Seconds between sending UDP offers
CHUNK_SIZE      = 1024       # Send data in 1KB chunks for both TCP and UDP
BIND_BACKLOG    = 5          # TCP listen backlog

# --------------------------------------------------------------------------------------
# Helper / Logging
# --------------------------------------------------------------------------------------

def log_info(message):
    """Print normal info messages."""
    print(f"{COL_GREEN}[INFO]{COL_RESET} {message}")

def log_warn(message):
    """Print warning messages."""
    print(f"{COL_YELLOW}[WARN]{COL_RESET} {message}")

def log_error(message):
    """Print error messages."""
    print(f"{COL_RED}[ERROR]{COL_RESET} {message}")

# --------------------------------------------------------------------------------------
# Broadcasting “Offer” Over UDP
# --------------------------------------------------------------------------------------

def broadcast_offers():
    """
    Periodically broadcast an offer message to all clients.
    The packet format:
        magic_cookie (4 bytes)
        msg_type (1 byte) = 0x2
        server_udp_port (2 bytes)
        server_tcp_port (2 bytes)
    """
    try:
        # Pack the broadcast payload once:
        offer_data = struct.pack("!IBHH", MAGIC_COOKIE, MSG_OFFER, SERVER_UDP_PORT, SERVER_TCP_PORT)

        # Create a UDP socket for broadcasting
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as bc_sock:
            bc_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            while True:
                # Broadcast to <broadcast> on the chosen UDP port
                bc_sock.sendto(offer_data, ("<broadcast>", SERVER_UDP_PORT))
                time.sleep(BROADCAST_DELAY)
    except Exception as exc:
        log_error(f"Failed to broadcast offers: {exc}")

# --------------------------------------------------------------------------------------
# Handling UDP Requests
# --------------------------------------------------------------------------------------

def handle_single_udp_request(data, client_addr, udp_sock):
    """
    Handle a single UDP request packet:
      - Validate the request (must have magic cookie and the right msg type).
      - Extract the requested file size.
      - Send back the appropriate data, segmented into chunks, each chunk preceded
        by a payload header.
    """
    try:
        # We expect: magic_cookie (4 bytes), msg_type (1 byte), file_size (8 bytes)
        if len(data) != 13:
            log_warn(f"Received UDP packet with invalid size {len(data)} from {client_addr}.")
            return

        unpacked = struct.unpack("!IBQ", data)
        if unpacked[0] != MAGIC_COOKIE or unpacked[1] != MSG_REQUEST:
            log_warn(f"Ignoring invalid UDP request from {client_addr}. (Bad cookie/type)")
            return

        requested_size = unpacked[2]
        log_info(f"UDP request from {client_addr}: {requested_size} bytes")

        # Calculate how many CHUNK_SIZE segments
        total_segs = (requested_size // CHUNK_SIZE) + (1 if requested_size % CHUNK_SIZE != 0 else 0)

        for seq_num in range(total_segs):
            seg_payload_len = min(CHUNK_SIZE, requested_size - seq_num * CHUNK_SIZE)
            # Build the payload header
            payload_hdr = struct.pack("!IBQQ", MAGIC_COOKIE, MSG_PAYLOAD, total_segs, seq_num)
            payload_data = b"x" * seg_payload_len  # The actual bytes

            udp_sock.sendto(payload_hdr + payload_data, client_addr)

        log_info(f"Finished UDP send to {client_addr}")

    except Exception as exc:
        log_error(f"Error handling UDP request from {client_addr}: {exc}")

def udp_server_loop(udp_sock):
    """
    Continuously listen for incoming UDP packets (requests).
    Spawn a new thread to handle each request so multiple clients can be served in parallel.
    """
    while True:
        try:
            msg_bytes, address = udp_sock.recvfrom(2048)
            thread = threading.Thread(
                target=handle_single_udp_request,
                args=(msg_bytes, address, udp_sock),
                daemon=True
            )
            thread.start()
        except Exception as exc:
            log_error(f"Error in UDP server loop: {exc}")
            break

# --------------------------------------------------------------------------------------
# Handling TCP Requests
# --------------------------------------------------------------------------------------

def handle_single_tcp_connection(tcp_conn, client_addr):
    """
    Deal with one TCP client:
      - Read the requested file size (ASCII string).
      - Send that many bytes back to the client in CHUNK_SIZE chunks.
    """
    try:
        request_data = tcp_conn.recv(1024).decode().strip()
        if not request_data:
            log_warn(f"No file size from {client_addr}. Closing.")
            tcp_conn.close()
            return

        requested_size = int(request_data)
        log_info(f"TCP request from {client_addr}: {requested_size} bytes")

        bytes_sent = 0
        while bytes_sent < requested_size:
            to_send = min(CHUNK_SIZE, requested_size - bytes_sent)
            tcp_conn.sendall(b"y" * to_send)
            bytes_sent += to_send

        log_info(f"Finished TCP send of {bytes_sent} bytes to {client_addr}")

    except Exception as exc:
        log_error(f"TCP connection error with {client_addr}: {exc}")

    finally:
        tcp_conn.close()

def tcp_server_loop(tcp_sock):
    """
    Continuously accept TCP connections and spawn a thread to handle each one.
    """
    while True:
        try:
            conn, addr = tcp_sock.accept()
            log_info(f"New TCP connection from {addr}")
            thread = threading.Thread(target=handle_single_tcp_connection, args=(conn, addr), daemon=True)
            thread.start()
        except Exception as exc:
            log_error(f"Error in TCP accept loop: {exc}")
            break

# --------------------------------------------------------------------------------------
# Main Server Flow
# --------------------------------------------------------------------------------------

def main():
    # 1. Create and bind a UDP socket
    try:
        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_socket.bind((SERVER_HOST, SERVER_UDP_PORT))
        log_info(f"Server listening on UDP {SERVER_HOST}:{SERVER_UDP_PORT}")
    except Exception as e:
        log_error(f"Failed binding UDP socket: {e}")
        sys.exit(1)

    # 2. Create and bind a TCP socket
    try:
        tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_socket.bind((SERVER_HOST, SERVER_TCP_PORT))
        tcp_socket.listen(BIND_BACKLOG)
        log_info(f"Server listening on TCP {SERVER_HOST}:{SERVER_TCP_PORT}")
    except Exception as e:
        log_error(f"Failed binding TCP socket: {e}")
        udp_socket.close()
        sys.exit(1)

    # 3. Start a thread to broadcast offers
    offer_thread = threading.Thread(target=broadcast_offers, daemon=True)
    offer_thread.start()

    # 4. Start a thread to handle UDP requests
    udp_thread = threading.Thread(target=udp_server_loop, args=(udp_socket,), daemon=True)
    udp_thread.start()

    # 5. Start a thread to handle TCP connections
    tcp_thread = threading.Thread(target=tcp_server_loop, args=(tcp_socket,), daemon=True)
    tcp_thread.start()

    # 6. Keep the main thread alive until Ctrl+C
    log_info("Server is up and running. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log_warn("Shutting down server by user request.")
    finally:
        udp_socket.close()
        tcp_socket.close()
        log_warn("All sockets closed. Server terminated.")

if __name__ == "__main__":
    main()
