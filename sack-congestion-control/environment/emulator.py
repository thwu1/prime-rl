"""
UDP link emulator: introduces configurable packet loss, delay, jitter,
reordering, corruption, and duplication between a sender and receiver.
"""

import socket
import threading
import random
import time
import argparse


class LinkEmulator:
    def __init__(self, listen_port, forward_port, loss_rate=0.0,
                 delay_ms=0.0, jitter_ms=0.0, reorder_rate=0.0,
                 corrupt_rate=0.0, dup_rate=0.0, seed=None):
        self.forward_port = forward_port
        self.loss_rate = loss_rate
        self.delay_ms = delay_ms
        self.jitter_ms = jitter_ms
        self.reorder_rate = reorder_rate
        self.corrupt_rate = corrupt_rate
        self.dup_rate = dup_rate
        self.rng = random.Random(seed)

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('127.0.0.1', listen_port))
        self.running = True
        self.pending = []
        self.lock = threading.Lock()
        self.stats = dict(forwarded=0, dropped=0, corrupted=0,
                          reordered=0, duplicated=0)

    def start(self):
        threading.Thread(target=self._recv_loop, daemon=True).start()
        threading.Thread(target=self._deliver_loop, daemon=True).start()

    def _recv_loop(self):
        while self.running:
            try:
                self.sock.settimeout(0.1)
                data, addr = self.sock.recvfrom(65535)
            except (socket.timeout, OSError):
                continue

            if self.rng.random() < self.loss_rate:
                self.stats['dropped'] += 1
                continue

            if self.rng.random() < self.corrupt_rate:
                data = self._corrupt(data)
                self.stats['corrupted'] += 1

            if self.rng.random() < self.dup_rate:
                self.stats['duplicated'] += 1
                self._schedule(data)

            self._schedule(data)

    def _schedule(self, data):
        delay = self.delay_ms + self.rng.uniform(-self.jitter_ms, self.jitter_ms)
        delay = max(0.0, delay) / 1000.0

        if self.rng.random() < self.reorder_rate:
            delay += self.rng.uniform(0.01, 0.05)
            self.stats['reordered'] += 1

        with self.lock:
            self.pending.append((time.time() + delay, data))

    def _deliver_loop(self):
        while self.running:
            time.sleep(0.001)
            now = time.time()
            to_send = []
            with self.lock:
                remaining = []
                for item in self.pending:
                    if item[0] <= now:
                        to_send.append(item)
                    else:
                        remaining.append(item)
                self.pending = remaining

            for _, data in to_send:
                try:
                    self.sock.sendto(data, ('127.0.0.1', self.forward_port))
                    self.stats['forwarded'] += 1
                except OSError:
                    pass

    def _corrupt(self, data):
        buf = bytearray(data)
        pos = self.rng.randint(0, len(buf) - 1)
        buf[pos] ^= self.rng.randint(1, 255)
        return bytes(buf)

    def stop(self):
        self.running = False
        try:
            self.sock.close()
        except OSError:
            pass


def main():
    parser = argparse.ArgumentParser(description='UDP Link Emulator')
    parser.add_argument('--listen-port', type=int, required=True)
    parser.add_argument('--forward-port', type=int, required=True)
    parser.add_argument('--loss', type=float, default=0.0)
    parser.add_argument('--delay', type=float, default=0.0)
    parser.add_argument('--jitter', type=float, default=0.0)
    parser.add_argument('--reorder', type=float, default=0.0)
    parser.add_argument('--corrupt', type=float, default=0.0)
    parser.add_argument('--duplicate', type=float, default=0.0)
    parser.add_argument('--seed', type=int, default=None)
    args = parser.parse_args()

    emu = LinkEmulator(
        args.listen_port, args.forward_port,
        loss_rate=args.loss, delay_ms=args.delay,
        jitter_ms=args.jitter, reorder_rate=args.reorder,
        corrupt_rate=args.corrupt, dup_rate=args.duplicate,
        seed=args.seed,
    )
    emu.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        emu.stop()


if __name__ == '__main__':
    main()
