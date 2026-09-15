"""
Tests for the reliable transport protocol implementation.

Verifies correct, in-order delivery under various channel impairments,
sequence number wraparound, congestion control behavior, throughput,
data integrity, and gnuplot visualization output.
"""

import hashlib
import os
import sys
import time

import pytest

sys.path.insert(0, '/app')
sys.path.insert(1, '/opt/transport_lib')

from channel import LossyChannel
from harness import transfer
from packet import FLAG_ACK, FLAG_DATA, FLAG_FIN, Packet
from transport import ReliableReceiver, ReliableSender


DEFAULT_CONFIG = {
    'mss': 500,
    'max_window': 32,
    'seq_bits': 16,
    'initial_timeout_ms': 1000,
    'recv_window': 64,
}


def make_data(size: int, seed: int = 0) -> bytes:
    """Generate deterministic pseudo-random data using SHA-256 chaining."""
    chunks = []
    total = 0
    n = 0
    while total < size:
        chunks.append(hashlib.sha256(f"{seed}:{n}".encode()).digest())
        total += 32
        n += 1
    return b''.join(chunks)[:size]


# ---------------------------------------------------------------------------
# Basic delivery (no impairments)
# ---------------------------------------------------------------------------

class TestBasicDelivery:

    def test_small_transfer_no_loss(self):
        """1 KB with zero channel impairments."""
        data = make_data(1000, seed=1)
        ch = LossyChannel(loss_rate=0.0, delay_ms=5, jitter_ms=1, seed=100)
        received, stats, _ = transfer(
            ReliableSender, ReliableReceiver, ch, data, DEFAULT_CONFIG, timeout=30)
        assert received == data
        assert stats['packets_sent'] > 0
        assert stats['retransmissions'] == 0

    def test_medium_transfer_no_loss(self):
        """50 KB with zero channel impairments."""
        data = make_data(50_000, seed=2)
        ch = LossyChannel(loss_rate=0.0, delay_ms=8, jitter_ms=2, seed=200)
        received, stats, _ = transfer(
            ReliableSender, ReliableReceiver, ch, data, DEFAULT_CONFIG, timeout=60)
        assert received == data

    def test_empty_transfer(self):
        """Empty payload — only FIN/FIN+ACK handshake."""
        ch = LossyChannel(loss_rate=0.0, delay_ms=5, jitter_ms=1, seed=300)
        received, stats, _ = transfer(
            ReliableSender, ReliableReceiver, ch, b'', DEFAULT_CONFIG, timeout=30)
        assert received == b''


# ---------------------------------------------------------------------------
# Loss resilience
# ---------------------------------------------------------------------------

class TestLossResilience:

    def test_loss_10_percent(self):
        """30 KB with 10 % packet loss."""
        data = make_data(30_000, seed=10)
        ch = LossyChannel(loss_rate=0.10, delay_ms=10, jitter_ms=3, seed=1000)
        received, stats, _ = transfer(
            ReliableSender, ReliableReceiver, ch, data, DEFAULT_CONFIG, timeout=60)
        assert received == data
        assert stats['retransmissions'] > 0

    def test_loss_30_percent(self):
        """15 KB with 30 % packet loss."""
        data = make_data(15_000, seed=11)
        ch = LossyChannel(loss_rate=0.30, delay_ms=10, jitter_ms=3, seed=1100)
        received, stats, _ = transfer(
            ReliableSender, ReliableReceiver, ch, data, DEFAULT_CONFIG, timeout=90)
        assert received == data

    def test_loss_50_percent(self):
        """10 KB with 50 % packet loss."""
        data = make_data(10_000, seed=12)
        ch = LossyChannel(loss_rate=0.50, delay_ms=10, jitter_ms=3, seed=1200)
        received, stats, _ = transfer(
            ReliableSender, ReliableReceiver, ch, data, DEFAULT_CONFIG, timeout=120)
        assert received == data


# ---------------------------------------------------------------------------
# Reordering and corruption
# ---------------------------------------------------------------------------

class TestReorderingAndCorruption:

    def test_reordering(self):
        """30 KB with 30 % packet reordering, zero loss."""
        data = make_data(30_000, seed=20)
        ch = LossyChannel(loss_rate=0.0, delay_ms=10, jitter_ms=3,
                          reorder_rate=0.30, seed=2000)
        received, stats, _ = transfer(
            ReliableSender, ReliableReceiver, ch, data, DEFAULT_CONFIG, timeout=60)
        assert received == data

    def test_corruption(self):
        """30 KB with 5 % bit corruption, zero loss."""
        data = make_data(30_000, seed=21)
        ch = LossyChannel(loss_rate=0.0, delay_ms=10, jitter_ms=3,
                          corrupt_rate=0.05, seed=2100)
        received, stats, _ = transfer(
            ReliableSender, ReliableReceiver, ch, data, DEFAULT_CONFIG, timeout=60)
        assert received == data

    def test_adversarial_combined(self):
        """15 KB with loss + reordering + corruption + high jitter."""
        data = make_data(15_000, seed=22)
        ch = LossyChannel(loss_rate=0.10, delay_ms=15, jitter_ms=8,
                          reorder_rate=0.15, corrupt_rate=0.03, seed=2200)
        received, stats, _ = transfer(
            ReliableSender, ReliableReceiver, ch, data, DEFAULT_CONFIG, timeout=90)
        assert received == data


# ---------------------------------------------------------------------------
# Sequence number wraparound
# ---------------------------------------------------------------------------

class TestSequenceWraparound:

    def test_wraparound_8bit(self):
        """200 KB over an 8-bit seq space (256 entries) — ~1.5 full wraps."""
        data = make_data(200_000, seed=30)
        ch = LossyChannel(loss_rate=0.02, delay_ms=3, jitter_ms=1, seed=3000)
        config = {**DEFAULT_CONFIG, 'seq_bits': 8, 'max_window': 16}
        received, stats, _ = transfer(
            ReliableSender, ReliableReceiver, ch, data, config, timeout=120)
        assert received == data

    def test_wraparound_10bit_with_loss(self):
        """600 KB over a 10-bit seq space (1024) with 15 % loss."""
        data = make_data(600_000, seed=31)
        ch = LossyChannel(loss_rate=0.15, delay_ms=3, jitter_ms=1, seed=3100)
        config = {**DEFAULT_CONFIG, 'seq_bits': 10, 'max_window': 24}
        received, stats, _ = transfer(
            ReliableSender, ReliableReceiver, ch, data, config, timeout=180)
        assert received == data


# ---------------------------------------------------------------------------
# Congestion control
# ---------------------------------------------------------------------------

class TestCongestionControl:

    def test_slow_start_growth(self):
        """cwnd must grow beyond 4 during slow start with no loss."""
        data = make_data(50_000, seed=40)
        ch = LossyChannel(loss_rate=0.0, delay_ms=10, jitter_ms=2, seed=4000)
        received, stats, _ = transfer(
            ReliableSender, ReliableReceiver, ch, data, DEFAULT_CONFIG, timeout=60)
        assert received == data
        cwnd_log = stats.get('cwnd_log', [])
        assert len(cwnd_log) >= 3, "cwnd_log too short — slow start not logged?"
        max_cwnd = max(c for _, c in cwnd_log)
        assert max_cwnd >= 4, (
            f"Max cwnd {max_cwnd} — slow start should reach at least 4")

    def test_cwnd_decrease_on_loss(self):
        """cwnd must decrease at least once under 15 % loss."""
        data = make_data(30_000, seed=41)
        ch = LossyChannel(loss_rate=0.15, delay_ms=10, jitter_ms=2, seed=4100)
        received, stats, _ = transfer(
            ReliableSender, ReliableReceiver, ch, data, DEFAULT_CONFIG, timeout=90)
        assert received == data
        cwnd_values = [c for _, c in stats.get('cwnd_log', [])]
        decreases = sum(1 for i in range(1, len(cwnd_values))
                        if cwnd_values[i] < cwnd_values[i - 1])
        assert decreases >= 1, "cwnd should decrease at least once under loss"

    def test_throughput_no_loss(self):
        """With no loss, throughput must exceed a conservative lower bound."""
        size = 100_000
        data = make_data(size, seed=42)
        ch = LossyChannel(loss_rate=0.0, delay_ms=10, jitter_ms=2, seed=4200)
        config = {**DEFAULT_CONFIG, 'max_window': 32}
        received, stats, elapsed = transfer(
            ReliableSender, ReliableReceiver, ch, data, config, timeout=60)
        assert received == data
        throughput_kbps = (size * 8) / elapsed / 1000
        # Theoretical max ~6.4 Mbps; require >= 200 Kbps (very conservative)
        assert throughput_kbps >= 200, (
            f"Throughput {throughput_kbps:.0f} Kbps too low (need >= 200 Kbps)")


# ---------------------------------------------------------------------------
# Data integrity
# ---------------------------------------------------------------------------

class TestDataIntegrity:

    def test_sha256_hash_large(self):
        """100 KB under mild impairments — SHA-256 of received must match."""
        data = make_data(100_000, seed=50)
        expected_hash = hashlib.sha256(data).hexdigest()
        ch = LossyChannel(loss_rate=0.05, delay_ms=8, jitter_ms=3,
                          reorder_rate=0.05, seed=5000)
        received, _, _ = transfer(
            ReliableSender, ReliableReceiver, ch, data, DEFAULT_CONFIG, timeout=90)
        assert hashlib.sha256(received).hexdigest() == expected_hash
        assert len(received) == len(data)

    def test_all_byte_values(self):
        """Transfer data containing every byte value 0x00-0xFF."""
        data = bytes(range(256)) * 100   # 25.6 KB
        ch = LossyChannel(loss_rate=0.08, delay_ms=10, jitter_ms=3, seed=5100)
        received, _, _ = transfer(
            ReliableSender, ReliableReceiver, ch, data, DEFAULT_CONFIG, timeout=60)
        assert received == data


# ---------------------------------------------------------------------------
# Visualization
# ---------------------------------------------------------------------------

class TestVisualization:

    def test_cwnd_svg_exists_and_valid(self):
        """cwnd_evolution.svg must exist and be gnuplot-generated SVG."""
        svg_path = '/app/cwnd_evolution.svg'
        assert os.path.isfile(svg_path), f"{svg_path} not found"
        with open(svg_path, 'r') as f:
            content = f.read()
        assert len(content) > 500, "SVG file too small to contain a real plot"
        content_lower = content.lower()
        assert '<svg' in content_lower, "File is not valid SVG"
        assert 'gnuplot' in content_lower, (
            "SVG must be generated by gnuplot (missing generator metadata)")
        assert any(tag in content_lower for tag in
                   ['<path', '<line', '<polyline', '<rect']), \
            "SVG contains no plot elements"
