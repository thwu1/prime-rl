#!/usr/bin/env python3
"""TCP SYN passive OS fingerprinting engine.

Reads a PCAP capture, extracts TCP SYN fingerprints, and matches
them against a SQLite signature database.
"""

import struct
import socket
import sqlite3
import json
import os

# TCP option kinds
TCPOPT_EOL = 0
TCPOPT_NOP = 1
TCPOPT_MSS = 2
TCPOPT_WSCALE = 3
TCPOPT_SACKOK = 4
TCPOPT_SACK = 5
TCPOPT_TSTAMP = 8

# Standard initial TTL values used by various operating systems
INITIAL_TTLS = [32, 64, 128, 255]

# Canonical quirk ordering for signature formatting
QUIRK_ORDER = [
    "df", "id+", "id-", "ecn", "0+", "flow", "seq-", "ack+", "ack-",
    "uptr+", "urgf+", "pushf+", "ts1-", "ts2+", "opt+", "exws",
]


def normalize_ttl(observed):
    """Guess the initial TTL from the observed TTL value.

    Returns the smallest standard TTL that could have been the initial value.
    """
    for t in INITIAL_TTLS:
        if t > observed:
            return t
    return 255


def parse_tcp_options(data):
    """Parse TCP options and extract fingerprint-relevant values."""
    options = []
    mss = -1
    wscale = -1
    ts1 = None
    ts2 = None
    eol_pad = 0
    opt_quirks = set()

    pos = 0
    total = len(data)

    while pos < total:
        kind = data[pos]

        if kind == TCPOPT_EOL:
            remaining = total - pos
            eol_pad = remaining
            options.append("eol")
            break

        if kind == TCPOPT_NOP:
            options.append("nop")
            pos += 1
            continue

        if pos + 1 >= total:
            break
        opt_len = data[pos + 1]
        if opt_len < 2 or pos + opt_len > total:
            break

        if kind == TCPOPT_MSS:
            if pos + 4 <= total:
                mss = struct.unpack("!H", data[pos + 2 : pos + 4])[0]
            options.append("mss")
        elif kind == TCPOPT_WSCALE:
            if pos + 3 <= total:
                wscale = data[pos + 2]
                if wscale > 14:
                    opt_quirks.add("exws")
            options.append("ws")
        elif kind == TCPOPT_SACKOK:
            options.append("sok")
        elif kind == TCPOPT_SACK:
            options.append("sack")
        elif kind == TCPOPT_TSTAMP:
            if pos + 10 <= total:
                ts1 = struct.unpack("!I", data[pos + 2 : pos + 6])[0]
                ts2 = struct.unpack("!I", data[pos + 6 : pos + 10])[0]
                if ts1 == 0:
                    opt_quirks.add("ts1-")
                if ts2 != 0:
                    opt_quirks.add("ts2+")
            options.append("ts")
        else:
            options.append(f"?{kind}")

        pos += opt_len

    return options, mss, wscale, ts1, ts2, eol_pad, opt_quirks


def format_olayout(options, eol_pad):
    """Format the TCP option layout string."""
    parts = []
    for opt in options:
        if opt == "eol":
            parts.append(f"eol+{eol_pad}")
        else:
            parts.append(opt)
    return ",".join(parts)


def compute_quirks(ip_flags_frag, ip_id, ip_tos, tcp_seq, tcp_ack_num,
                   tcp_flags, tcp_urg_ptr, opt_quirks):
    """Detect TCP/IP stack quirks from header fields."""
    quirks = set(opt_quirks)

    df = (ip_flags_frag & 0x4000) != 0
    if df:
        quirks.add("df")
        if ip_id != 0:
            quirks.add("id-")
    else:
        if ip_id == 0:
            quirks.add("id+")

    # Check ECN bits in IP TOS field
    if (ip_tos & 0xC0) != 0:
        quirks.add("ecn")

    if tcp_seq == 0:
        quirks.add("seq-")

    ack_flag = (tcp_flags & 0x10) != 0
    if ack_flag:
        if tcp_ack_num == 0:
            quirks.add("ack-")

    urg_flag = (tcp_flags & 0x20) != 0
    if urg_flag:
        quirks.add("urgf+")
    elif tcp_urg_ptr != 0:
        quirks.add("uptr+")

    if (tcp_flags & 0x08) != 0:
        quirks.add("pushf+")

    reserved = (tcp_flags >> 9) & 0x07
    if reserved != 0:
        quirks.add("0+")

    return quirks


def format_quirks(quirks):
    """Format quirks in canonical order."""
    return ",".join(q for q in QUIRK_ORDER if q in quirks)


def read_pcap(filepath):
    """Read packets from a standard libpcap file."""
    packets = []
    with open(filepath, 'rb') as f:
        magic = struct.unpack('<I', f.read(4))[0]
        if magic == 0xa1b2c3d4:
            endian = '<'
        elif magic == 0xd4c3b2a1:
            endian = '>'
        else:
            raise ValueError(f"Invalid PCAP magic: {magic:#x}")

        _ver_major = struct.unpack(endian + 'H', f.read(2))[0]
        _ver_minor = struct.unpack(endian + 'H', f.read(2))[0]
        _thiszone = struct.unpack(endian + 'i', f.read(4))[0]
        _sigfigs = struct.unpack(endian + 'I', f.read(4))[0]
        _snaplen = struct.unpack(endian + 'I', f.read(4))[0]
        network = struct.unpack(endian + 'I', f.read(4))[0]

        if network != 1:
            raise ValueError(f"Unsupported link type: {network}")

        while True:
            hdr = f.read(16)
            if len(hdr) < 16:
                break
            ts_sec, ts_usec, incl_len, orig_len = struct.unpack(
                endian + 'IIII', hdr)
            frame = f.read(incl_len)
            if len(frame) < incl_len:
                break
            ts = ts_sec + ts_usec / 1e6
            packets.append((ts, frame))

    return packets


def read_signatures(db_path):
    """Read signatures from SQLite database, ordered by priority."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""
        SELECT s.label, s.sig
        FROM signatures s
        JOIN sections sec ON s.section_id = sec.id
        WHERE sec.name = 'tcp:request'
        ORDER BY s.priority ASC
    """)
    entries = c.fetchall()
    conn.close()
    return entries


def parse_packet(frame):
    """Parse a raw Ethernet frame and extract TCP SYN fingerprint info."""
    if len(frame) < 14:
        return None

    ethertype = struct.unpack("!H", frame[12:14])[0]
    if ethertype != 0x0800:
        return None

    eth_payload = frame[14:]
    if len(eth_payload) < 20:
        return None

    ver_ihl = eth_payload[0]
    ip_ver = (ver_ihl >> 4) & 0x0F
    ihl = ver_ihl & 0x0F
    ip_hdr_len = ihl * 4

    if ip_ver != 4 or ip_hdr_len < 20 or len(eth_payload) < ip_hdr_len:
        return None

    ip_tos = eth_payload[1]
    ip_total_len = struct.unpack("!H", eth_payload[2:4])[0]
    ip_id = struct.unpack("!H", eth_payload[4:6])[0]
    ip_flags_frag = struct.unpack("!H", eth_payload[6:8])[0]
    ip_ttl = eth_payload[8]
    ip_proto = eth_payload[9]
    src_ip = socket.inet_ntoa(eth_payload[12:16])
    dst_ip = socket.inet_ntoa(eth_payload[16:20])

    if ip_proto != 6:
        return None

    ip_opt_len = ip_hdr_len - 20

    tcp_start = ip_hdr_len
    if len(eth_payload) < tcp_start + 20:
        return None

    tcp_data = eth_payload[tcp_start:]
    src_port = struct.unpack("!H", tcp_data[0:2])[0]
    dst_port = struct.unpack("!H", tcp_data[2:4])[0]
    tcp_seq = struct.unpack("!I", tcp_data[4:8])[0]
    tcp_ack_num = struct.unpack("!I", tcp_data[8:12])[0]
    tcp_off_flags = struct.unpack("!H", tcp_data[12:14])[0]
    tcp_window = struct.unpack("!H", tcp_data[14:16])[0]
    tcp_urg_ptr = struct.unpack("!H", tcp_data[18:20])[0]

    data_offset = (tcp_off_flags >> 12) & 0x0F
    tcp_hdr_len = data_offset * 4
    tcp_flags = tcp_off_flags & 0x01FF

    # SYN set, ACK clear
    if not (tcp_flags & 0x02) or (tcp_flags & 0x10):
        return None

    opts_data = tcp_data[20:tcp_hdr_len]
    options, mss, wscale, ts1, ts2, eol_pad, opt_quirks = parse_tcp_options(opts_data)

    tcp_payload_len = ip_total_len - ip_hdr_len - tcp_hdr_len
    pclass = "+" if tcp_payload_len > 0 else "0"

    ittl = normalize_ttl(ip_ttl)

    quirks = compute_quirks(
        ip_flags_frag, ip_id, ip_tos,
        tcp_seq, tcp_ack_num, tcp_flags, tcp_urg_ptr,
        opt_quirks,
    )

    olayout = format_olayout(options, eol_pad)
    quirks_str = format_quirks(quirks)
    mss_str = str(mss) if mss >= 0 else "*"
    wscale_str = str(wscale) if wscale >= 0 else "*"

    sig = f"{ip_ver}:{ittl}:{ip_opt_len}:{mss_str}:{tcp_window},{wscale_str}:{olayout}:{quirks_str}:{pclass}"

    return {
        "src_ip": src_ip,
        "src_port": src_port,
        "dst_ip": dst_ip,
        "dst_port": dst_port,
        "signature": sig,
        "mss": mss,
        "wscale": wscale,
        "quirks": quirks,
    }


def sig_matches(pkt_info, db_sig):
    """Check if a packet's fingerprint matches a database signature pattern."""
    parts = db_sig.split(":")
    if len(parts) != 8:
        return False

    db_ver, db_ittl, db_olen, db_mss, db_ww, db_olayout, db_quirks, db_pclass = parts

    pkt_parts = pkt_info["signature"].split(":")
    p_ver, p_ittl, p_olen, p_mss, p_ww, p_olayout, p_quirks, p_pclass = pkt_parts

    if db_ver != p_ver:
        return False
    if db_ittl != p_ittl:
        return False
    if db_olen != p_olen:
        return False
    if db_mss != "*" and db_mss != p_mss:
        return False

    db_ws_parts = db_ww.split(",")
    pkt_ws_parts = p_ww.split(",")
    if len(db_ws_parts) != 2 or len(pkt_ws_parts) != 2:
        return False

    db_wsize, db_wscale = db_ws_parts
    pkt_wsize, pkt_wscale = pkt_ws_parts

    if db_wscale != "*" and db_wscale != pkt_wscale:
        return False

    actual_window = int(pkt_wsize)
    actual_mss = pkt_info["mss"]

    if db_wsize == "*":
        pass
    elif db_wsize.startswith("mss*"):
        mult = int(db_wsize[4:])
        if actual_mss < 0 or actual_window != actual_mss * mult:
            return False
    elif db_wsize.startswith("mtu*"):
        mult = int(db_wsize[4:])
        mtu = (actual_mss + 40) if actual_mss > 0 else 1500
        if actual_window != mtu * mult:
            return False
    else:
        if int(db_wsize) != actual_window:
            return False

    if db_olayout != p_olayout:
        return False

    db_q = set(db_quirks.split(",")) if db_quirks else set()
    pkt_q = set(p_quirks.split(",")) if p_quirks else set()
    db_q.discard("")
    pkt_q.discard("")
    if db_q != pkt_q:
        return False

    if db_pclass != "*" and db_pclass != p_pclass:
        return False

    return True


def match_against_db(pkt_info, db_entries):
    """Match a packet fingerprint against all database signatures."""
    for label, sig in db_entries:
        if sig_matches(pkt_info, sig):
            return label
    return "unknown"


def main():
    pcap_file = "/app/data/capture.pcap"
    sig_db_file = "/app/data/fingerprints.db"
    output_file = "/app/output/results.json"

    raw_packets = read_pcap(pcap_file)
    db_entries = read_signatures(sig_db_file)

    results = []
    for ts, frame in raw_packets:
        pkt = parse_packet(frame)
        if pkt is None:
            continue

        os_label = match_against_db(pkt, db_entries)

        results.append({
            "src_ip": pkt["src_ip"],
            "src_port": pkt["src_port"],
            "dst_ip": pkt["dst_ip"],
            "dst_port": pkt["dst_port"],
            "signature": pkt["signature"],
            "match": os_label,
            "timestamp": ts,
        })

    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)

    print(f"Processed {len(raw_packets)} packets, found {len(results)} SYN packets")


if __name__ == "__main__":
    main()
