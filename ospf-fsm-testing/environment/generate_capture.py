#!/usr/bin/env python3
"""
Generate OSPF packet capture for adjacency forensics task.
Creates a pcap simulating a 5-router broadcast network with various
adjacency formation failures embedded.

Routers:
  R1 (1.1.1.1 / 10.0.1.1) - correct config
  R2 (2.2.2.2 / 10.0.1.2) - correct config
  R3 (3.3.3.3 / 10.0.1.3) - HelloInterval=30 (wrong), DeadInterval=120
  R4 (4.4.4.4 / 10.0.1.4) - correct Hello params, but MTU=9000 in DD
  R5 (5.5.5.5 / 10.0.1.5) - Options E-bit=0 (stub area mismatch)

Expected adjacency outcomes:
  R1-R2: Full (successful)
  R1-R3: Down (Hello rejected per RFC 2328 Section 10.5 check 4)
  R1-R4: ExStart stall (DD rejected per RFC 2328 Section 10.6 - MTU)
  R1-R5: Down (Hello rejected per RFC 2328 Section 10.5 check 5)
  R2-R4: ExStart stall (same MTU issue)
"""

from scapy.all import Ether, IP, wrpcap, conf
from scapy.contrib.ospf import OSPF_Hdr, OSPF_Hello, OSPF_DBDesc

conf.verb = 0

packets = []
T0 = 1704067200.0  # 2024-01-01 00:00:00 UTC

MACS = {
    "R1": "02:00:0a:00:01:01",
    "R2": "02:00:0a:00:01:02",
    "R3": "02:00:0a:00:01:03",
    "R4": "02:00:0a:00:01:04",
    "R5": "02:00:0a:00:01:05",
}
MCAST = "01:00:5e:00:00:05"

RID = {"R1": "1.1.1.1", "R2": "2.2.2.2", "R3": "3.3.3.3", "R4": "4.4.4.4", "R5": "5.5.5.5"}
RIP = {"R1": "10.0.1.1", "R2": "10.0.1.2", "R3": "10.0.1.3", "R4": "10.0.1.4", "R5": "10.0.1.5"}


def hello(rname, neighbors=None, hello_int=10, dead_int=40, options=0x02,
          dr="0.0.0.0", bdr="0.0.0.0", prio=1, ts=0):
    pkt = (Ether(src=MACS[rname], dst=MCAST) /
           IP(src=RIP[rname], dst="224.0.0.5", ttl=1, proto=89) /
           OSPF_Hdr(version=2, type=1, src=RID[rname], area="0.0.0.0") /
           OSPF_Hello(mask="255.255.255.0", hellointerval=hello_int,
                      options=options, prio=prio, deadinterval=dead_int,
                      router=dr, backup=bdr,
                      neighbors=neighbors or []))
    pkt.time = T0 + ts
    return pkt


def dd(src, dst, mtu=1500, options=0x02, flags=0x07, seq=1000, ts=0):
    pkt = (Ether(src=MACS[src], dst=MACS[dst]) /
           IP(src=RIP[src], dst=RIP[dst], ttl=1, proto=89) /
           OSPF_Hdr(version=2, type=2, src=RID[src], area="0.0.0.0") /
           OSPF_DBDesc(mtu=mtu, options=options, dbdescr=flags, ddseq=seq))
    pkt.time = T0 + ts
    return pkt


# ===================== Phase 1: Initial Hellos (t=0s) =====================
# All routers broadcast Hello. No neighbors known yet.
packets.append(hello("R1", ts=0.000))
packets.append(hello("R2", ts=0.100))
packets.append(hello("R3", hello_int=30, dead_int=120, ts=0.200))
packets.append(hello("R4", ts=0.300))
packets.append(hello("R5", options=0x00, ts=0.400))

# ===================== Phase 2: 2nd Hellos (t=10s) ========================
# R1, R2, R4 discover each other. R3 and R5 Hellos rejected.
packets.append(hello("R1", neighbors=["2.2.2.2", "4.4.4.4"], ts=10.000))
packets.append(hello("R2", neighbors=["1.1.1.1", "4.4.4.4"], ts=10.100))
packets.append(hello("R3", hello_int=30, dead_int=120, ts=10.200))
packets.append(hello("R4", neighbors=["1.1.1.1", "2.2.2.2"], ts=10.300))
packets.append(hello("R5", options=0x00, ts=10.400))

# ===================== Phase 3: 3rd Hellos (t=20s) ========================
# 2-Way confirmed for R1-R2, R1-R4, R2-R4 (bidirectional Hello)
packets.append(hello("R1", neighbors=["2.2.2.2", "4.4.4.4"], ts=20.000))
packets.append(hello("R2", neighbors=["1.1.1.1", "4.4.4.4"], ts=20.100))
packets.append(hello("R3", hello_int=30, dead_int=120, ts=20.200))
packets.append(hello("R4", neighbors=["1.1.1.1", "2.2.2.2"], ts=20.300))
packets.append(hello("R5", options=0x00, ts=20.400))

# ===================== Phase 4: ExStart DD exchange (t=21s) ===============
# I|M|MS = 0x07: both sides initially claim master
# R1-R2 ExStart
packets.append(dd("R1", "R2", flags=0x07, seq=1000, ts=21.000))
packets.append(dd("R2", "R1", flags=0x07, seq=2000, ts=21.100))
# R1-R4 ExStart (R4 sends MTU=9000)
packets.append(dd("R1", "R4", mtu=1500, flags=0x07, seq=1100, ts=21.200))
packets.append(dd("R4", "R1", mtu=9000, flags=0x07, seq=3000, ts=21.300))
# R2-R4 ExStart (R4 sends MTU=9000)
packets.append(dd("R2", "R4", mtu=1500, flags=0x07, seq=2100, ts=21.400))
packets.append(dd("R4", "R2", mtu=9000, flags=0x07, seq=3100, ts=21.500))

# ===================== Phase 5: R1-R2 Negotiation (t=22s) =================
# R2 has higher Router ID -> R2 is master
# R1 becomes slave: sends DD with R2's seq, MS bit cleared
packets.append(dd("R1", "R2", flags=0x02, seq=2000, ts=22.000))   # slave, M=1
packets.append(dd("R2", "R1", flags=0x03, seq=2001, ts=22.100))   # master, M=1

# R1-R4 retransmit (R1 rejected R4's DD: MTU 9000 > interface MTU 1500)
packets.append(dd("R1", "R4", mtu=1500, flags=0x07, seq=1100, ts=22.200))
packets.append(dd("R4", "R1", mtu=9000, flags=0x07, seq=3000, ts=22.300))
# R2-R4 retransmit
packets.append(dd("R2", "R4", mtu=1500, flags=0x07, seq=2100, ts=22.400))
packets.append(dd("R4", "R2", mtu=9000, flags=0x07, seq=3100, ts=22.500))

# ===================== Phase 6: R1-R2 Exchange Done (t=23s) ===============
# Empty DB summary lists -> direct to Full after ExchangeDone
packets.append(dd("R1", "R2", flags=0x00, seq=2001, ts=23.000))   # slave ack, M=0
packets.append(dd("R2", "R1", flags=0x01, seq=2002, ts=23.100))   # master final, M=0
packets.append(dd("R1", "R2", flags=0x00, seq=2002, ts=23.200))   # slave final ack

# ===================== Phase 7: More ExStart retransmits (t=27s) ==========
packets.append(dd("R1", "R4", mtu=1500, flags=0x07, seq=1100, ts=27.000))
packets.append(dd("R4", "R1", mtu=9000, flags=0x07, seq=3000, ts=27.100))
packets.append(dd("R2", "R4", mtu=1500, flags=0x07, seq=2100, ts=27.200))
packets.append(dd("R4", "R2", mtu=9000, flags=0x07, seq=3100, ts=27.300))

# ===================== Phase 8: Hellos with DR/BDR (t=30s) ================
# R1-R2 now fully adjacent, DR election occurred
packets.append(hello("R1", neighbors=["2.2.2.2", "4.4.4.4"],
                      dr="10.0.1.2", bdr="10.0.1.1", ts=30.000))
packets.append(hello("R2", neighbors=["1.1.1.1", "4.4.4.4"],
                      dr="10.0.1.2", bdr="10.0.1.1", ts=30.100))
packets.append(hello("R3", hello_int=30, dead_int=120, ts=30.200))
packets.append(hello("R4", neighbors=["1.1.1.1", "2.2.2.2"],
                      dr="10.0.1.4", bdr="10.0.1.1", ts=30.300))
packets.append(hello("R5", options=0x00, ts=30.400))

# ===================== Phase 9: More ExStart retransmits (t=32s) ==========
packets.append(dd("R1", "R4", mtu=1500, flags=0x07, seq=1100, ts=32.000))
packets.append(dd("R4", "R1", mtu=9000, flags=0x07, seq=3000, ts=32.100))

# ===================== Phase 10: Final Hellos (t=40s) =====================
packets.append(hello("R1", neighbors=["2.2.2.2", "4.4.4.4"],
                      dr="10.0.1.2", bdr="10.0.1.1", ts=40.000))
packets.append(hello("R2", neighbors=["1.1.1.1", "4.4.4.4"],
                      dr="10.0.1.2", bdr="10.0.1.1", ts=40.100))
packets.append(hello("R3", hello_int=30, dead_int=120, ts=40.200))
packets.append(hello("R4", neighbors=["1.1.1.1", "2.2.2.2"],
                      dr="10.0.1.4", bdr="10.0.1.1", ts=40.300))
packets.append(hello("R5", options=0x00, ts=40.400))

# Write pcap
wrpcap("/app/capture/ospf_adjacency.pcap", packets)
print(f"Generated {len(packets)} OSPF packets -> /app/capture/ospf_adjacency.pcap")
