#!/usr/bin/env python3
"""
Fixes five bugs in /app/tcp_tracker.py:

1. Retransmission detection uses plain '<' instead of wrapping_lt(),
   failing when sequence numbers wrap past 2^32.

2. Missing CLOSING state transition when FIN is received from peer
   while in FIN_WAIT_1 (simultaneous close).

3. SRTT EWMA weights are swapped: gives 87.5% weight to new sample
   instead of 12.5% per RFC 6298.

4. FIN does not advance sender.nxt — FIN consumes a sequence number
   but the code only advances nxt for payload bytes, breaking all
   subsequent ACK validation for the FIN.

5. bytes_sent counts seg_len (includes virtual FIN byte) instead of
   payload_len (actual application data).
"""

import re

with open('/app/tcp_tracker.py', 'r') as f:
    content = f.read()

# ---- Bug 1: Use wrapping_lt for retransmission detection ----
content = content.replace(
    'if seq < sender.nxt:',
    'if wrapping_lt(seq, sender.nxt):'
)

# ---- Bug 3: Fix SRTT EWMA formula ----
# Swap the weights back: 0.875 * SRTT + 0.125 * sample (not vice versa)
content = content.replace(
    'side.srtt = 0.875 * sample_sec + 0.125 * side.srtt',
    'side.srtt = 0.875 * side.srtt + 0.125 * sample_sec'
)

# ---- Bug 5: Count only payload bytes, not virtual FIN bytes ----
content = content.replace(
    'sender.bytes_sent += seg_len',
    'sender.bytes_sent += payload_len'
)

# ---- Bug 4: FIN must advance sender.nxt ----
# Insert FIN sequence consumption before the wrapping_lt nxt check
content = content.replace(
    '                new_nxt = seq_add(seq, payload_len)\n'
    '                if wrapping_lt(sender.nxt, new_nxt):',
    '                new_nxt = seq_add(seq, payload_len)\n'
    '                if fin:\n'
    '                    new_nxt = seq_add(new_nxt, 1)\n'
    '                if wrapping_lt(sender.nxt, new_nxt):'
)

# ---- Bug 2: Add CLOSING transition for simultaneous close ----
content = content.replace(
    "            elif conn.state == TcpState.FIN_WAIT_1 and who != conn.closer:\n"
    "                # TODO: handle simultaneous close\n"
    "                pass",
    "            elif conn.state == TcpState.FIN_WAIT_1 and who != conn.closer:\n"
    "                conn.transition(TcpState.CLOSING)"
)

with open('/app/tcp_tracker.py', 'w') as f:
    f.write(content)

print("All 5 bugs fixed in /app/tcp_tracker.py")
