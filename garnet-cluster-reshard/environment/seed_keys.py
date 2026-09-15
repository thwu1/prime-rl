#!/usr/bin/env python3
"""Seed 500 keys into a 3-node Garnet cluster using raw RESP over sockets."""
import socket
import sys
import time


def crc16(data):
    """CRC16-CCITT used by Redis/Garnet for hash slot calculation."""
    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    return crc


def key_slot(key):
    """Calculate the hash slot for a given key (handles hash tags)."""
    s = key.find('{')
    if s != -1:
        e = key.find('}', s + 1)
        if e != -1 and e != s + 1:
            key = key[s + 1:e]
    return crc16(key.encode()) % 16384


def resp_encode(*args):
    """Encode arguments as a RESP array command."""
    parts = [f"*{len(args)}\r\n".encode()]
    for a in args:
        b = a.encode() if isinstance(a, str) else a
        parts.append(f"${len(b)}\r\n".encode() + b + b"\r\n")
    return b"".join(parts)


def recv_line(sock):
    """Read a single RESP line from socket."""
    buf = b""
    while not buf.endswith(b"\r\n"):
        chunk = sock.recv(1)
        if not chunk:
            break
        buf += chunk
    return buf.decode().strip()


def main():
    slot_to_port = {}
    for s in range(0, 5461):
        slot_to_port[s] = 7000
    for s in range(5461, 10923):
        slot_to_port[s] = 7001
    for s in range(10923, 16384):
        slot_to_port[s] = 7002

    socks = {}
    for port in [7000, 7001, 7002]:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(10)
        s.connect(("127.0.0.1", port))
        socks[port] = s

    loaded = 0
    for i in range(500):
        key = f"key:{i:04d}"
        val = f"val:{i:04d}"
        slot = key_slot(key)
        port = slot_to_port[slot]
        sock = socks[port]
        sock.sendall(resp_encode("SET", key, val))
        resp = recv_line(sock)
        if "OK" in resp:
            loaded += 1
        else:
            print(f"WARN: SET {key} on port {port} returned: {resp}", file=sys.stderr)

    for s in socks.values():
        s.close()

    print(f"Loaded {loaded}/500 keys into cluster")
    return 0 if loaded == 500 else 1


if __name__ == "__main__":
    sys.exit(main())
