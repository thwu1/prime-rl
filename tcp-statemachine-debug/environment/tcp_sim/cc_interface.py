"""Abstract interface for pluggable TCP congestion control."""

from abc import ABC, abstractmethod


class CongestionControllerBase(ABC):
    """Base class for TCP congestion control implementations.

    The MSS (Maximum Segment Size) is 1460 bytes.
    """

    MSS = 1460

    @abstractmethod
    def __init__(self):
        """Initialize congestion control state."""
        pass

    @abstractmethod
    def on_ack(self, acked_bytes: int, rtt_sample: float) -> None:
        """Called when a new ACK acknowledges data.

        Args:
            acked_bytes: Number of newly acknowledged bytes.
            rtt_sample: Measured round-trip time in seconds.
        """
        pass

    @abstractmethod
    def on_duplicate_ack(self) -> None:
        """Called when a duplicate ACK is received."""
        pass

    @abstractmethod
    def on_timeout(self) -> None:
        """Called when a retransmission timeout fires."""
        pass

    @abstractmethod
    def get_cwnd(self) -> int:
        """Return current congestion window in bytes."""
        pass

    @abstractmethod
    def get_ssthresh(self) -> int:
        """Return current slow-start threshold in bytes."""
        pass

    @abstractmethod
    def get_state(self) -> str:
        """Return current CC state name.

        Must be one of: 'slow_start', 'congestion_avoidance', 'fast_recovery'.
        """
        pass
