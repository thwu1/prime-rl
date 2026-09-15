#!/usr/bin/env python3
"""Generate test packet data (PCAP/pcapng files) and signature database (SQLite)."""
import struct
import socket
import sqlite3
import os


def ip_checksum(header_bytes):
    if len(header_bytes) % 2 == 1:
        header_bytes += b'\x00'
    s = 0
    for i in range(0, len(header_bytes), 2):
        w = (header_bytes[i] << 8) + header_bytes[i + 1]
        s += w
    while s >> 16:
        s = (s & 0xFFFF) + (s >> 16)
    return ~s & 0xFFFF


def tcp_checksum(src_ip, dst_ip, tcp_segment):
    pseudo = struct.pack('!4s4sBBH',
                         socket.inet_aton(src_ip),
                         socket.inet_aton(dst_ip),
                         0, 6, len(tcp_segment))
    data = pseudo + tcp_segment
    if len(data) % 2 == 1:
        data += b'\x00'
    s = 0
    for i in range(0, len(data), 2):
        w = (data[i] << 8) + data[i + 1]
        s += w
    while s >> 16:
        s = (s & 0xFFFF) + (s >> 16)
    return ~s & 0xFFFF


def make_tcp_options(opts):
    result = b''
    for item in opts:
        kind = item[0]
        if kind == 0:
            result += b'\x00'
        elif kind == 1:
            result += b'\x01'
        elif kind == 2:
            result += struct.pack('!BBH', 2, 4, item[1])
        elif kind == 3:
            result += struct.pack('!BBB', 3, 3, item[1])
        elif kind == 4:
            result += struct.pack('!BB', 4, 2)
        elif kind == 8:
            result += struct.pack('!BBII', 8, 10, item[1], item[2])
    while len(result) % 4 != 0:
        result += b'\x00'
    return result


def build_packet(src_ip, dst_ip, src_port, dst_port, ttl, identification,
                 df, seq, ack_num, syn, ack_flag, psh, urg, urg_ptr,
                 window, tcp_options, ecn=0, ip_options=b'', payload=b'',
                 rst=False):
    src_mac = b'\xaa\xbb\xcc\xdd\xee\x01'
    dst_mac = b'\x00\x11\x22\x33\x44\x55'

    tcp_opts_bytes = make_tcp_options(tcp_options)

    data_offset = (20 + len(tcp_opts_bytes)) // 4
    flags = 0
    if syn:
        flags |= 0x02
    if ack_flag:
        flags |= 0x10
    if psh:
        flags |= 0x08
    if urg:
        flags |= 0x20
    if rst:
        flags |= 0x04
    off_res_flags = (data_offset << 12) | flags

    tcp_seg = struct.pack('!HHIIHHH',
                          src_port, dst_port,
                          seq, ack_num,
                          off_res_flags, window, 0)
    tcp_seg += struct.pack('!H', urg_ptr)
    tcp_seg += tcp_opts_bytes + payload

    cksum = tcp_checksum(src_ip, dst_ip, tcp_seg)
    tcp_seg = tcp_seg[:16] + struct.pack('!H', cksum) + tcp_seg[18:]

    ihl = 5 + len(ip_options) // 4
    ver_ihl = (4 << 4) | ihl
    tos = ecn & 0x03
    total_length = ihl * 4 + len(tcp_seg)
    flags_frag = 0x4000 if df else 0

    ip_hdr = struct.pack('!BBHHHBBH4s4s',
                         ver_ihl, tos, total_length,
                         identification, flags_frag,
                         ttl, 6, 0,
                         socket.inet_aton(src_ip),
                         socket.inet_aton(dst_ip))
    if ip_options:
        ip_hdr += ip_options

    ip_cksum = ip_checksum(ip_hdr)
    ip_hdr = ip_hdr[:10] + struct.pack('!H', ip_cksum) + ip_hdr[12:]

    ip_pkt = ip_hdr + tcp_seg
    frame = dst_mac + src_mac + struct.pack('!H', 0x0800) + ip_pkt
    return frame


def write_pcap(filepath, packets_with_ts):
    """Write packets in standard libpcap format."""
    with open(filepath, 'wb') as f:
        f.write(struct.pack('<I', 0xa1b2c3d4))
        f.write(struct.pack('<H', 2))
        f.write(struct.pack('<H', 4))
        f.write(struct.pack('<i', 0))
        f.write(struct.pack('<I', 0))
        f.write(struct.pack('<I', 65535))
        f.write(struct.pack('<I', 1))

        for ts, pkt in packets_with_ts:
            ts_sec = int(ts)
            ts_usec = int((ts - ts_sec) * 1e6)
            f.write(struct.pack('<I', ts_sec))
            f.write(struct.pack('<I', ts_usec))
            f.write(struct.pack('<I', len(pkt)))
            f.write(struct.pack('<I', len(pkt)))
            f.write(pkt)


def _write_pcapng_block(f, block_type, body):
    """Write a single pcapng block with type, body, and trailing length."""
    total_length = 12 + len(body)
    f.write(struct.pack('<I', block_type))
    f.write(struct.pack('<I', total_length))
    f.write(body)
    f.write(struct.pack('<I', total_length))


def write_pcapng(filepath, packets_with_ts):
    """Write packets in pcapng (next-generation) format."""
    with open(filepath, 'wb') as f:
        # Section Header Block (SHB)
        shb_body = struct.pack('<I', 0x1A2B3C4D)   # Byte-Order Magic
        shb_body += struct.pack('<HH', 1, 0)        # Version 1.0
        shb_body += struct.pack('<q', -1)            # Section Length (unspecified)
        _write_pcapng_block(f, 0x0A0D0D0A, shb_body)

        # Interface Description Block (IDB)
        idb_body = struct.pack('<HH', 1, 0)         # LinkType=Ethernet, Reserved=0
        idb_body += struct.pack('<I', 65535)         # SnapLen
        # if_tsresol option: code=9, length=1, value=6 (10^-6 = microseconds)
        idb_body += struct.pack('<HH', 9, 1)
        idb_body += b'\x06' + b'\x00' * 3           # value + padding to 4 bytes
        # opt_endofopt
        idb_body += struct.pack('<HH', 0, 0)
        _write_pcapng_block(f, 0x00000001, idb_body)

        # Enhanced Packet Blocks (EPB)
        for ts, pkt in packets_with_ts:
            ts_usec = int(round(ts * 1e6))
            ts_high = (ts_usec >> 32) & 0xFFFFFFFF
            ts_low = ts_usec & 0xFFFFFFFF
            pkt_pad = (4 - (len(pkt) % 4)) % 4

            epb_body = struct.pack('<I', 0)             # Interface ID
            epb_body += struct.pack('<II', ts_high, ts_low)  # Timestamp
            epb_body += struct.pack('<II', len(pkt), len(pkt))
            epb_body += pkt + b'\x00' * pkt_pad
            _write_pcapng_block(f, 0x00000006, epb_body)


def main():
    os.makedirs('/app/data/captures', exist_ok=True)
    os.makedirs('/app/output', exist_ok=True)
    os.makedirs('/app/tools', exist_ok=True)

    # ===== client.pcap: SYN packets from clients + noise (standard pcap) =====
    client_packets = []

    # 1: Linux 6.x SYN -- DF, non-zero ID (id+ quirk)
    client_packets.append((1700000001.123456, build_packet(
        src_ip='10.0.1.10', dst_ip='192.168.1.1',
        src_port=45678, dst_port=443,
        ttl=64, identification=0x1234, df=True,
        seq=100001, ack_num=0, syn=True, ack_flag=False,
        psh=False, urg=False, urg_ptr=0, window=29200,
        tcp_options=[(2, 1460), (4,), (8, 12345, 0), (1,), (3, 7)])))

    # 2: Windows 11 SYN -- TTL=128, DF, non-zero ID
    client_packets.append((1700000002.234567, build_packet(
        src_ip='10.0.2.20', dst_ip='192.168.1.1',
        src_port=52000, dst_port=80,
        ttl=128, identification=0xABCD, df=True,
        seq=200002, ack_num=0, syn=True, ack_flag=False,
        psh=False, urg=False, urg_ptr=0, window=64240,
        tcp_options=[(2, 1460), (1,), (3, 8), (1,), (1,), (4,)])))

    # 3: macOS 14.x SYN -- EOL with 1 byte padding
    client_packets.append((1700000003.345678, build_packet(
        src_ip='10.0.3.30', dst_ip='192.168.1.1',
        src_port=61234, dst_port=443,
        ttl=64, identification=0, df=True,
        seq=300003, ack_num=0, syn=True, ack_flag=False,
        psh=False, urg=False, urg_ptr=0, window=65535,
        tcp_options=[(2, 1460), (1,), (3, 6), (1,), (1,),
                     (8, 98765, 0), (4,), (0,)])))

    # 4: FreeBSD 14.x SYN -- different option ordering
    client_packets.append((1700000004.456789, build_packet(
        src_ip='10.0.4.40', dst_ip='192.168.1.1',
        src_port=39876, dst_port=22,
        ttl=64, identification=0, df=True,
        seq=400004, ack_num=0, syn=True, ack_flag=False,
        psh=False, urg=False, urg_ptr=0, window=65535,
        tcp_options=[(2, 1460), (1,), (1,), (4,), (1,), (3, 6)])))

    # 5: Linux ECN SYN -- ECN bits, non-zero ACK in SYN (ack+), TTL=63
    client_packets.append((1700000005.567890, build_packet(
        src_ip='10.0.5.50', dst_ip='192.168.1.1',
        src_port=55555, dst_port=80,
        ttl=63, identification=0x5678, df=True,
        seq=500005, ack_num=99999, syn=True, ack_flag=False,
        psh=False, urg=False, urg_ptr=0, window=29200,
        tcp_options=[(2, 1460), (4,), (8, 33333, 0), (1,), (3, 7)],
        ecn=3)))

    # 6: OpenBSD 7.x SYN -- yet another option ordering
    client_packets.append((1700000006.678901, build_packet(
        src_ip='10.0.6.60', dst_ip='192.168.1.1',
        src_port=44444, dst_port=443,
        ttl=64, identification=0, df=True,
        seq=600006, ack_num=0, syn=True, ack_flag=False,
        psh=False, urg=False, urg_ptr=0, window=16384,
        tcp_options=[(2, 1460), (1,), (1,), (4,), (1,), (3, 6),
                     (1,), (1,), (8, 77777, 0)])))

    # 7: Unknown device SYN -- TTL=255, no DF, unusual opt order, zero TSval, non-zero TSecr
    client_packets.append((1700000007.789012, build_packet(
        src_ip='10.0.7.70', dst_ip='192.168.1.1',
        src_port=11111, dst_port=80,
        ttl=255, identification=0, df=False,
        seq=700007, ack_num=0, syn=True, ack_flag=False,
        psh=False, urg=False, urg_ptr=0, window=4096,
        tcp_options=[(8, 0, 12345), (2, 536), (3, 0), (4,), (0,)])))

    # 8: Linux with IP options SYN -- IHL=6, olen=4
    client_packets.append((1700000008.890123, build_packet(
        src_ip='10.0.8.80', dst_ip='192.168.1.1',
        src_port=33333, dst_port=443,
        ttl=64, identification=0x9999, df=True,
        seq=800008, ack_num=0, syn=True, ack_flag=False,
        psh=False, urg=False, urg_ptr=0, window=29200,
        tcp_options=[(2, 1460), (4,), (8, 55555, 0), (1,), (3, 7)],
        ip_options=b'\x01\x01\x01\x01')))

    # 9: TCP ACK-only (no SYN) -- must be filtered
    client_packets.append((1700000009.901234, build_packet(
        src_ip='10.0.9.90', dst_ip='192.168.1.1',
        src_port=60000, dst_port=80,
        ttl=64, identification=50000, df=True,
        seq=900009, ack_num=12345, syn=False, ack_flag=True,
        psh=False, urg=False, urg_ptr=0, window=65535,
        tcp_options=[(1,), (1,), (8, 11111, 22222)])))

    # 10: TCP RST (no SYN) -- must be filtered
    client_packets.append((1700000010.012345, build_packet(
        src_ip='10.0.10.100', dst_ip='192.168.1.1',
        src_port=60001, dst_port=80,
        ttl=64, identification=50001, df=True,
        seq=1000010, ack_num=0, syn=False, ack_flag=False,
        psh=False, urg=False, urg_ptr=0, window=0,
        tcp_options=[], rst=True)))

    write_pcap('/app/data/captures/client.pcap', client_packets)

    # ===== server.pcapng: SYN+ACK packets from server + noise (pcapng format) =====
    server_packets = []

    # 11: Linux 6.x SYN+ACK -- DF, zero ID, ts2+ (normal for SYN+ACK)
    server_packets.append((1700000021.111111, build_packet(
        src_ip='192.168.1.1', dst_ip='10.0.1.10',
        src_port=443, dst_port=45678,
        ttl=64, identification=0, df=True,
        seq=200000, ack_num=100002, syn=True, ack_flag=True,
        psh=False, urg=False, urg_ptr=0, window=28960,
        tcp_options=[(2, 1460), (4,), (8, 44444, 12345), (1,), (3, 7)])))

    # 12: Windows Server SYN+ACK -- TTL=128, DF, non-zero ID
    server_packets.append((1700000022.222222, build_packet(
        src_ip='192.168.1.1', dst_ip='10.0.2.20',
        src_port=80, dst_port=52000,
        ttl=128, identification=0x1111, df=True,
        seq=300000, ack_num=200003, syn=True, ack_flag=True,
        psh=False, urg=False, urg_ptr=0, window=64240,
        tcp_options=[(2, 1460), (1,), (3, 8), (1,), (1,), (4,)])))

    # 13: Linux ECN SYN+ACK -- TTL=63, ECN=1, ts2+
    server_packets.append((1700000023.333333, build_packet(
        src_ip='192.168.1.1', dst_ip='10.0.3.30',
        src_port=443, dst_port=61234,
        ttl=63, identification=0, df=True,
        seq=400000, ack_num=300004, syn=True, ack_flag=True,
        psh=False, urg=False, urg_ptr=0, window=28960,
        tcp_options=[(2, 1460), (4,), (8, 66666, 98765), (1,), (3, 7)],
        ecn=1)))

    # 14: FreeBSD SYN+ACK -- DF, zero ID, no timestamps
    server_packets.append((1700000024.444444, build_packet(
        src_ip='192.168.1.1', dst_ip='10.0.4.40',
        src_port=22, dst_port=39876,
        ttl=64, identification=0, df=True,
        seq=500000, ack_num=400005, syn=True, ack_flag=True,
        psh=False, urg=False, urg_ptr=0, window=65535,
        tcp_options=[(2, 1460), (1,), (1,), (4,), (1,), (3, 6)])))

    # 15: TCP data (ACK, no SYN) -- must be filtered
    server_packets.append((1700000025.555555, build_packet(
        src_ip='192.168.1.1', dst_ip='10.0.1.10',
        src_port=443, dst_port=45678,
        ttl=64, identification=0x2222, df=True,
        seq=200001, ack_num=100003, syn=False, ack_flag=True,
        psh=False, urg=False, urg_ptr=0, window=65535,
        tcp_options=[(1,), (1,), (8, 44445, 12346)])))

    write_pcapng('/app/data/captures/server.pcapng', server_packets)

    # ===== Normalized Signature Database =====
    db_path = '/app/data/signatures.db'
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute('''CREATE TABLE sections (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE
    )''')

    c.execute('''CREATE TABLE os_families (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE
    )''')

    c.execute('''CREATE TABLE os_versions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        family_id INTEGER NOT NULL REFERENCES os_families(id),
        version TEXT NOT NULL,
        label TEXT NOT NULL UNIQUE
    )''')

    c.execute('''CREATE TABLE sig_patterns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        section_id INTEGER NOT NULL REFERENCES sections(id),
        version_id INTEGER NOT NULL REFERENCES os_versions(id),
        ip_ver TEXT NOT NULL,
        ittl TEXT NOT NULL,
        olen TEXT NOT NULL,
        mss_pattern TEXT NOT NULL,
        wsize_pattern TEXT NOT NULL,
        wscale_pattern TEXT NOT NULL,
        olayout TEXT NOT NULL,
        quirks TEXT NOT NULL DEFAULT '',
        pclass TEXT NOT NULL DEFAULT '0',
        priority INTEGER NOT NULL
    )''')

    c.execute('''CREATE INDEX idx_sig_priority
                 ON sig_patterns(section_id, priority)''')

    # Sections
    c.execute("INSERT INTO sections (id, name) VALUES (1, 'tcp:request')")
    c.execute("INSERT INTO sections (id, name) VALUES (2, 'tcp:response')")

    # OS Families
    families = [
        (1, "Linux"),
        (2, "Windows"),
        (3, "macOS"),
        (4, "FreeBSD"),
        (5, "OpenBSD"),
    ]
    for fid, name in families:
        c.execute("INSERT INTO os_families (id, name) VALUES (?, ?)", (fid, name))

    # OS Versions
    versions = [
        (1, 1, "6.x",       "Linux:6.x"),
        (2, 2, "11",        "Windows:11"),
        (3, 3, "14.x",      "macOS:14.x"),
        (4, 4, "14.x",      "FreeBSD:14.x"),
        (5, 1, "6.x-ecn",   "Linux:6.x-ecn"),
        (6, 5, "7.x",       "OpenBSD:7.x"),
        (7, 1, "6.x-ipopt", "Linux:6.x-ipopt"),
        (8, 2, "Server",    "Windows:Server"),
    ]
    for vid, fid, ver, label in versions:
        c.execute(
            "INSERT INTO os_versions (id, family_id, version, label) VALUES (?, ?, ?, ?)",
            (vid, fid, ver, label))

    # Signature patterns for tcp:request (SYN packets)
    # Each row decomposes the original sig string into individual fields
    request_patterns = [
        # version_id, ip_ver, ittl, olen, mss_pat, wsize_pat, wscale_pat, olayout, quirks, pclass, priority
        (1, "4", "64", "0", "*", "mss*20", "7", "mss,sok,ts,nop,ws", "df,id+", "0", 1),
        (2, "4", "128", "0", "1460", "64240", "8", "mss,nop,ws,nop,nop,sok", "df,id+", "0", 2),
        (3, "4", "64", "0", "*", "65535", "6", "mss,nop,ws,nop,nop,ts,sok,eol+1", "df", "0", 3),
        (4, "4", "64", "0", "*", "65535", "6", "mss,nop,nop,sok,nop,ws", "df", "0", 4),
        (5, "4", "64", "0", "*", "mss*20", "7", "mss,sok,ts,nop,ws", "df,id+,ecn,ack+", "0", 5),
        (6, "4", "64", "0", "*", "16384", "6", "mss,nop,nop,sok,nop,ws,nop,nop,ts", "df", "0", 6),
        (7, "4", "64", "4", "*", "mss*20", "7", "mss,sok,ts,nop,ws", "df,id+", "0", 7),
    ]

    # Signature patterns for tcp:response (SYN+ACK packets)
    response_patterns = [
        (1, "4", "64", "0", "*", "*", "7", "mss,sok,ts,nop,ws", "df,ts2+", "0", 1),
        (8, "4", "128", "0", "1460", "64240", "8", "mss,nop,ws,nop,nop,sok", "df,id+", "0", 2),
        (5, "4", "64", "0", "*", "*", "7", "mss,sok,ts,nop,ws", "df,ecn,ts2+", "0", 3),
        (4, "4", "64", "0", "*", "65535", "6", "mss,nop,nop,sok,nop,ws", "df", "0", 4),
    ]

    for ver_id, ipv, ittl, olen, mss, ws, wsc, olay, quirks, pcl, pri in request_patterns:
        c.execute("""INSERT INTO sig_patterns
            (section_id, version_id, ip_ver, ittl, olen, mss_pattern,
             wsize_pattern, wscale_pattern, olayout, quirks, pclass, priority)
            VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (ver_id, ipv, ittl, olen, mss, ws, wsc, olay, quirks, pcl, pri))

    for ver_id, ipv, ittl, olen, mss, ws, wsc, olay, quirks, pcl, pri in response_patterns:
        c.execute("""INSERT INTO sig_patterns
            (section_id, version_id, ip_ver, ittl, olen, mss_pattern,
             wsize_pattern, wscale_pattern, olayout, quirks, pclass, priority)
            VALUES (2, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (ver_id, ipv, ittl, olen, mss, ws, wsc, olay, quirks, pcl, pri))

    conn.commit()
    conn.close()

    print(f"Generated client.pcap with {len(client_packets)} packets (pcap format)")
    print(f"Generated server.pcapng with {len(server_packets)} packets (pcapng format)")
    print(f"Generated normalized signature database at {db_path}")


if __name__ == '__main__':
    main()
