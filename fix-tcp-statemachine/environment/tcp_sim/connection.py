
"""
TCP connection state machine implementation following RFC 793.

Handles connection establishment (three-way handshake), data transfer with
sequence/acknowledgment numbers, flow control via the sliding window, and
connection teardown through various close scenarios (active, passive,
simultaneous).

Sequence number arithmetic uses 32-bit unsigned wrapping per RFC 1323.
SYN and FIN each consume one sequence number in the sequence space
("phantom bytes").
"""

from enum import Enum, auto
from tcp_sim.segment import TcpSegment

MASK32 = 0xFFFFFFFF


def wrapping_lt(lhs, rhs):
    """Check if lhs < rhs in 32-bit unsigned wrapping arithmetic."""
    return ((lhs - rhs) & MASK32) > 0x80000000


def is_between_wrapped(start, x, end):
    """Check if x is in the open interval (start, end) in wrapping sequence space."""
    return wrapping_lt(start, x) and wrapping_lt(x, end)


class State(Enum):
    LISTEN = auto()
    SYN_SENT = auto()
    SYN_RCVD = auto()
    ESTABLISHED = auto()
    FIN_WAIT_1 = auto()
    FIN_WAIT_2 = auto()
    CLOSING = auto()
    TIME_WAIT = auto()
    CLOSE_WAIT = auto()
    LAST_ACK = auto()
    CLOSED = auto()


class TcpConnection:
    """A TCP connection state machine supporting both active and passive open."""

    def __init__(self, local_port=0, iss=0):
        self.state = State.LISTEN
        self.local_port = local_port
        self.remote_port = 0

        self.send_iss = iss
        self.send_una = iss
        self.send_nxt = iss
        self.send_wnd = 0

        self.recv_irs = 0
        self.recv_nxt = 0
        self.recv_wnd = 65535

        self.incoming = bytearray()
        self.unacked = bytearray()

        self.closed = False
        self.closed_at = None

        self._outgoing = []

    def connect(self, remote_port):
        """Active open: send SYN to initiate a connection."""
        if self.state != State.LISTEN:
            raise RuntimeError(f"Cannot connect in state {self.state}")
        self.remote_port = remote_port
        self.state = State.SYN_SENT
        self._outgoing = []
        self._send_control(syn=True)
        return self._flush()

    def on_segment(self, seg):
        """Process an incoming TCP segment."""
        self._outgoing = []

        if self.state in (State.CLOSED, State.LISTEN):
            return self._handle_closed_or_listen(seg)

        seqn = seg.seq_num
        slen = seg.seg_len()

        if self.state == State.SYN_SENT:
            return self._handle_syn_sent(seg)

        wend = (self.recv_nxt + self.recv_wnd) & MASK32
        if not self._is_acceptable(seqn, slen, wend):
            if not seg.rst:
                self._send_control(ack=True)
            return self._flush()

        if seg.rst:
            self.state = State.CLOSED
            return []

        if not seg.ack:
            return self._flush()

        ackn = seg.ack_num

        if self.state == State.SYN_RCVD:
            if is_between_wrapped(
                (self.send_una - 1) & MASK32,
                ackn,
                (self.send_nxt + 1) & MASK32,
            ):
                self.state = State.ESTABLISHED
            else:
                self._send_control(rst=True)
                return self._flush()

        if self.state in (
            State.ESTABLISHED, State.FIN_WAIT_1, State.FIN_WAIT_2,
            State.CLOSING, State.CLOSE_WAIT, State.LAST_ACK,
        ):
            if is_between_wrapped(
                self.send_una, ackn, (self.send_nxt + 1) & MASK32
            ):
                acked = min((ackn - self.send_una) & MASK32, len(self.unacked))
                self.unacked = self.unacked[acked:]
                self.send_una = ackn
                self.send_wnd = seg.window

        if self.state == State.FIN_WAIT_1:
            if self.closed_at is not None:
                if self.send_una == ((self.closed_at + 1) & MASK32):
                    self.state = State.FIN_WAIT_2

        if self.state == State.CLOSING:
            if self.closed_at is not None:
                if self.send_una == ((self.closed_at + 1) & MASK32):
                    self.state = State.TIME_WAIT
            return self._flush()

        if self.state == State.LAST_ACK:
            if self.closed_at is not None:
                if self.send_una == ((self.closed_at + 1) & MASK32):
                    self.state = State.CLOSED
            return self._flush()

        if seg.data and self.state in (
            State.ESTABLISHED, State.FIN_WAIT_1, State.FIN_WAIT_2,
        ):
            offset = (self.recv_nxt - seqn) & MASK32
            if offset > len(seg.data):
                offset = 0
            self.incoming.extend(seg.data[offset:])
            self.recv_nxt = (seqn + len(seg.data)) & MASK32
            self._send_control(ack=True)

        if seg.fin:
            self.recv_nxt = (self.recv_nxt + 1) & MASK32
            if self.state == State.ESTABLISHED:
                self.state = State.CLOSE_WAIT
                self._send_control(ack=True)
            elif self.state == State.FIN_WAIT_1:
                self.state = State.CLOSING
                self._send_control(ack=True)
            elif self.state == State.FIN_WAIT_2:
                self.state = State.TIME_WAIT
                self._send_control(ack=True)

        return self._flush()

    def send_data(self, data):
        """Queue data for sending and transmit what the window allows."""
        if self.state not in (State.ESTABLISHED, State.CLOSE_WAIT):
            raise RuntimeError(f"Cannot send data in state {self.state}")

        self._outgoing = []
        self.unacked.extend(data)

        nunacked = (self.send_nxt - self.send_una) & MASK32
        allowed = max(0, self.send_wnd - nunacked)
        to_send = min(len(data), allowed)

        if to_send > 0:
            self._send_data_segment(data[:to_send])

        return self._flush()

    def close(self):
        """Initiate connection close."""
        self._outgoing = []
        self.closed = True

        if self.state in (State.ESTABLISHED, State.SYN_RCVD):
            self.state = State.FIN_WAIT_1
            self.closed_at = (self.send_una + len(self.unacked)) & MASK32
            self._send_control(ack=True, fin=True)
        elif self.state == State.CLOSE_WAIT:
            self.state = State.LAST_ACK
            self.closed_at = (self.send_una + len(self.unacked)) & MASK32
            self._send_control(ack=True, fin=True)

        return self._flush()

    def read_data(self):
        """Read and clear the incoming data buffer."""
        data = bytes(self.incoming)
        self.incoming.clear()
        return data

    # ------------------------------------------------------------------ #
    #                       Private helpers                                #
    # ------------------------------------------------------------------ #

    def _handle_closed_or_listen(self, seg):
        if self.state == State.CLOSED:
            return []
        if seg.rst:
            return []
        if seg.ack:
            self._outgoing = []
            self._send_control(rst=True)
            return self._flush()
        if seg.syn:
            self.recv_irs = seg.seq_num
            self.recv_nxt = (seg.seq_num + 1) & MASK32
            self.send_wnd = seg.window
            self.remote_port = seg.src_port
            self.state = State.SYN_RCVD
            self._outgoing = []
            self._send_control(syn=True, ack=True)
        return self._flush()

    def _handle_syn_sent(self, seg):
        if seg.ack:
            if not is_between_wrapped(
                self.send_iss,
                seg.ack_num,
                (self.send_nxt + 1) & MASK32,
            ):
                if not seg.rst:
                    self._send_control(rst=True)
                return self._flush()

        if seg.rst:
            if seg.ack:
                self.state = State.CLOSED
            return self._flush()

        if seg.syn:
            self.recv_irs = seg.seq_num
            self.recv_nxt = (seg.seq_num + 1) & MASK32
            self.send_wnd = seg.window
            self.remote_port = seg.src_port

            if seg.ack:
                self.send_una = seg.ack_num
                self.state = State.ESTABLISHED
                self._send_control(ack=True)
            else:
                self.state = State.SYN_RCVD
                self._send_control(syn=True, ack=True)

        return self._flush()

    def _is_acceptable(self, seqn, slen, wend):
        if slen == 0:
            if self.recv_wnd == 0:
                return seqn == self.recv_nxt
            else:
                return is_between_wrapped(
                    (self.recv_nxt - 1) & MASK32, seqn, wend
                )
        else:
            if self.recv_wnd == 0:
                return False
            else:
                return (
                    is_between_wrapped(
                        (self.recv_nxt - 1) & MASK32, seqn, wend
                    )
                    or is_between_wrapped(
                        (self.recv_nxt - 1) & MASK32,
                        (seqn + slen - 1) & MASK32,
                        wend,
                    )
                )

    def _send_control(self, syn=False, ack=False, fin=False, rst=False):
        seg = TcpSegment(
            src_port=self.local_port,
            dst_port=self.remote_port,
            seq_num=self.send_nxt,
            ack_num=self.recv_nxt if ack else 0,
            window=self.recv_wnd,
            syn=syn, ack=ack, fin=fin, rst=rst,
        )
        nxt = self.send_nxt
        if syn:
            nxt = (nxt + 1) & MASK32
        if fin:
            nxt = (nxt + 1) & MASK32
        if wrapping_lt(self.send_nxt, nxt):
            self.send_nxt = nxt
        self._outgoing.append(seg)

    def _send_data_segment(self, data):
        seg = TcpSegment(
            src_port=self.local_port,
            dst_port=self.remote_port,
            seq_num=self.send_nxt,
            ack_num=self.recv_nxt,
            window=self.recv_wnd,
            ack=True,
            data=bytes(data),
        )
        nxt = (self.send_nxt + len(data)) & MASK32
        if wrapping_lt(self.send_nxt, nxt):
            self.send_nxt = nxt
        self._outgoing.append(seg)

    def _flush(self):
        out = self._outgoing
        self._outgoing = []
        return out
