#!/usr/bin/env python3
"""
TCP Connection State Tracker

Reads pcap files, tracks TCP connection state machine transitions,
and outputs a JSON trace with per-connection statistics.

Usage:
    python3 tcp_tracker.py <captures_dir> [output.json]

"""

import json
import os
import sys
import logging

logging.getLogger("scapy.runtime").setLevel(logging.ERROR)
from scapy.all import rdpcap, TCP, IP, conf
conf.verb = 0


# ---------- Sequence number arithmetic ----------

def seq_lt(a, b):
    """Check if TCP sequence number a < b (unsigned 32-bit comparison)."""
    return a < b


def seq_add(a, n):
    """Add n to 32-bit sequence number a."""
    return (a + n) & 0xFFFFFFFF


# ---------- Connection state tracker ----------

class TCPConnection:
    def __init__(self, client_ip, server_ip, client_port, server_port):
        self.client = (client_ip, client_port)
        self.server = (server_ip, server_port)
        self.state = "SYN_SENT"
        self.transitions = ["SYN_SENT"]
        self.client_bytes = 0
        self.server_bytes = 0
        self.retransmissions = 0
        self.client_next_seq = None
        self.server_next_seq = None
        self.client_wscale = None
        self.server_wscale = None
        self.handshake_complete = False
        self.syn_window_client = None
        self.syn_window_server = None
        self.effective_window_client = 0
        self.effective_window_server = 0
        self.client_fin = False
        self.server_fin = False
        self.anomalies = []

    def _transition(self, new_state):
        if self.state != new_state:
            self.state = new_state
            self.transitions.append(new_state)

    def _scaled_window(self, raw_window, from_client):
        """Apply negotiated window scaling factor."""
        wscale = self.client_wscale if from_client else self.server_wscale
        if wscale is not None:
            return raw_window << wscale
        return raw_window

    def _is_retransmission(self, seq, next_expected, data_len):
        """True if this segment's data has already been received."""
        if data_len == 0 or next_expected is None:
            return False
        return seq_lt(seq, next_expected)

    def _track_data(self, seq, data_len, from_client):
        """Account for new data bytes or retransmissions."""
        if data_len <= 0:
            return
        if from_client:
            if self._is_retransmission(seq, self.client_next_seq, data_len):
                self.retransmissions += 1
            else:
                self.client_bytes += data_len
                self.client_next_seq = seq_add(seq, data_len)
        else:
            if self._is_retransmission(seq, self.server_next_seq, data_len):
                self.retransmissions += 1
            else:
                self.server_bytes += data_len
                self.server_next_seq = seq_add(seq, data_len)

    def process(self, ip_pkt, tcp_pkt, from_client):
        """Feed one observed packet into the state machine."""
        flags = tcp_pkt.flags
        seq = tcp_pkt.seq
        ack = tcp_pkt.ack
        raw_win = tcp_pkt.window
        data_len = len(tcp_pkt.payload) if tcp_pkt.payload else 0

        syn = bool(flags & 0x02)
        ack_f = bool(flags & 0x10)
        fin = bool(flags & 0x01)
        rst = bool(flags & 0x04)

        # Learn window-scale option from SYN / SYN-ACK
        if syn:
            for opt_name, opt_val in tcp_pkt.options:
                if opt_name == "WScale":
                    if from_client:
                        self.client_wscale = opt_val
                    else:
                        self.server_wscale = opt_val

        # Record SYN advertised windows
        if syn and not ack_f and from_client:
            self.syn_window_client = self._scaled_window(raw_win, True)
        elif syn and ack_f and not from_client:
            self.syn_window_server = self._scaled_window(raw_win, False)

        # Effective (scaled) window — updated every packet
        eff = self._scaled_window(raw_win, from_client)
        if from_client:
            self.effective_window_client = eff
        else:
            self.effective_window_server = eff

        if rst:
            self._transition("CLOSED")
            return

        # --------------- State machine ---------------
        if self.state == "SYN_SENT":
            if not from_client and syn and ack_f:
                self.server_next_seq = seq_add(seq, 1)
                self._transition("SYN_RECEIVED")

        elif self.state == "SYN_RECEIVED":
            if from_client and ack_f and not syn:
                self.client_next_seq = seq
                self.handshake_complete = True
                self._transition("ESTABLISHED")

        elif self.state == "ESTABLISHED":
            self._track_data(seq, data_len, from_client)
            if fin:
                if from_client:
                    self.client_fin = True
                    if self.client_next_seq is not None:
                        self.client_next_seq = seq_add(seq, data_len + 1)
                    self._transition("FIN_WAIT_1")
                else:
                    self.server_fin = True
                    if self.server_next_seq is not None:
                        self.server_next_seq = seq_add(seq, data_len + 1)
                    self._transition("CLOSE_WAIT")

        elif self.state == "FIN_WAIT_1":
            if not from_client and fin:
                self.server_fin = True
                if self.server_next_seq is not None:
                    self.server_next_seq = seq_add(seq, data_len + 1)
                self._transition("CLOSED")
                return
            if not from_client and ack_f:
                self._transition("FIN_WAIT_2")

        elif self.state == "FIN_WAIT_2":
            if not from_client and fin:
                self.server_fin = True
                self._transition("TIME_WAIT")

        elif self.state == "CLOSE_WAIT":
            if from_client and fin:
                self.client_fin = True
                self._transition("LAST_ACK")

        elif self.state == "CLOSING":
            if ack_f:
                self._transition("TIME_WAIT")

        elif self.state == "LAST_ACK":
            if from_client and ack_f:
                self._transition("CLOSED")

        elif self.state == "TIME_WAIT":
            if ack_f:
                self._transition("CLOSED")

    def to_dict(self):
        return {
            "final_state": self.state,
            "state_transitions": self.transitions,
            "client_bytes": self.client_bytes,
            "server_bytes": self.server_bytes,
            "retransmissions": self.retransmissions,
            "client_window_scale": self.client_wscale,
            "server_window_scale": self.server_wscale,
            "syn_window_client": self.syn_window_client,
            "syn_window_server": self.syn_window_server,
            "effective_window_client": self.effective_window_client,
            "effective_window_server": self.effective_window_server,
            "anomalies": self.anomalies,
        }


# ---------- Main processing ----------

def process_pcap(pcap_path):
    """Read a pcap and return per-connection result dicts."""
    packets = rdpcap(pcap_path)
    connections = {}
    order = []

    for pkt in packets:
        if not pkt.haslayer(IP) or not pkt.haslayer(TCP):
            continue
        ip, tcp = pkt[IP], pkt[TCP]
        ep1, ep2 = (ip.src, tcp.sport), (ip.dst, tcp.dport)
        key = tuple(sorted([ep1, ep2]))

        if key not in connections:
            if tcp.flags & 0x02 and not (tcp.flags & 0x10):
                conn = TCPConnection(ip.src, ip.dst, tcp.sport, tcp.dport)
                connections[key] = conn
                order.append(key)
            else:
                continue

        conn = connections[key]
        from_client = (ip.src == conn.client[0] and tcp.sport == conn.client[1])
        conn.process(ip, tcp, from_client)

    fname = os.path.basename(pcap_path)
    return [dict(file=fname, **connections[k].to_dict()) for k in order]


def main():
    capture_dir = sys.argv[1] if len(sys.argv) > 1 else "/app/captures"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "/app/trace.json"

    results = []
    for name in sorted(os.listdir(capture_dir)):
        if name.endswith(".pcap"):
            results.extend(process_pcap(os.path.join(capture_dir, name)))

    with open(out_path, "w") as f:
        json.dump({"connections": results}, f, indent=2)

    print(f"Wrote {out_path} ({len(results)} connections)")


if __name__ == "__main__":
    main()
