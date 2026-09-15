#!/usr/bin/env python3
"""
Backend echo server - listens on a given port, accepts connections,
echoes back a confirmation message, and keeps connections alive.
"""
import socket
import sys
import threading
import signal

def handle_client(conn, addr, server_id):
    try:
        conn.sendall(f"HELLO from backend {server_id}\n".encode())
        while True:
            data = conn.recv(1024)
            if not data:
                break
            conn.sendall(data)
    except (ConnectionResetError, BrokenPipeError):
        pass
    finally:
        conn.close()

def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <bind_ip> <port>")
        sys.exit(1)

    bind_ip = sys.argv[1]
    port = int(sys.argv[2])
    server_id = f"{bind_ip}:{port}"

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((bind_ip, port))
    srv.listen(512)
    srv.settimeout(1.0)

    running = True
    def stop(sig, frame):
        nonlocal running
        running = False
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    print(f"Backend {server_id} listening", flush=True)
    while running:
        try:
            conn, addr = srv.accept()
            t = threading.Thread(target=handle_client, args=(conn, addr, server_id), daemon=True)
            t.start()
        except socket.timeout:
            continue
    srv.close()

if __name__ == "__main__":
    main()
