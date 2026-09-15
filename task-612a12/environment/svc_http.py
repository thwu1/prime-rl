#!/usr/bin/env python3
"""HTTP health-check endpoint.

This service responds to any TCP connection with an HTTP response.
It was deployed on port 9003 as part of a health-check migration,
replacing the binary protocol metrics service (svc-gamma) that
previously occupied this port.
"""

import socket
import sys


def serve(port=9003):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('0.0.0.0', port))
    sock.listen(5)

    while True:
        try:
            conn, addr = sock.accept()
            response = (
                "HTTP/1.0 200 OK\r\n"
                "Content-Type: application/json\r\n"
                "Connection: close\r\n"
                "\r\n"
                '{"status":"healthy","version":"2.1.0"}\n'
            )
            conn.sendall(response.encode('utf-8'))
            conn.close()
        except Exception:
            pass


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9003
    serve(port)
