"""
Connection manager for a reverse proxy service.

Manages outgoing TCP and UDP connections to backend servers.
Supports binding to specific source addresses for traffic separation
(e.g., CDN traffic vs. WARP traffic use different source IPs so that
origin servers can distinguish traffic types by source address).

Usage:
    mgr = ConnectionManager()
    sock = mgr.create_tcp_connection('10.0.0.1', 80, src_ip='192.168.1.1')
    sock = mgr.create_tcp_connection('10.0.0.2', 80, src_ip='192.168.1.1', src_port=12345)
    sock = mgr.create_udp_connection('10.0.0.1', 443, src_ip='192.168.1.1')
"""

import socket
import threading

# Socket option to defer source port allocation until connect() time.
# Available since Linux 4.2. May not be defined in Python's socket module.
IP_BIND_ADDRESS_NO_PORT = 24


class ConnectionManager:
    """
    Manages outgoing connections with optional source address binding.

    Source address binding (bind-before-connect) is used for traffic separation:
    different services use different source IPs so that destination servers
    can distinguish traffic types by source address.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._tcp_connections = []
        self._udp_connections = []

    def create_tcp_connection(self, dst_ip, dst_port, src_ip=None, src_port=0):
        """
        Create an outgoing TCP connection.

        Args:
            dst_ip: Destination IP address
            dst_port: Destination port
            src_ip: Optional source IP for traffic separation
            src_port: Optional explicit source port (0 = auto-assign)

        Returns:
            Connected socket
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)

        if src_ip is not None:
            if src_port != 0:
                sock.bind((src_ip, src_port))
            else:
                sock.bind((src_ip, 0))

        sock.connect((dst_ip, dst_port))

        with self._lock:
            self._tcp_connections.append(sock)
        return sock

    def create_udp_connection(self, dst_ip, dst_port, src_ip=None, src_port=0):
        """
        Create an outgoing UDP "connection" (connected UDP socket).

        Args:
            dst_ip: Destination IP address
            dst_port: Destination port
            src_ip: Optional source IP for traffic separation
            src_port: Optional explicit source port (0 = auto-assign)

        Returns:
            Connected UDP socket
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(5)

        if src_ip is not None:
            if src_port != 0:
                sock.bind((src_ip, src_port))
            else:
                sock.bind((src_ip, 0))

        sock.connect((dst_ip, dst_port))

        with self._lock:
            self._udp_connections.append(sock)
        return sock

    def close_all(self):
        """Close all managed connections."""
        with self._lock:
            for sock in self._tcp_connections + self._udp_connections:
                try:
                    sock.close()
                except Exception:
                    pass
            self._tcp_connections.clear()
            self._udp_connections.clear()
