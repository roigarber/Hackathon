import socket
import struct
import time
import threading
import sys

# --------------------------------------------------------------------------------------
# Color codes (optional)
# --------------------------------------------------------------------------------------
COL_RESET  = "\033[0m"
COL_BLUE   = "\033[94m"
COL_RED    = "\033[91m"
COL_GREEN  = "\033[92m"
COL_YELLOW = "\033[93m"

# --------------------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------------------
MAGIC_COOKIE    = 0xabcddcba
MSG_OFFER       = 0x2
MSG_REQUEST     = 0x3
MSG_PAYLOAD     = 0x4

UDP_LISTEN_PORT = 15000   # The same port on which server broadcasts offers
BROADCAST_WAIT  = 10      # Seconds to wait for a broadcast
CHUNK_SIZE      = 1024    # 1KB chunk, used in reading TCP data
EPSILON         = 1e-9    # Avoid division by zero

# --------------------------------------------------------------------------------------
# Logging helpers
# --------------------------------------------------------------------------------------

def log_info(msg):
    print(f"{COL_GREEN}[INFO]{COL_RESET} {msg}")

def log_warning(msg):
    print(f"{COL_YELLOW}[WARN]{COL_RESET} {msg}")

def log_error(msg):
    print(f"{COL_RED}[ERROR]{COL_RESET} {msg}")

# --------------------------------------------------------------------------------------
# Broadcast Reception (Client Side)
# --------------------------------------------------------------------------------------

def wait_for_offer(timeout_sec=BROADCAST_WAIT):
    """
    Opens a UDP socket to listen for an 'offer' broadcast from any server.
    Returns (server_ip, server_udp_port, server_tcp_port) if successful, otherwise None.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.bind(("", UDP_LISTEN_PORT))  # Listen on all interfaces for incoming broadcast
        s.settimeout(timeout_sec)

        data, addr = s.recvfrom(1024)  # Blocks until data arrives or times out
        if len(data) < 8:
            return None

        # Packet format: magic_cookie (4 bytes), msg_type (1 byte), udpPort (2 bytes), tcpPort (2 bytes)
        raw_cookie, raw_type, srv_udp, srv_tcp = struct.unpack("!IBHH", data)
        if raw_cookie == MAGIC_COOKIE and raw_type == MSG_OFFER:
            return addr[0], srv_udp, srv_tcp

    except socket.timeout:
        log_warning("No offer received within the timeout period.")
    except Exception as e:
        log_error(f"Error while waiting for offer: {e}")
    finally:
        s.close()
    return None

# --------------------------------------------------------------------------------------
# TCP Transfer
# --------------------------------------------------------------------------------------

def do_tcp_transfer(server_ip, tcp_port, size_bytes, index, result_list):
    """
    Connects to the server on the given TCP port, requests 'size_bytes' data,
    times how long it takes to receive it, and appends (description, time, speed)
    to result_list.
    """
    start_time = time.time()
    received   = 0

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect((server_ip, tcp_port))

        # Send ASCII request: the file size plus newline
        sock.sendall(str(size_bytes).encode() + b"\n")

        while received < size_bytes:
            chunk = sock.recv(CHUNK_SIZE)
            if not chunk:
                break
            received += len(chunk)

        elapsed = time.time() - start_time
        bit_rate = (size_bytes * 8.0) / max(elapsed, EPSILON)
        result_list.append((f"TCP #{index}", elapsed, bit_rate))

    except Exception as e:
        log_error(f"TCP transfer #{index} error: {e}")
    finally:
        sock.close()

# --------------------------------------------------------------------------------------
# UDP Transfer
# --------------------------------------------------------------------------------------

def do_udp_transfer(server_ip, udp_port, size_bytes, index, result_list):
    """
    Sends a UDP request to the server for 'size_bytes' of data, then receives
    payload packets until no more arrive (1-second timeout).
    Appends (description, time, speed, success_pct) to result_list.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(1.0)  # 1-second timeout for receiving data
    start_time = time.time()

    # Pack: magic_cookie (4 bytes), msg_type (1 byte), file_size (8 bytes)
    request_msg = struct.pack("!IBQ", MAGIC_COOKIE, MSG_REQUEST, size_bytes)
    s.sendto(request_msg, (server_ip, udp_port))

    total_segments   = 0
    received_segments = 0

    # Keep reading until we time out or we detect we're done
    while True:
        try:
            data, _ = s.recvfrom(4096)
            if len(data) < 20:
                continue

            # The payload header is: magic_cookie (4 bytes), msg_type (1 byte),
            #                        total_segments (8 bytes), current_segment (8 bytes)
            header = struct.unpack("!IBQQ", data[:21])  # 21 because 4+1+8+8 = 21 bytes
            if header[0] != MAGIC_COOKIE or header[1] != MSG_PAYLOAD:
                continue

            total_segments = header[2]
            seq_number     = header[3]

            received_segments += 1

            # If we've received the last segment, break
            if received_segments == total_segments:
                break

        except socket.timeout:
            # No more packets arrived within timeout
            break
        except Exception as e:
            log_error(f"UDP transfer error #{index}: {e}")
            break

    elapsed      = time.time() - start_time
    bit_rate     = (size_bytes * 8.0) / max(elapsed, EPSILON)
    success_rate = 0.0
    if total_segments > 0:
        success_rate = (received_segments / total_segments) * 100.0

    result_list.append((f"UDP #{index}", elapsed, bit_rate, success_rate))
    s.close()

# --------------------------------------------------------------------------------------
# Main Client Flow
# --------------------------------------------------------------------------------------

def main():
    while True:
        try:
            log_info("Waiting for an offer...")
            srv_info = wait_for_offer()
            if not srv_info:
                log_warning("No server found. Retrying...\n")
                continue

            server_ip, udp_port, tcp_port = srv_info
            log_info(f"Received offer from {server_ip}: UDP={udp_port}, TCP={tcp_port}")

            # Prompt the user for parameters
            try:
                file_size_str = input(f"{COL_BLUE}Enter file size in bytes: {COL_RESET}").strip()
                file_size     = int(file_size_str)

                tcp_count_str = input(f"{COL_BLUE}Enter number of TCP connections: {COL_RESET}").strip()
                tcp_count     = int(tcp_count_str)

                udp_count_str = input(f"{COL_BLUE}Enter number of UDP connections: {COL_RESET}").strip()
                udp_count     = int(udp_count_str)
            except ValueError:
                log_error("Invalid integer input. Please try again.")
                continue

            # Launch threads for transfers
            results = []
            threads = []

            # Start the TCP connections
            for i in range(1, tcp_count + 1):
                t = threading.Thread(
                    target=do_tcp_transfer,
                    args=(server_ip, tcp_port, file_size, i, results),
                    daemon=True
                )
                t.start()
                threads.append(t)

            # Start the UDP connections
            for i in range(1, udp_count + 1):
                t = threading.Thread(
                    target=do_udp_transfer,
                    args=(server_ip, udp_port, file_size, i, results),
                    daemon=True
                )
                t.start()
                threads.append(t)

            # Wait for all threads
            for t in threads:
                t.join()

            # Summarize
            for entry in results:
                if entry[0].startswith("TCP"):
                    _, t_elapsed, t_bitrate = entry
                    print(f"{COL_YELLOW}{entry[0]} finished{COL_RESET}, "
                          f"time: {t_elapsed:.2f}s, speed: {t_bitrate:.2f} bps")
                else:
                    _, u_elapsed, u_bitrate, u_success = entry
                    print(f"{COL_YELLOW}{entry[0]} finished{COL_RESET}, "
                          f"time: {u_elapsed:.2f}s, speed: {u_bitrate:.2f} bps, "
                          f"packets received: {u_success:.1f}%")

            print(f"{COL_GREEN}All transfers complete. Returning to wait for offers...{COL_RESET}\n")

        except KeyboardInterrupt:
            log_warning("Client terminated by user.")
            sys.exit(0)
        except Exception as e:
            log_error(f"Unexpected error in client main loop: {e}")
            # Continue listening or break? Here we just keep going.
            continue

if __name__ == "__main__":
    main()
