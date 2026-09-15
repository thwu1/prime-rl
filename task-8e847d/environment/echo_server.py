#!/usr/bin/env python3
"""TCP echo backend for load balancer testing.
Responds with JSON containing backend port, PROXY header (if any), and echoed data.
"""
import socket
import sys
import json
import threading


def handle_client(conn, port):
    try:
        data = b''
        while True:
            chunk = conn.recv(8192)
            if not chunk:
                break
            data += chunk

        if not data:
            return

        proxy_header = None
        payload = data

        if data.startswith(b'PROXY '):
            try:
                newline_idx = data.index(b'\r\n')
                proxy_header = data[:newline_idx].decode('utf-8')
                payload = data[newline_idx + 2:]
            except (ValueError, UnicodeDecodeError):
                pass

        response = json.dumps({
            "backend_port": port,
            "proxy_header": proxy_header,
            "data": payload.decode('utf-8', errors='replace')
        })
        conn.sendall(response.encode('utf-8'))
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def main():
    port = int(sys.argv[1])
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('0.0.0.0', port))
    sock.listen(128)

    while True:
        conn, addr = sock.accept()
        t = threading.Thread(target=handle_client, args=(conn, port), daemon=True)
        t.start()


if __name__ == '__main__':
    main()
