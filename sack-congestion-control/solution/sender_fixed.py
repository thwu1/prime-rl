"""
Selective Repeat Sender with SACK processing and TCP Reno congestion control.

Replaces the Go-Back-N sender to achieve:
  - SACK-informed selective retransmission (only truly missing packets)
  - TCP Reno congestion control: slow start, congestion avoidance,
    fast retransmit / fast recovery
  - Proper event logging for verification
"""

import socket
import time
import sys
import hashlib
import json

from packet import (Packet, TYPE_DATA, TYPE_ACK, TYPE_FIN, TYPE_FIN_ACK,
                    MAX_PAYLOAD)

WINDOW_SIZE = 64
TIMEOUT_MS = 1000


class SRSender:
    def __init__(self, dest_host, dest_port, listen_port, file_path,
                 log_file=None):
        self.dest = (dest_host, dest_port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('127.0.0.1', listen_port))
        self.sock.settimeout(0.05)

        with open(file_path, 'rb') as fh:
            self.data = fh.read()

        # protocol state
        self.base = 0
        self.window_size = WINDOW_SIZE
        self.send_buffer = {}      # seq -> (Packet, send_time)
        self.sacked = set()        # seq numbers selectively ack'd

        # congestion control
        self.cwnd = 1.0
        self.ssthresh = 64.0
        self.state = 'SLOW_START'  # SLOW_START | CONG_AVOID | FAST_RECOVERY
        self.dup_ack_count = 0
        self.last_ack = 0

        # stats
        self.total_sent = 0
        self.total_retransmit = 0
        self.total_acks = 0
        self.dup_acks = 0

        self.log_entries = []
        self.log_file = log_file
        self.done = False
        self.fin_acked = False

        # pre-build packets
        self.packets = []
        offset = 0
        seq = 0
        while offset < len(self.data):
            chunk = self.data[offset:offset + MAX_PAYLOAD]
            self.packets.append(Packet(TYPE_DATA, seq_num=seq, payload=chunk))
            offset += MAX_PAYLOAD
            seq += len(chunk)
        self.total_data_bytes = len(self.data)
        self.total_packets = len(self.packets)

    # ------------------------------------------------------------------ run
    def run(self):
        t0 = time.time()
        pkt_idx = 0

        while not self.done:
            # ---- send new packets within effective window
            outstanding = sum(1 for s in self.send_buffer if s not in self.sacked)
            eff_win = int(min(self.cwnd, self.window_size))

            while pkt_idx < self.total_packets and outstanding < eff_win:
                pkt = self.packets[pkt_idx]
                self._send(pkt)
                outstanding += 1
                pkt_idx += 1

            # ---- receive
            try:
                data, _ = self.sock.recvfrom(65535)
                ack = Packet.deserialize(data)
                if ack is not None:
                    if ack.ptype == TYPE_ACK:
                        self._handle_ack(ack)
                    elif ack.ptype == TYPE_FIN_ACK:
                        self.fin_acked = True
                        self.done = True
            except socket.timeout:
                pass

            # ---- timeout check
            self._check_timeouts()

            # ---- all done?
            if pkt_idx >= self.total_packets and not self.send_buffer:
                self._send_fin()

        self._write_log(time.time() - t0)

    # ------------------------------------------------------------ sending
    def _send(self, pkt):
        self.sock.sendto(pkt.serialize(), self.dest)
        self.send_buffer[pkt.seq_num] = (pkt, time.time())
        self.total_sent += 1

    # --------------------------------------------------------- ACK handling
    def _handle_ack(self, ack_pkt):
        self.total_acks += 1
        ack_num = ack_pkt.ack_num
        sack_blocks = ack_pkt.sack_blocks

        # always process SACK blocks
        if sack_blocks:
            for left, right in sack_blocks:
                for seq in list(self.send_buffer):
                    pkt, _ = self.send_buffer[seq]
                    pkt_end = seq + len(pkt.payload)
                    if left <= seq and pkt_end <= right:
                        self.sacked.add(seq)

        if ack_num > self.base:
            # ---- new cumulative ACK ----
            to_del = [s for s in self.send_buffer if s < ack_num]
            for s in to_del:
                del self.send_buffer[s]
                self.sacked.discard(s)
            self.base = ack_num

            if self.state == 'SLOW_START':
                self.cwnd += 1.0
                if self.cwnd >= self.ssthresh:
                    self.state = 'CONG_AVOID'
            elif self.state == 'CONG_AVOID':
                self.cwnd += 1.0 / self.cwnd
            elif self.state == 'FAST_RECOVERY':
                self.cwnd = self.ssthresh
                self.state = 'CONG_AVOID'

            self.dup_ack_count = 0
            self.last_ack = ack_num

            self._log_event('ACK', ack_num=ack_num, cwnd=self.cwnd,
                            ssthresh=self.ssthresh, state=self.state,
                            sack_blocks=[list(b) for b in sack_blocks]
                            if sack_blocks else [])

        elif ack_num == self.base:
            # ---- duplicate ACK ----
            self.dup_ack_count += 1
            self.dup_acks += 1

            if self.dup_ack_count == 3 and self.state != 'FAST_RECOVERY':
                self.ssthresh = max(self.cwnd / 2.0, 2.0)
                self.cwnd = self.ssthresh + 3.0
                self.state = 'FAST_RECOVERY'
                self._retransmit_first_missing()
                self._log_event('FAST_RETRANSMIT', seq=self.base,
                                cwnd=self.cwnd, ssthresh=self.ssthresh)
            elif self.state == 'FAST_RECOVERY':
                self.cwnd += 1.0

    def _retransmit_first_missing(self):
        for seq in sorted(self.send_buffer):
            if seq not in self.sacked:
                pkt, _ = self.send_buffer[seq]
                self.sock.sendto(pkt.serialize(), self.dest)
                self.send_buffer[seq] = (pkt, time.time())
                self.total_retransmit += 1
                self.total_sent += 1
                return

    # -------------------------------------------------------------- timers
    def _check_timeouts(self):
        now = time.time()
        oldest_seq = None
        oldest_time = float('inf')
        for seq in self.send_buffer:
            if seq in self.sacked:
                continue
            _, st = self.send_buffer[seq]
            if st < oldest_time:
                oldest_time = st
                oldest_seq = seq

        if oldest_seq is not None and (now - oldest_time) * 1000 > TIMEOUT_MS:
            pkt, _ = self.send_buffer[oldest_seq]
            self.sock.sendto(pkt.serialize(), self.dest)
            self.send_buffer[oldest_seq] = (pkt, now)
            self.total_retransmit += 1
            self.total_sent += 1

            self.ssthresh = max(self.cwnd / 2.0, 2.0)
            self.cwnd = 1.0
            self.state = 'SLOW_START'
            self.dup_ack_count = 0
            self._log_event('TIMEOUT', seq=oldest_seq,
                            cwnd=self.cwnd, ssthresh=self.ssthresh)

    # ----------------------------------------------------------------- FIN
    def _send_fin(self):
        last_seq = self.packets[-1].seq_num + len(self.packets[-1].payload) \
            if self.packets else 0
        fin = Packet(TYPE_FIN, seq_num=last_seq)
        raw = fin.serialize()
        self.sock.sendto(raw, self.dest)
        deadline = time.time() + 5.0
        while time.time() < deadline and not self.fin_acked:
            try:
                data, _ = self.sock.recvfrom(65535)
                p = Packet.deserialize(data)
                if p and p.ptype == TYPE_FIN_ACK:
                    self.fin_acked = True
                    self.done = True
                    return
            except socket.timeout:
                self.sock.sendto(raw, self.dest)
        self.done = True

    # --------------------------------------------------------------- logging
    def _log_event(self, etype, **kw):
        self.log_entries.append({'time': time.time(), 'event': etype, **kw})

    def _write_log(self, elapsed):
        stats = {
            'elapsed_sec': elapsed,
            'total_packets_sent': self.total_sent,
            'total_retransmissions': self.total_retransmit,
            'total_acks_received': self.total_acks,
            'duplicate_acks': self.dup_acks,
            'data_bytes': self.total_data_bytes,
            'throughput_kbps': ((self.total_data_bytes * 8)
                                / (elapsed * 1000)) if elapsed else 0,
        }
        if self.log_file:
            with open(self.log_file, 'w') as fh:
                json.dump({'stats': stats, 'events': self.log_entries}, fh)


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--dest-host', default='127.0.0.1')
    p.add_argument('--dest-port', type=int, required=True)
    p.add_argument('--listen-port', type=int, required=True)
    p.add_argument('--file', required=True)
    p.add_argument('--log', default=None)
    a = p.parse_args()
    SRSender(a.dest_host, a.dest_port, a.listen_port, a.file, a.log).run()


if __name__ == '__main__':
    main()
