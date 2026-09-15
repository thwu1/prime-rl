#!/usr/bin/env python3
"""
UDP connectx — source port reuse across destinations.

Overcomes Linux's default UDP behavior where connect() allocates exclusive
source ports via bind(), limiting total connections to the ephemeral port
range size. Uses SO_REUSEADDR to allow port sharing, with /proc/net/udp
inspection for cross-process 4-tuple conflict detection and SO_REUSEADDR
toggling as a cooperative lock.

"""
import json
import os
import random
import socket
import struct
import threading
import time

PORT_LO, PORT_HI = 50000, 50063
SRC_IP = '127.0.0.1'
DESTINATIONS = [('127.0.0.1', 9001 + i) for i in range(8)]
TARGET = 400


# ---------------------------------------------------------------------------
# Echo servers (for self-contained execution)
# ---------------------------------------------------------------------------

def _echo_loop(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('127.0.0.1', port))
    while True:
        try:
            data, addr = s.recvfrom(4096)
            s.sendto(data, addr)
        except Exception:
            pass


def start_echo_servers():
    for _, port in DESTINATIONS:
        t = threading.Thread(target=_echo_loop, args=(port,), daemon=True)
        t.start()
    time.sleep(0.3)


# ---------------------------------------------------------------------------
# Kernel socket state inspection via /proc/net/udp
# ---------------------------------------------------------------------------

def _hex_to_ip(hex_str):
    """Convert /proc/net/udp hex IP (native byte order) to dotted decimal."""
    return socket.inet_ntoa(struct.pack('=I', int(hex_str, 16)))


def get_kernel_udp_tuples():
    """Return set of (local_ip, local_port, remote_ip, remote_port) for all
    connected UDP sockets visible in /proc/net/udp."""
    tuples = set()
    with open('/proc/net/udp') as f:
        for line in f:
            fields = line.strip().split()
            if not fields or fields[0] == 'sl':
                continue
            local_hex, local_port_hex = fields[1].split(':')
            remote_hex, remote_port_hex = fields[2].split(':')

            remote_port = int(remote_port_hex, 16)
            if remote_port == 0:
                continue  # unconnected socket — skip

            local_ip = _hex_to_ip(local_hex)
            local_port = int(local_port_hex, 16)
            remote_ip = _hex_to_ip(remote_hex)

            tuples.add((local_ip, local_port, remote_ip, remote_port))
    return tuples


# ---------------------------------------------------------------------------
# Connection manager
# ---------------------------------------------------------------------------

_used_tuples = set()


def connect_udp(src_ip, src_port, dst_ip, dst_port):
    """Create a connected UDP socket with source port reuse.

    Uses SO_REUSEADDR to share the source port across different destinations.
    Detects 4-tuple conflicts both in-process (fast path) and via kernel
    state in /proc/net/udp (cross-process safety).  The SO_REUSEADDR flag
    is toggled off between bind() and connect() as a cooperative lock.

    Returns a connected socket.socket.
    Raises OSError on conflict or bind failure.
    """
    ft = (src_ip, src_port, dst_ip, dst_port)

    # Fast path: in-process registry
    if ft in _used_tuples:
        raise OSError(f"4-tuple already allocated in-process: {ft}")

    sd = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Phase 1: bind with SO_REUSEADDR — allows sharing a port already
        # in use by another socket
        sd.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sd.bind((src_ip, src_port))

        # Phase 2: cooperative lock — clear SO_REUSEADDR to prevent
        # concurrent bind() to this port during our conflict check
        sd.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)

        # Phase 3: kernel-level conflict check — look for an existing
        # connected UDP socket with the same 4-tuple (from any process)
        kernel_tuples = get_kernel_udp_tuples()
        if ft in kernel_tuples:
            raise OSError(f"4-tuple in use by another socket: {ft}")

        # Phase 4: form the connection
        sd.connect((dst_ip, dst_port))

        # Phase 5: re-enable SO_REUSEADDR so future sockets can share
        # this source port for different destinations
        sd.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        _used_tuples.add(ft)
        return sd
    except Exception:
        sd.close()
        raise


def find_available_port(dst_ip, dst_port, port_lo=PORT_LO, port_hi=PORT_HI):
    """Find a source port not conflicting with any existing 4-tuple."""
    candidates = list(range(port_lo, port_hi + 1))
    random.shuffle(candidates)
    for port in candidates:
        if (SRC_IP, port, dst_ip, dst_port) not in _used_tuples:
            return port
    raise OSError(f"All {port_hi - port_lo + 1} ports exhausted for "
                  f"{dst_ip}:{dst_port}")


# ---------------------------------------------------------------------------
# Main — create connections, verify, write output
# ---------------------------------------------------------------------------

def main():
    start_echo_servers()

    sockets = []
    for i in range(TARGET):
        dst_ip, dst_port = DESTINATIONS[i % len(DESTINATIONS)]
        src_port = find_available_port(dst_ip, dst_port)
        sd = connect_udp(SRC_IP, src_port, dst_ip, dst_port)
        sockets.append((sd, (SRC_IP, src_port, dst_ip, dst_port)))

    # Uniqueness verification
    tuples = [ft for _, ft in sockets]
    unique = len(set(tuples))
    dupes = len(tuples) - unique

    # Round-trip data test on every connection
    ok = 0
    for sd, ft in sockets:
        token = os.urandom(8).hex()
        try:
            sd.settimeout(2.0)
            sd.send(token.encode())
            resp = sd.recv(256)
            if resp == token.encode():
                ok += 1
        except Exception:
            pass

    results = {
        'total_connections': len(sockets),
        'unique_tuples': unique,
        'duplicates': dupes,
        'port_range_size': PORT_HI - PORT_LO + 1,
        'round_trip_successes': ok,
        'round_trip_tested': len(sockets),
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    with open('/app/connections.txt', 'w') as f:
        for _, (si, sp, di, dp) in sockets:
            f.write(f"{si}:{sp} {di}:{dp}\n")

    print(json.dumps(results, indent=2))

    for sd, _ in sockets:
        sd.close()


if __name__ == '__main__':
    main()
