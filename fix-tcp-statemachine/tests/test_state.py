
"""
Tests for TCP reliable delivery over lossy networks.

Validates:
- LossyChannel deterministic behavior
- RTT estimation per RFC 6298 (Jacobson/Karels)
- Congestion control per RFC 5681 (TCP Reno)
- Out-of-order segment reassembly
- End-to-end reliable data delivery under loss and reordering
"""

import sys
import hashlib
import pytest

sys.path.insert(0, "/app")
from tcp_sim.connection import TcpConnection, State
from tcp_sim.segment import TcpSegment


# ------------------------------------------------------------------ #
#  Helpers                                                             #
# ------------------------------------------------------------------ #


def _handshake(server_iss=1000, client_iss=100, client_window=65535):
    """Perform a three-way handshake. Returns (server, client) in ESTABLISHED."""
    server = TcpConnection(local_port=80, iss=server_iss)
    client = TcpConnection(local_port=5000, iss=client_iss)
    client.recv_wnd = client_window

    syns = client.connect(80)
    assert len(syns) == 1 and syns[0].syn

    syn_acks = server.on_segment(syns[0])
    assert len(syn_acks) == 1 and syn_acks[0].syn and syn_acks[0].ack

    acks = client.on_segment(syn_acks[0])
    assert client.state == State.ESTABLISHED

    server.on_segment(acks[0])
    assert server.state == State.ESTABLISHED

    return server, client


def _simulate_transfer(data, loss_rate=0.0, reorder_rate=0.0, seed=42,
                       base_delay_ms=50, max_time_ms=120000):
    """Simulate a full data transfer from server to client through a lossy channel.

    Returns (received_bytes, elapsed_time_ms, server, client).
    """
    from tcp_sim.network import LossyChannel

    channel = LossyChannel(
        loss_rate=loss_rate, reorder_rate=reorder_rate,
        seed=seed, base_delay_ms=base_delay_ms
    )
    server, client = _handshake()

    # Queue all data for sending
    initial_segs = server.send_data(data)
    for seg in initial_segs:
        channel.send(seg, 'a_to_b', 0)

    received = bytearray()
    time_ms = 0
    tick_interval = 10  # ms

    while time_ms < max_time_ms:
        time_ms += tick_interval

        # Tick first — updates current_time, handles retransmissions
        for seg in server.tick(time_ms):
            channel.send(seg, 'a_to_b', time_ms)
        for seg in client.tick(time_ms):
            channel.send(seg, 'b_to_a', time_ms)

        # Deliver segments from channel
        for seg, direction in channel.deliver(time_ms):
            if direction == 'a_to_b':
                for r in client.on_segment(seg):
                    channel.send(r, 'b_to_a', time_ms)
            else:
                for r in server.on_segment(seg):
                    channel.send(r, 'a_to_b', time_ms)

        # Read delivered data
        chunk = client.read_data()
        if chunk:
            received.extend(chunk)

        # Check completion
        if (len(received) >= len(data)
                and channel.pending() == 0
                and len(server.unacked) == 0):
            break

    return bytes(received), time_ms, server, client


# ------------------------------------------------------------------ #
#  Backwards Compatibility Tests                                       #
# ------------------------------------------------------------------ #


class TestBackwardsCompat:
    """Verify basic TCP state machine functionality is preserved."""

    def test_handshake(self):
        """Three-way handshake must still reach ESTABLISHED."""
        server, client = _handshake()
        assert server.state == State.ESTABLISHED
        assert client.state == State.ESTABLISHED

    def test_basic_data_transfer(self):
        """Simple data transfer without lossy channel must work."""
        server, client = _handshake()
        segs = server.send_data(b"hello world")
        assert len(segs) >= 1
        acks = client.on_segment(segs[0])
        assert client.read_data() == b"hello world"

    def test_tick_method_exists(self):
        """TcpConnection must expose a tick(current_time_ms) method."""
        server, client = _handshake()
        result = server.tick(0)
        assert isinstance(result, list)


# ------------------------------------------------------------------ #
#  LossyChannel Tests                                                  #
# ------------------------------------------------------------------ #


class TestLossyChannel:
    def test_no_loss_delivery(self):
        """With loss_rate=0, all segments are delivered after delay."""
        from tcp_sim.network import LossyChannel
        ch = LossyChannel(loss_rate=0.0, seed=1, base_delay_ms=10)
        seg = TcpSegment(80, 5000, 0, 0, 65535, data=b"test")
        ch.send(seg, 'a_to_b', 0)
        delivered = ch.deliver(10)
        assert len(delivered) == 1
        assert delivered[0][0].data == b"test"
        assert delivered[0][1] == 'a_to_b'

    def test_total_loss(self):
        """With loss_rate=1.0, no segments are ever delivered."""
        from tcp_sim.network import LossyChannel
        ch = LossyChannel(loss_rate=1.0, seed=1, base_delay_ms=10)
        for i in range(100):
            seg = TcpSegment(80, 5000, i, 0, 65535, data=b"x")
            ch.send(seg, 'a_to_b', 0)
        delivered = ch.deliver(1000000)
        assert len(delivered) == 0

    def test_deterministic_pattern(self):
        """Same seed must produce identical loss/delivery patterns."""
        from tcp_sim.network import LossyChannel
        results = []
        for _ in range(2):
            ch = LossyChannel(loss_rate=0.5, seed=42, base_delay_ms=10)
            for i in range(100):
                seg = TcpSegment(80, 5000, i, 0, 65535, data=b"x")
                ch.send(seg, 'a_to_b', 0)
            results.append(len(ch.deliver(1000000)))
        assert results[0] == results[1]
        assert 30 <= results[0] <= 70  # Roughly 50% ± tolerance

    def test_delay_timing(self):
        """Segments must not arrive before base_delay_ms."""
        from tcp_sim.network import LossyChannel
        ch = LossyChannel(loss_rate=0.0, seed=1, base_delay_ms=100)
        seg = TcpSegment(80, 5000, 0, 0, 65535)
        ch.send(seg, 'a_to_b', 0)
        assert len(ch.deliver(99)) == 0
        assert len(ch.deliver(100)) == 1

    def test_pending_count(self):
        """pending() must track segments in transit accurately."""
        from tcp_sim.network import LossyChannel
        ch = LossyChannel(loss_rate=0.0, seed=1, base_delay_ms=100)
        assert ch.pending() == 0
        seg = TcpSegment(80, 5000, 0, 0, 65535)
        ch.send(seg, 'a_to_b', 0)
        assert ch.pending() == 1
        ch.deliver(100)
        assert ch.pending() == 0


# ------------------------------------------------------------------ #
#  RTT Estimator Tests                                                 #
# ------------------------------------------------------------------ #


class TestRTTEstimator:
    def test_initial_rto(self):
        """Initial RTO must be 1 second per RFC 6298 Section 2.1."""
        from tcp_sim.rtt import RTTEstimator
        est = RTTEstimator()
        assert abs(est.rto - 1.0) < 1e-6

    def test_first_sample(self):
        """First sample: SRTT=R, RTTVAR=R/2 per RFC 6298 Section 2.2."""
        from tcp_sim.rtt import RTTEstimator
        est = RTTEstimator()
        est.on_ack_rtt(0.1)
        assert abs(est.srtt - 0.1) < 1e-9
        assert abs(est.rttvar - 0.05) < 1e-9

    def test_convergence(self):
        """SRTT must converge to consistent RTT within 5% after 50 samples."""
        from tcp_sim.rtt import RTTEstimator
        est = RTTEstimator()
        for _ in range(50):
            est.on_ack_rtt(0.05)
        assert abs(est.srtt - 0.05) < 0.005

    def test_exponential_backoff(self):
        """RTO must double on each timeout."""
        from tcp_sim.rtt import RTTEstimator
        est = RTTEstimator()
        est.on_ack_rtt(0.1)
        rto_before = est.rto
        est.on_timeout()
        assert est.rto >= 2 * rto_before - 1e-9

    def test_karn_algorithm(self):
        """Retransmitted segment RTT must not update SRTT."""
        from tcp_sim.rtt import RTTEstimator
        est = RTTEstimator()
        est.on_ack_rtt(0.1)
        srtt_before = est.srtt
        rttvar_before = est.rttvar
        est.on_ack_rtt(5.0, is_retransmit=True)
        assert est.srtt == srtt_before
        assert est.rttvar == rttvar_before


# ------------------------------------------------------------------ #
#  Congestion Controller Tests                                         #
# ------------------------------------------------------------------ #


class TestCongestionController:
    def test_initial_cwnd(self):
        """Initial congestion window must be 1 MSS."""
        from tcp_sim.congestion import CongestionController
        cc = CongestionController(mss=1000)
        assert cc.cwnd == 1000

    def test_slow_start_growth(self):
        """During slow start, cwnd increases by MSS per ACK."""
        from tcp_sim.congestion import CongestionController
        cc = CongestionController(mss=1000)
        cc.on_ack(1000)
        assert cc.cwnd == 2000
        cc.on_ack(1000)
        assert cc.cwnd == 3000

    def test_timeout_sets_ssthresh(self):
        """Timeout: ssthresh = cwnd/2, cwnd = MSS."""
        from tcp_sim.congestion import CongestionController
        cc = CongestionController(mss=1000)
        cc.cwnd = 10000
        cc.on_timeout()
        assert cc.ssthresh == 5000
        assert cc.cwnd == 1000

    def test_congestion_avoidance(self):
        """When cwnd >= ssthresh, cwnd grows by MSS*MSS/cwnd per ACK."""
        from tcp_sim.congestion import CongestionController
        cc = CongestionController(mss=1000)
        cc.ssthresh = 4000
        cc.cwnd = 4000
        cwnd_before = cc.cwnd
        cc.on_ack(1000)
        # cwnd += MSS * MSS / cwnd = 1000 * 1000 / 4000 = 250
        assert cc.cwnd == cwnd_before + 250

    def test_fast_retransmit_trigger(self):
        """3 duplicate ACKs must trigger fast retransmit and halve ssthresh."""
        from tcp_sim.congestion import CongestionController
        cc = CongestionController(mss=1000)
        cc.cwnd = 10000
        assert not cc.on_dup_ack()  # dup 1
        assert not cc.on_dup_ack()  # dup 2
        assert cc.on_dup_ack()      # dup 3 -> fast retransmit!
        assert cc.ssthresh == 5000  # cwnd/2


# ------------------------------------------------------------------ #
#  Integration: Reliable Delivery Tests                                #
# ------------------------------------------------------------------ #


class TestReliableDelivery:
    def test_perfect_channel(self):
        """100KB transfer over a perfect (0% loss) channel."""
        data = bytes(range(256)) * 400  # 102400 bytes
        received, time_ms, _, _ = _simulate_transfer(
            data, loss_rate=0.0, seed=1, max_time_ms=60000
        )
        assert hashlib.sha256(received).hexdigest() == hashlib.sha256(data).hexdigest()
        assert len(received) == len(data)

    def test_5pct_loss(self):
        """100KB transfer through 5% loss channel preserves data integrity."""
        data = bytes(range(256)) * 400
        received, time_ms, _, _ = _simulate_transfer(
            data, loss_rate=0.05, seed=100, max_time_ms=300000
        )
        assert hashlib.sha256(received).hexdigest() == hashlib.sha256(data).hexdigest()

    def test_15pct_loss(self):
        """50KB transfer through 15% loss channel preserves data integrity."""
        data = bytes(range(256)) * 200  # 51200 bytes
        received, time_ms, _, _ = _simulate_transfer(
            data, loss_rate=0.15, seed=200, max_time_ms=600000
        )
        assert hashlib.sha256(received).hexdigest() == hashlib.sha256(data).hexdigest()

    def test_25pct_loss(self):
        """10KB transfer through 25% loss channel preserves data integrity."""
        data = bytes(range(256)) * 40  # 10240 bytes
        received, time_ms, _, _ = _simulate_transfer(
            data, loss_rate=0.25, seed=300, base_delay_ms=100,
            max_time_ms=900000
        )
        assert hashlib.sha256(received).hexdigest() == hashlib.sha256(data).hexdigest()

    def test_reorder(self):
        """50KB transfer with 20% reordering reassembles correctly."""
        data = bytes(range(256)) * 200
        received, time_ms, _, _ = _simulate_transfer(
            data, loss_rate=0.0, reorder_rate=0.20, seed=400,
            max_time_ms=300000
        )
        assert received == data
