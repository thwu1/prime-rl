#!/usr/bin/env python3
"""UDP echo server — reflects received data back to sender."""
import socket
import threading
import signal
import sys


def echo_handler(port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('127.0.0.1', port))
    while True:
        try:
            data, addr = sock.recvfrom(4096)
            sock.sendto(data, addr)
        except Exception:
            pass


def main():
    for port in range(9001, 9009):
        t = threading.Thread(target=echo_handler, args=(port,), daemon=True)
        t.start()
    print(f"Echo servers running on ports 9001-9008", flush=True)
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))
    try:
        signal.pause()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
