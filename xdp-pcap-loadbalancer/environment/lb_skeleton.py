#!/usr/bin/env python3
"""XDP-style Load Balancer Packet Processor — Skeleton.

Reads /app/input.pcap + /app/config.json
Must produce /app/output.pcap + /app/stats.json

The pcap I/O helpers below handle the libpcap file format.
You must implement the packet processing logic in process_packets().
"""

import struct
import json


def read_pcap(path):
    """Read a pcap file. Returns list of (ts_sec, ts_usec, data_bytes, orig_len)."""
    with open(path, 'rb') as f:
        f.read(24)  # skip global header
        packets = []
        while True:
            rec = f.read(16)
            if len(rec) < 16:
                break
            ts_sec, ts_usec, incl_len, orig_len = struct.unpack('<IIII', rec)
            data = f.read(incl_len)
            if len(data) < incl_len:
                break
            packets.append((ts_sec, ts_usec, data, orig_len))
    return packets


def write_pcap(path, packets):
    """Write list of (ts_sec, ts_usec, data_bytes, orig_len) to a pcap file."""
    with open(path, 'wb') as f:
        f.write(struct.pack('<IHHiIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1))
        for ts_sec, ts_usec, data, orig_len in packets:
            f.write(struct.pack('<IIII', ts_sec, ts_usec, len(data), orig_len))
            f.write(data)


def process_packets():
    """Implement the complete load balancer here.

    Read /app/input.pcap and /app/config.json.
    Process each packet according to the specification.
    Write /app/output.pcap and /app/stats.json.
    """
    raise NotImplementedError("TODO: implement the load balancer processor")


if __name__ == '__main__':
    process_packets()
