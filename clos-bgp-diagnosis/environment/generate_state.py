#!/usr/bin/env python3
"""
Generate captured network state for a 13-node CLOS datacenter with injected faults.
Includes synthetic packet captures (PCAP) for protocol-level forensic analysis.

"""

import json
import os
import struct

BASE = "/app/network_state"


def mkdirs():
    for d in [
        "configs", "bgp_tables", "bgp_neighbors", "routing_tables",
        "interfaces", "host_configs", "nftables", "tc", "bgp_logs",
        "captures"
    ]:
        os.makedirs(os.path.join(BASE, d), exist_ok=True)
    os.makedirs("/app/results", exist_ok=True)


def write(path, content):
    with open(os.path.join(BASE, path), "w") as f:
        f.write(content)


def write_json(path, obj):
    with open(os.path.join(BASE, path), "w") as f:
        json.dump(obj, f, indent=2)


# ========== PCAP Construction Helpers ==========

def ip_to_bytes(ip_str):
    return bytes(int(x) for x in ip_str.split('.'))


def mac_to_bytes(mac_str):
    return bytes(int(x, 16) for x in mac_str.split(':'))


def _inet_checksum(data):
    if len(data) % 2:
        data += b'\x00'
    words = struct.unpack('!%dH' % (len(data) // 2), data)
    s = sum(words)
    while s >> 16:
        s = (s & 0xffff) + (s >> 16)
    return ~s & 0xffff


def _eth_frame(dst_mac, src_mac, ethertype, payload):
    return dst_mac + src_mac + struct.pack('!H', ethertype) + payload


def _ip_packet(src_ip, dst_ip, protocol, payload, ident=0):
    src = ip_to_bytes(src_ip)
    dst = ip_to_bytes(dst_ip)
    total_len = 20 + len(payload)
    hdr = struct.pack('!BBHHHBBH4s4s',
        0x45, 0, total_len, ident, 0x4000, 64, protocol, 0, src, dst)
    chk = _inet_checksum(hdr)
    hdr = struct.pack('!BBHHHBBH4s4s',
        0x45, 0, total_len, ident, 0x4000, 64, protocol, chk, src, dst)
    return hdr + payload


def _tcp_segment(src_port, dst_port, seq, ack, flags, src_ip, dst_ip,
                 payload=b'', options=b''):
    if len(options) % 4:
        options += b'\x00' * (4 - len(options) % 4)
    doff = 5 + len(options) // 4
    off_flags = (doff << 12) | flags
    hdr = struct.pack('!HHIIHHHH',
        src_port, dst_port, seq, ack, off_flags, 65535, 0, 0)
    full = hdr + options + payload
    pseudo = struct.pack('!4s4sBBH',
        ip_to_bytes(src_ip), ip_to_bytes(dst_ip), 0, 6, len(full))
    chk = _inet_checksum(pseudo + full)
    hdr = struct.pack('!HHIIHHHH',
        src_port, dst_port, seq, ack, off_flags, 65535, chk, 0)
    return hdr + options + payload


def _tcp_ip_eth(src_mac, dst_mac, src_ip, dst_ip,
                src_port, dst_port, seq, ack, flags,
                payload=b'', options=b'', ident=0):
    tcp = _tcp_segment(src_port, dst_port, seq, ack, flags,
                       src_ip, dst_ip, payload, options)
    ip = _ip_packet(src_ip, dst_ip, 6, tcp, ident)
    return _eth_frame(dst_mac, src_mac, 0x0800, ip)


def _bgp_open(my_as, hold_time, bgp_id_str):
    marker = b'\xff' * 16
    bgp_id = ip_to_bytes(bgp_id_str)
    body = struct.pack('!BHH4sB', 4, my_as, hold_time, bgp_id, 0)
    length = 19 + len(body)
    return marker + struct.pack('!HB', length, 1) + body


def _bgp_notification(error_code, error_subcode):
    marker = b'\xff' * 16
    body = struct.pack('!BB', error_code, error_subcode)
    length = 19 + len(body)
    return marker + struct.pack('!HB', length, 3) + body


def _arp_packet(opcode, sender_mac, sender_ip, target_mac, target_ip):
    arp = struct.pack('!HHBBH', 1, 0x0800, 6, 4, opcode)
    arp += sender_mac + ip_to_bytes(sender_ip)
    arp += target_mac + ip_to_bytes(target_ip)
    if opcode == 1:
        dst = b'\xff\xff\xff\xff\xff\xff'
    else:
        dst = target_mac
    return _eth_frame(dst, sender_mac, 0x0806, arp)


def _write_pcap(filepath, packets):
    with open(filepath, 'wb') as f:
        f.write(struct.pack('<IHHiIII',
            0xa1b2c3d4, 2, 4, 0, 0, 65535, 1))
        for ts_sec, ts_usec, data in packets:
            f.write(struct.pack('<IIII',
                ts_sec, ts_usec, len(data), len(data)))
            f.write(data)


# ========== Network State Generators ==========

def gen_topology():
    topo = {
        "description": (
            "A multi-tier data center Clos (fat-tree) topology using EBGP with FRR. "
            "One super-spine (ss0, AS 65000) connects to two spine routers. Each spine "
            "peers with the super-spine and all four leaf routers. Each leaf connects to "
            "one host via a /24 subnet (10.0.<leaf_index>.0/24) and should advertise this "
            "network via BGP. All inter-router links use /31 subnets from 172.16.0.0/16. "
            "Routing is entirely EBGP with no IGP."
        ),
        "design_as_assignments": {
            "ss0": 65000, "sp0": 65100, "sp1": 65101,
            "lf0": 65200, "lf1": 65201, "lf2": 65202, "lf3": 65203
        },
        "roles": {
            "ss0": "super_spine", "sp0": "spine", "sp1": "spine",
            "lf0": "leaf", "lf1": "leaf", "lf2": "leaf", "lf3": "leaf",
            "h0": "host", "h1": "host", "h2": "host", "h3": "host"
        },
        "links": [
            {"endpoints": ["ss0:eth0", "sp0:eth0"], "subnet": "172.16.0.0/31",
             "addresses": {"ss0:eth0": "172.16.0.0", "sp0:eth0": "172.16.0.1"}},
            {"endpoints": ["ss0:eth1", "sp1:eth0"], "subnet": "172.16.0.2/31",
             "addresses": {"ss0:eth1": "172.16.0.2", "sp1:eth0": "172.16.0.3"}},
            {"endpoints": ["sp0:eth1", "lf0:eth0"], "subnet": "172.16.0.4/31",
             "addresses": {"sp0:eth1": "172.16.0.4", "lf0:eth0": "172.16.0.5"}},
            {"endpoints": ["sp0:eth2", "lf1:eth0"], "subnet": "172.16.0.6/31",
             "addresses": {"sp0:eth2": "172.16.0.6", "lf1:eth0": "172.16.0.7"}},
            {"endpoints": ["sp0:eth3", "lf2:eth0"], "subnet": "172.16.0.8/31",
             "addresses": {"sp0:eth3": "172.16.0.8", "lf2:eth0": "172.16.0.9"}},
            {"endpoints": ["sp0:eth4", "lf3:eth0"], "subnet": "172.16.0.10/31",
             "addresses": {"sp0:eth4": "172.16.0.10", "lf3:eth0": "172.16.0.11"}},
            {"endpoints": ["sp1:eth1", "lf0:eth1"], "subnet": "172.16.0.12/31",
             "addresses": {"sp1:eth1": "172.16.0.12", "lf0:eth1": "172.16.0.13"}},
            {"endpoints": ["sp1:eth2", "lf1:eth1"], "subnet": "172.16.0.14/31",
             "addresses": {"sp1:eth2": "172.16.0.14", "lf1:eth1": "172.16.0.15"}},
            {"endpoints": ["sp1:eth3", "lf2:eth1"], "subnet": "172.16.0.16/31",
             "addresses": {"sp1:eth3": "172.16.0.16", "lf2:eth1": "172.16.0.17"}},
            {"endpoints": ["sp1:eth4", "lf3:eth1"], "subnet": "172.16.0.18/31",
             "addresses": {"sp1:eth4": "172.16.0.18", "lf3:eth1": "172.16.0.19"}},
            {"endpoints": ["lf0:eth2", "h0:eth0"], "subnet": "10.0.0.0/24",
             "addresses": {"lf0:eth2": "10.0.0.1", "h0:eth0": "10.0.0.2"}},
            {"endpoints": ["lf1:eth2", "h1:eth0"], "subnet": "10.0.1.0/24",
             "addresses": {"lf1:eth2": "10.0.1.1", "h1:eth0": "10.0.1.2"}},
            {"endpoints": ["lf2:eth2", "h2:eth0"], "subnet": "10.0.2.0/24",
             "addresses": {"lf2:eth2": "10.0.2.1", "h2:eth0": "10.0.2.2"}},
            {"endpoints": ["lf3:eth2", "h3:eth0"], "subnet": "10.0.3.0/24",
             "addresses": {"lf3:eth2": "10.0.3.1", "h3:eth0": "10.0.3.2"}},
        ],
        "host_subnets": {
            "h0": {"subnet": "10.0.0.0/24", "gateway": "10.0.0.1", "leaf": "lf0"},
            "h1": {"subnet": "10.0.1.0/24", "gateway": "10.0.1.1", "leaf": "lf1"},
            "h2": {"subnet": "10.0.2.0/24", "gateway": "10.0.2.1", "leaf": "lf2"},
            "h3": {"subnet": "10.0.3.0/24", "gateway": "10.0.3.1", "leaf": "lf3"},
        }
    }
    write_json("topology.json", topo)


def gen_ops_changelog():
    write("ops_changelog.txt", """\
# Network Operations Change Log
# DC1 CLOS EBGP Fabric — Last updated 2025-11-28

## Recently Applied Changes

### OPS-4499 | 2025-11-25 14:30 UTC | Device: ss0 | Approved by: J. Chen (SRE Lead)
Description: BGP timer optimization for super-spine peering.
Changed keepalive interval from 60s to 10s and hold timer from 180s to 30s
on all ss0 BGP neighbor sessions.
Purpose: Faster convergence and failure detection on critical super-spine
uplinks. Aligns with SRE runbook section 4.2 (sub-second failover target).
Verification: Confirmed all ss0 BGP sessions re-established after timer change.
Status: APPLIED — VERIFIED

### SEC-0088 | 2025-11-26 09:15 UTC | Device: sp0 | Approved by: M. Rodriguez (NOC Security)
Description: ICMP flood rate-limiting on sp0 forwarding path.
Added nftables forward-chain rule limiting ICMP forwarding to 50 packets/second
with 20-packet burst tolerance. Excess ICMP is dropped with counter tracking.
Purpose: Mitigate ICMP-based reconnaissance scanning and potential DDoS
amplification vectors per NOC security policy.
Verification: Confirmed non-ICMP traffic unaffected; ICMP rate limiting active.
Status: APPLIED — VERIFIED

### OPS-4521 | 2025-11-27 11:00 UTC | Device: lf3 Interface: eth2 | Approved by: A. Patel (Capacity Mgmt)
Description: Tenant bandwidth enforcement for h3 subnet.
Applied tc tbf (token bucket filter) on lf3 downlink eth2 toward h3.
Parameters: rate 50Mbit, burst 64Kb, latency 50ms.
Purpose: Enforce Gold-tier tenant SLA bandwidth cap (50 Mbps) for h3 services
per capacity management agreement CM-2025-0891.
Verification: Confirmed iperf3 throughput from h3 capped at ~48 Mbps.
Status: APPLIED — VERIFIED
""")


def gen_configs():
    # ss0 — super-spine (correct, non-default timers = planned change OPS-4499)
    write("configs/ss0.conf", """\
Building configuration...

Current configuration:
!
frr version 9.1.3
frr defaults traditional
hostname ss0
log file /var/log/frr/frr.log
no ipv6 forwarding
service integrated-vtysh-config
!
debug bgp keepalives
debug bgp updates in
debug bgp updates out
!
router bgp 65000
 bgp router-id 172.16.0.0
 no bgp ebgp-requires-policy
 neighbor 172.16.0.1 remote-as 65100
 neighbor 172.16.0.1 timers 10 30
 neighbor 172.16.0.3 remote-as 65101
 neighbor 172.16.0.3 timers 10 30
exit
!
end
""")

    # sp0 — spine (correct BGP config; nftables ICMP rate limit is planned change)
    write("configs/sp0.conf", """\
Building configuration...

Current configuration:
!
frr version 9.1.3
frr defaults traditional
hostname sp0
log file /var/log/frr/frr.log
no ipv6 forwarding
service integrated-vtysh-config
!
debug bgp keepalives
debug bgp updates in
debug bgp updates out
!
router bgp 65100
 bgp router-id 172.16.0.1
 no bgp ebgp-requires-policy
 neighbor 172.16.0.0 remote-as 65000
 neighbor 172.16.0.5 remote-as 65200
 neighbor 172.16.0.7 remote-as 65201
 neighbor 172.16.0.9 remote-as 65202
 neighbor 172.16.0.11 remote-as 65203
exit
!
end
""")

    # sp1 — spine (correct BGP config; nftables fault is separate)
    write("configs/sp1.conf", """\
Building configuration...

Current configuration:
!
frr version 9.1.3
frr defaults traditional
hostname sp1
log file /var/log/frr/frr.log
no ipv6 forwarding
service integrated-vtysh-config
!
debug bgp keepalives
debug bgp updates in
debug bgp updates out
!
router bgp 65101
 bgp router-id 172.16.0.3
 no bgp ebgp-requires-policy
 neighbor 172.16.0.2 remote-as 65000
 neighbor 172.16.0.13 remote-as 65200
 neighbor 172.16.0.15 remote-as 65201
 neighbor 172.16.0.17 remote-as 65202
 neighbor 172.16.0.19 remote-as 65203
exit
!
end
""")

    # lf0 — FAULT: AS 65199 instead of 65200
    write("configs/lf0.conf", """\
Building configuration...

Current configuration:
!
frr version 9.1.3
frr defaults traditional
hostname lf0
log file /var/log/frr/frr.log
no ipv6 forwarding
service integrated-vtysh-config
!
debug bgp keepalives
debug bgp updates in
debug bgp updates out
!
router bgp 65199
 bgp router-id 172.16.0.5
 no bgp ebgp-requires-policy
 neighbor 172.16.0.4 remote-as 65100
 neighbor 172.16.0.12 remote-as 65101
 !
 address-family ipv4 unicast
  network 10.0.0.0/24
 exit-address-family
exit
!
end
""")

    # lf1 — FAULT: static blackhole route for 10.0.2.0/24
    write("configs/lf1.conf", """\
Building configuration...

Current configuration:
!
frr version 9.1.3
frr defaults traditional
hostname lf1
log file /var/log/frr/frr.log
no ipv6 forwarding
service integrated-vtysh-config
!
debug bgp keepalives
debug bgp updates in
debug bgp updates out
!
ip route 10.0.2.0/24 Null0
!
router bgp 65201
 bgp router-id 172.16.0.7
 no bgp ebgp-requires-policy
 neighbor 172.16.0.6 remote-as 65100
 neighbor 172.16.0.14 remote-as 65101
 !
 address-family ipv4 unicast
  network 10.0.1.0/24
 exit-address-family
exit
!
end
""")

    # lf2 — FAULT: TCP-MD5 password on sp0 neighbor (sp0 has no password)
    write("configs/lf2.conf", """\
Building configuration...

Current configuration:
!
frr version 9.1.3
frr defaults traditional
hostname lf2
log file /var/log/frr/frr.log
no ipv6 forwarding
service integrated-vtysh-config
!
debug bgp keepalives
debug bgp updates in
debug bgp updates out
!
router bgp 65202
 bgp router-id 172.16.0.9
 no bgp ebgp-requires-policy
 neighbor 172.16.0.8 remote-as 65100
 neighbor 172.16.0.8 password S3cretKey1
 neighbor 172.16.0.16 remote-as 65101
 !
 address-family ipv4 unicast
  network 10.0.2.0/24
 exit-address-family
exit
!
end
""")

    # lf3 — FAULT: missing 'network 10.0.3.0/24'
    write("configs/lf3.conf", """\
Building configuration...

Current configuration:
!
frr version 9.1.3
frr defaults traditional
hostname lf3
log file /var/log/frr/frr.log
no ipv6 forwarding
service integrated-vtysh-config
!
debug bgp keepalives
debug bgp updates in
debug bgp updates out
!
router bgp 65203
 bgp router-id 172.16.0.11
 no bgp ebgp-requires-policy
 neighbor 172.16.0.10 remote-as 65100
 neighbor 172.16.0.18 remote-as 65101
exit
!
end
""")


def gen_bgp_neighbors():
    # ss0: both spine sessions established (non-default timers)
    write("bgp_neighbors/ss0.txt", """\
IPv4 Unicast Summary (VRF default):
BGP router identifier 172.16.0.0, local AS number 65000 vrf-id 0
BGP table version 4
RIB entries 3, using 576 bytes of memory
Peers 2, using 1433 KiB of memory

Neighbor        V         AS   MsgRcvd   MsgSent   TblVer  InQ OutQ  Up/Down State/PfxRcd   PfxSnt Desc
172.16.0.1      4      65100      1842      1845        0    0    0 02:15:33            1        2 N/A
172.16.0.3      4      65101      1840      1843        0    0    0 02:15:31            2        1 N/A

Total number of neighbors 2
""")

    # sp0: ss0 up; lf0 Idle (ASN); lf1 up; lf2 Active (TCP-MD5); lf3 up PfxRcvd=0
    write("bgp_neighbors/sp0.txt", """\
IPv4 Unicast Summary (VRF default):
BGP router identifier 172.16.0.1, local AS number 65100 vrf-id 0
BGP table version 5
RIB entries 3, using 576 bytes of memory
Peers 5, using 3583 KiB of memory

Neighbor        V         AS   MsgRcvd   MsgSent   TblVer  InQ OutQ  Up/Down State/PfxRcd   PfxSnt Desc
172.16.0.0      4      65000      1845      1842        0    0    0 02:15:33            2        1 N/A
172.16.0.5      4      65200         0         0        0    0    0    never       Idle        0 N/A
172.16.0.7      4      65201       142       145        0    0    0 02:15:28            1        2 N/A
172.16.0.9      4      65202         0         0        0    0    0    never     Active        0 N/A
172.16.0.11     4      65203       140       143        0    0    0 02:15:30            0        2 N/A

Total number of neighbors 5
""")

    # sp1: ss0 up; lf0 Idle (ASN); lf1 up; lf2 up; lf3 Active (nftables)
    write("bgp_neighbors/sp1.txt", """\
IPv4 Unicast Summary (VRF default):
BGP router identifier 172.16.0.3, local AS number 65101 vrf-id 0
BGP table version 5
RIB entries 3, using 576 bytes of memory
Peers 5, using 3583 KiB of memory

Neighbor        V         AS   MsgRcvd   MsgSent   TblVer  InQ OutQ  Up/Down State/PfxRcd   PfxSnt Desc
172.16.0.2      4      65000      1843      1840        0    0    0 02:15:31            1        2 N/A
172.16.0.13     4      65200         0         0        0    0    0    never       Idle        0 N/A
172.16.0.15     4      65201       141       144        0    0    0 02:15:27            1        1 N/A
172.16.0.17     4      65202       139       142        0    0    0 02:15:28            1        1 N/A
172.16.0.19     4      65203         0         0        0    0    0    never     Active        0 N/A

Total number of neighbors 5
""")

    # lf0: both sessions Idle (ASN mismatch — lf0 sends AS 65199, spines expect 65200)
    write("bgp_neighbors/lf0.txt", """\
IPv4 Unicast Summary (VRF default):
BGP router identifier 172.16.0.5, local AS number 65199 vrf-id 0
BGP table version 1
RIB entries 1, using 192 bytes of memory
Peers 2, using 1433 KiB of memory

Neighbor        V         AS   MsgRcvd   MsgSent   TblVer  InQ OutQ  Up/Down State/PfxRcd   PfxSnt Desc
172.16.0.4      4      65100         0         0        0    0    0    never       Idle        0 N/A
172.16.0.12     4      65101         0         0        0    0    0    never       Idle        0 N/A

Total number of neighbors 2
""")

    # lf1: both sessions established
    write("bgp_neighbors/lf1.txt", """\
IPv4 Unicast Summary (VRF default):
BGP router identifier 172.16.0.7, local AS number 65201 vrf-id 0
BGP table version 3
RIB entries 3, using 576 bytes of memory
Peers 2, using 1433 KiB of memory

Neighbor        V         AS   MsgRcvd   MsgSent   TblVer  InQ OutQ  Up/Down State/PfxRcd   PfxSnt Desc
172.16.0.6      4      65100       145       142        0    0    0 02:15:28            1        1 N/A
172.16.0.14     4      65101       144       141        0    0    0 02:15:27            1        1 N/A

Total number of neighbors 2
""")

    # lf2: sp0 Active (TCP-MD5 mismatch); sp1 established
    write("bgp_neighbors/lf2.txt", """\
IPv4 Unicast Summary (VRF default):
BGP router identifier 172.16.0.9, local AS number 65202 vrf-id 0
BGP table version 3
RIB entries 3, using 576 bytes of memory
Peers 2, using 1433 KiB of memory

Neighbor        V         AS   MsgRcvd   MsgSent   TblVer  InQ OutQ  Up/Down State/PfxRcd   PfxSnt Desc
172.16.0.8      4      65100         0         0        0    0    0    never     Active        0 N/A
172.16.0.16     4      65101       142       139        0    0    0 02:15:28            1        1 N/A

Total number of neighbors 2
""")

    # lf3: sp0 established PfxRcvd varies; sp1 Active (nftables blocking)
    write("bgp_neighbors/lf3.txt", """\
IPv4 Unicast Summary (VRF default):
BGP router identifier 172.16.0.11, local AS number 65203 vrf-id 0
BGP table version 3
RIB entries 3, using 576 bytes of memory
Peers 2, using 1433 KiB of memory

Neighbor        V         AS   MsgRcvd   MsgSent   TblVer  InQ OutQ  Up/Down State/PfxRcd   PfxSnt Desc
172.16.0.10     4      65100       143       140        0    0    0 02:15:30            2        0 N/A
172.16.0.18     4      65101         0         0        0    0    0    never     Active        0 N/A

Total number of neighbors 2
""")


def gen_bgp_tables():
    # ss0: sees 10.0.1.0/24 via both spines, 10.0.2.0/24 via sp1 only
    write("bgp_tables/ss0.txt", """\
BGP table version is 4, local router ID is 172.16.0.0, vrf id 0
Default local pref 100, local AS 65000
Status codes:  s suppressed, d damped, h history, * valid, > best, = multipath,
               i internal, r RIB-failure, S Stale, R Removed
Nexthop codes: @NNN nexthop's vrf id, < announce-nh-self
Origin codes:  i - IGP, e - EGP, ? - incomplete
RPKI validation codes: V valid, I invalid, N Not found

    Network          Next Hop            Metric LocPrf Weight Path
 *  10.0.1.0/24      172.16.0.3                             0 65101 65201 i
 *>                   172.16.0.1                             0 65100 65201 i
 *> 10.0.2.0/24      172.16.0.3                             0 65101 65202 i

Displayed  2 routes and 3 total paths
""")

    # sp0: 10.0.1.0/24 best from lf1; 10.0.2.0/24 via ss0
    write("bgp_tables/sp0.txt", """\
BGP table version is 5, local router ID is 172.16.0.1, vrf id 0
Default local pref 100, local AS 65100
Status codes:  s suppressed, d damped, h history, * valid, > best, = multipath,
               i internal, r RIB-failure, S Stale, R Removed
Nexthop codes: @NNN nexthop's vrf id, < announce-nh-self
Origin codes:  i - IGP, e - EGP, ? - incomplete
RPKI validation codes: V valid, I invalid, N Not found

    Network          Next Hop            Metric LocPrf Weight Path
 *> 10.0.1.0/24      172.16.0.7               0             0 65201 i
 *                    172.16.0.0                             0 65000 65101 65201 i
 *> 10.0.2.0/24      172.16.0.0                             0 65000 65101 65202 i

Displayed  2 routes and 3 total paths
""")

    # sp1: 10.0.1.0/24 best from lf1; 10.0.2.0/24 best from lf2
    write("bgp_tables/sp1.txt", """\
BGP table version is 5, local router ID is 172.16.0.3, vrf id 0
Default local pref 100, local AS 65101
Status codes:  s suppressed, d damped, h history, * valid, > best, = multipath,
               i internal, r RIB-failure, S Stale, R Removed
Nexthop codes: @NNN nexthop's vrf id, < announce-nh-self
Origin codes:  i - IGP, e - EGP, ? - incomplete
RPKI validation codes: V valid, I invalid, N Not found

    Network          Next Hop            Metric LocPrf Weight Path
 *> 10.0.1.0/24      172.16.0.15              0             0 65201 i
 *                    172.16.0.2                             0 65000 65100 65201 i
 *> 10.0.2.0/24      172.16.0.17              0             0 65202 i

Displayed  2 routes and 3 total paths
""")

    # lf0: only locally originated (sessions down)
    write("bgp_tables/lf0.txt", """\
BGP table version is 1, local router ID is 172.16.0.5, vrf id 0
Default local pref 100, local AS 65199
Status codes:  s suppressed, d damped, h history, * valid, > best, = multipath,
               i internal, r RIB-failure, S Stale, R Removed
Nexthop codes: @NNN nexthop's vrf id, < announce-nh-self
Origin codes:  i - IGP, e - EGP, ? - incomplete
RPKI validation codes: V valid, I invalid, N Not found

    Network          Next Hop            Metric LocPrf Weight Path
 *> 10.0.0.0/24      0.0.0.0                  0         32768 i

Displayed  1 routes and 1 total paths
""")

    # lf1: local 10.0.1.0/24, 10.0.2.0/24 with RIB-failure (static blackhole wins)
    write("bgp_tables/lf1.txt", """\
BGP table version is 3, local router ID is 172.16.0.7, vrf id 0
Default local pref 100, local AS 65201
Status codes:  s suppressed, d damped, h history, * valid, > best, = multipath,
               i internal, r RIB-failure, S Stale, R Removed
Nexthop codes: @NNN nexthop's vrf id, < announce-nh-self
Origin codes:  i - IGP, e - EGP, ? - incomplete
RPKI validation codes: V valid, I invalid, N Not found

    Network          Next Hop            Metric LocPrf Weight Path
 *> 10.0.1.0/24      0.0.0.0                  0         32768 i
 r> 10.0.2.0/24      172.16.0.14              0             0 65101 65202 i
 r                    172.16.0.6                             0 65100 65000 65101 65202 i

Displayed  2 routes and 3 total paths
""")

    # lf2: local 10.0.2.0/24, 10.0.1.0/24 only from sp1
    write("bgp_tables/lf2.txt", """\
BGP table version is 3, local router ID is 172.16.0.9, vrf id 0
Default local pref 100, local AS 65202
Status codes:  s suppressed, d damped, h history, * valid, > best, = multipath,
               i internal, r RIB-failure, S Stale, R Removed
Nexthop codes: @NNN nexthop's vrf id, < announce-nh-self
Origin codes:  i - IGP, e - EGP, ? - incomplete
RPKI validation codes: V valid, I invalid, N Not found

    Network          Next Hop            Metric LocPrf Weight Path
 *> 10.0.1.0/24      172.16.0.16              0             0 65101 65201 i
 *> 10.0.2.0/24      0.0.0.0                  0         32768 i

Displayed  2 routes and 2 total paths
""")

    # lf3: routes from sp0 only, no locally originated
    write("bgp_tables/lf3.txt", """\
BGP table version is 3, local router ID is 172.16.0.11, vrf id 0
Default local pref 100, local AS 65203
Status codes:  s suppressed, d damped, h history, * valid, > best, = multipath,
               i internal, r RIB-failure, S Stale, R Removed
Nexthop codes: @NNN nexthop's vrf id, < announce-nh-self
Origin codes:  i - IGP, e - EGP, ? - incomplete
RPKI validation codes: V valid, I invalid, N Not found

    Network          Next Hop            Metric LocPrf Weight Path
 *> 10.0.1.0/24      172.16.0.10              0             0 65100 65201 i
 *> 10.0.2.0/24      172.16.0.10              0             0 65100 65000 65101 65202 i

Displayed  2 routes and 2 total paths
""")


def gen_routing_tables():
    hdr = """\
Codes: K - kernel route, C - connected, S - static, R - RIP,
       O - OSPF, I - IS-IS, B - BGP, E - EIGRP, N - NHRP,
       T - Table, v - VNC, V - VNC-Direct, A - Babel, F - PBR,
       f - OpenFabric,
       > - selected route, * - FIB route, q - queued, r - rejected, b - backup
       t - trapped, o - offload failure

"""
    write("routing_tables/ss0.txt", hdr + """\
B>* 10.0.1.0/24 [20/0] via 172.16.0.1, eth0, weight 1, 02:15:33
                        via 172.16.0.3, eth1, weight 1, 02:15:31
B>* 10.0.2.0/24 [20/0] via 172.16.0.3, eth1, weight 1, 02:15:31
C>* 172.16.0.0/31 is directly connected, eth0, 02:30:00
C>* 172.16.0.2/31 is directly connected, eth1, 02:30:00
""")

    write("routing_tables/sp0.txt", hdr + """\
B>* 10.0.1.0/24 [20/0] via 172.16.0.7, eth2, weight 1, 02:15:28
B>* 10.0.2.0/24 [20/0] via 172.16.0.0, eth0, weight 1, 02:15:33
C>* 172.16.0.0/31 is directly connected, eth0, 02:30:00
C>* 172.16.0.4/31 is directly connected, eth1, 02:30:00
C>* 172.16.0.6/31 is directly connected, eth2, 02:30:00
C>* 172.16.0.8/31 is directly connected, eth3, 02:30:00
C>* 172.16.0.10/31 is directly connected, eth4, 02:30:00
""")

    write("routing_tables/sp1.txt", hdr + """\
B>* 10.0.1.0/24 [20/0] via 172.16.0.15, eth2, weight 1, 02:15:27
B>* 10.0.2.0/24 [20/0] via 172.16.0.17, eth3, weight 1, 02:15:28
C>* 172.16.0.2/31 is directly connected, eth0, 02:30:00
C>* 172.16.0.12/31 is directly connected, eth1, 02:30:00
C>* 172.16.0.14/31 is directly connected, eth2, 02:30:00
C>* 172.16.0.16/31 is directly connected, eth3, 02:30:00
C>* 172.16.0.18/31 is directly connected, eth4, 02:30:00
""")

    # lf0: no BGP routes (sessions down)
    write("routing_tables/lf0.txt", hdr + """\
C>* 10.0.0.0/24 is directly connected, eth2, 02:30:00
C>* 172.16.0.4/31 is directly connected, eth0, 02:30:00
C>* 172.16.0.12/31 is directly connected, eth1, 02:30:00
""")

    # lf1: FAULT visible here — static Null0 route for 10.0.2.0/24
    write("routing_tables/lf1.txt", hdr + """\
S>* 10.0.2.0/24 [1/0] is directly connected, Null0, weight 1, 03:45:12
C>* 10.0.1.0/24 is directly connected, eth2, 02:30:00
C>* 172.16.0.6/31 is directly connected, eth0, 02:30:00
C>* 172.16.0.14/31 is directly connected, eth1, 02:30:00
""")

    # lf2: only sp1 routes (sp0 session Active)
    write("routing_tables/lf2.txt", hdr + """\
B>* 10.0.1.0/24 [20/0] via 172.16.0.16, eth1, weight 1, 02:15:28
C>* 10.0.2.0/24 is directly connected, eth2, 02:30:00
C>* 172.16.0.8/31 is directly connected, eth0, 02:30:00
C>* 172.16.0.16/31 is directly connected, eth1, 02:30:00
""")

    # lf3: routes only via sp0 (sp1 session Active)
    write("routing_tables/lf3.txt", hdr + """\
B>* 10.0.1.0/24 [20/0] via 172.16.0.10, eth0, weight 1, 02:15:30
B>* 10.0.2.0/24 [20/0] via 172.16.0.10, eth0, weight 1, 02:15:30
C>* 10.0.3.0/24 is directly connected, eth2, 02:30:00
C>* 172.16.0.10/31 is directly connected, eth0, 02:30:00
C>* 172.16.0.18/31 is directly connected, eth1, 02:30:00
""")


def gen_interfaces():
    write("interfaces/ss0.txt", """\
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
    inet 127.0.0.1/8 scope host lo
       valid_lft forever preferred_lft forever
10: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000
    link/ether fe:bc:45:4a:7c:9f brd ff:ff:ff:ff:ff:ff
    inet 172.16.0.0/31 scope global eth0
       valid_lft forever preferred_lft forever
11: eth1: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000
    link/ether 36:b9:4d:bf:fa:ae brd ff:ff:ff:ff:ff:ff
    inet 172.16.0.2/31 scope global eth1
       valid_lft forever preferred_lft forever
""")

    write("interfaces/sp0.txt", """\
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
    inet 127.0.0.1/8 scope host lo
       valid_lft forever preferred_lft forever
20: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000
    link/ether 2a:b0:15:55:8b:3a brd ff:ff:ff:ff:ff:ff
    inet 172.16.0.1/31 scope global eth0
       valid_lft forever preferred_lft forever
21: eth1: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000
    link/ether 0e:22:cd:97:8a:53 brd ff:ff:ff:ff:ff:ff
    inet 172.16.0.4/31 scope global eth1
       valid_lft forever preferred_lft forever
22: eth2: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000
    link/ether a2:83:b3:16:59:03 brd ff:ff:ff:ff:ff:ff
    inet 172.16.0.6/31 scope global eth2
       valid_lft forever preferred_lft forever
23: eth3: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000
    link/ether 4c:d1:e8:73:29:b5 brd ff:ff:ff:ff:ff:ff
    inet 172.16.0.8/31 scope global eth3
       valid_lft forever preferred_lft forever
24: eth4: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000
    link/ether e7:f9:12:34:56:78 brd ff:ff:ff:ff:ff:ff
    inet 172.16.0.10/31 scope global eth4
       valid_lft forever preferred_lft forever
""")

    write("interfaces/sp1.txt", """\
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
    inet 127.0.0.1/8 scope host lo
       valid_lft forever preferred_lft forever
30: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000
    link/ether 36:00:7f:2e:0d:2f brd ff:ff:ff:ff:ff:ff
    inet 172.16.0.3/31 scope global eth0
       valid_lft forever preferred_lft forever
31: eth1: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000
    link/ether 7e:c4:3a:19:d8:cc brd ff:ff:ff:ff:ff:ff
    inet 172.16.0.12/31 scope global eth1
       valid_lft forever preferred_lft forever
32: eth2: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000
    link/ether fa:30:7c:c3:b2:20 brd ff:ff:ff:ff:ff:ff
    inet 172.16.0.14/31 scope global eth2
       valid_lft forever preferred_lft forever
33: eth3: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000
    link/ether 8b:22:5d:e1:f3:47 brd ff:ff:ff:ff:ff:ff
    inet 172.16.0.16/31 scope global eth3
       valid_lft forever preferred_lft forever
34: eth4: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000
    link/ether 3d:a1:2b:c8:e4:f0 brd ff:ff:ff:ff:ff:ff
    inet 172.16.0.18/31 scope global eth4
       valid_lft forever preferred_lft forever
""")

    write("interfaces/lf0.txt", """\
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
    inet 127.0.0.1/8 scope host lo
       valid_lft forever preferred_lft forever
40: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000
    link/ether aa:ec:84:6d:05:28 brd ff:ff:ff:ff:ff:ff
    inet 172.16.0.5/31 scope global eth0
       valid_lft forever preferred_lft forever
41: eth1: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000
    link/ether 5a:8a:78:5d:e0:e0 brd ff:ff:ff:ff:ff:ff
    inet 172.16.0.13/31 scope global eth1
       valid_lft forever preferred_lft forever
42: eth2: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000
    link/ether a6:c5:5b:e1:72:3f brd ff:ff:ff:ff:ff:ff
    inet 10.0.0.1/24 scope global eth2
       valid_lft forever preferred_lft forever
""")

    write("interfaces/lf1.txt", """\
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
    inet 127.0.0.1/8 scope host lo
       valid_lft forever preferred_lft forever
50: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000
    link/ether 82:d5:ff:90:3f:73 brd ff:ff:ff:ff:ff:ff
    inet 172.16.0.7/31 scope global eth0
       valid_lft forever preferred_lft forever
51: eth1: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000
    link/ether 8a:64:0a:91:41:6c brd ff:ff:ff:ff:ff:ff
    inet 172.16.0.15/31 scope global eth1
       valid_lft forever preferred_lft forever
52: eth2: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000
    link/ether 26:57:01:cc:2a:ed brd ff:ff:ff:ff:ff:ff
    inet 10.0.1.1/24 scope global eth2
       valid_lft forever preferred_lft forever
""")

    write("interfaces/lf2.txt", """\
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
    inet 127.0.0.1/8 scope host lo
       valid_lft forever preferred_lft forever
60: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000
    link/ether c4:7a:9e:b3:21:d8 brd ff:ff:ff:ff:ff:ff
    inet 172.16.0.9/31 scope global eth0
       valid_lft forever preferred_lft forever
61: eth1: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000
    link/ether 3e:f2:1a:c8:45:67 brd ff:ff:ff:ff:ff:ff
    inet 172.16.0.17/31 scope global eth1
       valid_lft forever preferred_lft forever
62: eth2: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000
    link/ether 91:ab:cd:ef:12:34 brd ff:ff:ff:ff:ff:ff
    inet 10.0.2.1/24 scope global eth2
       valid_lft forever preferred_lft forever
""")

    write("interfaces/lf3.txt", """\
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
    inet 127.0.0.1/8 scope host lo
       valid_lft forever preferred_lft forever
70: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000
    link/ether d1:23:45:67:89:ab brd ff:ff:ff:ff:ff:ff
    inet 172.16.0.11/31 scope global eth0
       valid_lft forever preferred_lft forever
71: eth1: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000
    link/ether b2:34:56:78:9a:bc brd ff:ff:ff:ff:ff:ff
    inet 172.16.0.19/31 scope global eth1
       valid_lft forever preferred_lft forever
72: eth2: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc tbf state UP group default qlen 1000
    link/ether f3:45:67:89:ab:cd brd ff:ff:ff:ff:ff:ff
    inet 10.0.3.1/24 scope global eth2
       valid_lft forever preferred_lft forever
""")

    write("interfaces/h0.txt", """\
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
    inet 127.0.0.1/8 scope host lo
       valid_lft forever preferred_lft forever
80: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000
    link/ether ce:75:cf:21:3e:e7 brd ff:ff:ff:ff:ff:ff
    inet 10.0.0.2/24 scope global eth0
       valid_lft forever preferred_lft forever
""")

    write("interfaces/h1.txt", """\
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
    inet 127.0.0.1/8 scope host lo
       valid_lft forever preferred_lft forever
90: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000
    link/ether f6:97:4a:59:b5:1f brd ff:ff:ff:ff:ff:ff
    inet 10.0.1.2/24 scope global eth0
       valid_lft forever preferred_lft forever
""")

    write("interfaces/h2.txt", """\
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
    inet 127.0.0.1/8 scope host lo
       valid_lft forever preferred_lft forever
100: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000
    link/ether d2:13:45:67:89:ab brd ff:ff:ff:ff:ff:ff
    inet 10.0.2.2/24 scope global eth0
       valid_lft forever preferred_lft forever
""")

    # h3: FAULT — /16 netmask instead of /24
    write("interfaces/h3.txt", """\
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
    inet 127.0.0.1/8 scope host lo
       valid_lft forever preferred_lft forever
110: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000
    link/ether a4:56:78:9a:bc:de brd ff:ff:ff:ff:ff:ff
    inet 10.0.3.2/16 scope global eth0
       valid_lft forever preferred_lft forever
""")


def gen_host_configs():
    write_json("host_configs/h0.json", {
        "hostname": "h0",
        "interface": "eth0",
        "ip_address": "10.0.0.2/24",
        "default_gateway": "10.0.0.1",
        "dns_server": "8.8.8.8",
        "ip_route": "default via 10.0.0.1 dev eth0\n10.0.0.0/24 dev eth0 proto kernel scope link src 10.0.0.2"
    })
    write_json("host_configs/h1.json", {
        "hostname": "h1",
        "interface": "eth0",
        "ip_address": "10.0.1.2/24",
        "default_gateway": "10.0.1.1",
        "dns_server": "8.8.8.8",
        "ip_route": "default via 10.0.1.1 dev eth0\n10.0.1.0/24 dev eth0 proto kernel scope link src 10.0.1.2"
    })
    write_json("host_configs/h2.json", {
        "hostname": "h2",
        "interface": "eth0",
        "ip_address": "10.0.2.2/24",
        "default_gateway": "10.0.2.1",
        "dns_server": "8.8.8.8",
        "ip_route": "default via 10.0.2.1 dev eth0\n10.0.2.0/24 dev eth0 proto kernel scope link src 10.0.2.2"
    })
    # h3: FAULT — /16 netmask instead of /24
    write_json("host_configs/h3.json", {
        "hostname": "h3",
        "interface": "eth0",
        "ip_address": "10.0.3.2/16",
        "default_gateway": "10.0.3.1",
        "dns_server": "8.8.8.8",
        "ip_route": "default via 10.0.3.1 dev eth0\n10.0.0.0/16 dev eth0 proto kernel scope link src 10.0.3.2"
    })


def gen_nftables():
    empty_nft = "table inet filter {\n}\n"
    # Clean: ss0, lf0, lf1, lf2, lf3
    for dev in ["ss0", "lf0", "lf1", "lf2", "lf3"]:
        write(f"nftables/{dev}.txt", empty_nft)

    # sp0: PLANNED CHANGE (SEC-0088) — ICMP rate limit in forward chain
    write("nftables/sp0.txt", """\
table inet filter {
    chain forward {
        type filter hook forward priority filter; policy accept;
        ip protocol icmp limit rate 50/second burst 20 packets counter packets 24819 bytes 2084796 accept
        ip protocol icmp counter packets 156 bytes 13104 drop
    }
}
""")

    # sp1: FAULT — BGP port 179 blocked on eth4 (toward lf3), misleading table name
    write("nftables/sp1.txt", """\
table inet filter {
}
table inet sec_hardening {
    chain ingress {
        type filter hook input priority filter; policy accept;
        iifname "eth4" tcp dport 179 counter packets 1847 bytes 92350 drop
    }
    chain egress {
        type filter hook output priority filter; policy accept;
        oifname "eth4" tcp dport 179 counter packets 1203 bytes 60150 drop
    }
}
""")


def gen_tc():
    default_tc_tpl = "qdisc fq_codel 0: dev {eth} root refcnt 2 limit 10240p flows 1024 quantum 1514 target 5ms interval 100ms memory_limit 32Mb ecn drop_batch 64\n"

    router_ifaces = {
        "ss0": ["eth0", "eth1"],
        "sp0": ["eth0", "eth1", "eth2", "eth3", "eth4"],
        "sp1": ["eth0", "eth1", "eth2", "eth3", "eth4"],
        "lf0": ["eth0", "eth1", "eth2"],
        "lf1": ["eth0", "eth1", "eth2"],
        "lf2": ["eth0", "eth1", "eth2"],
        "lf3": ["eth0", "eth1", "eth2"],
    }

    for dev, ifaces in router_ifaces.items():
        for iface in ifaces:
            if dev == "lf3" and iface == "eth2":
                # PLANNED CHANGE (OPS-4521) — tenant bandwidth cap
                write(f"tc/{dev}_{iface}.txt",
                      "qdisc tbf 8001: dev eth2 root refcnt 2 rate 50Mbit burst 64Kb lat 50ms \n")
            else:
                write(f"tc/{dev}_{iface}.txt", default_tc_tpl.format(eth=iface))


def gen_reachability():
    results = {
        "description": "ICMP reachability matrix: 3 echo packets between all host pairs and diagnostic paths",
        "timestamp": "2025-11-28T16:21:30Z",
        "host_to_host": [
            {"src": "h0", "dst": "h1", "dst_ip": "10.0.1.2",
             "packets_tx": 3, "packets_rx": 0, "loss_percent": 100.0,
             "rtt_avg_ms": None, "status": "unreachable",
             "notes": "No route to 10.0.1.0/24 in lf0 routing table; lf0 BGP sessions not established"},
            {"src": "h0", "dst": "h2", "dst_ip": "10.0.2.2",
             "packets_tx": 3, "packets_rx": 0, "loss_percent": 100.0,
             "rtt_avg_ms": None, "status": "unreachable",
             "notes": "No route to 10.0.2.0/24 in lf0 routing table"},
            {"src": "h0", "dst": "h3", "dst_ip": "10.0.3.2",
             "packets_tx": 3, "packets_rx": 0, "loss_percent": 100.0,
             "rtt_avg_ms": None, "status": "unreachable",
             "notes": "No route to 10.0.3.0/24 in lf0 routing table"},
            {"src": "h1", "dst": "h0", "dst_ip": "10.0.0.2",
             "packets_tx": 3, "packets_rx": 0, "loss_percent": 100.0,
             "rtt_avg_ms": None, "status": "unreachable",
             "notes": "Network 10.0.0.0/24 not present in fabric routing tables"},
            {"src": "h1", "dst": "h2", "dst_ip": "10.0.2.2",
             "packets_tx": 3, "packets_rx": 0, "loss_percent": 100.0,
             "rtt_avg_ms": None, "status": "unreachable",
             "notes": "Packets dropped at lf1 — routing table shows Null0 for 10.0.2.0/24"},
            {"src": "h1", "dst": "h3", "dst_ip": "10.0.3.2",
             "packets_tx": 3, "packets_rx": 0, "loss_percent": 100.0,
             "rtt_avg_ms": None, "status": "unreachable",
             "notes": "Network 10.0.3.0/24 not present in fabric routing tables"},
            {"src": "h2", "dst": "h0", "dst_ip": "10.0.0.2",
             "packets_tx": 3, "packets_rx": 0, "loss_percent": 100.0,
             "rtt_avg_ms": None, "status": "unreachable",
             "notes": "Network 10.0.0.0/24 not present in fabric routing tables"},
            {"src": "h2", "dst": "h1", "dst_ip": "10.0.1.2",
             "packets_tx": 3, "packets_rx": 3, "loss_percent": 0.0,
             "rtt_avg_ms": 1.2, "status": "reachable",
             "notes": "Path via sp1 operational"},
            {"src": "h2", "dst": "h3", "dst_ip": "10.0.3.2",
             "packets_tx": 3, "packets_rx": 0, "loss_percent": 100.0,
             "rtt_avg_ms": None, "status": "unreachable",
             "notes": "Network 10.0.3.0/24 not present in fabric routing tables"},
            {"src": "h3", "dst": "h0", "dst_ip": "10.0.0.2",
             "packets_tx": 3, "packets_rx": 0, "loss_percent": 100.0,
             "rtt_avg_ms": None, "status": "unreachable",
             "notes": "ARP resolution failure: h3 attempts direct L2 for 10.0.0.2 (within configured /16)"},
            {"src": "h3", "dst": "h1", "dst_ip": "10.0.1.2",
             "packets_tx": 3, "packets_rx": 0, "loss_percent": 100.0,
             "rtt_avg_ms": None, "status": "unreachable",
             "notes": "ARP resolution failure: h3 attempts direct L2 for 10.0.1.2 (within configured /16)"},
            {"src": "h3", "dst": "h2", "dst_ip": "10.0.2.2",
             "packets_tx": 3, "packets_rx": 0, "loss_percent": 100.0,
             "rtt_avg_ms": None, "status": "unreachable",
             "notes": "ARP resolution failure: h3 attempts direct L2 for 10.0.2.2 (within configured /16)"},
        ],
        "host_to_leaf": [
            {"src": "h0", "dst": "lf0", "dst_ip": "10.0.0.1",
             "packets_tx": 3, "packets_rx": 3, "loss_percent": 0.0,
             "rtt_avg_ms": 0.4, "status": "reachable"},
            {"src": "h1", "dst": "lf1", "dst_ip": "10.0.1.1",
             "packets_tx": 3, "packets_rx": 3, "loss_percent": 0.0,
             "rtt_avg_ms": 0.3, "status": "reachable"},
            {"src": "h2", "dst": "lf2", "dst_ip": "10.0.2.1",
             "packets_tx": 3, "packets_rx": 3, "loss_percent": 0.0,
             "rtt_avg_ms": 0.3, "status": "reachable"},
            {"src": "h3", "dst": "lf3", "dst_ip": "10.0.3.1",
             "packets_tx": 3, "packets_rx": 3, "loss_percent": 0.0,
             "rtt_avg_ms": 0.5, "status": "reachable"},
        ],
        "spine_reachability": [
            {"src": "lf0", "dst": "sp0", "dst_ip": "172.16.0.4",
             "packets_tx": 3, "packets_rx": 3, "loss_percent": 0.0,
             "rtt_avg_ms": 0.2, "status": "reachable"},
            {"src": "lf0", "dst": "sp1", "dst_ip": "172.16.0.12",
             "packets_tx": 3, "packets_rx": 3, "loss_percent": 0.0,
             "rtt_avg_ms": 0.2, "status": "reachable"},
            {"src": "lf1", "dst": "sp0", "dst_ip": "172.16.0.6",
             "packets_tx": 3, "packets_rx": 3, "loss_percent": 0.0,
             "rtt_avg_ms": 0.2, "status": "reachable"},
            {"src": "lf1", "dst": "sp1", "dst_ip": "172.16.0.14",
             "packets_tx": 3, "packets_rx": 3, "loss_percent": 0.0,
             "rtt_avg_ms": 0.3, "status": "reachable"},
            {"src": "lf2", "dst": "sp0", "dst_ip": "172.16.0.8",
             "packets_tx": 3, "packets_rx": 3, "loss_percent": 0.0,
             "rtt_avg_ms": 0.2, "status": "reachable",
             "notes": "L3 ICMP reachable but BGP session in Active state — TCP-level issue suspected"},
            {"src": "lf2", "dst": "sp1", "dst_ip": "172.16.0.16",
             "packets_tx": 3, "packets_rx": 3, "loss_percent": 0.0,
             "rtt_avg_ms": 0.3, "status": "reachable"},
            {"src": "lf3", "dst": "sp0", "dst_ip": "172.16.0.10",
             "packets_tx": 3, "packets_rx": 3, "loss_percent": 0.0,
             "rtt_avg_ms": 0.2, "status": "reachable"},
            {"src": "lf3", "dst": "sp1", "dst_ip": "172.16.0.18",
             "packets_tx": 3, "packets_rx": 3, "loss_percent": 0.0,
             "rtt_avg_ms": 0.3, "status": "reachable",
             "notes": "L3 ICMP reachable but BGP session in Active state — TCP-level issue suspected"},
        ],
    }
    write_json("reachability.json", results)


def gen_bgp_logs():
    # lf0: "Bad Peer AS" NOTIFICATIONs from both spines
    write("bgp_logs/lf0_frr.log", """\
2025-11-28T14:00:01.234 BGP: 172.16.0.4 [FSM] Timer (start timer expire).
2025-11-28T14:00:01.235 BGP: 172.16.0.4 [FSM] BGP_Start (Idle->Connect), fd -1
2025-11-28T14:00:01.236 BGP: 172.16.0.4 [FSM] Trying to connect to 172.16.0.4 port 179
2025-11-28T14:00:01.238 BGP: 172.16.0.4 open active, local address 172.16.0.5
2025-11-28T14:00:01.240 BGP: 172.16.0.4 [FSM] TCP_connection_open (Connect->OpenSent), fd 8
2025-11-28T14:00:01.241 BGP: 172.16.0.4 sending OPEN, version 4, my as 65199, holdtime 180 id 172.16.0.5
2025-11-28T14:00:01.243 BGP: 172.16.0.4 rcv NOTIFICATION (code 2 subcode 2) Bad Peer AS
2025-11-28T14:00:01.244 BGP: 172.16.0.4 [FSM] NOTIFICATION received (OpenSent->Idle)
2025-11-28T14:00:01.245 BGP: 172.16.0.4 [Event] BGP connection closed fd 8
2025-11-28T14:00:31.250 BGP: 172.16.0.4 [FSM] Timer (start timer expire).
2025-11-28T14:00:31.251 BGP: 172.16.0.4 [FSM] BGP_Start (Idle->Connect), fd -1
2025-11-28T14:00:31.253 BGP: 172.16.0.4 sending OPEN, version 4, my as 65199, holdtime 180 id 172.16.0.5
2025-11-28T14:00:31.256 BGP: 172.16.0.4 rcv NOTIFICATION (code 2 subcode 2) Bad Peer AS
2025-11-28T14:00:31.257 BGP: 172.16.0.4 [FSM] NOTIFICATION received (OpenSent->Idle)
2025-11-28T14:01:01.260 BGP: 172.16.0.12 [FSM] Timer (start timer expire).
2025-11-28T14:01:01.261 BGP: 172.16.0.12 [FSM] BGP_Start (Idle->Connect), fd -1
2025-11-28T14:01:01.263 BGP: 172.16.0.12 sending OPEN, version 4, my as 65199, holdtime 180 id 172.16.0.5
2025-11-28T14:01:01.266 BGP: 172.16.0.12 rcv NOTIFICATION (code 2 subcode 2) Bad Peer AS
2025-11-28T14:01:01.267 BGP: 172.16.0.12 [FSM] NOTIFICATION received (OpenSent->Idle)
""")

    # sp0: lf0 "Bad Peer AS"; lf2 TCP timeout; lf1/lf3 normal
    write("bgp_logs/sp0_frr.log", """\
2025-11-28T14:00:01.239 BGP: 172.16.0.5 rcv OPEN w/ OPTION://
2025-11-28T14:00:01.240 BGP: 172.16.0.5 rcv OPEN, version 4, remote-as (in open) 65199
2025-11-28T14:00:01.241 BGP: 172.16.0.5 bad OPEN, remote AS is 65199, expected 65200
2025-11-28T14:00:01.242 BGP: %NOTIFICATION: sent to neighbor 172.16.0.5 2/2 (Bad Peer AS) 0 bytes
2025-11-28T14:00:01.243 BGP: 172.16.0.5 [FSM] NOTIFICATION sent (OpenSent->Idle)
2025-11-28T14:00:01.300 BGP: 172.16.0.7 [FSM] TCP_connection_open (Connect->OpenSent)
2025-11-28T14:00:01.301 BGP: 172.16.0.7 rcv OPEN, version 4, remote-as 65201
2025-11-28T14:00:01.302 BGP: 172.16.0.7 [FSM] BGP_OPEN received (OpenSent->OpenConfirm)
2025-11-28T14:00:01.303 BGP: 172.16.0.7 [FSM] BGP_KEEPALIVE received (OpenConfirm->Established)
2025-11-28T14:00:01.310 BGP: 172.16.0.11 [FSM] TCP_connection_open (Connect->OpenSent)
2025-11-28T14:00:01.311 BGP: 172.16.0.11 rcv OPEN, version 4, remote-as 65203
2025-11-28T14:00:01.312 BGP: 172.16.0.11 [FSM] BGP_OPEN received (OpenSent->OpenConfirm)
2025-11-28T14:00:01.313 BGP: 172.16.0.11 [FSM] BGP_KEEPALIVE received (OpenConfirm->Established)
2025-11-28T14:00:05.400 BGP: 172.16.0.9 [FSM] Timer (start timer expire).
2025-11-28T14:00:05.401 BGP: 172.16.0.9 [FSM] BGP_Start (Idle->Connect), fd -1
2025-11-28T14:00:05.402 BGP: 172.16.0.9 [FSM] Trying to connect to 172.16.0.9 port 179
2025-11-28T14:00:35.403 BGP: 172.16.0.9 [FSM] TCP connection timed out (Connect->Active)
2025-11-28T14:01:05.410 BGP: 172.16.0.9 [FSM] Timer (start timer expire).
2025-11-28T14:01:05.411 BGP: 172.16.0.9 [FSM] BGP_Start (Active->Connect), fd -1
2025-11-28T14:01:05.412 BGP: 172.16.0.9 [FSM] Trying to connect to 172.16.0.9 port 179
2025-11-28T14:01:35.413 BGP: 172.16.0.9 [FSM] TCP connection timed out (Connect->Active)
""")

    # sp1: lf0 "Bad Peer AS"; lf3 TCP timeout; lf1/lf2 normal
    write("bgp_logs/sp1_frr.log", """\
2025-11-28T14:00:01.250 BGP: 172.16.0.13 rcv OPEN w/ OPTION://
2025-11-28T14:00:01.251 BGP: 172.16.0.13 rcv OPEN, version 4, remote-as (in open) 65199
2025-11-28T14:00:01.252 BGP: 172.16.0.13 bad OPEN, remote AS is 65199, expected 65200
2025-11-28T14:00:01.253 BGP: %NOTIFICATION: sent to neighbor 172.16.0.13 2/2 (Bad Peer AS) 0 bytes
2025-11-28T14:00:01.254 BGP: 172.16.0.13 [FSM] NOTIFICATION sent (OpenSent->Idle)
2025-11-28T14:00:01.320 BGP: 172.16.0.15 [FSM] TCP_connection_open (Connect->OpenSent)
2025-11-28T14:00:01.321 BGP: 172.16.0.15 rcv OPEN, version 4, remote-as 65201
2025-11-28T14:00:01.322 BGP: 172.16.0.15 [FSM] BGP_OPEN received (OpenSent->OpenConfirm)
2025-11-28T14:00:01.323 BGP: 172.16.0.15 [FSM] BGP_KEEPALIVE received (OpenConfirm->Established)
2025-11-28T14:00:01.330 BGP: 172.16.0.17 [FSM] TCP_connection_open (Connect->OpenSent)
2025-11-28T14:00:01.331 BGP: 172.16.0.17 rcv OPEN, version 4, remote-as 65202
2025-11-28T14:00:01.332 BGP: 172.16.0.17 [FSM] BGP_OPEN received (OpenSent->OpenConfirm)
2025-11-28T14:00:01.333 BGP: 172.16.0.17 [FSM] BGP_KEEPALIVE received (OpenConfirm->Established)
2025-11-28T14:00:06.500 BGP: 172.16.0.19 [FSM] Timer (start timer expire).
2025-11-28T14:00:06.501 BGP: 172.16.0.19 [FSM] BGP_Start (Idle->Connect), fd -1
2025-11-28T14:00:06.502 BGP: 172.16.0.19 [FSM] Trying to connect to 172.16.0.19 port 179
2025-11-28T14:00:36.503 BGP: 172.16.0.19 [FSM] TCP connection timed out (Connect->Active)
2025-11-28T14:01:06.510 BGP: 172.16.0.19 [FSM] Timer (start timer expire).
2025-11-28T14:01:06.511 BGP: 172.16.0.19 [FSM] BGP_Start (Active->Connect), fd -1
2025-11-28T14:01:06.512 BGP: 172.16.0.19 [FSM] Trying to connect to 172.16.0.19 port 179
2025-11-28T14:01:36.513 BGP: 172.16.0.19 [FSM] TCP connection timed out (Connect->Active)
""")

    # lf2: sp0 TCP timeouts (TCP-MD5 mismatch prevents connection)
    write("bgp_logs/lf2_frr.log", """\
2025-11-28T14:00:02.100 BGP: 172.16.0.8 [FSM] Timer (start timer expire).
2025-11-28T14:00:02.101 BGP: 172.16.0.8 [FSM] BGP_Start (Idle->Connect), fd -1
2025-11-28T14:00:02.102 BGP: 172.16.0.8 [FSM] Trying to connect to 172.16.0.8 port 179
2025-11-28T14:00:32.103 BGP: 172.16.0.8 [FSM] TCP connection timed out (Connect->Active)
2025-11-28T14:01:02.110 BGP: 172.16.0.8 [FSM] Timer (start timer expire).
2025-11-28T14:01:02.111 BGP: 172.16.0.8 [FSM] BGP_Start (Active->Connect), fd -1
2025-11-28T14:01:02.112 BGP: 172.16.0.8 [FSM] Trying to connect to 172.16.0.8 port 179
2025-11-28T14:01:32.113 BGP: 172.16.0.8 [FSM] TCP connection timed out (Connect->Active)
2025-11-28T14:00:02.200 BGP: 172.16.0.16 [FSM] TCP_connection_open (Connect->OpenSent)
2025-11-28T14:00:02.201 BGP: 172.16.0.16 rcv OPEN, version 4, remote-as 65101
2025-11-28T14:00:02.202 BGP: 172.16.0.16 [FSM] BGP_OPEN received (OpenSent->OpenConfirm)
2025-11-28T14:00:02.203 BGP: 172.16.0.16 [FSM] BGP_KEEPALIVE received (OpenConfirm->Established)
""")

    # lf3: sp1 TCP timeouts (nftables blocking port 179 on sp1 side)
    write("bgp_logs/lf3_frr.log", """\
2025-11-28T14:00:03.100 BGP: 172.16.0.10 [FSM] TCP_connection_open (Connect->OpenSent)
2025-11-28T14:00:03.101 BGP: 172.16.0.10 rcv OPEN, version 4, remote-as 65100
2025-11-28T14:00:03.102 BGP: 172.16.0.10 [FSM] BGP_OPEN received (OpenSent->OpenConfirm)
2025-11-28T14:00:03.103 BGP: 172.16.0.10 [FSM] BGP_KEEPALIVE received (OpenConfirm->Established)
2025-11-28T14:00:03.200 BGP: 172.16.0.18 [FSM] Timer (start timer expire).
2025-11-28T14:00:03.201 BGP: 172.16.0.18 [FSM] BGP_Start (Idle->Connect), fd -1
2025-11-28T14:00:03.202 BGP: 172.16.0.18 [FSM] Trying to connect to 172.16.0.18 port 179
2025-11-28T14:00:33.203 BGP: 172.16.0.18 [FSM] TCP connection timed out (Connect->Active)
2025-11-28T14:01:03.210 BGP: 172.16.0.18 [FSM] Timer (start timer expire).
2025-11-28T14:01:03.211 BGP: 172.16.0.18 [FSM] BGP_Start (Active->Connect), fd -1
2025-11-28T14:01:03.212 BGP: 172.16.0.18 [FSM] Trying to connect to 172.16.0.18 port 179
2025-11-28T14:01:33.213 BGP: 172.16.0.18 [FSM] TCP connection timed out (Connect->Active)
""")


def gen_pcaps():
    """Generate synthetic packet captures for protocol-level forensic analysis."""
    captures_dir = os.path.join(BASE, "captures")
    base_ts = 1732798800  # 2025-11-28 14:00:00 UTC

    # MAC addresses (matching interface definitions)
    lf0_mac = mac_to_bytes('aa:ec:84:6d:05:28')
    sp0_eth1_mac = mac_to_bytes('0e:22:cd:97:8a:53')
    lf2_mac = mac_to_bytes('c4:7a:9e:b3:21:d8')
    sp0_eth3_mac = mac_to_bytes('4c:d1:e8:73:29:b5')
    sp1_eth4_mac = mac_to_bytes('3d:a1:2b:c8:e4:f0')
    lf3_eth1_mac = mac_to_bytes('b2:34:56:78:9a:bc')
    h3_mac = mac_to_bytes('a4:56:78:9a:bc:de')
    lf3_eth2_mac = mac_to_bytes('f3:45:67:89:ab:cd')

    # TCP flag constants
    SYN = 0x002
    SYN_ACK = 0x012
    ACK = 0x010
    PSH_ACK = 0x018
    RST_ACK = 0x014

    # ── PCAP 1: lf0_eth0.pcap ──
    # BGP OPEN from lf0 with wrong ASN 65199, NOTIFICATION response from sp0
    bgp_open = _bgp_open(65199, 180, '172.16.0.5')
    bgp_notif = _bgp_notification(2, 2)  # Bad Peer AS

    pkts1 = [
        # TCP 3-way handshake
        (base_ts, 0, _tcp_ip_eth(lf0_mac, sp0_eth1_mac,
            '172.16.0.5', '172.16.0.4', 45678, 179, 100, 0, SYN, ident=1)),
        (base_ts, 1000, _tcp_ip_eth(sp0_eth1_mac, lf0_mac,
            '172.16.0.4', '172.16.0.5', 179, 45678, 200, 101, SYN_ACK, ident=2)),
        (base_ts, 2000, _tcp_ip_eth(lf0_mac, sp0_eth1_mac,
            '172.16.0.5', '172.16.0.4', 45678, 179, 101, 201, ACK, ident=3)),
        # BGP OPEN from lf0 (AS 65199)
        (base_ts, 3000, _tcp_ip_eth(lf0_mac, sp0_eth1_mac,
            '172.16.0.5', '172.16.0.4', 45678, 179, 101, 201, PSH_ACK,
            payload=bgp_open, ident=4)),
        # BGP NOTIFICATION from sp0 (Bad Peer AS)
        (base_ts, 4000, _tcp_ip_eth(sp0_eth1_mac, lf0_mac,
            '172.16.0.4', '172.16.0.5', 179, 45678, 201,
            101 + len(bgp_open), PSH_ACK, payload=bgp_notif, ident=5)),
        # TCP RST
        (base_ts, 5000, _tcp_ip_eth(sp0_eth1_mac, lf0_mac,
            '172.16.0.4', '172.16.0.5', 179, 45678,
            201 + len(bgp_notif), 101 + len(bgp_open), RST_ACK, ident=6)),
    ]
    _write_pcap(os.path.join(captures_dir, 'lf0_eth0.pcap'), pkts1)

    # ── PCAP 2: lf2_eth0.pcap ──
    # TCP SYN with MD5 option (kind 19), no SYN-ACK responses
    md5_opt = struct.pack('!BB', 19, 18) + b'\xde\xad\xbe\xef' * 4  # 18 bytes
    md5_opt += b'\x01\x00'  # NOP + EOL pad to 20 bytes

    pkts2 = [
        (base_ts + i, 0, _tcp_ip_eth(lf2_mac, sp0_eth3_mac,
            '172.16.0.9', '172.16.0.8', 49200, 179, 300, 0, SYN,
            options=md5_opt, ident=10 + i))
        for i in range(3)
    ]
    _write_pcap(os.path.join(captures_dir, 'lf2_eth0.pcap'), pkts2)

    # ── PCAP 3: sp1_eth4.pcap ──
    # TCP SYN in both directions, all dropped by nftables
    pkts3 = []
    for i in range(2):
        # lf3 → sp1
        pkts3.append((base_ts + i * 2, 0, _tcp_ip_eth(lf3_eth1_mac, sp1_eth4_mac,
            '172.16.0.19', '172.16.0.18', 51000, 179, 400, 0, SYN, ident=20 + i)))
        # sp1 → lf3 (outbound also blocked)
        pkts3.append((base_ts + i * 2 + 1, 0, _tcp_ip_eth(sp1_eth4_mac, lf3_eth1_mac,
            '172.16.0.18', '172.16.0.19', 52000, 179, 500, 0, SYN, ident=30 + i)))
    _write_pcap(os.path.join(captures_dir, 'sp1_eth4.pcap'), pkts3)

    # ── PCAP 4: h3_eth0.pcap ──
    # ARP requests for IPs outside /24 (h3 has /16 mask, thinks they're on-link)
    zero_mac = b'\x00\x00\x00\x00\x00\x00'
    pkts4 = [
        (base_ts, 0, _arp_packet(1, h3_mac, '10.0.3.2', zero_mac, '10.0.1.2')),
        (base_ts, 500000, _arp_packet(1, h3_mac, '10.0.3.2', zero_mac, '10.0.0.2')),
        (base_ts + 1, 0, _arp_packet(1, h3_mac, '10.0.3.2', zero_mac, '10.0.2.2')),
        # Normal ARP reply from lf3 gateway
        (base_ts + 1, 500000, _arp_packet(2, lf3_eth2_mac, '10.0.3.1', h3_mac, '10.0.3.2')),
    ]
    _write_pcap(os.path.join(captures_dir, 'h3_eth0.pcap'), pkts4)

    # Write a manifest describing available captures
    write("captures/README.txt", """\
Packet captures from key network segments during the connectivity incident.
Each capture covers a ~30-second window around the BGP session attempts.

Files:
  lf0_eth0.pcap  — Traffic on lf0 uplink (eth0) toward sp0
  lf2_eth0.pcap  — Traffic on lf2 uplink (eth0) toward sp0
  sp1_eth4.pcap  — Traffic on sp1 downlink (eth4) toward lf3
  h3_eth0.pcap   — Traffic on h3 host interface (eth0)

Use tshark or similar tools to analyze these captures.
Example: tshark -r captures/lf0_eth0.pcap -V
""")


def gen_expected_schema():
    schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "required": ["total_anomalies", "anomalies", "remediation_order",
                      "packet_forensics"],
        "properties": {
            "total_anomalies": {
                "type": "integer",
                "description": "Total count of all anomalies found (both faults and planned changes)"
            },
            "anomalies": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["device", "classification", "description"],
                    "properties": {
                        "device": {
                            "type": "string",
                            "description": "Device name where the anomaly was observed"
                        },
                        "interface": {
                            "type": ["string", "null"],
                            "description": "Specific interface involved, if applicable"
                        },
                        "classification": {
                            "type": "string",
                            "enum": ["fault", "planned_change"],
                            "description": "Whether this is a genuine fault or a documented operational change"
                        },
                        "description": {
                            "type": "string",
                            "description": "Detailed explanation of the anomaly, its root cause, its impact, and supporting evidence"
                        },
                        "ops_reference": {
                            "type": ["string", "null"],
                            "description": "Reference to ops changelog entry ID if this is a planned change; null for faults"
                        },
                        "corrected_config": {
                            "type": ["string", "null"],
                            "description": "The corrected configuration snippet or remediation command for faults; null for planned changes"
                        }
                    }
                }
            },
            "remediation_order": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Ordered list of faulty device names specifying the sequence in which faults should be remediated, accounting for inter-fault dependencies"
            },
            "packet_forensics": {
                "type": "object",
                "description": "Protocol-level evidence extracted from packet captures using tshark",
                "required": [
                    "lf0_bgp_open_as",
                    "lf0_bgp_notification_code",
                    "lf0_bgp_notification_subcode",
                    "lf2_tcp_md5_present",
                    "lf2_tcp_syn_count",
                    "lf2_tcp_synack_count",
                    "sp1_eth4_syn_count",
                    "sp1_eth4_synack_count",
                    "h3_arp_targets_outside_24"
                ],
                "properties": {
                    "lf0_bgp_open_as": {
                        "type": "integer",
                        "description": "AS number extracted from BGP OPEN message in lf0_eth0.pcap"
                    },
                    "lf0_bgp_notification_code": {
                        "type": "integer",
                        "description": "BGP NOTIFICATION major error code from lf0_eth0.pcap"
                    },
                    "lf0_bgp_notification_subcode": {
                        "type": "integer",
                        "description": "BGP NOTIFICATION minor error code from lf0_eth0.pcap"
                    },
                    "lf2_tcp_md5_present": {
                        "type": "boolean",
                        "description": "Whether TCP MD5 option (kind 19) is present in lf2_eth0.pcap SYN packets"
                    },
                    "lf2_tcp_syn_count": {
                        "type": "integer",
                        "description": "Number of TCP SYN packets (no ACK) in lf2_eth0.pcap"
                    },
                    "lf2_tcp_synack_count": {
                        "type": "integer",
                        "description": "Number of TCP SYN-ACK packets in lf2_eth0.pcap (expected 0)"
                    },
                    "sp1_eth4_syn_count": {
                        "type": "integer",
                        "description": "Number of TCP SYN packets to port 179 in sp1_eth4.pcap"
                    },
                    "sp1_eth4_synack_count": {
                        "type": "integer",
                        "description": "Number of TCP SYN-ACK packets in sp1_eth4.pcap (expected 0)"
                    },
                    "h3_arp_targets_outside_24": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of ARP target IPs from h3 that fall outside the correct /24 subnet"
                    }
                }
            }
        }
    }
    with open("/app/expected_schema.json", "w") as f:
        json.dump(schema, f, indent=2)


def main():
    mkdirs()
    gen_topology()
    gen_ops_changelog()
    gen_configs()
    gen_bgp_neighbors()
    gen_bgp_tables()
    gen_routing_tables()
    gen_interfaces()
    gen_host_configs()
    gen_nftables()
    gen_tc()
    gen_reachability()
    gen_bgp_logs()
    gen_pcaps()
    gen_expected_schema()
    print("Network state generated successfully at /app/network_state/")


if __name__ == "__main__":
    main()
