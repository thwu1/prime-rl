"""
Go-Back-N Sender -- reliably transfers a file over UDP.

This implementation uses a fixed-size sliding window with cumulative
acknowledgments only.  On any timeout the ENTIRE window is retransmitted
(classic Go-Back-N behaviour).

Performance under lossy or high-delay conditions is poor because:
  - every timeout retransmits ALL unacknowledged packets,
  - the receiver sends no SACK information to guide selective recovery,
  - there is no congestion control -- the window is a compile-time constant.

The protocol specification requires:
  1. Selective Repeat with SACK-based retransmission
  2. TCP Reno congestion control (slow start / AIMD / fast retransmit+recovery)
  3. Correct logging of cwnd and SACK state for verification

Modify this file (and receiver.py) to meet those requirements.
"""

import socket
import time
import sys
import hashlib
import json

from packet import (Packet, TYPE_DATA, TYPE_ACK, TYPE_FIN, TYPE_FIN_ACK,
                    MAX_PAYLOAD)

WINDOW_SIZE = 64          # max send window in packets
TIMEOUT_MS = 1000         # retransmission timeout (ms)


class GBNSender:
    def __init__(self, dest_host, dest_port, listen_port, file_path,
                 log_file=None):
        self.dest = (dest_host, dest_port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('127.0.0.1', listen_port))
        self.sock.settimeout(0.05)

        with open(file_path, 'rb') as fh:
            self.data = fh.read()

        # Protocol state
        self.base = 0
        self.next_seq = 0
        self.window_size = WINDOW_SIZE
        self.send_buffer = {}          # seq -> (Packet, send_time)

        # Statistics
        self.total_sent = 0
        self.total_retransmit = 0
        self.total_acks = 0
        self.dup_acks = 0

        # (unused in GBN -- present for interface compatibility)
        self.cwnd = self.window_size
        self.ssthresh = self.window_size

        self.log_entries = []
        self.log_file = log_file
        self.done = False
        self.fin_acked = False

        # Pre-build packets
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
        start_time = time.time()
        pkt_idx = 0

        while not self.done:
            # ---- send new packets within window
            while (pkt_idx < self.total_packets and
                   self._in_window(self.packets[pkt_idx].seq_num)):
                pkt = self.packets[pkt_idx]
                raw = pkt.serialize()
                self.sock.sendto(raw, self.dest)
                self.send_buffer[pkt.seq_num] = (pkt, time.time())
                self.total_sent += 1
                pkt_idx += 1

            # ---- receive ACKs
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

            # ---- timeout check: GBN retransmits ALL unacked
            if self.send_buffer:
                oldest = min(t for _, t in self.send_buffer.values())
                if (time.time() - oldest) * 1000 > TIMEOUT_MS:
                    self._timeout_retransmit()

            # ---- finished?
            if pkt_idx >= self.total_packets and not self.send_buffer:
                self._send_fin()

        self._write_log(time.time() - start_time)

    # ------------------------------------------------------------- helpers
    def _in_window(self, seq_num):
        return seq_num < self.base + self.window_size * MAX_PAYLOAD

    def _handle_ack(self, ack_pkt):
        self.total_acks += 1
        ack_num = ack_pkt.ack_num

        if ack_num > self.base:
            to_del = [s for s in self.send_buffer if s < ack_num]
            for s in to_del:
                del self.send_buffer[s]
            self.base = ack_num
            self._log_event('ACK', ack_num=ack_num, cwnd=self.cwnd)
        else:
            self.dup_acks += 1

    def _timeout_retransmit(self):
        """GBN: retransmit every unacked packet."""
        self.total_retransmit += len(self.send_buffer)
        now = time.time()
        for seq in sorted(self.send_buffer):
            pkt, _ = self.send_buffer[seq]
            self.sock.sendto(pkt.serialize(), self.dest)
            self.send_buffer[seq] = (pkt, now)
        self._log_event('TIMEOUT', base=self.base,
                        buffer_size=len(self.send_buffer))

    def _send_fin(self):
        fin = Packet(TYPE_FIN, seq_num=self.next_seq if self.packets
                     else 0)
        raw = fin.serialize()
        self.sock.sendto(raw, self.dest)
        deadline = time.time() + 5.0
        while time.time() < deadline and not self.fin_acked:
            try:
                data, _ = self.sock.recvfrom(65535)
                pkt = Packet.deserialize(data)
                if pkt and pkt.ptype == TYPE_FIN_ACK:
                    self.fin_acked = True
                    self.done = True
                    return
            except socket.timeout:
                self.sock.sendto(raw, self.dest)
        self.done = True

    def _log_event(self, etype, **kw):
        entry = {'time': time.time(), 'event': etype}
        entry.update(kw)
        self.log_entries.append(entry)

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
    GBNSender(a.dest_host, a.dest_port, a.listen_port, a.file, a.log).run()


if __name__ == '__main__':
    main()
