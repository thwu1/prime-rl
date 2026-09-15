#!/usr/bin/env python3
"""Generate OSPF pcap file containing the full LSDB for router R1.
Run during Docker build only - NOT included in the final image.

"""
from scapy.all import Ether, IP, wrpcap, conf
conf.verb = 0
from scapy.contrib.ospf import (
    OSPF_Hdr, OSPF_LSUpd,
    OSPF_Router_LSA, OSPF_Link,
    OSPF_SummaryIP_LSA,
    OSPF_External_LSA,
)


def make_pkt(src_ip, src_mac, router_id, lsas):
    return (
        Ether(src=src_mac, dst="01:00:5e:00:00:05") /
        IP(src=src_ip, dst="224.0.0.5", ttl=1, proto=89) /
        OSPF_Hdr(version=2, type=4, src=router_id, area="0.0.0.0") /
        OSPF_LSUpd(lsalist=lsas)
    )


# ===== ROUTER LSAs (Type 1) =====
r1_rlsa = OSPF_Router_LSA(
    age=120, options=0x22, type=1,
    id="1.1.1.1", adrouter="1.1.1.1", seq=0x80000005,
    flags=0, linklist=[
        OSPF_Link(id="2.2.2.2", data="10.0.12.1", type=1, metric=10),
        OSPF_Link(id="10.0.12.0", data="255.255.255.252", type=3, metric=10),
        OSPF_Link(id="3.3.3.3", data="10.0.13.1", type=1, metric=5),
        OSPF_Link(id="10.0.13.0", data="255.255.255.252", type=3, metric=5),
        OSPF_Link(id="1.1.1.1", data="255.255.255.255", type=3, metric=0),
    ]
)

r2_rlsa = OSPF_Router_LSA(
    age=150, options=0x22, type=1,
    id="2.2.2.2", adrouter="2.2.2.2", seq=0x80000003,
    flags=1, linklist=[
        OSPF_Link(id="1.1.1.1", data="10.0.12.2", type=1, metric=10),
        OSPF_Link(id="10.0.12.0", data="255.255.255.252", type=3, metric=10),
        OSPF_Link(id="4.4.4.4", data="10.0.24.1", type=1, metric=5),
        OSPF_Link(id="10.0.24.0", data="255.255.255.252", type=3, metric=5),
        OSPF_Link(id="2.2.2.2", data="255.255.255.255", type=3, metric=0),
    ]
)

r3_rlsa = OSPF_Router_LSA(
    age=140, options=0x22, type=1,
    id="3.3.3.3", adrouter="3.3.3.3", seq=0x80000004,
    flags=1, linklist=[
        OSPF_Link(id="1.1.1.1", data="10.0.13.2", type=1, metric=5),
        OSPF_Link(id="10.0.13.0", data="255.255.255.252", type=3, metric=5),
        OSPF_Link(id="4.4.4.4", data="10.0.34.1", type=1, metric=10),
        OSPF_Link(id="10.0.34.0", data="255.255.255.252", type=3, metric=10),
        OSPF_Link(id="3.3.3.3", data="255.255.255.255", type=3, metric=0),
    ]
)

r4_rlsa = OSPF_Router_LSA(
    age=160, options=0x22, type=1,
    id="4.4.4.4", adrouter="4.4.4.4", seq=0x80000002,
    flags=1, linklist=[
        OSPF_Link(id="2.2.2.2", data="10.0.24.2", type=1, metric=5),
        OSPF_Link(id="10.0.24.0", data="255.255.255.252", type=3, metric=5),
        OSPF_Link(id="3.3.3.3", data="10.0.34.2", type=1, metric=10),
        OSPF_Link(id="10.0.34.0", data="255.255.255.252", type=3, metric=10),
        OSPF_Link(id="4.4.4.4", data="255.255.255.255", type=3, metric=0),
    ]
)

# ===== SUMMARY LSAs (Type 3) =====
sum_r3 = [
    OSPF_SummaryIP_LSA(age=200, options=0x22, type=3, id="10.5.0.0",
        adrouter="3.3.3.3", seq=0x80000001, mask="255.255.255.0", metric=6),
    OSPF_SummaryIP_LSA(age=200, options=0x22, type=3, id="10.5.1.0",
        adrouter="3.3.3.3", seq=0x80000001, mask="255.255.255.0", metric=7),
    OSPF_SummaryIP_LSA(age=200, options=0x22, type=3, id="10.7.0.0",
        adrouter="3.3.3.3", seq=0x80000001, mask="255.255.255.0", metric=9),
    OSPF_SummaryIP_LSA(age=200, options=0x22, type=3, id="10.4.1.0",
        adrouter="3.3.3.3", seq=0x80000001, mask="255.255.255.0", metric=11),
    OSPF_SummaryIP_LSA(age=200, options=0x22, type=3, id="10.1.35.0",
        adrouter="3.3.3.3", seq=0x80000001, mask="255.255.255.252", metric=5),
    OSPF_SummaryIP_LSA(age=200, options=0x22, type=3, id="10.1.45.0",
        adrouter="3.3.3.3", seq=0x80000001, mask="255.255.255.252", metric=10),
    OSPF_SummaryIP_LSA(age=200, options=0x22, type=3, id="10.1.57.0",
        adrouter="3.3.3.3", seq=0x80000001, mask="255.255.255.252", metric=8),
]

sum_r4_a1 = [
    OSPF_SummaryIP_LSA(age=210, options=0x22, type=3, id="10.5.0.0",
        adrouter="4.4.4.4", seq=0x80000001, mask="255.255.255.0", metric=6),
    OSPF_SummaryIP_LSA(age=210, options=0x22, type=3, id="10.5.1.0",
        adrouter="4.4.4.4", seq=0x80000001, mask="255.255.255.0", metric=7),
    OSPF_SummaryIP_LSA(age=210, options=0x22, type=3, id="10.7.0.0",
        adrouter="4.4.4.4", seq=0x80000001, mask="255.255.255.0", metric=9),
    OSPF_SummaryIP_LSA(age=210, options=0x22, type=3, id="10.4.1.0",
        adrouter="4.4.4.4", seq=0x80000001, mask="255.255.255.0", metric=1),
    OSPF_SummaryIP_LSA(age=210, options=0x22, type=3, id="10.1.45.0",
        adrouter="4.4.4.4", seq=0x80000001, mask="255.255.255.252", metric=5),
    OSPF_SummaryIP_LSA(age=210, options=0x22, type=3, id="10.1.35.0",
        adrouter="4.4.4.4", seq=0x80000001, mask="255.255.255.252", metric=10),
    OSPF_SummaryIP_LSA(age=210, options=0x22, type=3, id="10.1.57.0",
        adrouter="4.4.4.4", seq=0x80000001, mask="255.255.255.252", metric=8),
]

sum_r2 = [
    OSPF_SummaryIP_LSA(age=190, options=0x22, type=3, id="10.6.0.0",
        adrouter="2.2.2.2", seq=0x80000001, mask="255.255.255.0", metric=11),
    OSPF_SummaryIP_LSA(age=190, options=0x22, type=3, id="10.2.26.0",
        adrouter="2.2.2.2", seq=0x80000001, mask="255.255.255.252", metric=10),
    OSPF_SummaryIP_LSA(age=190, options=0x22, type=3, id="10.2.46.0",
        adrouter="2.2.2.2", seq=0x80000001, mask="255.255.255.252", metric=25),
]

sum_r4_a2 = [
    OSPF_SummaryIP_LSA(age=220, options=0x22, type=3, id="10.6.0.0",
        adrouter="4.4.4.4", seq=0x80000001, mask="255.255.255.0", metric=16),
    OSPF_SummaryIP_LSA(age=220, options=0x22, type=3, id="10.2.46.0",
        adrouter="4.4.4.4", seq=0x80000001, mask="255.255.255.252", metric=15),
    OSPF_SummaryIP_LSA(age=220, options=0x22, type=3, id="10.2.26.0",
        adrouter="4.4.4.4", seq=0x80000001, mask="255.255.255.252", metric=25),
]

# ===== ASBR SUMMARY LSAs (Type 4) =====
# Same wire format as Type 3 per RFC 2328 A.4.4
asbr_lsas = [
    OSPF_SummaryIP_LSA(age=180, options=0x22, type=4, id="6.6.6.6",
        adrouter="2.2.2.2", seq=0x80000001, mask="0.0.0.0", metric=10),
    OSPF_SummaryIP_LSA(age=180, options=0x22, type=4, id="6.6.6.6",
        adrouter="4.4.4.4", seq=0x80000001, mask="0.0.0.0", metric=15),
    OSPF_SummaryIP_LSA(age=180, options=0x22, type=4, id="7.7.7.7",
        adrouter="3.3.3.3", seq=0x80000001, mask="0.0.0.0", metric=8),
    OSPF_SummaryIP_LSA(age=180, options=0x22, type=4, id="7.7.7.7",
        adrouter="4.4.4.4", seq=0x80000001, mask="0.0.0.0", metric=8),
]

# ===== EXTERNAL LSAs (Type 5) =====
# ebit=0 → E1 (type 1 external), ebit=1 → E2 (type 2 external)
ext_lsas = [
    OSPF_External_LSA(age=300, options=0x22, type=5, id="192.168.0.0",
        adrouter="6.6.6.6", seq=0x80000001,
        mask="255.255.0.0", ebit=0, metric=20, fwdaddr="0.0.0.0", tag=0),
    OSPF_External_LSA(age=300, options=0x22, type=5, id="172.16.0.0",
        adrouter="6.6.6.6", seq=0x80000001,
        mask="255.240.0.0", ebit=1, metric=100, fwdaddr="0.0.0.0", tag=0),
    OSPF_External_LSA(age=300, options=0x22, type=5, id="172.16.0.0",
        adrouter="7.7.7.7", seq=0x80000001,
        mask="255.240.0.0", ebit=0, metric=5, fwdaddr="0.0.0.0", tag=0),
]

# ===== BUILD PACKETS =====
# Packet 1: R1 self-originated Router LSA
pkt1 = make_pkt("10.0.12.1", "00:00:00:00:01:01", "1.1.1.1", [r1_rlsa])

# Packet 2: via R2 — Router LSAs, Area 2 summaries, ASBR summaries, externals
pkt2 = make_pkt("10.0.12.2", "00:00:00:00:02:01", "2.2.2.2",
    [r2_rlsa, r4_rlsa] + sum_r2 + sum_r4_a2 +
    [asbr_lsas[0], asbr_lsas[1], asbr_lsas[3]] + ext_lsas)

# Packet 3: via R3 — Router LSA, Area 1 summaries, ASBR summary
pkt3 = make_pkt("10.0.13.2", "00:00:00:00:03:01", "3.3.3.3",
    [r3_rlsa] + sum_r3 + sum_r4_a1 + [asbr_lsas[2]])

packets = [pkt1, pkt2, pkt3]
wrpcap('/app/ospf_capture.pcap', packets)
total_lsas = sum(len(p[OSPF_LSUpd].lsalist) for p in packets)
print(f"Generated /app/ospf_capture.pcap: {len(packets)} packets, {total_lsas} LSAs")
