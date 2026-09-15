"""
Go-Back-N Receiver -- accepts data from the sender and writes it to a file.

This receiver sends cumulative ACKs only.  It buffers out-of-order packets
but does NOT include SACK blocks in its ACKs, so the sender cannot tell
which specific packets were received out of order.

The protocol specification requires the receiver to:
  1. Generate SACK blocks (up to 3) in every ACK, reporting non-contiguous
     byte ranges that have been received out of order.
  2. Advertise a receiver window so the sender respects flow control.

Modify this file (and sender.py) to meet those requirements.
"""

import socket
import time
import hashlib
import json

from packet import (Packet, TYPE_DATA, TYPE_ACK, TYPE_FIN, TYPE_FIN_ACK,
                    MAX_PAYLOAD)


class GBNReceiver:
    def __init__(self, listen_port, sender_host, sender_port, output_file,
                 log_file=None):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('127.0.0.1', listen_port))
        self.sock.settimeout(0.1)

        self.sender_addr = (sender_host, sender_port)
        self.output_file = output_file
        self.log_file = log_file

        self.expected_seq = 0
        self.recv_buffer = {}        # seq -> payload bytes
        self.delivered_data = bytearray()

        self.total_received = 0
        self.total_acks_sent = 0
        self.total_duplicates = 0

        self.done = False
        self.log_entries = []

    def run(self):
        start_time = time.time()
        while not self.done:
            try:
                data, addr = self.sock.recvfrom(65535)
                pkt = Packet.deserialize(data)
                if pkt is None:
                    continue
                if pkt.ptype == TYPE_DATA:
                    self._handle_data(pkt)
                elif pkt.ptype == TYPE_FIN:
                    self._handle_fin(pkt)
            except socket.timeout:
                continue

        with open(self.output_file, 'wb') as fh:
            fh.write(bytes(self.delivered_data))
        self._write_log(time.time() - start_time)

    def _handle_data(self, pkt):
        self.total_received += 1
        seq = pkt.seq_num
        plen = len(pkt.payload)

        if seq == self.expected_seq:
            self.delivered_data.extend(pkt.payload)
            self.expected_seq += plen
            # deliver contiguous buffered packets
            while self.expected_seq in self.recv_buffer:
                buf = self.recv_buffer.pop(self.expected_seq)
                self.delivered_data.extend(buf)
                self.expected_seq += len(buf)
        elif seq > self.expected_seq:
            if seq not in self.recv_buffer:
                self.recv_buffer[seq] = pkt.payload
        else:
            self.total_duplicates += 1

        # --- cumulative ACK only (no SACK) ---
        ack = Packet(TYPE_ACK, ack_num=self.expected_seq)
        self.sock.sendto(ack.serialize(), self.sender_addr)
        self.total_acks_sent += 1

    def _handle_fin(self, pkt):
        fin_ack = Packet(TYPE_FIN_ACK, ack_num=self.expected_seq)
        raw = fin_ack.serialize()
        for _ in range(4):
            self.sock.sendto(raw, self.sender_addr)
            time.sleep(0.05)
        self.done = True

    def _log_event(self, etype, **kw):
        entry = {'time': time.time(), 'event': etype}
        entry.update(kw)
        self.log_entries.append(entry)

    def _write_log(self, elapsed):
        md5 = hashlib.md5(bytes(self.delivered_data)).hexdigest()
        stats = {
            'elapsed_sec': elapsed,
            'total_received': self.total_received,
            'total_acks_sent': self.total_acks_sent,
            'total_duplicates': self.total_duplicates,
            'bytes_delivered': len(self.delivered_data),
            'md5': md5,
        }
        if self.log_file:
            with open(self.log_file, 'w') as fh:
                json.dump({'stats': stats, 'events': self.log_entries}, fh)


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--listen-port', type=int, required=True)
    p.add_argument('--sender-host', default='127.0.0.1')
    p.add_argument('--sender-port', type=int, required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--log', default=None)
    a = p.parse_args()
    GBNReceiver(a.listen_port, a.sender_host, a.sender_port,
                a.output, a.log).run()


if __name__ == '__main__':
    main()
