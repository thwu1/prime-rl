"""TCP Connection state machine simulator.

Implements a simplified server-side TCP state machine per RFC 793,
for deterministic simulation and testing of TCP protocol behavior.
Processes Segment objects and produces response Segments without
any actual network I/O.

Inspired by Jon Gjengset's userspace TCP implementation (rust-tcp).
"""

import time
from enum import Enum, auto

from .segment import Segment
from .sequence import (
    wrapping_add, wrapping_sub, wrapping_lt, is_between_wrapped
)


class State(Enum):
    LISTEN = auto()
    SYN_RCVD = auto()
    ESTABLISHED = auto()
    FIN_WAIT_1 = auto()
    FIN_WAIT_2 = auto()
    CLOSING = auto()
    TIME_WAIT = auto()
    CLOSE_WAIT = auto()
    LAST_ACK = auto()
    CLOSED = auto()


class Connection:
    """Simulates one side of a TCP connection (server / passive open)."""

    def __init__(self, iss=0, clock=None):
        """Initialize connection in LISTEN state.

        Args:
            iss: Initial Send Sequence number.
            clock: Callable returning monotonic time (for testing).
        """
        self.state = State.LISTEN
        self.clock = clock or time.monotonic

        # Send Sequence Space (RFC 793 Section 3.2, Figure 4)
        self.snd_iss = iss
        self.snd_una = iss      # oldest unacknowledged sequence number
        self.snd_nxt = iss      # next sequence number to send
        self.snd_wnd = 0        # send window (peer's advertised receive window)

        # Receive Sequence Space (RFC 793 Section 3.2, Figure 5)
        self.rcv_irs = 0        # initial receive sequence number
        self.rcv_nxt = 0        # next expected receive sequence number
        self.rcv_wnd = 65535    # our advertised receive window

        # Data buffers
        self.incoming = bytearray()   # received data awaiting read
        self.unacked = bytearray()    # sent data awaiting acknowledgment

        # RTT estimation (RFC 6298)
        self.srtt = 1.0               # smoothed round-trip time (seconds)
        self.send_times = {}          # seq -> timestamp of transmission

        # Connection close tracking
        self.closed = False
        self.fin_seq = None           # sequence number of our FIN

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def on_segment(self, seg):
        """Process an incoming TCP segment.

        Returns a list of response Segments to transmit.
        """
        responses = []

        if self.state == State.LISTEN:
            return self._handle_listen(seg)

        if self.state == State.CLOSED:
            return []

        # Step 1: Sequence number validation (RFC 793 Section 3.9)
        if not self._is_acceptable(seg):
            if not seg.rst:
                responses.append(self._make_ack())
            return responses

        # Step 2: RST check
        if seg.rst:
            self.state = State.CLOSED
            return []

        # Step 3: ACK processing
        if seg.ack_flag:
            self._process_ack(seg)

        # Step 4: Data processing (only in states that accept data)
        if seg.data and self.state in (
            State.ESTABLISHED, State.FIN_WAIT_1, State.FIN_WAIT_2
        ):
            self._process_data(seg)
            responses.append(self._make_ack())

        # Step 5: FIN processing
        if seg.fin:
            self._process_fin(seg)
            responses.append(self._make_ack())

        return responses

    def send_data(self, data):
        """Queue data for transmission. Returns the outgoing Segment."""
        data = bytes(data)
        self.unacked.extend(data)

        seg = Segment(
            seq=self.snd_nxt,
            ack=self.rcv_nxt,
            flags=Segment.ACK,
            data=data,
            window=self.rcv_wnd,
        )

        self.send_times[self.snd_nxt] = self.clock()
        self.snd_nxt = wrapping_add(self.snd_nxt, len(data))
        return seg

    def close(self):
        """Initiate active close. Returns the FIN segment to transmit."""
        self.closed = True

        seg = Segment(
            seq=self.snd_nxt,
            ack=self.rcv_nxt,
            flags=Segment.FIN | Segment.ACK,
            window=self.rcv_wnd,
        )

        self.snd_nxt = wrapping_add(self.snd_nxt, 1)
        self.fin_seq = self.snd_nxt

        if self.state == State.ESTABLISHED:
            self.state = State.FIN_WAIT_1
        elif self.state == State.CLOSE_WAIT:
            self.state = State.LAST_ACK

        return seg

    def on_tick(self):
        """Handle periodic timer events. Returns Segments to retransmit."""
        if self.state in (State.FIN_WAIT_2, State.TIME_WAIT, State.CLOSED):
            return []

        segments = []
        if self.snd_una != self.snd_nxt and self.send_times:
            candidates = [
                s for s in self.send_times
                if not wrapping_lt(s, self.snd_una)
            ]
            if candidates:
                earliest_seq = min(candidates,
                                   key=lambda s: self.send_times[s])
                elapsed = self.clock() - self.send_times[earliest_seq]

                if elapsed > max(1.0, 1.5 * self.srtt):
                    resend = (min(len(self.unacked), self.snd_wnd)
                              if self.snd_wnd > 0
                              else len(self.unacked))
                    data = bytes(self.unacked[:resend])
                    flags = Segment.ACK
                    if self.closed and self.fin_seq is not None:
                        flags |= Segment.FIN

                    seg = Segment(
                        seq=self.snd_una,
                        ack=self.rcv_nxt,
                        flags=flags,
                        data=data,
                        window=self.rcv_wnd,
                    )
                    self.send_times[self.snd_una] = self.clock()
                    segments.append(seg)

        return segments

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _handle_listen(self, seg):
        """Handle segment received in LISTEN state (passive open)."""
        if not seg.syn:
            return []

        self.rcv_irs = seg.seq
        self.rcv_nxt = wrapping_add(seg.seq, 1)
        self.snd_wnd = seg.window

        syn_ack = Segment(
            seq=self.snd_iss,
            ack=self.rcv_nxt,
            flags=Segment.SYN | Segment.ACK,
            window=self.rcv_wnd,
        )
        self.snd_nxt = wrapping_add(self.snd_nxt, 1)
        self.state = State.SYN_RCVD
        self.send_times[self.snd_iss] = self.clock()
        return [syn_ack]

    def _is_acceptable(self, seg):
        """Check segment acceptability per RFC 793 Section 3.9.

        Validates that the segment's sequence number(s) fall within
        the current receive window.
        """
        seqn = seg.seq
        slen = seg.segment_length()
        wend = wrapping_add(self.rcv_nxt, self.rcv_wnd)

        if slen == 0:
            if self.rcv_wnd == 0:
                return seqn == self.rcv_nxt
            else:
                return is_between_wrapped(
                    wrapping_sub(self.rcv_nxt, 1), seqn, wend
                )
        else:
            if self.rcv_wnd == 0:
                return False
            else:
                seg_end = wrapping_add(seqn, slen - 1)
                return (
                    is_between_wrapped(
                        wrapping_sub(self.rcv_nxt, 1), seqn, wend
                    )
                    and
                    is_between_wrapped(
                        wrapping_sub(self.rcv_nxt, 1), seg_end, wend
                    )
                )

    def _process_ack(self, seg):
        """Process the ACK field of an incoming segment."""
        ackn = seg.ack

        if self.state == State.SYN_RCVD:
            # RFC 793: SND.UNA =< SEG.ACK =< SND.NXT
            if is_between_wrapped(
                wrapping_sub(self.snd_una, 1), ackn,
                wrapping_add(self.snd_nxt, 1)
            ):
                self.state = State.ESTABLISHED
            return

        if self.state in (
            State.ESTABLISHED, State.FIN_WAIT_1, State.FIN_WAIT_2,
            State.CLOSING, State.CLOSE_WAIT, State.LAST_ACK
        ):
            if not is_between_wrapped(
                self.snd_una, ackn, wrapping_add(self.snd_nxt, 1)
            ):
                return

            # Prune acknowledged data from unacked buffer
            if self.unacked:
                acked_bytes = wrapping_sub(ackn, self.snd_una)
                prune = min(acked_bytes, len(self.unacked))
                del self.unacked[:prune]

            # Update smoothed RTT from acknowledged segments
            new_send_times = {}
            for seq, sent_time in self.send_times.items():
                if is_between_wrapped(self.snd_una, seq, ackn):
                    sample = self.clock() - sent_time
                    self.srtt = 0.2 * self.srtt + 0.8 * sample
                else:
                    new_send_times[seq] = sent_time
            self.send_times = new_send_times

            self.snd_una = ackn

        # Check FIN acknowledgment for closing states
        if self.state == State.FIN_WAIT_1:
            if self.fin_seq is not None:
                if self.snd_una == wrapping_add(self.fin_seq, 1):
                    self.state = State.FIN_WAIT_2

        if self.state == State.CLOSING:
            if self.fin_seq is not None:
                if self.snd_una == wrapping_add(self.fin_seq, 1):
                    self.state = State.TIME_WAIT

        if self.state == State.LAST_ACK:
            if self.fin_seq is not None:
                if self.snd_una == wrapping_add(self.fin_seq, 1):
                    self.state = State.CLOSED

    def _process_data(self, seg):
        """Process payload data from an incoming segment."""
        seqn = seg.seq
        data = seg.data

        unread_at = wrapping_sub(self.rcv_nxt, seqn)
        if unread_at > len(data):
            unread_at = 0

        self.incoming.extend(data[unread_at:])
        self.rcv_nxt = wrapping_add(seqn, len(data))

    def _process_fin(self, seg):
        """Process the FIN flag of an incoming segment."""
        self.rcv_nxt = wrapping_add(self.rcv_nxt, 1)

        if self.state == State.ESTABLISHED:
            self.state = State.CLOSE_WAIT
        elif self.state == State.FIN_WAIT_2:
            self.state = State.TIME_WAIT

    def _make_ack(self):
        """Create a pure ACK segment."""
        return Segment(
            seq=self.snd_nxt,
            ack=self.rcv_nxt,
            flags=Segment.ACK,
            window=self.rcv_wnd,
        )

    def _make_rst(self):
        """Create a RST segment."""
        return Segment(
            seq=self.snd_nxt,
            ack=self.rcv_nxt,
            flags=Segment.RST | Segment.ACK,
            window=0,
        )
