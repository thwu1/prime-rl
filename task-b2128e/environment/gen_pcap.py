#!/usr/bin/env python3
"""Generate a pcap file containing syslog messages from OSPF routers.

The pcap includes OSPF adjacency reports (OSPF-ADJ) with link costs,
mixed with Hello and SPF noise messages. Only state=FULL messages
contain the correct link costs; state=INIT messages have cost=0.
"""
import struct
import socket

ROUTER_IPS = {
    'R1': '10.1.1.1', 'R2': '10.2.2.2', 'R3': '10.3.3.3',
    'R4': '10.4.4.4', 'R5': '10.5.5.5', 'R6': '10.6.6.6',
    'R7': '10.7.7.7', 'R8': '10.8.8.8', 'R9': '10.9.9.9',
    'R10': '10.10.10.10', 'R11': '10.11.11.11', 'R12': '10.12.12.12',
}

COLLECTOR_IP = '10.0.0.100'

# Links whose costs are NULL in the database
PCAP_LINKS = [
    ('R1', 'R3', 0, 20),
    ('R2', 'R4', 0, 8),
    ('R1', 'R6', 0, 15),
    ('R4', 'R8', 1, 6),
    ('R5', 'R10', 2, 14),
    ('R6', 'R12', 3, 11),
]


def compute_ip_checksum(header):
    """Compute the Internet checksum per RFC 1071."""
    if len(header) % 2:
        header = header + b'\x00'
    total = 0
    for i in range(0, len(header), 2):
        total += (header[i] << 8) + header[i + 1]
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return ~total & 0xFFFF


def build_packet(src_ip, message, src_port, pkt_id):
    """Build an Ethernet/IPv4/UDP frame with syslog payload."""
    payload = message.encode('ascii')

    # UDP header: src_port, dst_port(514), length, checksum(0)
    udp_len = 8 + len(payload)
    udp_hdr = struct.pack('!HHHH', src_port, 514, udp_len, 0)

    # IPv4 header with placeholder checksum
    ip_total_len = 20 + udp_len
    ip_hdr = bytearray(struct.pack('!BBHHHBBH4s4s',
        0x45, 0x00, ip_total_len,
        pkt_id & 0xFFFF, 0x4000,
        64, 17, 0,
        socket.inet_aton(src_ip),
        socket.inet_aton(COLLECTOR_IP),
    ))

    # Fill in IP checksum
    cksum = compute_ip_checksum(bytes(ip_hdr))
    struct.pack_into('!H', ip_hdr, 10, cksum)

    # Ethernet header
    eth_hdr = struct.pack('!6s6sH',
        b'\xff\xff\xff\xff\xff\xff',
        bytes([0x02, 0x00, 0x00, 0x00, 0x00, pkt_id & 0xFF]),
        0x0800,
    )

    return bytes(eth_hdr) + bytes(ip_hdr) + udp_hdr + payload


def main():
    packets = []
    base_ts = 1705312800  # 2024-01-15T10:00:00 UTC
    pkt_id = 1
    sorted_routers = sorted(ROUTER_IPS.keys(), key=lambda r: int(r[1:]))

    # Phase 1: OSPF Hello messages (noise)
    for i, rname in enumerate(sorted_routers):
        rip = ROUTER_IPS[rname]
        ts = base_ts + i
        msg = ("<134>Jan 15 10:00:%02d %s ospfd[%d]: "
               "OSPF-HELLO sent interface=GigabitEthernet0/0 "
               "router-id=%s area=0 neighbors=2") % (i, rname, 4890 + i, rip)
        packets.append((ts, 0, build_packet(rip, msg, 40000 + i, pkt_id)))
        pkt_id += 1

    # Phase 2: INIT adjacencies (noise — cost=0, wrong state)
    for idx, (r1, r2, area, _cost) in enumerate(PCAP_LINKS):
        sec1 = idx * 2
        sec2 = idx * 2 + 1
        ts = base_ts + 60 + sec1

        msg1 = ("<134>Jan 15 10:01:%02d %s ospfd[4891]: "
                "OSPF-ADJ interface=GigabitEthernet0/%d area=%d "
                "neighbor-id=%s neighbor-name=%s "
                "state=INIT cost=0") % (sec1, r1, area, area, ROUTER_IPS[r2], r2)
        packets.append((ts, 0, build_packet(ROUTER_IPS[r1], msg1, 41000 + idx * 2, pkt_id)))
        pkt_id += 1

        msg2 = ("<134>Jan 15 10:01:%02d %s ospfd[4891]: "
                "OSPF-ADJ interface=GigabitEthernet0/%d area=%d "
                "neighbor-id=%s neighbor-name=%s "
                "state=INIT cost=0") % (sec2, r2, area, area, ROUTER_IPS[r1], r1)
        packets.append((ts + 1, 0, build_packet(ROUTER_IPS[r2], msg2, 41000 + idx * 2 + 1, pkt_id)))
        pkt_id += 1

    # Phase 3: SPF calculation notices (noise)
    abr_for_area = ['R1', 'R4', 'R5', 'R6']
    for area_id in range(4):
        ts = base_ts + 120 + area_id
        rname = abr_for_area[area_id]
        msg = ("<134>Jan 15 10:02:%02d %s ospfd[4891]: "
               "OSPF-SPF area=%d calculation-started spf-runs=1 "
               "routes-updated=0") % (area_id, rname, area_id)
        packets.append((ts, 0, build_packet(ROUTER_IPS[rname], msg, 42000 + area_id, pkt_id)))
        pkt_id += 1

    # Phase 4: FULL adjacencies (correct costs)
    for idx, (r1, r2, area, cost) in enumerate(PCAP_LINKS):
        sec1 = idx * 2
        sec2 = idx * 2 + 1
        ts = base_ts + 180 + sec1

        msg1 = ("<134>Jan 15 10:03:%02d %s ospfd[4891]: "
                "OSPF-ADJ interface=GigabitEthernet0/%d area=%d "
                "neighbor-id=%s neighbor-name=%s "
                "state=FULL cost=%d") % (sec1, r1, area, area, ROUTER_IPS[r2], r2, cost)
        packets.append((ts, 0, build_packet(ROUTER_IPS[r1], msg1, 43000 + idx * 2, pkt_id)))
        pkt_id += 1

        msg2 = ("<134>Jan 15 10:03:%02d %s ospfd[4891]: "
                "OSPF-ADJ interface=GigabitEthernet0/%d area=%d "
                "neighbor-id=%s neighbor-name=%s "
                "state=FULL cost=%d") % (sec2, r2, area, area, ROUTER_IPS[r1], r1, cost)
        packets.append((ts + 1, 0, build_packet(ROUTER_IPS[r2], msg2, 43000 + idx * 2 + 1, pkt_id)))
        pkt_id += 1

    # Phase 5: More Hello noise
    for i in range(6):
        rname = 'R%d' % (i + 1)
        ts = base_ts + 240 + i
        msg = ("<134>Jan 15 10:04:%02d %s ospfd[%d]: "
               "OSPF-HELLO sent interface=GigabitEthernet0/0 "
               "router-id=%s area=0 neighbors=3") % (i, rname, 4890 + i, ROUTER_IPS[rname])
        packets.append((ts, 0, build_packet(ROUTER_IPS[rname], msg, 44000 + i, pkt_id)))
        pkt_id += 1

    # Sort by timestamp
    packets.sort(key=lambda x: (x[0], x[1]))

    # Write pcap file
    with open('/app/router_logs.pcap', 'wb') as f:
        # Pcap global header (little-endian, microsecond resolution)
        f.write(struct.pack('<IHHiIII',
            0xA1B2C3D4, 2, 4, 0, 0, 65535, 1))

        for ts_sec, ts_usec, pkt_data in packets:
            cap_len = len(pkt_data)
            f.write(struct.pack('<IIII', ts_sec, ts_usec, cap_len, cap_len))
            f.write(pkt_data)


if __name__ == '__main__':
    main()
