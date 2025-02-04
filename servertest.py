import socket
import struct
import time
from threading import Thread

# Color constants for printing
GREEN = "\033[0;32m"
RED = "\033[0;31m"
YELLOW = "\033[1;33m"

# Server configuration
serverIP = '192.168.155.103'   # Replace with your server machine's IP
serverUDPPort = 12000
serverTCPPort = 12345
magic_cookie = 0xabcddcba

def handle_error(message, exception):
    """
    A local error-handling function to log/display an error message
    alongside the exception details (mimicking the original ErrorHandler).
    """
    print(message)
    print(f"Exception details: {exception}")

try:
    # Create and bind UDP socket
    udpSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udpSocket.bind((serverIP, serverUDPPort))
    # Increase the UDP socket's send buffer size
    udpSocket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024 * 1024)

    # Create and bind TCP socket
    tcpSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcpSocket.bind((serverIP, serverTCPPort))
    tcpSocket.listen(5)

    print(f"{GREEN}Server started, listening on IP address {serverIP}{GREEN}")
except Exception as e:
    handle_error(f"{RED}Error initializing server sockets{RED}", e)
    exit(1)

def send_offer():
    """
    Sends periodic offer messages via UDP broadcast.

    Description:
        This function broadcasts a structured offer message over UDP to all
        clients on the network. The offer contains a magic cookie, message type,
        and the server's UDP/TCP port numbers. It runs continuously, sending
        the broadcast every 1 second.
    """
    try:
        offer_message = struct.pack('!IBHH', magic_cookie, 0x2, serverUDPPort, serverTCPPort)
        broadcast_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        broadcast_address = '255.255.255.255'
        while True:
            broadcast_socket.sendto(offer_message, (broadcast_address, serverUDPPort))
            time.sleep(1)
    except Exception as e:
        handle_error(f"{RED}Error in send_offer, couldn't send the offer{RED}", e)

def handle_single_udp_request(message, clientAddress):
    """
    Processes a single UDP request from a client.

    Description:
        Validates the incoming request by checking its size and magic cookie.
        Extracts the requested file size and sends the data back to the client
        in 1KB chunks. Each chunk includes a payload header (magic cookie, type,
        segment count, segment number) followed by the data.
    """
    try:
        # Expected size for '!IBQ' is 13 bytes
        if len(message) != 13:
            return

        header = struct.unpack('!IBQ', message)
        if header[0] != magic_cookie or header[1] != 0x3:
            print(f"\n{YELLOW}Ignoring invalid message from {clientAddress}. "
                  f"Incorrect magic cookie or type.{YELLOW}")
            return

        file_size = header[2]
        print(f"\n{YELLOW}UDP client {clientAddress} requested {file_size} bytes.{YELLOW}")

        # Calculate how many 1KB segments we need
        segment_count = file_size // 1024 + (1 if file_size % 1024 else 0)
        for segment_number in range(segment_count):
            payload_header = struct.pack('!IBQQ', magic_cookie, 0x4, segment_count, segment_number)
            payload_data = b'a' * min(1024, file_size - segment_number * 1024)
            udpSocket.sendto(payload_header + payload_data, clientAddress)

        print(f"\n{GREEN}Completed UDP transfer to {clientAddress}{GREEN}")

    except Exception as e:
        handle_error(f"\n{RED}Error handling UDP request from {clientAddress}{RED}", e)

def handle_udp_requests():
    """
    Continuously listens for incoming UDP messages and spawns a thread
    to handle each request.
    """
    try:
        while True:
            message, clientAddress = udpSocket.recvfrom(2048)
            Thread(target=handle_single_udp_request, args=(message, clientAddress), daemon=True).start()
    except Exception as e:
        handle_error(f"{RED}Error in handle_udp_requests{RED}", e)

def handle_client(client_socket, client_address):
    """
    Handles a single TCP client request.

    Description:
        Receives the requested file size from the client, then sends that
        amount of data back to the client in 1KB chunks. Closes the connection
        once the requested number of bytes has been sent.
    """
    try:
        file_size_request = client_socket.recv(1024).decode('utf-8').strip()
        if not file_size_request:
            print(f"\n{YELLOW}No file size received from {client_address}{YELLOW}")
            client_socket.close()
            return

        file_size = int(file_size_request)
        print(f"\n{YELLOW}TCP client {client_address} requested {file_size} bytes.{YELLOW}")

        bytes_sent = 0
        chunk_size = 1024  # 1KB
        while bytes_sent < file_size:
            remaining = file_size - bytes_sent
            to_send = b'x' * min(chunk_size, remaining)
            client_socket.sendall(to_send)
            bytes_sent += len(to_send)

        print(f"\n{GREEN}Finished sending {bytes_sent} bytes to {client_address}{GREEN}")

    except Exception as e:
        handle_error(f"\n{RED}Error handling TCP request from {client_address}{RED}", e)
    finally:
        client_socket.close()

def handle_tcp_clients():
    """
    Continuously accepts incoming TCP connections and spawns a thread
    to handle each client.
    """
    try:
        while True:
            client_socket, client_address = tcpSocket.accept()
            print(f"\n{GREEN}TCP connection established with {client_address}{GREEN}")
            Thread(target=handle_client, args=(client_socket, client_address), daemon=True).start()
    except Exception as e:
        handle_error(f"{RED}Error in handle_tcp_clients{RED}", e)

# Start the server threads
Thread(target=send_offer, daemon=True).start()
Thread(target=handle_udp_requests, daemon=True).start()
Thread(target=handle_tcp_clients, daemon=True).start()

# Keep main thread running until interrupted
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt as e:
    print(f"\n{RED}Shutting down the server.{RED}")
    handle_error("Error in main", e)
    udpSocket.close()
    tcpSocket.close()
