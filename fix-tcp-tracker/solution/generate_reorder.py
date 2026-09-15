#!/usr/bin/env python3
"""Generate reorder.pcap: out-of-order TCP segments with retransmission.

Creates a single TCP connection where segments arrive out of order:
  Seg1 (256B) -> Seg3 (256B, out of order) -> Seg2 (256B, fills gap)
  -> Retransmit Seg1 -> Seg4 (256B) -> Server 128B -> Normal close

"""
import logging
logging.getLogger("scapy.runtime").setLevel(logging.ERROR)
from scapy.all import Ether, IP, TCP, Raw, wrpcap, conf
import os

conf.verb = 0


def make_pkt(src, dst, sp, dp, flags, seq, ack, win, data=b"", t=0.0):
    p = Ether(dst="ff:ff:ff:ff:ff:ff") / IP(src=src, dst=dst) / TCP(
        sport=sp, dport=dp, flags=flags, seq=seq, ack=ack, window=win
    )
    if data:
        p = p / Raw(load=data)
    p.time = t
    return p


def gen_reorder():
    C, S = "10.0.1.10", "10.0.2.20"
    cp, sp = 45005, 80
    ISN_C, ISN_S = 1000, 5000
    t = [0.0]
    pkts = []

    def a(src, dst, srcp, dstp, fl, sq, ak, w, d=b""):
        pkts.append(make_pkt(src, dst, srcp, dstp, fl, sq, ak, w, d, t[0]))
        t[0] += 0.05

    cn = ISN_C + 1  # 1001 (first data seq after handshake)
    sn = ISN_S + 1  # 5001

    # 3-way handshake
    a(C, S, cp, sp, "S",  ISN_C, 0, 65535)
    a(S, C, sp, cp, "SA", ISN_S, cn, 32768)
    a(C, S, cp, sp, "A",  cn, sn, 65535)

    # Seg1: 256 bytes (seq 1001 -> 1257)
    a(C, S, cp, sp, "PA", cn, sn, 65535, b"\x61" * 256)
    a(S, C, sp, cp, "A",  sn, cn + 256, 32768)  # ACK 1257

    # Seg3: 256 bytes (seq 1513 -> 1769) — arrives BEFORE seg2 (out of order)
    a(C, S, cp, sp, "PA", cn + 512, sn, 65535, b"\x63" * 256)
    # Server can only ACK cumulatively up to 1257 (gap at 1257-1512)
    a(S, C, sp, cp, "A",  sn, cn + 256, 32768)  # ACK 1257 (dup)

    # Seg2: 256 bytes (seq 1257 -> 1513) — fills the gap
    a(C, S, cp, sp, "PA", cn + 256, sn, 65535, b"\x62" * 256)
    # Now server has contiguous data up to 1769
    a(S, C, sp, cp, "A",  sn, cn + 768, 32768)  # ACK 1769

    # Retransmit of Seg1 (seq 1001 -> 1257) — genuine retransmission
    a(C, S, cp, sp, "PA", cn, sn, 65535, b"\x61" * 256)
    a(S, C, sp, cp, "A",  sn, cn + 768, 32768)  # ACK 1769 (dup, already had it)

    # Seg4: 256 bytes (seq 1769 -> 2025) — normal in-order
    a(C, S, cp, sp, "PA", cn + 768, sn, 65535, b"\x64" * 256)
    a(S, C, sp, cp, "A",  sn, cn + 1024, 32768)  # ACK 2025

    # Server sends 128 bytes
    a(S, C, sp, cp, "PA", sn, cn + 1024, 32768, b"\x73" * 128)
    a(C, S, cp, sp, "A",  cn + 1024, sn + 128, 65535)  # ACK 5129

    # Normal 4-way close
    a(C, S, cp, sp, "FA", cn + 1024, sn + 128, 65535)       # Client FIN
    a(S, C, sp, cp, "A",  sn + 128, cn + 1025, 32768)       # Server ACK
    a(S, C, sp, cp, "FA", sn + 128, cn + 1025, 32768)       # Server FIN
    a(C, S, cp, sp, "A",  cn + 1025, sn + 129, 65535)       # Client ACK

    os.makedirs("/app/captures", exist_ok=True)
    wrpcap("/app/captures/reorder.pcap", pkts)
    print("Generated /app/captures/reorder.pcap")


if __name__ == "__main__":
    gen_reorder()
