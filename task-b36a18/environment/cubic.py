"""CUBIC Congestion Control Implementation.

Based on draft-ietf-tcpm-rfc8312bis-02 and production QUIC transport
stacks. Implements the CUBIC window growth function, multiplicative
decrease, fast convergence, and TCP-friendly AIMD fallback.

References:
- https://tools.ietf.org/html/draft-ietf-tcpm-rfc8312bis-02
- https://www.rfc-editor.org/rfc/rfc8312
"""


import math
from dataclasses import dataclass, field

# CUBIC constants per RFC 8312
BETA_CUBIC = 0.7
C = 0.4
ALPHA_AIMD = 3.0 * (1.0 - BETA_CUBIC) / (1.0 + BETA_CUBIC)
MINIMUM_WINDOW_PACKETS = 2
INITIAL_WINDOW_PACKETS = 10


@dataclass
class CubicState:
    """State variables for the CUBIC algorithm.

    Tracks the cubic function parameters (k, w_max), the TCP-friendly
    estimate (w_est, alpha_aimd), and fractional cwnd accumulation.
    """
    k: float = 0.0
    w_max: float = 0.0
    w_est: float = 0.0
    alpha_aimd: float = ALPHA_AIMD
    cwnd_inc: int = 0


class CubicCC:
    """CUBIC congestion control.

    Manages congestion window evolution through slow start, congestion
    avoidance (CUBIC curve), and multiplicative decrease phases.
    """

    def __init__(self, max_datagram_size: int = 1200):
        self.max_datagram_size = max_datagram_size
        self.congestion_window = max_datagram_size * INITIAL_WINDOW_PACKETS
        self.ssthresh = float('inf')
        self.cubic = CubicState()
        self.congestion_recovery_start_time = None

    def cubic_k(self, cwnd: int) -> float:
        """Compute K: the time for the CUBIC function to reach W_max.

        K = cubic_root((W_max - cwnd) / C)
        where values are converted to packet counts.
        See Eq. 2 in RFC 8312bis.
        """
        w_max = self.cubic.w_max / self.max_datagram_size
        cwnd_pkts = cwnd / self.max_datagram_size
        return math.pow(w_max / C, 1.0 / 3.0)

    def w_cubic(self, t: float) -> float:
        """Compute W_cubic(t) = C * (t - K)^3 + W_max.

        Returns the CUBIC target window in bytes at time t seconds
        since the last congestion event.
        See Eq. 1 in RFC 8312bis.
        """
        w_max = self.cubic.w_max / self.max_datagram_size
        return (C * (t - self.cubic.k) ** 3 + w_max) * self.max_datagram_size

    def w_est_inc(self, acked: int, cwnd: int) -> float:
        """Compute the W_est (TCP-friendly) window increment per ACK.

        W_est += alpha_aimd * (segments_acked / cwnd)
        See Eq. 4 in RFC 8312bis.
        """
        return self.cubic.alpha_aimd * (acked / cwnd)

    def on_congestion_event(self, now: float) -> None:
        """Handle a congestion event (packet loss detected).

        Reduces the congestion window by beta_cubic and computes
        new CUBIC parameters. Applies fast convergence when the
        current window hasn't recovered to the previous maximum.
        """
        # Skip if already in a congestion recovery period
        if self.congestion_recovery_start_time is not None:
            if now <= self.congestion_recovery_start_time:
                return

        self.congestion_recovery_start_time = now

        # Fast convergence (RFC 8312bis Section 4.6):
        # When cwnd < w_max, reduce w_max further to allow
        # competing flows to converge faster.
        if self.congestion_window < self.cubic.w_max:
            self.cubic.w_max = self.congestion_window * BETA_CUBIC / 2.0
        else:
            self.cubic.w_max = float(self.congestion_window)

        # Multiplicative decrease
        ssthresh = int(self.congestion_window * BETA_CUBIC)
        ssthresh = max(ssthresh, self.max_datagram_size * MINIMUM_WINDOW_PACKETS)
        self.ssthresh = ssthresh
        self.congestion_window = ssthresh

        # Compute K for the new congestion avoidance epoch
        if self.cubic.w_max < self.congestion_window:
            self.cubic.k = 0.0
        else:
            self.cubic.k = self.cubic_k(self.congestion_window)

        self.cubic.cwnd_inc = int(self.cubic.cwnd_inc * BETA_CUBIC)
        self.cubic.w_est = float(self.congestion_window)
        self.cubic.alpha_aimd = ALPHA_AIMD

    def on_ack(self, acked_bytes: int, time_sent: float,
               now: float, min_rtt: float) -> None:
        """Handle an acknowledgement for acked_bytes.

        Updates the congestion window based on whether we are in
        slow start or congestion avoidance. In congestion avoidance,
        uses the larger of the CUBIC window and the TCP-friendly
        AIMD estimate.
        """
        # Ignore ACKs for packets sent during the recovery period
        if self.congestion_recovery_start_time is not None:
            if time_sent <= self.congestion_recovery_start_time:
                return

        if self.congestion_window < self.ssthresh:
            # Slow start: increase cwnd by one MSS per ACK
            self.congestion_window += self.max_datagram_size
        else:
            # Congestion avoidance
            if self.congestion_recovery_start_time is None:
                # First time entering CA without a prior loss event
                self.congestion_recovery_start_time = now
                self.cubic.w_max = float(self.congestion_window)
                self.cubic.k = 0.0
                self.cubic.w_est = float(self.congestion_window)
                self.cubic.alpha_aimd = ALPHA_AIMD

            t = now - self.congestion_recovery_start_time

            # Target window: W_cubic evaluated one RTT into the future
            target = self.w_cubic(t + min_rtt)

            # Clip target to [cwnd, 1.5 * cwnd] to prevent burst growth
            target = max(target, float(self.congestion_window))
            target = min(target, self.congestion_window * 1.5)

            # Update TCP-friendly estimate (W_est)
            w_est_inc = self.w_est_inc(acked_bytes, self.congestion_window)
            self.cubic.w_est += w_est_inc

            cubic_cwnd = self.congestion_window

            if self.w_cubic(t) < self.cubic.w_est:
                # TCP-friendly region: use AIMD estimate
                cubic_cwnd = max(cubic_cwnd, int(self.cubic.w_est))
            else:
                # CUBIC concave or convex region
                cubic_inc = (self.max_datagram_size *
                             (int(target) - cubic_cwnd) // cubic_cwnd)
                cubic_cwnd += cubic_inc

            # Accumulate fractional window increments
            self.cubic.cwnd_inc += cubic_cwnd - self.congestion_window

            # Increase cwnd by one MSS when enough bytes accumulated
            if self.cubic.cwnd_inc >= self.max_datagram_size:
                self.congestion_window += self.max_datagram_size
                self.cubic.cwnd_inc -= self.max_datagram_size
