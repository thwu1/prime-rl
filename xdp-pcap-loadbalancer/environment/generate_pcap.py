#!/usr/bin/env python3
"""Generate test pcap and config for XDP-style load balancer task.

Creates /app/input.pcap with mixed traffic and /app/config.json with LB config.
"""


import struct
import json
import os

# ── helpers ──────────────────────────────────────────────────────────

def mac_bytes(mac_str):
    return bytes(int(x, 16) for x in mac_str.split(':'))

def ip_bytes(ip_str):
    return bytes(int(x) for x in ip_str.split('.'))

def compute_checksum(data):
    """RFC 1071 one's complement checksum."""
    if len(data) % 2:
        data = data + b'\x00'
    s = 0
    for i in range(0, len(data), 2):
        s += (data[i] << 8) | data[i + 1]
    while s >> 16:
        s = (s & 0xFFFF) + (s >> 16)
    return (~s) & 0xFFFF

def make_ethernet(dst, src, ethertype):
    return dst + src + struct.pack('!H', ethertype)

def make_vlan_ethernet(dst, src, vlan_id, inner_etype):
    return dst + src + struct.pack('!HHH', 0x8100, vlan_id, inner_etype)

def make_ip_header(src, dst, proto, payload_len, ip_id):
    hdr = bytearray(struct.pack('!BBHHHBBH',
        0x45, 0x00,
        20 + payload_len,
        ip_id,
        0x4000,   # DF
        64,       # TTL
        proto,
        0,        # checksum placeholder
    ))
    hdr += ip_bytes(src) + ip_bytes(dst)
    csum = compute_checksum(bytes(hdr))
    hdr[10:12] = struct.pack('!H', csum)
    return bytes(hdr)

def make_tcp(sport, dport, seq, ack, flags, src_ip, dst_ip, payload=b''):
    tcp = bytearray(struct.pack('!HHIIBBHHH',
        sport, dport, seq, ack,
        0x50,     # data offset = 5 words
        flags,
        65535,    # window
        0,        # checksum placeholder
        0,        # urgent
    ))
    tcp += payload
    pseudo = ip_bytes(src_ip) + ip_bytes(dst_ip) + struct.pack('!BBH', 0, 6, len(tcp))
    csum = compute_checksum(pseudo + bytes(tcp))
    tcp[16:18] = struct.pack('!H', csum)
    return bytes(tcp)

def make_udp(sport, dport, src_ip, dst_ip, payload=b''):
    length = 8 + len(payload)
    udp = bytearray(struct.pack('!HHHH', sport, dport, length, 0))
    udp += payload
    pseudo = ip_bytes(src_ip) + ip_bytes(dst_ip) + struct.pack('!BBH', 0, 17, len(udp))
    csum = compute_checksum(pseudo + bytes(udp))
    if csum == 0:
        csum = 0xFFFF
    udp[6:8] = struct.pack('!H', csum)
    return bytes(udp)

def make_udp_no_checksum(sport, dport, payload=b''):
    """Create UDP datagram with checksum disabled (field = 0x0000)."""
    length = 8 + len(payload)
    udp = struct.pack('!HHHH', sport, dport, length, 0)
    return udp + payload

def make_icmp_echo(icmp_id, seq, payload=b''):
    icmp = bytearray(struct.pack('!BBHHH', 8, 0, 0, icmp_id, seq))
    icmp += payload
    csum = compute_checksum(bytes(icmp))
    icmp[2:4] = struct.pack('!H', csum)
    return bytes(icmp)

def make_arp_request(sha, spa, tpa):
    arp = struct.pack('!HHBBH', 1, 0x0800, 6, 4, 1)
    arp += sha + ip_bytes(spa) + b'\x00' * 6 + ip_bytes(tpa)
    return arp

def write_pcap(path, packets):
    with open(path, 'wb') as f:
        f.write(struct.pack('<IHHiIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1))
        for i, data in enumerate(packets):
            ts_sec = 1000000 + i
            f.write(struct.pack('<IIII', ts_sec, 0, len(data), len(data)))
            f.write(data)

# ── config ───────────────────────────────────────────────────────────

VIP = '10.0.0.1'
LB_IP = '10.0.0.254'
LB_MAC = '02:00:00:00:00:fe'

BACKENDS = [
    {'ip': '10.0.1.1', 'mac': '02:00:00:01:00:01', 'weight': 1},
    {'ip': '10.0.1.2', 'mac': '02:00:00:01:00:02', 'weight': 2},
    {'ip': '10.0.1.3', 'mac': '02:00:00:01:00:03', 'weight': 1},
]

# ── packets ──────────────────────────────────────────────────────────

def build_packets():
    lb = mac_bytes(LB_MAC)
    pkts = []

    # Pkt 0: TCP SYN  192.168.1.10:12345 -> VIP:80   (flow A)
    eth = make_ethernet(lb, mac_bytes('02:00:00:aa:00:01'), 0x0800)
    ip  = make_ip_header('192.168.1.10', VIP, 6, 20, 0x0001)
    tcp = make_tcp(12345, 80, 1000, 0, 0x02, '192.168.1.10', VIP)
    pkts.append(eth + ip + tcp)

    # Pkt 1: TCP PSH+ACK same flow A  (flow affinity test)
    payload = b'GET / HTTP/1.1\r\n'
    tcp2 = make_tcp(12345, 80, 1001, 2000, 0x18, '192.168.1.10', VIP, payload)
    ip2  = make_ip_header('192.168.1.10', VIP, 6, len(tcp2), 0x0002)
    pkts.append(eth + ip2 + tcp2)

    # Pkt 2: TCP SYN  192.168.1.20:54321 -> VIP:443  (flow B)
    eth3 = make_ethernet(lb, mac_bytes('02:00:00:aa:00:02'), 0x0800)
    ip3  = make_ip_header('192.168.1.20', VIP, 6, 20, 0x0003)
    tcp3 = make_tcp(54321, 443, 3000, 0, 0x02, '192.168.1.20', VIP)
    pkts.append(eth3 + ip3 + tcp3)

    # Pkt 3: UDP  192.168.1.30:9999 -> VIP:53  (flow C, checksum enabled)
    eth4 = make_ethernet(lb, mac_bytes('02:00:00:aa:00:03'), 0x0800)
    udp_payload = b'dns_query!!!'
    udp4 = make_udp(9999, 53, '192.168.1.30', VIP, udp_payload)
    ip4  = make_ip_header('192.168.1.30', VIP, 17, len(udp4), 0x0004)
    pkts.append(eth4 + ip4 + udp4)

    # Pkt 4: UDP  192.168.1.35:7777 -> VIP:53  (flow F, checksum disabled)
    eth4b = make_ethernet(lb, mac_bytes('02:00:00:aa:00:09'), 0x0800)
    udp_nc = make_udp_no_checksum(7777, 53, b'nocsum_query!')
    ip4b  = make_ip_header('192.168.1.35', VIP, 17, len(udp_nc), 0x0008)
    pkts.append(eth4b + ip4b + udp_nc)

    # Pkt 5: ICMP echo request  192.168.1.40 -> VIP
    eth5 = make_ethernet(lb, mac_bytes('02:00:00:aa:00:04'), 0x0800)
    icmp = make_icmp_echo(0x1234, 1, b'pingdata')
    ip5  = make_ip_header('192.168.1.40', VIP, 1, len(icmp), 0x0005)
    pkts.append(eth5 + ip5 + icmp)

    # Pkt 6: ARP request for VIP
    eth6 = make_ethernet(b'\xff\xff\xff\xff\xff\xff',
                         mac_bytes('02:00:00:aa:00:05'), 0x0806)
    arp  = make_arp_request(mac_bytes('02:00:00:aa:00:05'),
                            '192.168.1.50', VIP)
    pkts.append(eth6 + arp)

    # Pkt 7: IPv6 (passthrough)
    eth7 = make_ethernet(mac_bytes('33:33:00:00:00:01'),
                         mac_bytes('02:00:00:aa:00:06'), 0x86DD)
    ipv6 = bytes([
        0x60, 0x00, 0x00, 0x00,
        0x00, 0x08,
        0x3A, 0x40,
    ])
    ipv6 += bytes([0xfe, 0x80] + [0]*6 + [0,0,0,0,0,0,0,1])
    ipv6 += bytes([0xff, 0x02] + [0]*6 + [0,0,0,0,0,0,0,1])
    ipv6 += bytes([0x80, 0x00, 0x7f, 0xbe, 0x00, 0x01, 0x00, 0x01])
    pkts.append(eth7 + ipv6)

    # Pkt 8: Truncated (only 8 bytes - not enough for Ethernet header)
    pkts.append(b'\xde\xad\xbe\xef\xca\xfe\xba\xbe')

    # Pkt 9: TCP SYN  192.168.1.60:11111 -> VIP:8080 (flow D)
    eth9 = make_ethernet(lb, mac_bytes('02:00:00:aa:00:07'), 0x0800)
    ip9  = make_ip_header('192.168.1.60', VIP, 6, 20, 0x0006)
    tcp9 = make_tcp(11111, 8080, 5000, 0, 0x02, '192.168.1.60', VIP)
    pkts.append(eth9 + ip9 + tcp9)

    # Pkt 10: VLAN-tagged TCP SYN  192.168.1.80:22222 -> VIP:80  (flow E, VLAN 100)
    eth10 = make_vlan_ethernet(lb, mac_bytes('02:00:00:aa:00:08'), 100, 0x0800)
    ip10  = make_ip_header('192.168.1.80', VIP, 6, 20, 0x0007)
    tcp10 = make_tcp(22222, 80, 6000, 0, 0x02, '192.168.1.80', VIP)
    pkts.append(eth10 + ip10 + tcp10)

    return pkts


# ── main ─────────────────────────────────────────────────────────────

def main():
    os.makedirs('/app', exist_ok=True)

    packets = build_packets()
    write_pcap('/app/input.pcap', packets)

    config = {
        'vip': VIP,
        'lb_ip': LB_IP,
        'lb_mac': LB_MAC,
        'backends': BACKENDS,
    }
    with open('/app/config.json', 'w') as f:
        json.dump(config, f, indent=2)

    print(f"Created /app/input.pcap with {len(packets)} packets")
    print(f"Created /app/config.json")

if __name__ == '__main__':
    main()
