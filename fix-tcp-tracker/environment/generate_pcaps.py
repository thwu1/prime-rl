#!/usr/bin/env python3
"""Generate pcap files with TCP edge-case scenarios.

"""
import logging
logging.getLogger("scapy.runtime").setLevel(logging.ERROR)
from scapy.all import Ether, IP, TCP, Raw, wrpcap, conf
import os

conf.verb = 0
OUTDIR = "/app/captures"
os.makedirs(OUTDIR, exist_ok=True)


def make_pkt(src, dst, sp, dp, flags, seq, ack, win, data=b"", t=0.0, opts=None):
    tcp_kw = dict(sport=sp, dport=dp, flags=flags, seq=seq, ack=ack, window=win)
    if opts:
        tcp_kw["options"] = opts
    p = Ether(dst="ff:ff:ff:ff:ff:ff") / IP(src=src, dst=dst) / TCP(**tcp_kw)
    if data:
        p = p / Raw(load=data)
    p.time = t
    return p


def gen_normal():
    """Standard TCP: 3WHS, bidirectional data, orderly 4-way close."""
    C, S = "10.0.1.10", "10.0.2.20"
    cp, sp = 45000, 80
    t = [0.0]

    def a(src, dst, srcp, dstp, fl, sq, ak, w, d=b"", o=None):
        r = make_pkt(src, dst, srcp, dstp, fl, sq, ak, w, d, t[0], o)
        t[0] += 0.05
        return r

    pkts = [
        a(C, S, cp, sp, "S",  1000, 0,    65535),
        a(S, C, sp, cp, "SA", 5000, 1001, 32768),
        a(C, S, cp, sp, "A",  1001, 5001, 65535),
        a(C, S, cp, sp, "PA", 1001, 5001, 65535, b"\x41" * 500),
        a(S, C, sp, cp, "A",  5001, 1501, 32768),
        a(S, C, sp, cp, "PA", 5001, 1501, 32768, b"\x42" * 300),
        a(C, S, cp, sp, "A",  1501, 5301, 65535),
        a(C, S, cp, sp, "FA", 1501, 5301, 65535),
        a(S, C, sp, cp, "A",  5301, 1502, 32768),
        a(S, C, sp, cp, "FA", 5301, 1502, 32768),
        a(C, S, cp, sp, "A",  1502, 5302, 65535),
    ]
    wrpcap(f"{OUTDIR}/normal.pcap", pkts)


def gen_seqwrap():
    """Client ISN near 2^32; data transfer wraps sequence numbers past zero.
    Includes a delayed retransmission of an early segment arriving after the wrap."""
    C, S = "10.0.1.10", "10.0.2.20"
    cp, sp = 45001, 80
    ISN_C = 0xFFFFFA00
    ISN_S = 100000
    t = [0.0]
    pkts = []

    def a(src, dst, srcp, dstp, fl, sq, ak, w, d=b"", o=None):
        pkts.append(make_pkt(src, dst, srcp, dstp, fl, sq, ak, w, d, t[0], o))
        t[0] += 0.05

    cs = ISN_C
    ss = ISN_S

    # 3WHS
    a(C, S, cp, sp, "S",  cs, 0, 65535)
    a(S, C, sp, cp, "SA", ss, (cs + 1) & 0xFFFFFFFF, 32768)
    cn = (cs + 1) & 0xFFFFFFFF   # 0xFFFFFA01
    sn = (ss + 1) & 0xFFFFFFFF   # 100001
    a(C, S, cp, sp, "A",  cn, sn, 65535)

    seg1_seq = cn

    # Seg1: 512B
    a(C, S, cp, sp, "PA", cn, sn, 65535, b"\x41" * 512)
    cn = (cn + 512) & 0xFFFFFFFF  # 0xFFFFFC01
    a(S, C, sp, cp, "A", sn, cn, 32768)

    # Seg2: 512B
    a(C, S, cp, sp, "PA", cn, sn, 65535, b"\x42" * 512)
    cn = (cn + 512) & 0xFFFFFFFF  # 0xFFFFFE01
    a(S, C, sp, cp, "A", sn, cn, 32768)

    # Seg3: 512B — wraps sequence numbers past 2^32
    a(C, S, cp, sp, "PA", cn, sn, 65535, b"\x43" * 512)
    cn = (cn + 512) & 0xFFFFFFFF  # 0x00000001
    a(S, C, sp, cp, "A", sn, cn, 32768)

    # Delayed retransmission of Seg1 arrives after wrap
    a(C, S, cp, sp, "PA", seg1_seq, sn, 65535, b"\x41" * 512)

    # Seg4: 512B (post-wrap)
    a(C, S, cp, sp, "PA", cn, sn, 65535, b"\x44" * 512)
    cn = (cn + 512) & 0xFFFFFFFF  # 0x00000201
    a(S, C, sp, cp, "A", sn, cn, 32768)

    # Seg5: 512B
    a(C, S, cp, sp, "PA", cn, sn, 65535, b"\x45" * 512)
    cn = (cn + 512) & 0xFFFFFFFF  # 0x00000401
    a(S, C, sp, cp, "A", sn, cn, 32768)

    # Server sends 256B
    a(S, C, sp, cp, "PA", sn, cn, 32768, b"\x46" * 256)
    sn = (sn + 256) & 0xFFFFFFFF
    a(C, S, cp, sp, "A", cn, sn, 65535)

    # Orderly close
    a(C, S, cp, sp, "FA", cn, sn, 65535)
    a(S, C, sp, cp, "A",  sn, (cn + 1) & 0xFFFFFFFF, 32768)
    a(S, C, sp, cp, "FA", sn, (cn + 1) & 0xFFFFFFFF, 32768)
    a(C, S, cp, sp, "A",  (cn + 1) & 0xFFFFFFFF, (sn + 1) & 0xFFFFFFFF, 65535)

    wrpcap(f"{OUTDIR}/seqwrap.pcap", pkts)


def gen_simclose():
    """Simultaneous close: both endpoints send FIN before receiving the other's."""
    C, S = "10.0.1.10", "10.0.2.20"
    cp, sp = 45002, 80
    t = [0.0]
    pkts = []

    def a(src, dst, srcp, dstp, fl, sq, ak, w, d=b"", o=None):
        pkts.append(make_pkt(src, dst, srcp, dstp, fl, sq, ak, w, d, t[0], o))
        t[0] += 0.05

    a(C, S, cp, sp, "S",  3000, 0,    65535)
    a(S, C, sp, cp, "SA", 7000, 3001, 32768)
    a(C, S, cp, sp, "A",  3001, 7001, 65535)
    a(C, S, cp, sp, "PA", 3001, 7001, 65535, b"\x43" * 200)
    a(S, C, sp, cp, "A",  7001, 3201, 32768)
    # Both FIN before receiving the other's
    a(C, S, cp, sp, "FA", 3201, 7001, 65535)
    a(S, C, sp, cp, "FA", 7001, 3201, 32768)
    # Both ACK the other's FIN
    a(C, S, cp, sp, "A",  3202, 7002, 65535)
    a(S, C, sp, cp, "A",  7002, 3202, 32768)

    wrpcap(f"{OUTDIR}/simclose.pcap", pkts)


def gen_halfclose():
    """Half-close: client FINs, server keeps sending data, then server FINs."""
    C, S = "10.0.1.10", "10.0.2.20"
    cp, sp = 45003, 80
    t = [0.0]
    pkts = []

    def a(src, dst, srcp, dstp, fl, sq, ak, w, d=b"", o=None):
        pkts.append(make_pkt(src, dst, srcp, dstp, fl, sq, ak, w, d, t[0], o))
        t[0] += 0.05

    a(C, S, cp, sp, "S",  4000, 0,    65535)
    a(S, C, sp, cp, "SA", 8000, 4001, 32768)
    a(C, S, cp, sp, "A",  4001, 8001, 65535)
    a(C, S, cp, sp, "PA", 4001, 8001, 65535, b"\x51" * 100)
    a(S, C, sp, cp, "A",  8001, 4101, 32768)
    # Client closes its send direction
    a(C, S, cp, sp, "FA", 4101, 8001, 65535)
    a(S, C, sp, cp, "A",  8001, 4102, 32768)
    # Server continues sending 3 x 200B = 600B
    a(S, C, sp, cp, "PA", 8001, 4102, 32768, b"\x52" * 200)
    a(C, S, cp, sp, "A",  4102, 8201, 65535)
    a(S, C, sp, cp, "PA", 8201, 4102, 32768, b"\x53" * 200)
    a(C, S, cp, sp, "A",  4102, 8401, 65535)
    a(S, C, sp, cp, "PA", 8401, 4102, 32768, b"\x54" * 200)
    a(C, S, cp, sp, "A",  4102, 8601, 65535)
    # Server closes
    a(S, C, sp, cp, "FA", 8601, 4102, 32768)
    a(C, S, cp, sp, "A",  4102, 8602, 65535)

    wrpcap(f"{OUTDIR}/halfclose.pcap", pkts)


def gen_wscale():
    """TCP window scaling: both sides negotiate wscale in SYN/SYN-ACK."""
    C, S = "10.0.1.10", "10.0.2.20"
    cp, sp = 45004, 80
    t = [0.0]
    pkts = []

    def a(src, dst, srcp, dstp, fl, sq, ak, w, d=b"", o=None):
        pkts.append(make_pkt(src, dst, srcp, dstp, fl, sq, ak, w, d, t[0], o))
        t[0] += 0.05

    # Client: wscale=7, raw SYN window=512
    a(C, S, cp, sp, "S",  6000, 0,    512, o=[("WScale", 7)])
    # Server: wscale=3, raw SYN-ACK window=8192
    a(S, C, sp, cp, "SA", 9000, 6001, 8192, o=[("WScale", 3)])
    # Post-handshake: windows are now scaled
    a(C, S, cp, sp, "A",  6001, 9001, 512)   # effective: 512 << 7 = 65536
    a(C, S, cp, sp, "PA", 6001, 9001, 512, b"\x57" * 100)
    a(S, C, sp, cp, "A",  9001, 6101, 8192)  # effective: 8192 << 3 = 65536
    a(S, C, sp, cp, "PA", 9001, 6101, 8192, b"\x56" * 100)
    a(C, S, cp, sp, "A",  6101, 9101, 512)
    a(C, S, cp, sp, "FA", 6101, 9101, 512)
    a(S, C, sp, cp, "A",  9101, 6102, 8192)
    a(S, C, sp, cp, "FA", 9101, 6102, 8192)
    a(C, S, cp, sp, "A",  6102, 9102, 512)

    wrpcap(f"{OUTDIR}/wscale.pcap", pkts)


if __name__ == "__main__":
    gen_normal()
    gen_seqwrap()
    gen_simclose()
    gen_halfclose()
    gen_wscale()
    print(f"Generated pcap files in {OUTDIR}/")
    for f in sorted(os.listdir(OUTDIR)):
        print(f"  {f}")
