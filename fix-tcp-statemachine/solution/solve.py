#!/usr/bin/env python3


"""
Deploy TCP reliable delivery implementation.

Creates three new modules and replaces connection.py with an extended
version integrating retransmission, RTT estimation, congestion control,
and out-of-order reassembly.
"""

import os

# ------------------------------------------------------------------ #
#  Module 1: network.py — LossyChannel                                #
# ------------------------------------------------------------------ #

NETWORK_PY = '''\
"""Deterministic lossy network channel for TCP simulation."""

import heapq
import random


class LossyChannel:
    """Simulates a lossy, potentially-reordering network channel.

    Uses a seeded PRNG for deterministic behavior and a min-heap
    priority queue for time-ordered delivery.
    """

    def __init__(self, loss_rate=0.0, reorder_rate=0.0, seed=42, base_delay_ms=50):
        self.loss_rate = loss_rate
        self.reorder_rate = reorder_rate
        self.base_delay_ms = base_delay_ms
        self.rng = random.Random(seed)
        self._queue = []  # min-heap: (delivery_time, counter, segment, direction)
        self._counter = 0

    def send(self, segment, direction=\'a_to_b\', current_time_ms=0):
        # Drop decision
        if self.rng.random() < self.loss_rate:
            return

        # Compute delivery time with potential reordering jitter
        delay = self.base_delay_ms
        if self.rng.random() < self.reorder_rate:
            delay += self.rng.randint(0, self.base_delay_ms * 3)

        delivery_time = current_time_ms + delay
        heapq.heappush(self._queue,
                       (delivery_time, self._counter, segment, direction))
        self._counter += 1

    def deliver(self, current_time_ms):
        result = []
        while self._queue and self._queue[0][0] <= current_time_ms:
            _, _, segment, direction = heapq.heappop(self._queue)
            result.append((segment, direction))
        return result

    def pending(self):
        return len(self._queue)
'''

# ------------------------------------------------------------------ #
#  Module 2: rtt.py — RTT Estimator (RFC 6298)                        #
# ------------------------------------------------------------------ #

RTT_PY = '''\
"""Jacobson/Karels RTT estimation per RFC 6298."""


class RTTEstimator:
    """Computes smoothed RTT (SRTT), RTT variance (RTTVAR), and
    retransmission timeout (RTO) from ACK round-trip samples.

    Implements:
    - RFC 6298 Section 2: initial RTO, SRTT/RTTVAR computation
    - Karn\'s algorithm: skip retransmitted segment samples
    - Exponential backoff on timeout
    """

    ALPHA = 1.0 / 8.0
    BETA = 1.0 / 4.0
    MIN_RTO = 0.2    # 200ms floor
    MAX_RTO = 8.0    # 8s ceiling (practical limit for simulation)

    def __init__(self):
        self.srtt = None
        self.rttvar = None
        self.rto = 1.0  # Initial RTO = 1 second (RFC 6298 Section 2.1)
        self._first = True

    def on_ack_rtt(self, rtt_sample, is_retransmit=False):
        """Update estimates with a new RTT measurement.

        Args:
            rtt_sample: Measured RTT in seconds.
            is_retransmit: If True, sample is from a retransmitted segment
                           and is ignored per Karn\'s algorithm.
        """
        if is_retransmit:
            return

        if self._first:
            # RFC 6298 Section 2.2: first measurement
            self.srtt = rtt_sample
            self.rttvar = rtt_sample / 2.0
            self._first = False
        else:
            # RFC 6298 Section 2.3: subsequent measurements
            self.rttvar = (1 - self.BETA) * self.rttvar + \\
                          self.BETA * abs(self.srtt - rtt_sample)
            self.srtt = (1 - self.ALPHA) * self.srtt + \\
                        self.ALPHA * rtt_sample

        self.rto = self.srtt + 4.0 * self.rttvar
        self.rto = max(self.MIN_RTO, min(self.rto, self.MAX_RTO))

    def on_timeout(self):
        """Apply exponential backoff: double the RTO."""
        self.rto = min(self.rto * 2.0, self.MAX_RTO)
'''

# ------------------------------------------------------------------ #
#  Module 3: congestion.py — TCP Reno Congestion Control (RFC 5681)    #
# ------------------------------------------------------------------ #

CONGESTION_PY = '''\
"""TCP Reno congestion control per RFC 5681."""


class CongestionController:
    """Manages congestion window (cwnd) and slow-start threshold (ssthresh).

    Phases:
    - Slow start: cwnd < ssthresh, cwnd += MSS per ACK
    - Congestion avoidance: cwnd >= ssthresh, cwnd += MSS*MSS/cwnd per ACK
    - Fast retransmit: 3 duplicate ACKs -> retransmit, enter fast recovery
    - Fast recovery: inflate cwnd, deflate on new ACK
    """

    def __init__(self, mss=1000):
        self.mss = mss
        self.cwnd = mss           # Start at 1 MSS
        self.ssthresh = 65535     # Initial ssthresh (large)
        self.dup_ack_count = 0
        self._in_fast_recovery = False

    def on_ack(self, bytes_acked):
        """Process a new (non-duplicate) ACK."""
        self.dup_ack_count = 0

        if self._in_fast_recovery:
            # Exit fast recovery: deflate cwnd
            self.cwnd = self.ssthresh
            self._in_fast_recovery = False
            return

        if self.cwnd < self.ssthresh:
            # Slow start: exponential growth
            self.cwnd += self.mss
        else:
            # Congestion avoidance: linear growth
            self.cwnd += self.mss * self.mss // self.cwnd

    def on_dup_ack(self):
        """Process a duplicate ACK. Returns True if fast retransmit fires."""
        self.dup_ack_count += 1

        if self.dup_ack_count == 3:
            # Fast retransmit + fast recovery entry
            self.ssthresh = max(self.cwnd // 2, 2 * self.mss)
            self.cwnd = self.ssthresh + 3 * self.mss
            self._in_fast_recovery = True
            return True
        elif self.dup_ack_count > 3 and self._in_fast_recovery:
            # Inflate cwnd during fast recovery
            self.cwnd += self.mss

        return False

    def on_timeout(self):
        """Process a retransmission timeout."""
        self.ssthresh = max(self.cwnd // 2, 2 * self.mss)
        self.cwnd = self.mss
        self.dup_ack_count = 0
        self._in_fast_recovery = False

    def send_window(self):
        """Current congestion window in bytes."""
        return self.cwnd
'''

# ------------------------------------------------------------------ #
#  Module 4: connection.py — Extended with reliable delivery           #
# ------------------------------------------------------------------ #

CONNECTION_PY = '''\
"""
TCP connection state machine with reliable delivery extensions.

Extends RFC 793 state machine with:
- Single retransmission timer per RFC 6298 Section 5
- Jacobson/Karels RTT estimation with Karn\'s algorithm
- Out-of-order segment reassembly
- TCP Reno congestion control (RFC 5681)
- Send buffer decoupled from unacked queue
"""

from enum import Enum, auto
from tcp_sim.segment import TcpSegment
from tcp_sim.rtt import RTTEstimator
from tcp_sim.congestion import CongestionController

MASK32 = 0xFFFFFFFF
MSS = 1000

_ACTIVE_STATES = frozenset()  # filled after State definition


def wrapping_lt(lhs, rhs):
    """Check if lhs < rhs in 32-bit wrapping arithmetic."""
    return ((lhs - rhs) & MASK32) > 0x80000000


def is_between_wrapped(start, x, end):
    """Check if x is in (start, end) under modular 2^32 arithmetic."""
    return wrapping_lt(start, x) and wrapping_lt(x, end)


class State(Enum):
    LISTEN = auto()
    SYN_SENT = auto()
    SYN_RCVD = auto()
    ESTABLISHED = auto()
    FIN_WAIT_1 = auto()
    FIN_WAIT_2 = auto()
    CLOSING = auto()
    TIME_WAIT = auto()
    CLOSE_WAIT = auto()
    LAST_ACK = auto()
    CLOSED = auto()


_ACTIVE_STATES = frozenset({
    State.ESTABLISHED, State.CLOSE_WAIT,
    State.FIN_WAIT_1, State.FIN_WAIT_2,
    State.CLOSING, State.LAST_ACK,
})


class TcpConnection:
    """TCP connection with reliable delivery over lossy networks."""

    def __init__(self, local_port=0, iss=0):
        self.state = State.LISTEN
        self.local_port = local_port
        self.remote_port = 0

        # Send sequence space
        self.send_iss = iss
        self.send_una = iss
        self.send_nxt = iss
        self.send_wnd = 0

        # Receive sequence space
        self.recv_irs = 0
        self.recv_nxt = 0
        self.recv_wnd = 65535

        # Data buffers
        self.incoming = bytearray()
        self.unacked = bytearray()
        self.send_buffer = bytearray()

        # Teardown
        self.closed = False
        self.closed_at = None
        self._outgoing = []

        # --- Reliable delivery state ---
        self.rtt_estimator = RTTEstimator()
        self.congestion = CongestionController(mss=MSS)
        self.oo_buffer = {}             # {seq: bytes} out-of-order segments
        self.send_times = {}            # {seq: send_time_ms} for RTT sampling
        self.retransmitted_seqs = set() # seqs retransmitted (Karn exclusion)
        self.dup_ack_count = 0
        self.current_time_ms = 0
        self.rto_timer_start = None     # single retransmission timer

    def connect(self, remote_port):
        """Active open: send SYN."""
        if self.state != State.LISTEN:
            raise RuntimeError(f"Cannot connect in state {self.state}")
        self.remote_port = remote_port
        self.state = State.SYN_SENT
        self._outgoing = []
        self._send_control(syn=True)
        return self._flush()

    def tick(self, current_time_ms):
        """Advance clock. Handle retransmission timeout and pending sends."""
        self.current_time_ms = current_time_ms
        self._outgoing = []

        if self.state not in _ACTIVE_STATES:
            return self._flush()

        # --- Single retransmission timer (RFC 6298 Section 5) ---
        if (self.rto_timer_start is not None
                and len(self.unacked) > 0):
            rto_ms = self.rtt_estimator.rto * 1000.0
            if current_time_ms - self.rto_timer_start >= rto_ms:
                # Timeout: retransmit the segment at send_una
                data = bytes(self.unacked[:MSS])
                if data:
                    self._send_data_segment_at(self.send_una, data)
                    self.retransmitted_seqs.add(self.send_una)
                    self.rtt_estimator.on_timeout()
                    self.congestion.on_timeout()
                    self.rto_timer_start = current_time_ms  # restart timer

        # Try sending buffered data
        self._try_send()
        return self._flush()

    def on_segment(self, seg):
        """Process an incoming TCP segment."""
        self._outgoing = []

        if self.state in (State.CLOSED, State.LISTEN):
            return self._handle_closed_or_listen(seg)

        seqn = seg.seq_num
        slen = seg.seg_len()

        if self.state == State.SYN_SENT:
            return self._handle_syn_sent(seg)

        # Segment acceptability
        wend = (self.recv_nxt + self.recv_wnd) & MASK32
        if not self._is_acceptable(seqn, slen, wend):
            if not seg.rst:
                self._send_control(ack=True)
            return self._flush()

        if seg.rst:
            self.state = State.CLOSED
            return []

        if not seg.ack:
            return self._flush()

        ackn = seg.ack_num

        # SYN_RCVD ACK
        if self.state == State.SYN_RCVD:
            if is_between_wrapped(
                (self.send_una - 1) & MASK32, ackn,
                (self.send_nxt + 1) & MASK32,
            ):
                self.state = State.ESTABLISHED
            else:
                self._send_control(rst=True)
                return self._flush()

        # ACK processing in synchronized states
        if self.state in _ACTIVE_STATES:
            if is_between_wrapped(
                self.send_una, ackn, (self.send_nxt + 1) & MASK32
            ):
                # --- New ACK: advances the window ---
                acked = min((ackn - self.send_una) & MASK32,
                            len(self.unacked))

                # RTT sampling: use oldest non-retransmitted acked segment
                for seq in sorted(self.send_times.keys()):
                    if not wrapping_lt(seq, ackn):
                        break
                    if seq not in self.retransmitted_seqs:
                        rtt_s = (self.current_time_ms
                                 - self.send_times[seq]) / 1000.0
                        if rtt_s > 0:
                            self.rtt_estimator.on_ack_rtt(rtt_s)
                        break  # one sample per ACK

                # Clean up acked entries
                for seq in [s for s in self.send_times
                            if wrapping_lt(s, ackn)]:
                    del self.send_times[seq]
                    self.retransmitted_seqs.discard(seq)

                self.unacked = self.unacked[acked:]
                self.send_una = ackn
                self.send_wnd = seg.window

                # Congestion control
                self.congestion.on_ack(acked)
                self.dup_ack_count = 0

                # Restart retransmission timer (RFC 6298 Section 5.3)
                if len(self.unacked) > 0:
                    self.rto_timer_start = self.current_time_ms
                else:
                    self.rto_timer_start = None

                self._try_send()

            elif ackn == self.send_una and len(self.unacked) > 0:
                # --- Duplicate ACK ---
                self.dup_ack_count += 1
                if self.congestion.on_dup_ack():
                    # Fast retransmit
                    rt_data = bytes(self.unacked[:MSS])
                    if rt_data:
                        self._send_data_segment_at(self.send_una, rt_data)
                        self.retransmitted_seqs.add(self.send_una)
                        self.rto_timer_start = self.current_time_ms

        # FIN_WAIT_1 -> FIN_WAIT_2
        if self.state == State.FIN_WAIT_1:
            if self.closed_at is not None:
                if self.send_una == ((self.closed_at + 1) & MASK32):
                    self.state = State.FIN_WAIT_2

        # CLOSING -> TIME_WAIT
        if self.state == State.CLOSING:
            if self.closed_at is not None:
                if self.send_una == ((self.closed_at + 1) & MASK32):
                    self.state = State.TIME_WAIT
            return self._flush()

        # LAST_ACK -> CLOSED
        if self.state == State.LAST_ACK:
            if self.closed_at is not None:
                if self.send_una == ((self.closed_at + 1) & MASK32):
                    self.state = State.CLOSED
            return self._flush()

        # --- Data processing with out-of-order reassembly ---
        if seg.data and self.state in (
            State.ESTABLISHED, State.FIN_WAIT_1, State.FIN_WAIT_2,
        ):
            if seqn == self.recv_nxt:
                # In-order: deliver and flush OO buffer
                self.incoming.extend(seg.data)
                self.recv_nxt = (seqn + len(seg.data)) & MASK32
                while self.recv_nxt in self.oo_buffer:
                    oo_data = self.oo_buffer.pop(self.recv_nxt)
                    self.incoming.extend(oo_data)
                    self.recv_nxt = (self.recv_nxt + len(oo_data)) & MASK32
                self._send_control(ack=True)
            elif wrapping_lt(self.recv_nxt, seqn):
                # Out-of-order: buffer
                if seqn not in self.oo_buffer:
                    self.oo_buffer[seqn] = bytes(seg.data)
                self._send_control(ack=True)  # dup ACK
            else:
                self._send_control(ack=True)

        # --- FIN processing ---
        if seg.fin:
            self.recv_nxt = (self.recv_nxt + 1) & MASK32
            if self.state == State.ESTABLISHED:
                self.state = State.CLOSE_WAIT
                self._send_control(ack=True)
            elif self.state == State.FIN_WAIT_1:
                self.state = State.CLOSING
                self._send_control(ack=True)
            elif self.state == State.FIN_WAIT_2:
                self.state = State.TIME_WAIT
                self._send_control(ack=True)

        return self._flush()

    def send_data(self, data):
        """Queue data for sending. Transmits what the window allows."""
        if self.state not in (State.ESTABLISHED, State.CLOSE_WAIT):
            raise RuntimeError(f"Cannot send data in state {self.state}")
        self._outgoing = []
        self.send_buffer.extend(data)
        self._try_send()
        return self._flush()

    def close(self):
        """Initiate connection close."""
        self._outgoing = []
        self.closed = True
        if self.state in (State.ESTABLISHED, State.SYN_RCVD):
            self.state = State.FIN_WAIT_1
            self.closed_at = (self.send_una + len(self.unacked)) & MASK32
            self._send_control(ack=True, fin=True)
        elif self.state == State.CLOSE_WAIT:
            self.state = State.LAST_ACK
            self.closed_at = (self.send_una + len(self.unacked)) & MASK32
            self._send_control(ack=True, fin=True)
        return self._flush()

    def read_data(self):
        """Read and clear the incoming data buffer."""
        data = bytes(self.incoming)
        self.incoming.clear()
        return data

    # ------------------------------------------------------------------ #
    #                       Private helpers                                #
    # ------------------------------------------------------------------ #

    def _try_send(self):
        """Send as much buffered data as the congestion+flow window allows."""
        while self.send_buffer:
            nunacked = (self.send_nxt - self.send_una) & MASK32
            eff_wnd = min(self.send_wnd, self.congestion.send_window())
            allowed = max(0, eff_wnd - nunacked)
            if allowed <= 0:
                break
            chunk_sz = min(len(self.send_buffer), allowed, MSS)
            if chunk_sz <= 0:
                break
            chunk = bytes(self.send_buffer[:chunk_sz])
            self.send_buffer = self.send_buffer[chunk_sz:]
            seq = self.send_nxt
            self.unacked.extend(chunk)
            self._send_data_segment(chunk)
            self.send_times[seq] = self.current_time_ms
            # Start retransmission timer if idle
            if self.rto_timer_start is None:
                self.rto_timer_start = self.current_time_ms

    def _handle_closed_or_listen(self, seg):
        if self.state == State.CLOSED:
            return []
        if seg.rst:
            return []
        if seg.ack:
            self._outgoing = []
            self._send_control(rst=True)
            return self._flush()
        if seg.syn:
            self.recv_irs = seg.seq_num
            self.recv_nxt = (seg.seq_num + 1) & MASK32
            self.send_wnd = seg.window
            self.remote_port = seg.src_port
            self.state = State.SYN_RCVD
            self._outgoing = []
            self._send_control(syn=True, ack=True)
        return self._flush()

    def _handle_syn_sent(self, seg):
        if seg.ack:
            if not is_between_wrapped(
                self.send_iss, seg.ack_num,
                (self.send_nxt + 1) & MASK32,
            ):
                if not seg.rst:
                    self._send_control(rst=True)
                return self._flush()
        if seg.rst:
            if seg.ack:
                self.state = State.CLOSED
            return self._flush()
        if seg.syn:
            self.recv_irs = seg.seq_num
            self.recv_nxt = (seg.seq_num + 1) & MASK32
            self.send_wnd = seg.window
            self.remote_port = seg.src_port
            if seg.ack:
                self.send_una = seg.ack_num
                self.state = State.ESTABLISHED
                self._send_control(ack=True)
            else:
                self.state = State.SYN_RCVD
                self._send_control(syn=True, ack=True)
        return self._flush()

    def _is_acceptable(self, seqn, slen, wend):
        if slen == 0:
            if self.recv_wnd == 0:
                return seqn == self.recv_nxt
            return is_between_wrapped(
                (self.recv_nxt - 1) & MASK32, seqn, wend)
        if self.recv_wnd == 0:
            return False
        return (is_between_wrapped(
                    (self.recv_nxt - 1) & MASK32, seqn, wend)
                or is_between_wrapped(
                    (self.recv_nxt - 1) & MASK32,
                    (seqn + slen - 1) & MASK32, wend))

    def _send_control(self, syn=False, ack=False, fin=False, rst=False):
        seg = TcpSegment(
            src_port=self.local_port, dst_port=self.remote_port,
            seq_num=self.send_nxt,
            ack_num=self.recv_nxt if ack else 0,
            window=self.recv_wnd,
            syn=syn, ack=ack, fin=fin, rst=rst)
        nxt = self.send_nxt
        if syn:
            nxt = (nxt + 1) & MASK32
        if fin:
            nxt = (nxt + 1) & MASK32
        if wrapping_lt(self.send_nxt, nxt):
            self.send_nxt = nxt
        self._outgoing.append(seg)

    def _send_data_segment(self, data):
        seg = TcpSegment(
            src_port=self.local_port, dst_port=self.remote_port,
            seq_num=self.send_nxt, ack_num=self.recv_nxt,
            window=self.recv_wnd, ack=True, data=bytes(data))
        nxt = (self.send_nxt + len(data)) & MASK32
        if wrapping_lt(self.send_nxt, nxt):
            self.send_nxt = nxt
        self._outgoing.append(seg)

    def _send_data_segment_at(self, seq, data):
        """Retransmit: send data at specific seq without advancing send_nxt."""
        seg = TcpSegment(
            src_port=self.local_port, dst_port=self.remote_port,
            seq_num=seq, ack_num=self.recv_nxt,
            window=self.recv_wnd, ack=True, data=bytes(data))
        self._outgoing.append(seg)

    def _flush(self):
        out = self._outgoing
        self._outgoing = []
        return out
'''

# ------------------------------------------------------------------ #
#  Deploy all modules                                                  #
# ------------------------------------------------------------------ #

def deploy():
    modules = {
        '/app/tcp_sim/network.py': NETWORK_PY,
        '/app/tcp_sim/rtt.py': RTT_PY,
        '/app/tcp_sim/congestion.py': CONGESTION_PY,
        '/app/tcp_sim/connection.py': CONNECTION_PY,
    }

    for path, content in modules.items():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write(content)
        print(f"Deployed {path}")

    print("All TCP reliable delivery modules deployed successfully.")


if __name__ == '__main__':
    deploy()
