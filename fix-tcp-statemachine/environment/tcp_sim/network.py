
"""
Network channel simulation for TCP testing.

Provides a deterministic lossy network model with configurable:
- Packet loss probability
- Packet reordering probability
- Base propagation delay

Uses a seeded PRNG for reproducible behavior across runs.
"""


class LossyChannel:
    """Deterministic lossy network channel for TCP simulation.

    Segments sent through the channel may be dropped, delayed, or
    delivered out of order. Delivery is time-based: segments become
    available when their scheduled delivery time is reached.
    """

    def __init__(self, loss_rate=0.0, reorder_rate=0.0, seed=42, base_delay_ms=50):
        """Initialize the lossy channel.

        Args:
            loss_rate: Probability [0.0, 1.0] of dropping each segment.
            reorder_rate: Probability [0.0, 1.0] of adding extra random delay
                          to simulate packet reordering.
            seed: PRNG seed for deterministic loss/reorder patterns.
            base_delay_ms: Minimum one-way propagation delay in milliseconds.
        """
        raise NotImplementedError("Implement LossyChannel")

    def send(self, segment, direction='a_to_b', current_time_ms=0):
        """Submit a segment for transmission through the channel.

        The segment may be silently dropped (based on loss_rate) or
        delayed beyond base_delay_ms (based on reorder_rate).

        Args:
            segment: TcpSegment to transmit.
            direction: 'a_to_b' or 'b_to_a' to identify the flow.
            current_time_ms: Current simulation time in milliseconds.
        """
        raise NotImplementedError

    def deliver(self, current_time_ms):
        """Retrieve segments whose delivery time has arrived.

        Returns:
            List of (segment, direction) tuples for segments whose
            scheduled delivery time <= current_time_ms, ordered by
            delivery time then insertion order.
        """
        raise NotImplementedError

    def pending(self):
        """Return the number of segments currently in transit."""
        raise NotImplementedError
