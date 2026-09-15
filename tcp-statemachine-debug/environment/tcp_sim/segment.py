"""TCP Segment representation for the state machine simulator."""


class Segment:
    """Represents a single TCP segment with header fields and optional payload.

    Used as the input/output unit for the Connection state machine,
    replacing raw packet bytes with structured Python objects for
    deterministic simulation.
    """

    # TCP flag constants (matching RFC 793 bit positions)
    FIN = 0x01
    SYN = 0x02
    RST = 0x04
    PSH = 0x08
    ACK = 0x10
    URG = 0x20

    def __init__(self, seq=0, ack=0, flags=0, data=b'', window=65535):
        self.seq = seq & 0xFFFFFFFF
        self.ack = ack & 0xFFFFFFFF
        self.flags = flags
        self.data = bytes(data)
        self.window = window

    @property
    def syn(self):
        return bool(self.flags & self.SYN)

    @property
    def ack_flag(self):
        return bool(self.flags & self.ACK)

    @property
    def fin(self):
        return bool(self.flags & self.FIN)

    @property
    def rst(self):
        return bool(self.flags & self.RST)

    def segment_length(self):
        """Length of segment in sequence number space (data + SYN/FIN)."""
        length = len(self.data)
        if self.syn:
            length += 1
        if self.fin:
            length += 1
        return length

    def __repr__(self):
        flags = []
        if self.syn:
            flags.append('SYN')
        if self.ack_flag:
            flags.append('ACK')
        if self.fin:
            flags.append('FIN')
        if self.rst:
            flags.append('RST')
        return (f"Segment(seq={self.seq}, ack={self.ack}, "
                f"flags=[{','.join(flags)}], data={len(self.data)}B, "
                f"window={self.window})")
