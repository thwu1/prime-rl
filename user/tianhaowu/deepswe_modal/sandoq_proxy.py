"""Loopback CONNECT proxy for direct Sandoq gateway access from CPU nodes."""

import select
import socket
import socketserver
import threading


class _ConnectServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class _ConnectHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        header = bytearray()
        self.request.settimeout(30)
        while b"\r\n\r\n" not in header:
            chunk = self.request.recv(4096)
            if not chunk:
                return
            header.extend(chunk)
            if len(header) > 64 * 1024:
                raise ValueError("CONNECT request header is too large")

        request_line = bytes(header).split(b"\r\n", 1)[0].decode("ascii")
        method, authority, _version = request_line.split(" ", 2)
        host, separator, raw_port = authority.rpartition(":")
        if method != "CONNECT" or not separator:
            self.request.sendall(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
            return
        host = host.strip("[]").lower()
        port = int(raw_port)
        if port != 443 or not host.endswith(".metafb.cloud"):
            self.request.sendall(b"HTTP/1.1 403 Forbidden\r\n\r\n")
            return

        try:
            upstream = socket.create_connection((host, port), timeout=30)
        except OSError:
            self.request.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            raise
        with upstream:
            self.request.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            sockets = (self.request, upstream)
            while True:
                readable, _, _ = select.select(sockets, (), (), 60)
                if not readable:
                    continue
                for source in readable:
                    data = source.recv(64 * 1024)
                    if not data:
                        return
                    destination = upstream if source is self.request else self.request
                    destination.sendall(data)


class DirectConnectProxy:
    def __init__(self) -> None:
        self._server = _ConnectServer(("127.0.0.1", 0), _ConnectHandler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="sandoq-connect-proxy",
        )

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def __enter__(self) -> "DirectConnectProxy":
        self._thread.start()
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()
