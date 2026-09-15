"""
Simulated lossy network channel for testing reliable transport protocols.

Provides a bidirectional link between a sender and receiver with
configurable impairments: packet loss, propagation delay with jitter,
packet reordering, and single-bit corruption.

The channel uses a seeded PRNG for reproducible impairment patterns.
Packets are delivered asynchronously via background threads after
their computed delay.
"""

import random
import threading
import time
from queue import Queue, Empty
from typing import Optional



class LossyChannel:
    """
    Bidirectional lossy channel simulating a network link.

    Parameters
    ----------
    loss_rate : float
        Probability [0,1] that any given packet is silently dropped.
    delay_ms : float
        Base one-way propagation delay in milliseconds.
    jitter_ms : float
        Maximum uniform jitter added/subtracted from the base delay.
    reorder_rate : float
        Probability [0,1] that a packet receives extra delay, causing it
        to arrive after subsequently sent packets.
    corrupt_rate : float
        Probability [0,1] that a random bit in the packet is flipped.
    seed : int
        PRNG seed for reproducibility.
    """

    def __init__(self, loss_rate: float = 0.0, delay_ms: float = 50.0,
                 jitter_ms: float = 10.0, reorder_rate: float = 0.0,
                 corrupt_rate: float = 0.0, seed: int = 42):
        self._rng = random.Random(seed)
        self._lock = threading.Lock()
        self._loss_rate = loss_rate
        self._delay_ms = delay_ms
        self._jitter_ms = jitter_ms
        self._reorder_rate = reorder_rate
        self._corrupt_rate = corrupt_rate
        self._forward_q: Queue = Queue()   # sender -> receiver
        self._reverse_q: Queue = Queue()   # receiver -> sender
        self._running = True

    def send_forward(self, data: bytes) -> None:
        """Send a packet from sender toward receiver."""
        self._transmit(data, self._forward_q)

    def send_reverse(self, data: bytes) -> None:
        """Send a packet from receiver toward sender."""
        self._transmit(data, self._reverse_q)

    def recv_forward(self, timeout: Optional[float] = None) -> Optional[bytes]:
        """Receive the next packet at the receiver side (blocks)."""
        try:
            return self._forward_q.get(timeout=timeout)
        except Empty:
            return None

    def recv_reverse(self, timeout: Optional[float] = None) -> Optional[bytes]:
        """Receive the next packet at the sender side (blocks)."""
        try:
            return self._reverse_q.get(timeout=timeout)
        except Empty:
            return None

    @property
    def is_running(self) -> bool:
        return self._running

    def _transmit(self, data: bytes, dest_q: Queue) -> None:
        if not self._running:
            return
        with self._lock:
            # Packet loss
            if self._rng.random() < self._loss_rate:
                return
            # Corruption
            if self._rng.random() < self._corrupt_rate:
                data = self._corrupt(data)
            # Delay computation
            delay = self._delay_ms + self._rng.uniform(-self._jitter_ms, self._jitter_ms)
            # Reordering via extra delay
            if self._rng.random() < self._reorder_rate:
                delay += self._delay_ms * (1.0 + self._rng.random())
            delay = max(0.5, delay) / 1000.0

        def _deliver():
            time.sleep(delay)
            if self._running:
                dest_q.put(data)

        threading.Thread(target=_deliver, daemon=True).start()

    def _corrupt(self, data: bytes) -> bytes:
        if not data:
            return data
        ba = bytearray(data)
        pos = self._rng.randint(0, len(ba) - 1)
        ba[pos] ^= 1 << self._rng.randint(0, 7)
        return bytes(ba)

    def shutdown(self) -> None:
        """Stop delivering new packets."""
        self._running = False
