"""
Complete reliable transport protocol with SACK and congestion control.

This is the reference solution for the transport task.
"""

import time

from channel import LossyChannel
from packet import FLAG_ACK, FLAG_DATA, FLAG_FIN, Packet



class ReliableSender:
    """Reliable sender with sliding window, SACK, and congestion control."""

    def __init__(self, channel: LossyChannel, config: dict):
        self.channel = channel
        self.mss = config.get('mss', 500)
        self.max_window = config.get('max_window', 32)
        self.seq_bits = config.get('seq_bits', 16)
        self.seq_mod = 1 << self.seq_bits
        self.initial_timeout_ms = config.get('initial_timeout_ms', 1000)

    # -- helpers --

    def _seq(self, index: int) -> int:
        """Map a linear segment index to a sequence number."""
        return index % self.seq_mod

    def _ack_to_index(self, ack_num: int, base_index: int) -> int:
        """Convert an ACK sequence number back to a segment index."""
        base_seq = self._seq(base_index)
        offset = (ack_num - base_seq) % self.seq_mod
        return base_index + offset

    # -- main send loop --

    def send(self, data: bytes) -> dict:
        segments = [data[i:i + self.mss] for i in range(0, len(data), self.mss)] if data else []
        total = len(segments)

        base = 0           # index of first unacked segment
        next_to_send = 0   # index of next segment to transmit

        # Congestion control
        cwnd = 1.0
        ssthresh = float(self.max_window)
        dup_ack_count = 0
        in_fast_recovery = False

        # RTT estimation (Jacobson / Karn)
        srtt = None
        rttvar = None
        rto = self.initial_timeout_ms / 1000.0

        # Per-segment tracking
        send_times: dict[int, float] = {}
        retransmitted: set[int] = set()
        sack_acked: set[int] = set()

        stats = {
            'bytes_sent': 0,
            'packets_sent': 0,
            'retransmissions': 0,
            'cwnd_log': [],
        }
        t0 = time.time()
        stats['cwnd_log'].append((0.0, cwnd))

        fin_sent = False
        fin_acked = False

        def log_cwnd():
            stats['cwnd_log'].append((time.time() - t0, cwnd))

        def _send_segment(idx: int, retransmit: bool = False):
            pkt = Packet(seq_num=self._seq(idx), flags=FLAG_DATA,
                         window=self.max_window, payload=segments[idx])
            self.channel.send_forward(pkt.serialize())
            send_times[idx] = time.time()
            stats['packets_sent'] += 1
            stats['bytes_sent'] += len(segments[idx])
            if retransmit:
                stats['retransmissions'] += 1
                retransmitted.add(idx)

        def _send_fin():
            nonlocal fin_sent
            for _ in range(5):
                pkt = Packet(seq_num=self._seq(total), flags=FLAG_FIN, window=0)
                self.channel.send_forward(pkt.serialize())
                stats['packets_sent'] += 1
            fin_sent = True

        def _update_rtt(idx: int):
            nonlocal srtt, rttvar, rto
            if idx in retransmitted or idx not in send_times:
                return
            sample = time.time() - send_times[idx]
            if srtt is None:
                srtt = sample
                rttvar = sample / 2.0
            else:
                rttvar = 0.75 * rttvar + 0.25 * abs(srtt - sample)
                srtt = 0.875 * srtt + 0.125 * sample
            rto = max(0.05, min(srtt + 4.0 * rttvar, 30.0))

        def _rough_rtt_estimate(idx: int):
            """Fallback RTT estimate from retransmitted segment (violates
            Karn strictly, but prevents RTO stall under heavy loss)."""
            nonlocal srtt, rttvar, rto
            if idx not in send_times:
                return
            sample = time.time() - send_times[idx]
            if srtt is None:
                srtt = sample
                rttvar = sample
            else:
                rttvar = 0.75 * rttvar + 0.25 * abs(srtt - sample)
                srtt = 0.875 * srtt + 0.125 * sample
            rto = max(0.05, min(srtt + 4.0 * rttvar, 30.0))

        while not fin_acked:
            # --- transmit new segments within the window ---
            eff_win = min(int(cwnd), self.max_window)
            while next_to_send < total and (next_to_send - base) < eff_win:
                _send_segment(next_to_send)
                next_to_send += 1

            # --- send FIN once all data is cumulatively acked ---
            if base >= total and not fin_sent:
                _send_fin()

            # --- wait for an ACK ---
            raw = self.channel.recv_reverse(timeout=rto)

            if raw is None:
                # Timeout
                ssthresh = max(cwnd / 2.0, 2.0)
                cwnd = 1.0
                dup_ack_count = 0
                in_fast_recovery = False
                log_cwnd()
                if base < total:
                    for idx in range(base, min(next_to_send, total)):
                        if idx not in sack_acked:
                            _send_segment(idx, retransmit=True)
                            break
                elif fin_sent and not fin_acked:
                    _send_fin()
                # Backoff: only after RTT is established; cap tightly
                if srtt is not None:
                    max_rto = max(srtt + 4.0 * rttvar, 0.05) * 8
                    rto = min(rto * 2.0, max_rto)
                # else: keep rto at initial value (no backoff without RTT data)
                continue

            pkt = Packet.deserialize(raw)
            if pkt is None or not (pkt.flags & FLAG_ACK):
                continue

            # FIN+ACK → transfer complete
            if pkt.flags & FLAG_FIN:
                fin_acked = True
                break

            ack_idx = self._ack_to_index(pkt.ack_num, base)
            # Guard: reject ACKs beyond what was actually sent (catches
            # stale/reordered ACKs misinterpreted via modular arithmetic)
            if ack_idx < base or ack_idx > next_to_send:
                continue

            if ack_idx > base:
                # New cumulative ACK — RTT sampling.
                # When a retransmission triggers a burst of cumulative ACKs,
                # segments sent *before* that retransmission have inflated
                # "RTT" (they waited in the receiver buffer). Only accept
                # clean samples from segments sent AFTER the latest retx.
                latest_retx_time = 0
                latest_retx_idx = None
                for i in range(base, ack_idx):
                    if i in retransmitted and i in send_times:
                        if send_times[i] > latest_retx_time:
                            latest_retx_time = send_times[i]
                            latest_retx_idx = i

                sampled = False
                for i in range(base, ack_idx):
                    if (i not in retransmitted and i in send_times
                            and send_times[i] > latest_retx_time):
                        _update_rtt(i)
                        sampled = True
                        break

                # Fallback: rough estimate from most recent retransmission
                # to bootstrap SRTT under heavy loss (prevents RTO stall)
                if not sampled and srtt is None and latest_retx_idx is not None:
                    _rough_rtt_estimate(latest_retx_idx)

                for i in range(base, ack_idx):
                    sack_acked.discard(i)
                    send_times.pop(i, None)
                    retransmitted.discard(i)

                # Reset RTO from SRTT (counteracts exponential backoff)
                if srtt is not None:
                    rto = max(0.05, min(srtt + 4.0 * rttvar, 30.0))

                old_cwnd = cwnd
                if in_fast_recovery:
                    cwnd = ssthresh
                    in_fast_recovery = False
                elif cwnd < ssthresh:
                    cwnd += (ack_idx - base)     # slow start
                else:
                    cwnd += (ack_idx - base) / cwnd  # congestion avoidance
                cwnd = min(cwnd, float(self.max_window))
                if cwnd != old_cwnd:
                    log_cwnd()

                base = ack_idx
                dup_ack_count = 0

            else:
                # Duplicate ACK
                dup_ack_count += 1
                if dup_ack_count == 3 and not in_fast_recovery:
                    ssthresh = max(cwnd / 2.0, 2.0)
                    cwnd = ssthresh + 3.0
                    in_fast_recovery = True
                    log_cwnd()
                    for idx in range(base, min(next_to_send, total)):
                        if idx not in sack_acked:
                            _send_segment(idx, retransmit=True)
                            break
                elif dup_ack_count > 3 and in_fast_recovery:
                    cwnd += 1.0
                    cwnd = min(cwnd, float(self.max_window * 2))
                    log_cwnd()

            # Process SACK blocks (bound-checked against sent range)
            for left, right in pkt.sack_blocks:
                li = self._ack_to_index(left, base)
                ri = self._ack_to_index(right, base)
                if ri > next_to_send:
                    continue  # stale/invalid SACK block
                for idx in range(li, min(ri, total)):
                    if idx >= base:
                        sack_acked.add(idx)

            # Opportunistic retransmit of timed-out segments
            now = time.time()
            for idx in range(base, min(next_to_send, total)):
                if idx not in sack_acked and idx in send_times:
                    if now - send_times[idx] > rto:
                        _send_segment(idx, retransmit=True)
                        break

        return stats


class ReliableReceiver:
    """Reliable receiver with out-of-order buffering and SACK."""

    def __init__(self, channel: LossyChannel, config: dict):
        self.channel = channel
        self.mss = config.get('mss', 500)
        self.max_window = config.get('max_window', 32)
        self.seq_bits = config.get('seq_bits', 16)
        self.seq_mod = 1 << self.seq_bits
        self.recv_window = config.get('recv_window', 64)

    def _in_window(self, seq: int, expected: int) -> bool:
        return ((seq - expected) % self.seq_mod) < self.recv_window

    def _compute_sack_blocks(self, ooo: dict, expected: int):
        if not ooo:
            return []
        seqs = sorted(ooo.keys(),
                      key=lambda s: (s - expected) % self.seq_mod)
        blocks = []
        left = seqs[0]
        right = (seqs[0] + 1) % self.seq_mod
        for s in seqs[1:]:
            if s == right:
                right = (right + 1) % self.seq_mod
            else:
                blocks.append((left, right))
                left = s
                right = (s + 1) % self.seq_mod
        blocks.append((left, right))
        return blocks[:4]

    def receive(self) -> bytes:
        expected = 0
        ooo_buffer: dict[int, bytes] = {}
        received = bytearray()
        last_activity = time.time()
        idle_limit = 60.0

        while True:
            raw = self.channel.recv_forward(timeout=0.5)
            if raw is None:
                if not self.channel.is_running:
                    break
                if time.time() - last_activity > idle_limit:
                    break
                continue

            last_activity = time.time()
            pkt = Packet.deserialize(raw)
            if pkt is None:
                continue

            if pkt.flags & FLAG_FIN:
                ack = Packet(ack_num=expected, flags=FLAG_ACK | FLAG_FIN,
                             window=self.recv_window)
                for _ in range(5):
                    self.channel.send_reverse(ack.serialize())
                # Linger briefly to catch re-sent FINs
                deadline = time.time() + 2.0
                while time.time() < deadline:
                    r = self.channel.recv_forward(timeout=0.5)
                    if r is None:
                        break
                    p = Packet.deserialize(r)
                    if p is not None and (p.flags & FLAG_FIN):
                        self.channel.send_reverse(ack.serialize())
                break

            if pkt.flags & FLAG_DATA:
                seq = pkt.seq_num
                if seq == expected:
                    received.extend(pkt.payload)
                    expected = (expected + 1) % self.seq_mod
                    while expected in ooo_buffer:
                        received.extend(ooo_buffer.pop(expected))
                        expected = (expected + 1) % self.seq_mod
                elif self._in_window(seq, expected):
                    if seq not in ooo_buffer:
                        ooo_buffer[seq] = pkt.payload

                sack_blocks = self._compute_sack_blocks(ooo_buffer, expected)
                ack = Packet(ack_num=expected, flags=FLAG_ACK,
                             window=self.recv_window, sack_blocks=sack_blocks)
                self.channel.send_reverse(ack.serialize())

        return bytes(received)
