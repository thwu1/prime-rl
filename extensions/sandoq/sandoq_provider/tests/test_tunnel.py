from __future__ import annotations

import base64
import hashlib
import queue
import socket
import struct
import threading

import pytest
from sandoq_provider.tunnel import SandoqRelayTunnel, _websocket_url

_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_MARKER = b"reverse-tunnel-test-ok"


def _read_exact(sock: socket.socket, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionError("socket closed")
        data += chunk
    return data


def _read_client_frame(sock: socket.socket) -> tuple[int, bytes]:
    first, second = struct.unpack("!BB", _read_exact(sock, 2))
    size = second & 0x7F
    if size == 126:
        size = struct.unpack("!H", _read_exact(sock, 2))[0]
    elif size == 127:
        size = struct.unpack("!Q", _read_exact(sock, 8))[0]
    assert second & 0x80, "RFC6455 clients must mask frames"
    mask = _read_exact(sock, 4)
    payload = _read_exact(sock, size)
    return first & 0x0F, bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))


def _serve_websocket(listener: socket.socket, result: queue.Queue[object]) -> None:
    try:
        connection, _ = listener.accept()
        with connection:
            connection.settimeout(5)
            request = b""
            while b"\r\n\r\n" not in request:
                request += connection.recv(4096)
            headers = {}
            for line in request.split(b"\r\n")[1:]:
                name, separator, value = line.partition(b":")
                if separator:
                    headers[name.decode().strip().lower()] = value.decode().strip()
            accept = base64.b64encode(hashlib.sha1(f"{headers['sec-websocket-key']}{_GUID}".encode()).digest()).decode()
            connection.sendall(
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n\r\n".encode()
            )
            guest_request = b"GET /probe HTTP/1.1\r\nHost: guest\r\n\r\n"
            connection.sendall(bytes((0x82, len(guest_request))) + guest_request)
            payload = b""
            while _MARKER not in payload:
                opcode, chunk = _read_client_frame(connection)
                if opcode == 0x8:
                    raise ConnectionError("client closed before forwarding the response")
                if opcode == 0x2:
                    payload += chunk
            result.put(payload)
            while connection.recv(4096):
                pass
    except BaseException as error:  # pass server-thread failures back to the test
        result.put(error)
    finally:
        listener.close()


def _serve_http(listener: socket.socket, result: queue.Queue[object]) -> None:
    try:
        connection, _ = listener.accept()
        with connection:
            connection.settimeout(5)
            request = b""
            while b"\r\n\r\n" not in request:
                request += connection.recv(4096)
            assert request.startswith(b"GET /probe HTTP/1.1")
            connection.sendall(
                b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(_MARKER)).encode() + b"\r\n\r\n" + _MARKER
            )
            while connection.recv(4096):
                pass
        result.put(None)
    except BaseException as error:
        result.put(error)
    finally:
        listener.close()


def test_relay_forwards_a_guest_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("SANDOQ_TUNNEL_HTTPS_PROXY", "https_proxy", "HTTPS_PROXY"):
        monkeypatch.delenv(name, raising=False)
    gateway = socket.socket()
    gateway.bind(("127.0.0.1", 0))
    gateway.listen(1)
    local = socket.socket()
    local.bind(("127.0.0.1", 0))
    local.listen(1)
    gateway_result: queue.Queue[object] = queue.Queue()
    local_result: queue.Queue[object] = queue.Queue()
    gateway_thread = threading.Thread(target=_serve_websocket, args=(gateway, gateway_result), daemon=True)
    local_thread = threading.Thread(target=_serve_http, args=(local, local_result), daemon=True)
    gateway_thread.start()
    local_thread.start()

    gateway_host, gateway_port = gateway.getsockname()
    tunnel = SandoqRelayTunnel(
        local.getsockname()[1],
        tunnel_url=f"ws://{gateway_host}:{gateway_port}/tunnel?session=test",
        pool_size=1,
    )
    tunnel.start()
    response = gateway_result.get(timeout=5)
    if isinstance(response, BaseException):
        raise response
    assert _MARKER in response
    tunnel.stop()

    gateway_thread.join(timeout=5)
    local_thread.join(timeout=5)
    local_outcome = local_result.get(timeout=5)
    if isinstance(local_outcome, BaseException):
        raise local_outcome
    served, errors = tunnel.stats()
    assert served == 1
    assert errors == []


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("https://example.test/tunnel?id=1", "wss://example.test/tunnel?id=1"),
        ("http://example.test", "ws://example.test/"),
        ("wss://example.test/path", "wss://example.test/path"),
    ],
)
def test_websocket_url(source: str, expected: str) -> None:
    assert _websocket_url(source) == expected


def test_relay_tunnel_validates_pool_and_port() -> None:
    with pytest.raises(ValueError, match="invalid local port"):
        SandoqRelayTunnel(0, tunnel_url="wss://example.test/tunnel")
    with pytest.raises(ValueError, match="pool size"):
        SandoqRelayTunnel(8000, tunnel_url="wss://example.test/tunnel", pool_size=0)
