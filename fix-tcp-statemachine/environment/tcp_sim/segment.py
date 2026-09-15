
"""TCP segment representation for the state machine simulator."""

MASK32 = 0xFFFFFFFF


class TcpSegment:
    """Represents a TCP segment with header fields and optional payload."""

    __slots__ = (
        "src_port", "dst_port", "seq_num", "ack_num",
        "window", "syn", "ack", "fin", "rst", "data",
    )

    def __init__(self, src_port, dst_port, seq_num, ack_num, window,
                 syn=False, ack=False, fin=False, rst=False, data=b""):
        self.src_port = src_port
        self.dst_port = dst_port
        self.seq_num = seq_num & MASK32
        self.ack_num = ack_num & MASK32
        self.window = window
        self.syn = syn
        self.ack = ack
        self.fin = fin
        self.rst = rst
        self.data = bytes(data)

    def seg_len(self):
        """Segment length in sequence number space.

        Includes SYN and FIN phantom bytes per RFC 793:
        SYN and FIN each consume exactly one sequence number.
        """
        length = len(self.data)
        if self.syn:
            length += 1
        if self.fin:
            length += 1
        return length

    def __repr__(self):
        flags = []
        if self.syn:
            flags.append("SYN")
        if self.ack:
            flags.append("ACK")
        if self.fin:
            flags.append("FIN")
        if self.rst:
            flags.append("RST")
        return (
            f"TcpSegment(seq={self.seq_num}, ack={self.ack_num}, "
            f"win={self.window}, flags=[{','.join(flags)}], "
            f"data={len(self.data)}B)"
        )
