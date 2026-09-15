#!/usr/bin/env python3
"""
TCP Segmentation Engine

Simulates TCP segmentation based on Maximum Segment Size (MSS).
Models how an IP stack breaks an outgoing TCP stream into
MSS-sized segments, as negotiated during the TCP 3-way handshake
via the Maximum Segment Size TCP Option (RFC 793 Section 3.1).

"""


class TCPSegmenter:
    """
    Segments a TCP byte stream into MSS-sized chunks.

    MSS governs the maximum payload in a single TCP segment
    (excluding IP and TCP headers).  An attacker who controls
    the MSS value (via the SYN-ACK during the handshake) can
    manipulate where segment boundaries fall in the victim's
    outbound stream.
    """

    def __init__(self, mss):
        if not isinstance(mss, int) or mss < 1:
            raise ValueError(f"MSS must be a positive integer, got {mss}")
        self.mss = mss

    def segment(self, data):
        """
        Split *data* into segments of at most *self.mss* bytes.

        Args:
            data: bytes or str (str is UTF-8-encoded first)

        Returns:
            List[bytes] – one entry per TCP segment
        """
        if isinstance(data, str):
            data = data.encode('utf-8')
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError(f"Expected bytes or str, got {type(data)}")

        segments = []
        for offset in range(0, len(data), self.mss):
            segments.append(bytes(data[offset : offset + self.mss]))
        return segments
