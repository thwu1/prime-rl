#!/usr/bin/env python3
"""
SCTP SACK State Machine - computes correct SACK fields from an event trace.

Implements the receiver-side TSN tracking and Selective Acknowledgment
generation per RFC 4960 Section 3.3.4, with FORWARD-TSN support per RFC 3758.
Handles uint32 TSN wraparound using serial number arithmetic (RFC 1982).
"""


import json

UINT32_MOD = 2 ** 32
HALF_UINT32 = 2 ** 31


def tsn_diff(a, b):
    """Compute (a - b) mod 2^32."""
    return (a - b) % UINT32_MOD


def tsn_gt(a, b):
    """Serial number arithmetic (RFC 1982): a > b."""
    diff = tsn_diff(a, b)
    return 0 < diff < HALF_UINT32


def tsn_lte(a, b):
    """a <= b in serial number arithmetic."""
    return a == b or tsn_gt(b, a)


class SCTPReceiver:
    """Tracks receiver-side SCTP TSN state and computes SACK fields."""

    def __init__(self, initial_tsn):
        # Cumulative TSN Ack starts at initial_tsn - 1 (uint32 wraparound)
        self.cumulative_tsn = (initial_tsn - 1) % UINT32_MOD
        # Set of TSNs received that are beyond the cumulative TSN
        self.received_beyond = set()
        # Duplicate TSNs accumulated since the last compute_sack
        self.dup_tsns = []

    def receive_data(self, tsn):
        """Process a received DATA chunk with the given TSN."""
        if tsn_lte(tsn, self.cumulative_tsn):
            # TSN is at or before cumulative ack point - duplicate
            self.dup_tsns.append(tsn)
        elif tsn in self.received_beyond:
            # Already received out of order - duplicate
            self.dup_tsns.append(tsn)
        else:
            self.received_beyond.add(tsn)
            self._advance_cumulative()

    def process_forward_tsn(self, new_cumulative_tsn):
        """Process a FORWARD-TSN chunk (RFC 3758).

        Advances the cumulative TSN ack point to at least new_cumulative_tsn,
        then cascades through any contiguous received TSNs above it.
        """
        if tsn_gt(new_cumulative_tsn, self.cumulative_tsn):
            self.cumulative_tsn = new_cumulative_tsn
            # Remove TSNs from received_beyond that are now <= cumulative_tsn
            self.received_beyond = {
                t for t in self.received_beyond
                if tsn_gt(t, self.cumulative_tsn)
            }
            self._advance_cumulative()

    def _advance_cumulative(self):
        """Advance cumulative TSN through contiguous received TSNs."""
        while True:
            next_tsn = (self.cumulative_tsn + 1) % UINT32_MOD
            if next_tsn in self.received_beyond:
                self.received_beyond.remove(next_tsn)
                self.cumulative_tsn = next_tsn
            else:
                break

    def compute_sack(self):
        """Compute SACK fields at this checkpoint.

        Returns a dict with cumulative_tsn, gap_blocks (RFC 4960 offset
        encoding), and dup_tsns. Clears the duplicate list for the next
        checkpoint interval.
        """
        gap_blocks = []
        if self.received_beyond:
            # Compute offsets from cumulative_tsn using uint32 arithmetic
            offsets = sorted(
                tsn_diff(t, self.cumulative_tsn)
                for t in self.received_beyond
            )
            # Group contiguous offsets into gap ack blocks
            start = offsets[0]
            end = offsets[0]
            for i in range(1, len(offsets)):
                if offsets[i] == end + 1:
                    end = offsets[i]
                else:
                    gap_blocks.append([start, end])
                    start = offsets[i]
                    end = offsets[i]
            gap_blocks.append([start, end])

        result = {
            "cumulative_tsn": self.cumulative_tsn,
            "gap_blocks": gap_blocks,
            "dup_tsns": list(self.dup_tsns),
        }
        self.dup_tsns = []
        return result


def main():
    with open("/app/sctp_trace.json", "r") as f:
        trace = json.load(f)

    receiver = SCTPReceiver(trace["initial_tsn"])
    sacks = {}

    for event in trace["events"]:
        etype = event["type"]
        if etype == "data_received":
            receiver.receive_data(event["tsn"])
        elif etype == "forward_tsn":
            receiver.process_forward_tsn(event["new_cumulative_tsn"])
        elif etype == "compute_sack":
            sacks[event["id"]] = receiver.compute_sack()

    with open("/app/results.json", "w") as f:
        json.dump({"sacks": sacks}, f, indent=2)


if __name__ == "__main__":
    main()
