#!/usr/bin/env python3
"""Generate WebRTC session captures for the multi-capture forensics task."""

import struct
import hmac
import hashlib
import json
import zlib
import os

MAGIC_COOKIE = 0x2112A442
MAGIC_COOKIE_BYTES = struct.pack("!I", MAGIC_COOKIE)

LOCAL_IP = "10.0.0.1"
LOCAL_PORT = 50000
LOCAL_ADDR = f"{LOCAL_IP}:{LOCAL_PORT}"
REMOTE_IP = "10.0.0.2"
REMOTE_PORT = 50001
REMOTE_ADDR = f"{REMOTE_IP}:{REMOTE_PORT}"
LOCAL_UFRAG = "kDRs"
LOCAL_PWD = "YOe2AkGqBMuq5tU5YMXR2P3d"
REMOTE_UFRAG = "VxPH"
REMOTE_PWD = "KJ4EVzLBnC3UTqEfQB7HGKVZ"

RTP_SSRC = 0x12345678
RTP_SSRC2 = 0xDEADBEEF
RTP_PT = 111
RTP_PT2 = 96
RTP_CLOCK_RATE = 48000
RTP_CLOCK_RATE2 = 90000
RTP_TS_INCREMENT = 960
RTP_TS_INCREMENT2 = 3000

packets = []  # (timestamp_us, src_addr_str, dst_addr_str, payload_bytes)


def pad4(data):
    padding = (4 - (len(data) % 4)) % 4
    return data + b'\x00' * padding


def build_stun_message(msg_type, txn_id, attributes, integrity_key=None, add_fingerprint=True):
    attrs = b""
    for attr_type, attr_value in attributes:
        attr_bytes = struct.pack("!HH", attr_type, len(attr_value)) + attr_value
        attrs += pad4(attr_bytes)

    if integrity_key is not None:
        mi_length = len(attrs) + 24
        header_for_hmac = struct.pack("!HH", msg_type, mi_length) + MAGIC_COOKIE_BYTES + txn_id
        hmac_data = header_for_hmac + attrs
        mi_value = hmac.new(integrity_key.encode('utf-8'), hmac_data, hashlib.sha1).digest()
        attrs += struct.pack("!HH", 0x0008, 20) + mi_value

    if add_fingerprint:
        fp_length = len(attrs) + 8
        header_for_crc = struct.pack("!HH", msg_type, fp_length) + MAGIC_COOKIE_BYTES + txn_id
        crc_data = header_for_crc + attrs
        crc = zlib.crc32(crc_data) & 0xFFFFFFFF
        crc ^= 0x5354554e
        attrs += struct.pack("!HHI", 0x8028, 4, crc)

    header = struct.pack("!HH", msg_type, len(attrs)) + MAGIC_COOKIE_BYTES + txn_id
    return header + attrs


def make_txn_id(n):
    return hashlib.md5(f"txn-{n}".encode()).digest()[:12]


def build_xor_mapped_address_ipv4(ip_str, port, txn_id):
    ip_parts = [int(x) for x in ip_str.split('.')]
    ip_int = (ip_parts[0] << 24) | (ip_parts[1] << 16) | (ip_parts[2] << 8) | ip_parts[3]
    x_port = port ^ (MAGIC_COOKIE >> 16)
    x_addr = ip_int ^ MAGIC_COOKIE
    return struct.pack("!BBHI", 0x00, 0x01, x_port, x_addr)


def build_rtp_packet(seq, timestamp, ssrc, pt, payload_size=160):
    byte0 = 0x80
    byte1 = pt & 0x7F
    header = struct.pack("!BBHII", byte0, byte1, seq, timestamp, ssrc)
    payload = bytes([(i * 3 + seq) & 0xFF for i in range(payload_size)])
    return header + payload


def build_rtcp_sr(ssrc, ntp_sec, ntp_frac, rtp_ts, pkt_count, octet_count):
    header = struct.pack("!BBH", 0x80, 200, 6)
    body = struct.pack("!I", ssrc)
    body += struct.pack("!II", ntp_sec, ntp_frac)
    body += struct.pack("!III", rtp_ts, pkt_count, octet_count)
    return header + body


def build_rtcp_rr(reporter_ssrc, report_blocks):
    byte0 = 0x80 | (len(report_blocks) & 0x1F)
    length = 1 + 6 * len(report_blocks)
    header = struct.pack("!BBH", byte0, 201, length)
    body = struct.pack("!I", reporter_ssrc)
    for b in report_blocks:
        body += struct.pack("!I", b['ssrc'])
        body += struct.pack("!I", (b['fraction_lost'] << 24) | (b['cumulative_lost'] & 0xFFFFFF))
        body += struct.pack("!IIII", b['highest_seq'], b['jitter'], b['lsr'], b['dlsr'])
    return header + body


def build_dtls_record(content_type, epoch, seq_num, payload_size=50):
    seq_bytes = struct.pack("!Q", seq_num)[2:]
    payload = bytes([(i * 7 + content_type) & 0xFF for i in range(payload_size)])
    header = struct.pack("!BH", content_type, 0xFEFD)
    header += struct.pack("!H", epoch) + seq_bytes + struct.pack("!H", len(payload))
    return header + payload


def add_packet(timestamp_us, src, dst, payload):
    packets.append((timestamp_us, src, dst, payload))


# === STUN packets ===

# Binding request from remote (valid integrity with local_pwd)
txn1 = make_txn_id(1)
add_packet(0, REMOTE_ADDR, LOCAL_ADDR, build_stun_message(0x0001, txn1,
    [(0x0006, f"{LOCAL_UFRAG}:{REMOTE_UFRAG}".encode()),
     (0x0024, struct.pack("!I", 1845501695))], integrity_key=LOCAL_PWD))

# Binding response to remote (valid integrity with local_pwd)
add_packet(5000, LOCAL_ADDR, REMOTE_ADDR, build_stun_message(0x0101, txn1,
    [(0x0020, build_xor_mapped_address_ipv4("10.0.0.2", 50001, txn1))], integrity_key=LOCAL_PWD))

# Binding request from local with USE-CANDIDATE (nomination, valid integrity with remote_pwd)
txn2 = make_txn_id(2)
add_packet(10000, LOCAL_ADDR, REMOTE_ADDR, build_stun_message(0x0001, txn2,
    [(0x0006, f"{REMOTE_UFRAG}:{LOCAL_UFRAG}".encode()),
     (0x0024, struct.pack("!I", 1853824767)),
     (0x0025, b'')], integrity_key=REMOTE_PWD))

# Binding response from remote (valid integrity with remote_pwd)
add_packet(15000, REMOTE_ADDR, LOCAL_ADDR, build_stun_message(0x0101, txn2,
    [(0x0020, build_xor_mapped_address_ipv4("10.0.0.1", 50000, txn2))], integrity_key=REMOTE_PWD))

# Binding request from unauthorized peer (invalid integrity - wrong password)
txn3 = make_txn_id(3)
add_packet(20000, "10.0.0.99:9999", LOCAL_ADDR, build_stun_message(0x0001, txn3,
    [(0x0006, f"{LOCAL_UFRAG}:FAKE".encode()),
     (0x0024, struct.pack("!I", 1000000000))], integrity_key="wrong_password_here"))

# === DTLS packets ===

add_packet(25000, LOCAL_ADDR, REMOTE_ADDR, build_dtls_record(22, 0, 0, 200))
add_packet(30000, REMOTE_ADDR, LOCAL_ADDR, build_dtls_record(22, 0, 1, 150))
add_packet(32000, LOCAL_ADDR, REMOTE_ADDR, build_dtls_record(20, 1, 0, 10))

# === RTP audio (SSRC 0x12345678, PT 111, 48kHz) ===

missing1 = {1003, 1008, 1023, 1037, 1042}
jitter1 = [0, 200, -150, 400, -200, 350, -100, 500, -300, 250,
           100, -400, 300, -250, 150, -350, 200, -150, 400, -100,
           50, -200, 350, -300, 100, -50, 200, -400, 300, -200,
           150, -350, 250, -100, 50, -250, 400, -150, 100, -300,
           200, -50, 350, -200, 50, 0, 100, -100, 200, -50]
for off in range(50):
    seq = 1000 + off
    if seq in missing1:
        continue
    add_packet(40000 + off * 20000 + jitter1[off], REMOTE_ADDR, LOCAL_ADDR,
               build_rtp_packet(seq, 960000 + off * RTP_TS_INCREMENT, RTP_SSRC, RTP_PT))

# === RTP video (SSRC 0xdeadbeef, PT 96, 90kHz) ===

missing2 = {5004, 5011, 5019}
jitter2 = [0, 300, -200, 500, -100, 400, -300, 200, -500, 100,
           -200, 300, -400, 500, -100, 200, -300, 400, -200, 100,
           300, -100, 500, -300, 200]
for off in range(25):
    seq = 5000 + off
    if seq in missing2:
        continue
    add_packet(41000 + off * 33333 + jitter2[off], REMOTE_ADDR, LOCAL_ADDR,
               build_rtp_packet(seq, 270000 + off * RTP_TS_INCREMENT2, RTP_SSRC2, RTP_PT2, 1200))

# === RTCP packets ===

add_packet(1040000, REMOTE_ADDR, LOCAL_ADDR, build_rtcp_sr(RTP_SSRC, 3917151600, 0x80000000,
    960000 + 25 * RTP_TS_INCREMENT, 25, 4000))
add_packet(2040000, REMOTE_ADDR, LOCAL_ADDR, build_rtcp_sr(RTP_SSRC, 3917151601, 0x40000000,
    960000 + 50 * RTP_TS_INCREMENT, 50, 8000))
add_packet(2045000, REMOTE_ADDR, LOCAL_ADDR, build_rtcp_sr(RTP_SSRC2, 3917151601, 0xC0000000,
    270000 + 25 * RTP_TS_INCREMENT2, 25, 30000))
add_packet(2050000, LOCAL_ADDR, REMOTE_ADDR, build_rtcp_rr(0xABCDEF01,
    [{'ssrc': RTP_SSRC, 'fraction_lost': 26, 'cumulative_lost': 5,
      'highest_seq': 1049, 'jitter': 500, 'lsr': 0, 'dlsr': 0}]))

# === Unknown protocol packet ===

add_packet(2060000, LOCAL_ADDR, REMOTE_ADDR, bytes([0x04, 0x05, 0x06, 0x07, 0x08, 0x09]))

# === Sort packets ===

packets.sort(key=lambda p: p[0])


# === Helper functions for writing pcap ===

def ip_str_to_bytes(ip_str):
    return bytes([int(x) for x in ip_str.split('.')])


def compute_ip_checksum(header_bytes):
    """One's complement checksum over 16-bit words."""
    if len(header_bytes) % 2:
        header_bytes += b'\x00'
    s = 0
    for i in range(0, len(header_bytes), 2):
        s += struct.unpack("!H", header_bytes[i:i + 2])[0]
    while s >> 16:
        s = (s & 0xFFFF) + (s >> 16)
    return ~s & 0xFFFF


def build_pcap_frame(src_addr, dst_addr, udp_payload):
    """Build Ethernet + IPv4 + UDP frame wrapping a UDP payload."""
    src_ip, src_port = src_addr.rsplit(":", 1)
    dst_ip, dst_port = dst_addr.rsplit(":", 1)
    src_port, dst_port = int(src_port), int(dst_port)

    # UDP header (8 bytes)
    udp_len = 8 + len(udp_payload)
    udp_hdr = struct.pack("!HHHH", src_port, dst_port, udp_len, 0)

    # IPv4 header (20 bytes, no options)
    ip_total_len = 20 + udp_len
    ip_hdr = struct.pack("!BBHHHBBH",
                         0x45,       # version=4, IHL=5
                         0x00,       # DSCP/ECN
                         ip_total_len,
                         0,          # identification
                         0x4000,     # flags=DF, frag offset=0
                         64,         # TTL
                         17,         # protocol=UDP
                         0)          # checksum placeholder
    ip_hdr += ip_str_to_bytes(src_ip) + ip_str_to_bytes(dst_ip)
    cksum = compute_ip_checksum(ip_hdr)
    ip_hdr = ip_hdr[:10] + struct.pack("!H", cksum) + ip_hdr[12:]

    # Ethernet header (14 bytes)
    eth_hdr = (b'\x00\x11\x22\x33\x44\x55'    # dst MAC
               b'\x66\x77\x88\x99\xaa\xbb'    # src MAC
               + struct.pack("!H", 0x0800))    # EtherType IPv4

    return eth_hdr + ip_hdr + udp_hdr + udp_payload


def write_pcap(filename, packet_list):
    """Write a list of (ts_us, src, dst, payload) as a libpcap file."""
    with open(filename, "wb") as f:
        # Pcap global header (24 bytes, little-endian)
        f.write(struct.pack("<IHHiIII",
                            0xa1b2c3d4,   # magic number
                            2, 4,         # version major.minor
                            0,            # thiszone
                            0,            # sigfigs
                            65535,        # snaplen
                            1))           # LINKTYPE_ETHERNET

        for ts_us, src, dst, payload in packet_list:
            frame = build_pcap_frame(src, dst, payload)
            ts_sec = ts_us // 1_000_000
            ts_usec = ts_us % 1_000_000
            # Pcap packet header (16 bytes, little-endian)
            f.write(struct.pack("<IIII", ts_sec, ts_usec, len(frame), len(frame)))
            f.write(frame)


# === Split packets by source and write two capture files ===

# tap_alpha: packets originating from endpoint A (LOCAL_ADDR = 10.0.0.1:50000)
alpha_packets = [p for p in packets if p[1] == LOCAL_ADDR]
# tap_beta: packets originating from endpoint B and third parties
beta_packets = [p for p in packets if p[1] != LOCAL_ADDR]

os.makedirs("/app/captures", exist_ok=True)
write_pcap("/app/captures/tap_alpha.pcap", alpha_packets)
write_pcap("/app/captures/tap_beta.pcap", beta_packets)

# === Write session config ===

config = {
    "local_ufrag": LOCAL_UFRAG, "local_pwd": LOCAL_PWD,
    "remote_ufrag": REMOTE_UFRAG, "remote_pwd": REMOTE_PWD,
    "rtp_clock_rates": {str(RTP_PT): RTP_CLOCK_RATE, str(RTP_PT2): RTP_CLOCK_RATE2},
    "local_addr": LOCAL_ADDR, "remote_addr": REMOTE_ADDR
}
with open("/app/session_config.json", "w") as f:
    json.dump(config, f, indent=2)

# === Generate HMAC-SHA256 integrity signature ===

HMAC_KEY = "webrtc-forensic-integrity-2024"
with open("/app/session_config.json", "rb") as f:
    config_bytes = f.read()
sig = hmac.new(HMAC_KEY.encode(), config_bytes, hashlib.sha256).hexdigest()

with open("/app/session_integrity.hmac", "w") as f:
    f.write(sig)
with open("/app/hmac_key.txt", "w") as f:
    f.write(HMAC_KEY)

print(f"Generated /app/captures/tap_alpha.pcap ({len(alpha_packets)} packets)")
print(f"Generated /app/captures/tap_beta.pcap ({len(beta_packets)} packets)")
print(f"Generated /app/session_config.json")
print(f"Generated /app/session_integrity.hmac (HMAC-SHA256: {sig[:16]}...)")
print(f"Generated /app/hmac_key.txt")
