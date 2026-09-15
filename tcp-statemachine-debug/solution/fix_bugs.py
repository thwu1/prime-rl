#!/usr/bin/env python3
"""Fix all bugs in the TCP connection state machine simulator.

Reads /app/tcp_sim/connection.py, applies targeted fixes to five
protocol-level bugs, and writes the corrected file back.
"""


import sys

TARGET = '/app/tcp_sim/connection.py'

with open(TARGET, 'r') as f:
    code = f.read()

original = code

# ---------- Fix 1: _is_acceptable ----------
# RFC 793 Section 3.9: a segment with non-zero length is acceptable
# if EITHER its first OR its last sequence number falls within the
# receive window.  The buggy code uses 'and', requiring BOTH ends
# to be inside the window, which rejects segments that partially
# overlap the window boundary.
old_1 = (
    "                    and\n"
    "                    is_between_wrapped(\n"
    "                        wrapping_sub(self.rcv_nxt, 1), seg_end, wend\n"
    "                    )"
)
new_1 = (
    "                    or\n"
    "                    is_between_wrapped(\n"
    "                        wrapping_sub(self.rcv_nxt, 1), seg_end, wend\n"
    "                    )"
)
assert old_1 in code, "Fix 1: pattern not found"
code = code.replace(old_1, new_1, 1)

# ---------- Fix 2: SRTT smoothing weights ----------
# RFC 6298: SRTT = (1 - alpha) * SRTT + alpha * R'
# With alpha = 0.125-0.2, the OLD srtt should have the LARGER weight
# so the estimate is smoothed.  The buggy code has the weights
# backwards (0.2 for old, 0.8 for new), making SRTT snap to the
# latest sample instead of converging gradually.
old_2 = "self.srtt = 0.2 * self.srtt + 0.8 * sample"
new_2 = "self.srtt = 0.8 * self.srtt + 0.2 * sample"
assert old_2 in code, "Fix 2: pattern not found"
code = code.replace(old_2, new_2, 1)

# ---------- Fix 3: _process_fin missing CLOSING transition ----------
# RFC 793: If the connection is in FIN-WAIT-1 and we receive a FIN
# (simultaneous close), the connection should transition to CLOSING.
# The buggy code only handles ESTABLISHED -> CLOSE_WAIT and
# FIN_WAIT_2 -> TIME_WAIT, omitting the FIN_WAIT_1 case entirely.
old_3 = (
    "        if self.state == State.ESTABLISHED:\n"
    "            self.state = State.CLOSE_WAIT\n"
    "        elif self.state == State.FIN_WAIT_2:\n"
    "            self.state = State.TIME_WAIT"
)
new_3 = (
    "        if self.state == State.ESTABLISHED:\n"
    "            self.state = State.CLOSE_WAIT\n"
    "        elif self.state == State.FIN_WAIT_1:\n"
    "            self.state = State.CLOSING\n"
    "        elif self.state == State.FIN_WAIT_2:\n"
    "            self.state = State.TIME_WAIT"
)
assert old_3 in code, "Fix 3: pattern not found"
code = code.replace(old_3, new_3, 1)

# ---------- Fix 4: close() fin_seq off-by-one ----------
# fin_seq must record the sequence number of the FIN *before*
# snd_nxt is incremented.  The buggy code increments snd_nxt first
# and then records the (now wrong) value, causing the ACK check
# in _process_ack to compare against fin_seq+1 that is one too high.
old_4 = (
    "        self.snd_nxt = wrapping_add(self.snd_nxt, 1)\n"
    "        self.fin_seq = self.snd_nxt"
)
new_4 = (
    "        self.fin_seq = self.snd_nxt\n"
    "        self.snd_nxt = wrapping_add(self.snd_nxt, 1)"
)
assert old_4 in code, "Fix 4: pattern not found"
code = code.replace(old_4, new_4, 1)

# ---------- Fix 5: _process_ack early return in SYN_RCVD ----------
# After transitioning from SYN_RCVD to ESTABLISHED, the code must
# fall through to the ESTABLISHED ACK processing so that snd_una is
# updated (acknowledging the SYN).  The buggy code returns early,
# leaving snd_una at ISS, which causes the first data ACK to
# over-prune the unacked buffer by one byte (the phantom SYN byte).
old_5 = (
    "                self.state = State.ESTABLISHED\n"
    "            return"
)
new_5 = (
    "                self.state = State.ESTABLISHED"
)
assert old_5 in code, "Fix 5: pattern not found"
code = code.replace(old_5, new_5, 1)

# ---------- Write corrected file ----------
assert code != original, "No changes were applied"

with open(TARGET, 'w') as f:
    f.write(code)

print(f"Applied 5 fixes to {TARGET}")
