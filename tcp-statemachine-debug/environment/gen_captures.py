#!/usr/bin/env python3
"""Generate synthetic TCP pcap captures for network analysis scenarios.

Creates three pcap files modelling different network environments
(datacenter, WAN, satellite) with varying RTT and loss characteristics.
Uses LINKTYPE_RAW (101) for raw IPv4 packets.

Run at Docker build time; removed after execution.
"""

import struct
import os
import random

# ── PCAP format constants ──────────────────────────────────────────
PCAP_MAGIC = 0xa1b2c3d4
PCAP_VMAJOR = 2
PCAP_VMINOR = 4
LINKTYPE_RAW = 101  # raw IPv4

# ── TCP flag bits ──────────────────────────────────────────────────
TH_FIN = 0x01
TH_SYN = 0x02
TH_RST = 0x04
TH_PSH = 0x08
TH_ACK = 0x10


def inet_cksum(data: bytes) -> int:
    """RFC 1071 ones-complement checksum."""
    if len(data) & 1:
        data += b'\x00'
    s = 0
    for i in range(0, len(data), 2):
        s += (data[i] << 8) | data[i + 1]
    while s >> 16:
        s = (s >> 16) + (s & 0xffff)
    return ~s & 0xffff


def _ip4(addr: str) -> bytes:
    return bytes(int(x) for x in addr.split('.'))


def _build_packet(src_ip, dst_ip, sport, dport, seq, ack, flags,
                  window=32768, payload=b''):
    """Construct a raw IPv4 + TCP packet with correct checksums."""
    sb = _ip4(src_ip)
    db = _ip4(dst_ip)

    # TCP header  (20 bytes, no options)
    tcp = struct.pack('!HHIIBBHHH',
                      sport, dport,
                      seq & 0xFFFFFFFF, ack & 0xFFFFFFFF,
                      0x50, flags,      # data-offset=5, flags
                      window, 0, 0)

    pseudo = struct.pack('!4s4sBBH', sb, db, 0, 6, len(tcp) + len(payload))
    csum = inet_cksum(pseudo + tcp + payload)
    tcp = tcp[:16] + struct.pack('!H', csum) + tcp[18:]

    # IPv4 header  (20 bytes)
    tlen = 20 + len(tcp) + len(payload)
    ip = struct.pack('!BBHHHBBH4s4s',
                     0x45, 0x00, tlen,
                     0, 0x4000,
                     64, 6, 0,
                     sb, db)
    csum = inet_cksum(ip)
    ip = ip[:10] + struct.pack('!H', csum) + ip[12:]

    return ip + tcp + payload


class _PcapWriter:
    def __init__(self, path):
        self._f = open(path, 'wb')
        self._f.write(struct.pack('<IHHiIII',
                                  PCAP_MAGIC, PCAP_VMAJOR, PCAP_VMINOR,
                                  0, 0, 65535, LINKTYPE_RAW))

    def pkt(self, ts: float, data: bytes):
        sec = int(ts)
        usec = int((ts - sec) * 1_000_000)
        self._f.write(struct.pack('<IIII', sec, usec, len(data), len(data)))
        self._f.write(data)

    def close(self):
        self._f.close()


def generate_session(path, cip, sip, cport, sport,
                     base_rtt, rtt_jitter, n_data, retransmit_at,
                     data_sz=1000):
    """Write a complete TCP session pcap (client-side capture perspective).

    Packets are timestamped as if captured at the client: outgoing packets
    at their send time, incoming packets at their arrival time (send + RTT).
    This lets tshark compute tcp.analysis.ack_rtt ≈ base_rtt.
    """
    pw = _PcapWriter(path)
    retx = set(retransmit_at)
    payload = b'\xAB' * data_sz

    t = 0.0
    cseq = 1000
    sseq = 5000

    # ── Handshake ──────────────────────────────────────────────────
    # SYN
    pw.pkt(t, _build_packet(cip, sip, cport, sport, cseq, 0, TH_SYN))
    rtt = base_rtt + random.uniform(-rtt_jitter / 4, rtt_jitter / 4)
    t += rtt
    # SYN-ACK  (arrives after 1 RTT)
    pw.pkt(t, _build_packet(sip, cip, sport, cport,
                            sseq, cseq + 1, TH_SYN | TH_ACK))
    cseq += 1
    sseq += 1
    t += 0.00005
    # ACK
    pw.pkt(t, _build_packet(cip, sip, cport, sport,
                            cseq, sseq, TH_ACK))

    # ── Data transfer (stop-and-wait) ──────────────────────────────
    for i in range(n_data):
        t += 0.00005  # small inter-packet gap

        # Client sends data
        send_t = t
        pw.pkt(t, _build_packet(cip, sip, cport, sport,
                                cseq, sseq, TH_ACK | TH_PSH,
                                payload=payload))
        orig_cseq = cseq
        cseq += data_sz

        # Retransmission?
        if i in retx:
            t += 2 * base_rtt  # RTO ≈ 2×RTT
            pw.pkt(t, _build_packet(cip, sip, cport, sport,
                                    orig_cseq, sseq, TH_ACK | TH_PSH,
                                    payload=payload))
            rtt_sample = base_rtt + random.uniform(-rtt_jitter / 2,
                                                   rtt_jitter / 2)
            t += rtt_sample
        else:
            rtt_sample = base_rtt + random.uniform(-rtt_jitter / 2,
                                                   rtt_jitter / 2)
            t = send_t + rtt_sample

        # ACK from server (arrives at client after RTT)
        pw.pkt(t, _build_packet(sip, cip, sport, cport,
                                sseq, cseq, TH_ACK))

    # ── Teardown ───────────────────────────────────────────────────
    t += 0.00005
    pw.pkt(t, _build_packet(cip, sip, cport, sport,
                            cseq, sseq, TH_FIN | TH_ACK))
    t += base_rtt
    pw.pkt(t, _build_packet(sip, cip, sport, cport,
                            sseq, cseq + 1, TH_FIN | TH_ACK))
    t += 0.00005
    pw.pkt(t, _build_packet(cip, sip, cport, sport,
                            cseq + 1, sseq + 1, TH_ACK))

    pw.close()


def main():
    random.seed(42)
    os.makedirs('/app/captures', exist_ok=True)

    # Scenario A – datacenter:  ~1 ms RTT, 1 retransmission in 100 pkts
    generate_session('/app/captures/scenario_a.pcap',
                     '10.0.1.1', '10.0.1.2', 50001, 8080,
                     base_rtt=0.001, rtt_jitter=0.0003,
                     n_data=100, retransmit_at=[50])

    # Scenario B – WAN:  ~50 ms RTT, 3 retransmissions in 80 pkts
    generate_session('/app/captures/scenario_b.pcap',
                     '10.0.2.1', '10.0.2.2', 50002, 8080,
                     base_rtt=0.050, rtt_jitter=0.012,
                     n_data=80, retransmit_at=[20, 45, 65])

    # Scenario C – satellite:  ~300 ms RTT, 4 retransmissions in 60 pkts
    generate_session('/app/captures/scenario_c.pcap',
                     '10.0.3.1', '10.0.3.2', 50003, 8080,
                     base_rtt=0.300, rtt_jitter=0.060,
                     n_data=60, retransmit_at=[10, 25, 40, 55])

    print('Generated pcap files in /app/captures/')


if __name__ == '__main__':
    main()
