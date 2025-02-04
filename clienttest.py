from socket import *
import struct
import time
import threading
from Error_handler import ErrorHandler

# ------------------------------------------------------------------------------
# Local replacement for the external StatisticsHandler
# ------------------------------------------------------------------------------
class StatisticsHandler:
    """
    A local replacement for the external StatisticsHandler module.
    Stores TCP/UDP results and writes them to a CSV file.
    """
    def __init__(self):
        self.tcp_results = []
        self.udp_results = []

    def add_tcp_result(self, connection_number, file_size, elapsed_time, speed):
        """
        Stores a single TCP result.
        """
        self.tcp_results.append({
            'connection_number': connection_number,
            'file_size': file_size,
            'elapsed_time': elapsed_time,
            'speed': speed
        })

    def add_udp_result(self, connection_number, file_size, elapsed_time, speed, success_rate, lost_packets):
        """
        Stores a single UDP result.
        """
        self.udp_results.append({
            'connection_number': connection_number,
            'file_size': file_size,
            'elapsed_time': elapsed_time,
            'speed': speed,
            'success_rate': success_rate,
            'lost_packets': lost_packets
        })

    def save_statistics_to_csv(self, filename='statistics.csv'):
        """
        Saves both TCP and UDP results to a CSV file.
        """
        import csv
        with open(filename, mode='w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            # Write a header for TCP results
            writer.writerow(["TCP_Connection", "File_Size", "Elapsed_Time_s", "Speed_bps"])
            for result in self.tcp_results:
                writer.writerow([
                    result['connection_number'],
                    result['file_size'],
                    f"{result['elapsed_time']:.6f}",
                    f"{result['speed']:.6f}"
                ])
            # Write a separator line
            writer.writerow([])
            # Write a header for UDP results
            writer.writerow(["UDP_Connection", "File_Size", "Elapsed_Time_s", "Speed_bps", "Success_Rate_%", "Lost_Packets"])
            for result in self.udp_results:
                writer.writerow([
                    result['connection_number'],
                    result['file_size'],
                    f"{result['elapsed_time']:.6f}",
                    f"{result['speed']:.6f}",
                    f"{result['success_rate']:.2f}",
                    result['lost_packets'] if result['lost_packets'] is not None else "N/A"
                ])

# ------------------------------------------------------------------------------
# Error Handler and Colors
# ------------------------------------------------------------------------------
error_handler = ErrorHandler()

GREEN = "\033[0;32m"
RED = "\033[0;31m"
YELLOW = "\033[1;33m"

# ------------------------------------------------------------------------------
# Instantiate the statistics handler
# ------------------------------------------------------------------------------
stats = StatisticsHandler()

# ------------------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------------------
magic_cookie = 0xabcddcba
serverUDPPort = 12000
broadcast_timeout = 10  # Time to listen for broadcast (in seconds)
epsilon = 1e-8  # Small value to prevent division by zero


def is_valid_port(port):
    """
    Check if the given port is within the valid range (1024–65535).

    Args:
        port (int): The port number to validate.

    Returns:
        bool: True if the port is valid, False otherwise.
    """
    return 1024 <= port <= 65535


def receive_broadcast():
    """
    Listen for the server's broadcast message.

    Opens a UDP socket to listen for broadcast messages from the server. If a valid
    broadcast message is received, it extracts the UDP and TCP ports and validates them.

    Returns:
        tuple: A tuple containing the server IP, UDP port, and TCP port if successful.
               Otherwise, returns (None, None, None).
    """
    clientSocket = socket(AF_INET, SOCK_DGRAM)
    clientSocket.setsockopt(SOL_SOCKET, SO_BROADCAST, 1)
    clientSocket.bind(('', serverUDPPort))
    clientSocket.settimeout(broadcast_timeout)
    try:
        message, serverAddress = clientSocket.recvfrom(2048)
        header = struct.unpack('!IBHH', message)
        if header[0] == magic_cookie and header[1] == 0x2:
            udp_port = header[2]
            tcp_port = header[3]

            # Validate the ports
            if not is_valid_port(udp_port) or not is_valid_port(tcp_port):
                error_handler.handle_error(
                    f"\n{RED}Invalid ports received: UDP Port {udp_port}, TCP Port {tcp_port}.{RED}"
                )
            print(f"Offer received from {serverAddress[0]}: UDP Port {udp_port}, TCP Port {tcp_port}")
            return serverAddress[0], udp_port, tcp_port
    except timeout as e:
        error_handler.handle_error(f"\n{RED}No broadcast received within the timeout period.{RED}", e)
    except struct.error as e:
        error_handler.handle_error(f"\n{RED}Error decoding broadcast message.{RED}", e)
    except Exception as e:
        error_handler.handle_error(f"\n{RED}Unexpected error during broadcast reception.{RED}", e)
    finally:
        clientSocket.close()
    return None, None, None


def tcp_transfer(serverIP, tcpPort, file_size, connection_number, num_connections, results):
    """
    Run a single TCP transfer.

    Connects to the server using a TCP socket and requests a specific segment of the file.
    Measures the transfer time and calculates the transfer speed.

    Args:
        serverIP (str): The server's IP address.
        tcpPort (int): The server's TCP port.
        file_size (int): The total file size to be transferred.
        connection_number (int): The identifier for the current connection.
        num_connections (int): The total number of TCP connections.
        results (list): A shared list to store the results of the transfer.
    """
    clientSocket = socket(AF_INET, SOCK_STREAM)
    try:
        clientSocket.connect((serverIP, tcpPort))
        segment_file_size = file_size
        start_time = time.time()

        # Send request
        clientSocket.sendall(str(segment_file_size).encode('utf-8'))

        # Receive data
        received_bytes = 0
        while received_bytes < segment_file_size:
            chunk = clientSocket.recv(1024)
            if not chunk:
                break
            received_bytes += len(chunk)

        # Calculate transfer summary
        end_time = time.time()
        elapsed_time = end_time - start_time
        speed = (segment_file_size * 8) / (elapsed_time + epsilon)  # Speed in bits per second
        results.append((f"TCP transfer #{connection_number}", elapsed_time, speed))

        # Record the result in stats
        stats.add_tcp_result(connection_number, segment_file_size, elapsed_time, speed)

    except ConnectionError as e:
        error_handler.handle_error(f"\n{RED}TCP connection #{connection_number} error.{RED}", e)
    except Exception as e:
        error_handler.handle_error(f"\n{RED}Unexpected error in TCP transfer #{connection_number}.{RED}", e)
    finally:
        clientSocket.close()


def udp_transfer(serverIP, udpPort, file_size, connection_number, num_connections, results):
    """
    Run a single UDP transfer.

    Sends a request to the server over UDP for a specific segment of the file.
    Receives data packets and calculates transfer metrics like speed and packet success rate.

    Args:
        serverIP (str): The server's IP address.
        udpPort (int): The server's UDP port.
        file_size (int): The total file size to be transferred.
        connection_number (int): The identifier for the current connection.
        num_connections (int): The total number of UDP connections.
        results (list): A shared list to store the results of the transfer.
    """
    clientSocket = socket(AF_INET, SOCK_DGRAM)
    clientSocket.settimeout(1)

    try:
        segment_file_size = file_size
        start_time = time.time()

        # Send request
        request_message = struct.pack('!IBQ', magic_cookie, 0x3, segment_file_size)
        clientSocket.sendto(request_message, (serverIP, udpPort))

        # Receive data
        received_segments = 0
        total_segments = None

        while True:
            try:
                packet, _ = clientSocket.recvfrom(2048)
                # Minimum length check (magic cookie, type, segment count, segment number)
                if len(packet) < 21:
                    continue

                header = struct.unpack('!IBQQ', packet[:21])
                if header[0] != magic_cookie or header[1] != 0x4:
                    continue

                total_segments = header[2]
                received_segments += 1

                if received_segments == total_segments:
                    break
            except timeout:
                break

        # Calculate transfer summary
        end_time = time.time()
        elapsed_time = end_time - start_time
        speed = (segment_file_size * 8) / (elapsed_time + epsilon)  # bits per second
        packet_success_rate = (received_segments / total_segments) * 100 if total_segments else 0
        success_rate = (received_segments / total_segments) * 100 if total_segments else 0
        lost_packets = total_segments - received_segments if total_segments else None

        # Record results
        results.append((f"UDP transfer #{connection_number}", elapsed_time, speed, packet_success_rate))
        stats.add_udp_result(connection_number, segment_file_size, elapsed_time, speed, success_rate, lost_packets)

    except Exception as e:
        error_handler.handle_error(f"\n{RED}Error in UDP transfer #{connection_number}.{RED}", e)
    finally:
        clientSocket.close()


def main():
    """
    Main function to coordinate the client workflow.

    Steps:
    1. Receive broadcast from the server to obtain connection details.
    2. Prompt the user for file size and the number of connections.
    3. Perform TCP and UDP transfers using threads.
    4. Display transfer results and save statistics.
    """
    try:
        while True:
            try:
                # Step 1: Receive broadcast
                serverIP, udpPort, tcpPort = receive_broadcast()
                if not serverIP:
                    print(f"{RED}No server found. Exiting.{RED}")
                    continue

                # Step 2: Enter test parameters
                try:
                    file_size = int(input(f"{YELLOW}Enter file size to request (in bytes): {YELLOW}").strip())
                    num_tcp_connections = int(input(f"{YELLOW}Enter number of TCP connections: {YELLOW}").strip())
                    num_udp_connections = int(input(f"{YELLOW}Enter number of UDP connections: {YELLOW}").strip())
                except ValueError as e:
                    error_handler.handle_error(f"\nEntered wrong parameters", e)
                    continue

                # Step 3: Run tests using threads
                threads = []
                results = []

                # Start TCP connections
                for i in range(num_tcp_connections):
                    thread = threading.Thread(
                        target=tcp_transfer,
                        args=(serverIP, tcpPort, file_size, i + 1, num_tcp_connections, results)
                    )
                    threads.append(thread)
                    thread.start()

                # Start UDP connections
                for i in range(num_udp_connections):
                    thread = threading.Thread(
                        target=udp_transfer,
                        args=(serverIP, udpPort, file_size, i + 1, num_udp_connections, results)
                    )
                    threads.append(thread)
                    thread.start()

                # Wait for all threads to complete
                for thread in threads:
                    thread.join()

                # Step 4: Display results
                for result in results:
                    if "TCP" in result[0]:
                        print(f"{YELLOW}{result[0]} finished, total time: "
                              f"{GREEN}{result[1]:.2f}{GREEN} seconds, "
                              f"total speed: {GREEN}{result[2]:.2f}{GREEN} bits/second.{YELLOW}")
                    elif "UDP" in result[0]:
                        print(f"{YELLOW}{result[0]} finished, total time: "
                              f"{GREEN}{result[1]:.2f}{GREEN} seconds, "
                              f"total speed: {GREEN}{result[2]:.2f}{GREEN} bits/second, "
                              f"percentage of packets received successfully: "
                              f"{GREEN}{result[3]:.2f}%{GREEN}.{YELLOW}")

                print(f"{GREEN}All transfers complete, listening to offer requests{GREEN}")
                stats.save_statistics_to_csv()
                print(f"{GREEN}Statistics saved to CSV file.{GREEN}")

            except Exception as e:
                error_handler.handle_error("An unexpected error occurred in the main workflow.", e)

    except KeyboardInterrupt:
        print(f"\n{RED}KeyboardInterrupt detected. Exiting{RED}")
        error_handler.handle_error("Program terminated by user (KeyboardInterrupt).")


if __name__ == "__main__":
    main()
