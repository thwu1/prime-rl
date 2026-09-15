"""Tests for CUBIC congestion control implementation.

Verifies correctness of the CUBIC algorithm per RFC 8312bis,
including K computation, W_cubic, fast convergence, W_est
increments, alpha_aimd adaptation, and end-to-end simulation.
"""

import sys
sys.path.insert(0, '/app')

import math
import pytest
from cubic import CubicCC, CubicState, BETA_CUBIC, C, ALPHA_AIMD

MDS = 1200  # max_datagram_size


class TestCubicK:
    """Tests for K computation (Eq. 2: K = cbrt((W_max - cwnd) / C))."""

    def test_k_basic(self):
        """K must account for both w_max and current cwnd."""
        cc = CubicCC(max_datagram_size=MDS)
        cc.cubic.w_max = 30000.0  # 25 packets
        k = cc.cubic_k(21000)     # 17.5 packets

        w_max_pkts = 30000.0 / MDS
        cwnd_pkts = 21000.0 / MDS
        expected_k = math.pow((w_max_pkts - cwnd_pkts) / C, 1.0 / 3.0)

        assert abs(k - expected_k) < 0.001, \
            f"K={k:.4f}, expected={expected_k:.4f}"

    def test_k_when_cwnd_equals_w_max(self):
        """When cwnd equals w_max, K must be zero (no recovery needed)."""
        cc = CubicCC(max_datagram_size=MDS)
        cc.cubic.w_max = 24000.0
        k = cc.cubic_k(24000)
        assert abs(k) < 0.001, f"K should be ~0 when cwnd=w_max, got {k}"

    def test_k_determines_w_cubic_peak(self):
        """W_cubic(K) must equal w_max: the CUBIC curve peaks at t=K."""
        cc = CubicCC(max_datagram_size=MDS)
        cc.cubic.w_max = 36000.0  # 30 packets
        cwnd_after_loss = int(36000 * BETA_CUBIC)  # 25200
        cc.cubic.k = cc.cubic_k(cwnd_after_loss)

        w_at_k = cc.w_cubic(cc.cubic.k)
        assert abs(w_at_k - 36000.0) < 10.0, \
            f"W_cubic(K)={w_at_k:.1f}, expected ~36000.0"

    def test_k_different_mds(self):
        """K computation must work with different datagram sizes."""
        cc = CubicCC(max_datagram_size=1000)
        cc.cubic.w_max = 25000.0  # 25 packets
        k = cc.cubic_k(17500)     # 17.5 packets

        expected_k = math.pow((25.0 - 17.5) / C, 1.0 / 3.0)
        assert abs(k - expected_k) < 0.001


class TestCongestionEvent:
    """Tests for congestion event handling and fast convergence."""

    def test_multiplicative_decrease(self):
        """Loss must reduce cwnd by factor BETA_CUBIC."""
        cc = CubicCC(max_datagram_size=MDS)
        cc.congestion_window = 30000
        cc.on_congestion_event(1.0)

        expected_cwnd = int(30000 * BETA_CUBIC)
        assert cc.congestion_window == expected_cwnd, \
            f"cwnd={cc.congestion_window}, expected={expected_cwnd}"
        assert cc.ssthresh == expected_cwnd

    def test_w_max_set_on_first_loss(self):
        """First loss must set w_max to the pre-loss cwnd."""
        cc = CubicCC(max_datagram_size=MDS)
        cc.congestion_window = 30000
        cc.on_congestion_event(1.0)
        assert cc.cubic.w_max == 30000.0

    def test_fast_convergence_formula(self):
        """Fast convergence: when cwnd < w_max at loss,
        w_max = cwnd * (1 + beta) / 2 (RFC 8312bis Section 4.6)."""
        cc = CubicCC(max_datagram_size=MDS)
        cc.congestion_window = 20000
        cc.cubic.w_max = 30000.0
        cc.congestion_recovery_start_time = 0.5

        cc.on_congestion_event(2.0)

        expected_w_max = 20000.0 * (1.0 + BETA_CUBIC) / 2.0
        assert abs(cc.cubic.w_max - expected_w_max) < 1.0, \
            f"w_max={cc.cubic.w_max}, expected={expected_w_max}"

        expected_cwnd = int(20000 * BETA_CUBIC)
        assert cc.congestion_window == expected_cwnd

    def test_fast_convergence_bounds(self):
        """Fast convergence w_max must lie between cwnd*beta and cwnd."""
        cc = CubicCC(max_datagram_size=MDS)
        pre_loss_cwnd = 24000
        cc.congestion_window = pre_loss_cwnd
        cc.cubic.w_max = 36000.0
        cc.congestion_recovery_start_time = 0.5

        cc.on_congestion_event(2.0)

        assert cc.cubic.w_max > pre_loss_cwnd * BETA_CUBIC, \
            f"Fast convergence w_max={cc.cubic.w_max} too small"
        assert cc.cubic.w_max < pre_loss_cwnd, \
            f"Fast convergence w_max={cc.cubic.w_max} too large"

    def test_minimum_window(self):
        """cwnd after loss must be at least MINIMUM_WINDOW_PACKETS * MSS."""
        cc = CubicCC(max_datagram_size=MDS)
        cc.congestion_window = MDS * 2  # very small
        cc.on_congestion_event(1.0)
        assert cc.congestion_window >= MDS * 2


class TestWEst:
    """Tests for the TCP-friendly AIMD estimate (W_est)."""

    def test_w_est_increment_formula(self):
        """W_est increment = alpha * (acked/cwnd) * MSS."""
        cc = CubicCC(max_datagram_size=MDS)
        cc.cubic.alpha_aimd = ALPHA_AIMD

        inc = cc.w_est_inc(MDS, 24000)

        expected = ALPHA_AIMD * (MDS / 24000) * MDS
        assert abs(inc - expected) < 0.1, \
            f"w_est_inc={inc:.4f}, expected={expected:.4f}"

    def test_w_est_increment_not_negligible(self):
        """W_est increment must produce meaningful byte growth,
        not fractional values that round to zero."""
        cc = CubicCC(max_datagram_size=MDS)
        inc = cc.w_est_inc(MDS, 24000)
        assert inc > 10.0, \
            f"w_est_inc={inc:.6f} too small; TCP-friendly region non-functional"

    def test_w_est_increment_scales_with_mds(self):
        """Larger datagrams must produce proportionally larger increments."""
        cc1 = CubicCC(max_datagram_size=1200)
        cc2 = CubicCC(max_datagram_size=1400)

        inc1 = cc1.w_est_inc(1200, 24000)
        inc2 = cc2.w_est_inc(1400, 28000)  # same ratio acked/cwnd

        # Both have same acked/cwnd ratio (1/20), so inc should scale with mds
        assert inc2 > inc1, \
            f"Larger MSS should give larger increment: {inc2} vs {inc1}"

    def test_alpha_aimd_update(self):
        """When w_est reaches w_max, alpha_aimd must be set to 1.0."""
        cc = CubicCC(max_datagram_size=MDS)
        cc.congestion_window = 24000
        cc.ssthresh = 20000
        cc.cubic.w_max = 24001.0
        cc.cubic.w_est = 24000.99
        cc.cubic.k = 0.0
        cc.cubic.alpha_aimd = ALPHA_AIMD
        cc.congestion_recovery_start_time = 0.0

        # A single ACK should push w_est past w_max
        cc.on_ack(MDS, 0.5, 0.6, 0.1)

        assert cc.cubic.alpha_aimd == 1.0, \
            f"alpha_aimd={cc.cubic.alpha_aimd}, expected 1.0 after w_est >= w_max"


class TestSimulation:
    """End-to-end integration tests."""

    def test_slow_start(self):
        """Slow start: cwnd += MSS per ACK."""
        cc = CubicCC(max_datagram_size=MDS)
        initial = cc.congestion_window

        for _ in range(5):
            cc.on_ack(MDS, 0.0, 0.1, 0.1)

        assert cc.congestion_window == initial + 5 * MDS

    def test_loss_reduces_cwnd(self):
        """Loss at the end of slow start reduces cwnd correctly."""
        cc = CubicCC(max_datagram_size=MDS)
        for _ in range(15):
            cc.on_ack(MDS, 0.0, 0.1, 0.1)
        pre_loss = cc.congestion_window
        assert pre_loss == 12000 + 15 * MDS

        cc.on_congestion_event(0.2)
        assert cc.congestion_window == int(pre_loss * BETA_CUBIC)

    def test_cwnd_recovery(self):
        """After loss, cwnd must recover through congestion avoidance."""
        cc = CubicCC(max_datagram_size=MDS)
        for _ in range(15):
            cc.on_ack(MDS, 0.0, 0.1, 0.1)
        pre_loss = cc.congestion_window  # 30000

        t_loss = 0.2
        cc.on_congestion_event(t_loss)
        post_loss = cc.congestion_window  # 21000

        # Run 200 ACKs over ~20 seconds of congestion avoidance
        for i in range(200):
            send_time = t_loss + 0.01 + i * 0.1
            ack_time = send_time + 0.1
            cc.on_ack(MDS, send_time, ack_time, 0.1)

        assert cc.congestion_window > post_loss, \
            f"cwnd={cc.congestion_window} must exceed post_loss={post_loss}"
        assert cc.congestion_window >= pre_loss, \
            f"After 20s CA, cwnd={cc.congestion_window} should reach pre_loss={pre_loss}"

    def test_two_losses_fast_convergence(self):
        """Two consecutive losses should trigger fast convergence on the
        second loss, producing a smaller w_max than a single loss."""
        cc = CubicCC(max_datagram_size=MDS)
        cc.congestion_window = 30000

        # First loss
        cc.on_congestion_event(1.0)
        w_max_after_first = cc.cubic.w_max
        cwnd_after_first = cc.congestion_window

        # Brief recovery (a few ACKs, not enough to reach w_max)
        for i in range(5):
            send_time = 1.01 + i * 0.1
            cc.on_ack(MDS, send_time, send_time + 0.1, 0.1)

        # Second loss while cwnd < w_max
        assert cc.congestion_window < w_max_after_first, \
            "cwnd should still be below w_max for fast convergence to apply"

        pre_second_loss = cc.congestion_window
        cc.on_congestion_event(2.0)

        # Fast convergence should make w_max < pre_second_loss
        assert cc.cubic.w_max < pre_second_loss, \
            f"w_max={cc.cubic.w_max} should be reduced below cwnd={pre_second_loss}"
        assert cc.cubic.w_max > cc.congestion_window, \
            f"w_max={cc.cubic.w_max} should exceed post-loss cwnd={cc.congestion_window}"
