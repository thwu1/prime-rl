#!/usr/bin/env python3
"""Generate DICOM PDU capture files for analysis testing.

Run this script to create binary capture files at /app/captures/.
These files contain concatenated DICOM Upper Layer PDUs in raw,
timestamped, and PCAP framing formats.
"""

import struct
import os


# ---------------------------------------------------------------------------
# PCAP construction helpers (importable by test suite)
# ---------------------------------------------------------------------------

def _cksum(data):
    """Ones-complement checksum for IP/TCP headers."""
    if len(data) % 2:
        data += b'\x00'
    s = 0
    for i in range(0, len(data), 2):
        s += (data[i] << 8) | data[i + 1]
    while s >> 16:
        s = (s & 0xffff) + (s >> 16)
    return ~s & 0xffff


def _make_tcp_pkt(src_mac, dst_mac, src_ip, dst_ip, src_port, dst_port,
                  seq, ack, flags, payload, ts_sec, ts_usec):
    """Build one PCAP record: pcap_rec_hdr + Ethernet + IPv4 + TCP + payload."""
    fl = 0
    for f in flags:
        fl |= {'S': 0x02, 'A': 0x10, 'F': 0x01, 'P': 0x08}[f]
    tcp = struct.pack('>HHIIBBHHH',
                      src_port, dst_port, seq, ack, 0x50, fl, 65535, 0, 0)
    pseudo = struct.pack('>4s4sBBH', src_ip, dst_ip, 0, 6,
                         len(tcp) + len(payload))
    cs = _cksum(pseudo + tcp + payload)
    tcp = tcp[:16] + struct.pack('>H', cs) + tcp[18:]

    ip_len = 20 + len(tcp) + len(payload)
    ip_hdr = struct.pack('>BBHHHBBH4s4s',
                         0x45, 0, ip_len, 0, 0x4000, 64, 6, 0, src_ip, dst_ip)
    ics = _cksum(ip_hdr)
    ip_hdr = ip_hdr[:10] + struct.pack('>H', ics) + ip_hdr[12:]

    eth = dst_mac + src_mac + b'\x08\x00'
    pkt = eth + ip_hdr + tcp + payload
    return struct.pack('<IIII', ts_sec, ts_usec, len(pkt), len(pkt)) + pkt


def build_dicom_pcap(exchange, split_first=False):
    """Build a PCAP file from a DICOM PDU exchange.

    Args:
        exchange: list of ('c2s'|'s2c', pdu_bytes) tuples describing the
                  ordered PDU exchange between client and server.
        split_first: if True, split the first client-to-server PDU across
                     two TCP segments (at the midpoint) to require TCP
                     stream reassembly.
    Returns:
        Complete PCAP file contents as bytes.
    """
    CMAC = b'\x00\x11\x22\x33\x44\x55'
    SMAC = b'\x00\xaa\xbb\xcc\xdd\xee'
    CIP = struct.pack('>4B', 10, 0, 0, 1)
    SIP = struct.pack('>4B', 10, 0, 0, 2)
    CP, SP = 45678, 11112

    hdr = struct.pack('<IHHiIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1)
    cs, ss = 1000, 2000
    ts, tu = 1700000000, 0

    def c2s(seq, ack_num, fl, data):
        return _make_tcp_pkt(CMAC, SMAC, CIP, SIP, CP, SP,
                             seq, ack_num, fl, data, ts, tu)

    def s2c(seq, ack_num, fl, data):
        return _make_tcp_pkt(SMAC, CMAC, SIP, CIP, SP, CP,
                             seq, ack_num, fl, data, ts, tu)

    out = hdr
    # TCP 3-way handshake
    out += c2s(cs, 0, 'S', b''); cs += 1; tu += 100
    out += s2c(ss, cs, 'SA', b''); ss += 1; tu += 100
    out += c2s(cs, ss, 'A', b''); tu += 100

    first_c2s_done = False
    for direction, pdu in exchange:
        if direction == 'c2s':
            if split_first and not first_c2s_done and len(pdu) > 20:
                mid = len(pdu) // 2
                out += c2s(cs, ss, 'A', pdu[:mid])
                cs += mid; tu += 500
                out += c2s(cs, ss, 'PA', pdu[mid:])
                cs += len(pdu) - mid; tu += 500
                first_c2s_done = True
            else:
                out += c2s(cs, ss, 'PA', pdu)
                cs += len(pdu); tu += 1000
            out += s2c(ss, cs, 'A', b''); tu += 100
        else:
            out += s2c(ss, cs, 'PA', pdu)
            ss += len(pdu); tu += 1000
            out += c2s(cs, ss, 'A', b''); tu += 100

    # TCP teardown
    out += c2s(cs, ss, 'FA', b''); cs += 1; tu += 100
    out += s2c(ss, cs, 'FA', b''); ss += 1; tu += 100
    out += c2s(cs, ss, 'A', b'')
    return out


# ---------------------------------------------------------------------------
# Minimal PDU fixtures for capture generation
# ---------------------------------------------------------------------------

RELEASE_RQ = b"\x05\x00\x00\x00\x00\x04\x00\x00\x00\x00"
RELEASE_RP = b"\x06\x00\x00\x00\x00\x04\x00\x00\x00\x00"
ABORT = b"\x07\x00\x00\x00\x00\x04\x00\x00\x00\x00"
REJECT = b"\x03\x00\x00\x00\x00\x04\x00\x01\x01\x01"

ASSOC_RQ = (
    b"\x01\x00\x00\x00\x00\xd1\x00\x01\x00\x00\x41\x4e\x59\x2d"
    b"\x53\x43\x50\x20\x20\x20\x20\x20\x20\x20\x20\x20\x45\x43"
    b"\x48\x4f\x53\x43\x55\x20\x20\x20\x20\x20\x20\x20\x20\x20"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x10\x00\x00\x15\x31\x2e\x32\x2e\x38\x34"
    b"\x30\x2e\x31\x30\x30\x30\x38\x2e\x33\x2e\x31\x2e\x31\x2e"
    b"\x31\x20\x00\x00\x2e\x01\x00\x00\x00\x30\x00\x00\x11\x31"
    b"\x2e\x32\x2e\x38\x34\x30\x2e\x31\x30\x30\x30\x38\x2e\x31"
    b"\x2e\x31\x40\x00\x00\x11\x31\x2e\x32\x2e\x38\x34\x30\x2e"
    b"\x31\x30\x30\x30\x38\x2e\x31\x2e\x32\x50\x00\x00\x3e\x51"
    b"\x00\x00\x04\x00\x00\x3f\xfe\x52\x00\x00\x20\x31\x2e\x32"
    b"\x2e\x38\x32\x36\x2e\x30\x2e\x31\x2e\x33\x36\x38\x30\x30"
    b"\x34\x33\x2e\x39\x2e\x33\x38\x31\x31\x2e\x30\x2e\x39\x2e"
    b"\x30\x55\x00\x00\x0e\x50\x59\x4e\x45\x54\x44\x49\x43\x4f"
    b"\x4d\x5f\x30\x39\x30"
)

ASSOC_AC = (
    b"\x02\x00\x00\x00\x00\xb8\x00\x01\x00\x00\x41\x4e\x59\x2d"
    b"\x53\x43\x50\x20\x20\x20\x20\x20\x20\x20\x20\x20\x45\x43"
    b"\x48\x4f\x53\x43\x55\x20\x20\x20\x20\x20\x20\x20\x20\x20"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x10\x00\x00\x15\x31\x2e\x32\x2e\x38\x34"
    b"\x30\x2e\x31\x30\x30\x30\x38\x2e\x33\x2e\x31\x2e\x31\x2e"
    b"\x31\x21\x00\x00\x19\x01\x00\x00\x00\x40\x00\x00\x11\x31"
    b"\x2e\x32\x2e\x38\x34\x30\x2e\x31\x30\x30\x30\x38\x2e\x31"
    b"\x2e\x32\x50\x00\x00\x3a\x51\x00\x00\x04\x00\x00\x40\x00"
    b"\x52\x00\x00\x1b\x31\x2e\x32\x2e\x32\x37\x36\x2e\x30\x2e"
    b"\x37\x32\x33\x30\x30\x31\x30\x2e\x33\x2e\x30\x2e\x33\x2e"
    b"\x36\x2e\x30\x55\x00\x00\x0f\x4f\x46\x46\x49\x53\x5f\x44"
    b"\x43\x4d\x54\x4b\x5f\x33\x36\x30"
)

P_DATA = (
    b"\x04\x00\x00\x00\x00\x54\x00\x00\x00\x50\x01\x03\x00\x00\x00"
    b"\x00\x04\x00\x00\x00\x42\x00\x00\x00\x00\x00\x02\x00\x12\x00"
    b"\x00\x00\x31\x2e\x32\x2e\x38\x34\x30\x2e\x31\x30\x30\x30\x38"
    b"\x2e\x31\x2e\x31\x00\x00\x00\x00\x01\x02\x00\x00\x00\x30\x80"
    b"\x00\x00\x20\x01\x02\x00\x00\x00\x01\x00\x00\x00\x00\x08\x02"
    b"\x00\x00\x00\x01\x01\x00\x00\x00\x09\x02\x00\x00\x00\x00\x00"
)


if __name__ == '__main__':
    os.makedirs('/app/captures', exist_ok=True)

    # --- Raw framing: echo exchange ---
    with open('/app/captures/raw_exchange.bin', 'wb') as f:
        f.write(ASSOC_RQ + ASSOC_AC + P_DATA + RELEASE_RQ + RELEASE_RP)

    # --- Timestamped framing ---
    with open('/app/captures/timed_exchange.bin', 'wb') as f:
        ts_base = 1700000000
        for i, pdu in enumerate([RELEASE_RQ, RELEASE_RP, ABORT]):
            f.write(struct.pack('>II', ts_base + i, len(pdu)))
            f.write(pdu)

    # --- Raw framing with violations ---
    release_rq_bad = bytearray(RELEASE_RQ)
    release_rq_bad[1] = 0xFF
    with open('/app/captures/violations.bin', 'wb') as f:
        f.write(bytes(release_rq_bad) + RELEASE_RP)

    # --- PCAP: echo exchange (single PDU per TCP segment) ---
    pcap_exchange = [
        ('c2s', ASSOC_RQ), ('s2c', ASSOC_AC),
        ('c2s', P_DATA), ('c2s', RELEASE_RQ), ('s2c', RELEASE_RP),
    ]
    with open('/app/captures/echo_exchange.pcap', 'wb') as f:
        f.write(build_dicom_pcap(pcap_exchange))

    # --- PCAP: echo exchange with first PDU split across TCP segments ---
    with open('/app/captures/echo_split.pcap', 'wb') as f:
        f.write(build_dicom_pcap(pcap_exchange, split_first=True))

    print("Capture files generated in /app/captures/")
