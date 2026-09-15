"""
Connection manager for multi-service proxy.

Handles outgoing TCP and UDP connections with source address binding
for traffic separation between services (CDN, WARP, DNS, gaming, etc.).

TCP connections correctly handle all three binding modes:
  - No source binding (vanilla connect)
  - Source IP only (IP_BIND_ADDRESS_NO_PORT)
  - Full source IP + port (SO_REUSEADDR)

UDP connections use SO_REUSEADDR for source port sharing but currently
lack protection against 4-tuple collisions.
"""

import socket
import threading

# Socket option to defer source port allocation until connect() time.
# Available since Linux 4.2.
IP_BIND_ADDRESS_NO_PORT = 24


class ConnectionConflictError(OSError):
    """Raised when a new connection would conflict with an existing one."""
    pass


class ConnectionManager:
    """Manages outgoing connections with optional source address binding."""

    def __init__(self):
        self._lock = threading.Lock()
        self._connections = []

    def create_tcp_connection(self, dst_ip, dst_port, src_ip=None, src_port=0):
        """Create an outgoing TCP connection.

        Correctly handles all three binding modes using appropriate
        socket options (IP_BIND_ADDRESS_NO_PORT for auto-port,
        SO_REUSEADDR for explicit port).
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)

        if src_ip is not None:
            if src_port != 0:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind((src_ip, src_port))
            else:
                sock.setsockopt(socket.IPPROTO_IP, IP_BIND_ADDRESS_NO_PORT, 1)
                sock.bind((src_ip, 0))

        sock.connect((dst_ip, dst_port))

        with self._lock:
            self._connections.append(sock)
        return sock

    def create_udp_connection(self, dst_ip, dst_port, src_ip=None, src_port=0):
        """Create an outgoing UDP connection.

        Uses SO_REUSEADDR for source port sharing across destinations.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(5)

        if src_ip is not None:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if src_port != 0:
                sock.bind((src_ip, src_port))
            else:
                sock.bind((src_ip, 0))

        sock.connect((dst_ip, dst_port))

        with self._lock:
            self._connections.append(sock)
        return sock

    def close_connection(self, sock):
        """Close and untrack a connection."""
        with self._lock:
            self._connections = [s for s in self._connections if s is not sock]
        try:
            sock.close()
        except Exception:
            pass

    def close_all(self):
        """Close all managed connections."""
        with self._lock:
            for sock in self._connections:
                try:
                    sock.close()
                except Exception:
                    pass
            self._connections.clear()
