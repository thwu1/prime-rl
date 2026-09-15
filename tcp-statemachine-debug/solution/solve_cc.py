#!/usr/bin/env python3
"""Solution: analyse network captures and implement TCP congestion control.

Uses tshark to extract RTT and retransmission metrics from pcap files,
stores them in SQLite, and writes a Reno-style CongestionController.
"""


import json
import os
import sqlite3
import statistics
import subprocess
import sys


# ── tshark helpers ─────────────────────────────────────────────────

def _tshark_rtt_samples(pcap):
    """Extract tcp.analysis.ack_rtt values via tshark."""
    r = subprocess.run(
        ['tshark', '-r', pcap, '-T', 'fields',
         '-e', 'tcp.analysis.ack_rtt',
         '-Y', 'tcp.analysis.ack_rtt'],
        capture_output=True, text=True)
    vals = []
    for line in r.stdout.strip().splitlines():
        line = line.strip()
        if line:
            try:
                vals.append(float(line))
            except ValueError:
                pass
    return vals


def _tshark_retransmissions(pcap):
    r = subprocess.run(
        ['tshark', '-r', pcap, '-Y', 'tcp.analysis.retransmission'],
        capture_output=True, text=True)
    return len([l for l in r.stdout.strip().splitlines() if l.strip()])


def _tshark_total_packets(pcap):
    r = subprocess.run(['tshark', '-r', pcap],
                       capture_output=True, text=True)
    return len([l for l in r.stdout.strip().splitlines() if l.strip()])


# ── analysis ───────────────────────────────────────────────────────

def analyse_captures():
    analysis = {}
    for name in ('scenario_a', 'scenario_b', 'scenario_c'):
        pcap = f'/app/captures/{name}.pcap'
        rtts = _tshark_rtt_samples(pcap)
        retx = _tshark_retransmissions(pcap)
        total = _tshark_total_packets(pcap)

        avg_rtt_ms = statistics.mean(rtts) * 1000 if rtts else 0.0
        retx_pct = (retx / total * 100) if total > 0 else 0.0

        analysis[name] = {
            'avg_rtt_ms': round(avg_rtt_ms, 3),
            'retransmission_pct': round(retx_pct, 3),
            'packet_count': total,
        }
    return analysis


def write_analysis_json(analysis):
    with open('/app/analysis.json', 'w') as f:
        json.dump(analysis, f, indent=2)


def write_analysis_db(analysis):
    os.makedirs('/app/metrics', exist_ok=True)
    db = '/app/metrics/analysis.db'
    conn = sqlite3.connect(db)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS network_metrics (
        scenario            TEXT PRIMARY KEY,
        avg_rtt_ms          REAL,
        retransmission_pct  REAL,
        packet_count        INTEGER,
        bdp_bytes           INTEGER
    )''')
    for name, m in analysis.items():
        bdp = int(m['avg_rtt_ms'] / 1000.0 * 1_000_000)  # rough BDP
        c.execute('INSERT OR REPLACE INTO network_metrics VALUES (?,?,?,?,?)',
                  (name, m['avg_rtt_ms'], m['retransmission_pct'],
                   m['packet_count'], bdp))
    conn.commit()
    conn.close()


# ── congestion controller ──────────────────────────────────────────

CC_SOURCE = '''\
"""TCP Reno congestion control implementation."""

from tcp_sim.cc_interface import CongestionControllerBase


class CongestionController(CongestionControllerBase):
    """TCP Reno with slow start, congestion avoidance, and fast recovery."""

    MSS = 1460

    def __init__(self):
        self._cwnd = self.MSS
        self._ssthresh = 65535
        self._state = \'slow_start\'
        self._dup_ack_count = 0

    # ── event handlers ─────────────────────────────────────────

    def on_ack(self, acked_bytes: int, rtt_sample: float) -> None:
        if self._state == \'fast_recovery\':
            # Deflate: exit FR, set cwnd to ssthresh
            self._cwnd = self._ssthresh
            self._state = \'congestion_avoidance\'
            self._dup_ack_count = 0
            return

        self._dup_ack_count = 0

        if self._state == \'slow_start\':
            self._cwnd += self.MSS
            if self._cwnd >= self._ssthresh:
                self._state = \'congestion_avoidance\'
        elif self._state == \'congestion_avoidance\':
            # Additive increase: ~MSS per RTT
            self._cwnd += max(1, (self.MSS * self.MSS) // self._cwnd)

    def on_duplicate_ack(self) -> None:
        self._dup_ack_count += 1
        if self._dup_ack_count == 3 and self._state != \'fast_recovery\':
            # Multiplicative decrease + enter fast recovery
            self._ssthresh = max(self._cwnd // 2, 2 * self.MSS)
            self._cwnd = self._ssthresh + 3 * self.MSS
            self._state = \'fast_recovery\'
        elif self._state == \'fast_recovery\':
            # Inflate window for each additional dup ACK
            self._cwnd += self.MSS

    def on_timeout(self) -> None:
        self._ssthresh = max(self._cwnd // 2, 2 * self.MSS)
        self._cwnd = self.MSS
        self._state = \'slow_start\'
        self._dup_ack_count = 0

    # ── queries ────────────────────────────────────────────────

    def get_cwnd(self) -> int:
        return self._cwnd

    def get_ssthresh(self) -> int:
        return self._ssthresh

    def get_state(self) -> str:
        return self._state
'''


def write_cc():
    with open('/app/tcp_sim/congestion.py', 'w') as f:
        f.write(CC_SOURCE)


# ── main ───────────────────────────────────────────────────────────

def main():
    print('=== Analysing pcap captures with tshark ===')
    analysis = analyse_captures()
    for name, m in sorted(analysis.items()):
        print(f'  {name}: RTT={m["avg_rtt_ms"]:.2f} ms  '
              f'loss={m["retransmission_pct"]:.2f}%  '
              f'packets={m["packet_count"]}')

    print('\\n=== Writing analysis.json ===')
    write_analysis_json(analysis)

    print('=== Creating analysis SQLite database ===')
    write_analysis_db(analysis)

    print('=== Writing congestion controller ===')
    write_cc()

    print('\\nDone.')


if __name__ == '__main__':
    main()
