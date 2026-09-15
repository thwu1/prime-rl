"""
Reliable transport protocol — IMPLEMENT THIS FILE.

Complete the ReliableSender and ReliableReceiver classes to provide
reliable, in-order data delivery over a LossyChannel.

See packet.py for the wire format, channel.py for the channel API,
and harness.py for the test harness that runs sender and receiver
in separate threads.
"""

from channel import LossyChannel
from packet import Packet, FLAG_DATA, FLAG_ACK, FLAG_FIN



class ReliableSender:
    """Reliable sender — implement the send() method."""

    def __init__(self, channel: LossyChannel, config: dict):
        self.channel = channel
        self.mss = config.get('mss', 500)
        self.max_window = config.get('max_window', 32)
        self.seq_bits = config.get('seq_bits', 16)
        self.seq_mod = 1 << self.seq_bits
        self.initial_timeout_ms = config.get('initial_timeout_ms', 1000)

    def send(self, data: bytes) -> dict:
        """
        Reliably send all of *data* to the receiver.

        Returns a stats dict:
            bytes_sent      : int   — total payload bytes sent (including retransmits)
            packets_sent    : int   — total packets sent
            retransmissions : int   — number of retransmitted packets
            cwnd_log        : list  — [(elapsed_seconds, cwnd_value), ...]
        """
        raise NotImplementedError("Implement the reliable sender")


class ReliableReceiver:
    """Reliable receiver — implement the receive() method."""

    def __init__(self, channel: LossyChannel, config: dict):
        self.channel = channel
        self.mss = config.get('mss', 500)
        self.max_window = config.get('max_window', 32)
        self.seq_bits = config.get('seq_bits', 16)
        self.seq_mod = 1 << self.seq_bits
        self.recv_window = config.get('recv_window', 64)

    def receive(self) -> bytes:
        """
        Receive all data from the sender and return it as bytes.

        The transfer is complete when a FIN packet is received;
        respond with FIN+ACK.
        """
        raise NotImplementedError("Implement the reliable receiver")
