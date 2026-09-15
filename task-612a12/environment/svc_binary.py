#!/usr/bin/env python3
"""Binary protocol metrics service.

Protocol: 4-byte big-endian length prefix followed by JSON payload.
Sends metrics data immediately upon accepting a TCP connection.
"""

import socket
import struct
import json
import time
import sys
import os


def serve(port, name):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('0.0.0.0', port))
    sock.listen(5)

    while True:
        try:
            conn, addr = sock.accept()
            metrics = {
                "service": name,
                "status": "healthy",
                "uptime_sec": int(time.time()) % 100000,
                "cpu_pct": 12.3,
                "mem_mb": 256,
                "requests": 4817
            }
            payload = json.dumps(metrics).encode('utf-8')
            header = struct.pack('!I', len(payload))
            conn.sendall(header + payload)
            conn.close()
        except Exception:
            pass


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} PORT [NAME]", file=sys.stderr)
        sys.exit(1)
    port = int(sys.argv[1])
    name = sys.argv[2] if len(sys.argv) > 2 else f"svc-{port}"
    serve(port, name)
