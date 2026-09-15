#!/usr/bin/env python3


"""
Apply four TCP state machine bug fixes to /app/tcp_sim/connection.py.

Bug 1 - FIN phantom byte: recv_nxt must be incremented by 1 when a FIN
         is received, because FIN consumes one sequence number.

Bug 2 - Simultaneous close: when a FIN is received while in FIN_WAIT_1,
         the connection must transition to CLOSING and send an ACK.

Bug 3 - Stale send window: send_wnd must be updated from the window
         field of incoming ACK segments, not just during the handshake.

Bug 4 - Passive close path: close() must handle the CLOSE_WAIT state
         by transitioning to LAST_ACK and sending a FIN.
"""

import sys

filepath = "/app/tcp_sim/connection.py"

with open(filepath, "r") as f:
    code = f.read()

# ---- Fix 1: FIN phantom byte ----
# Add recv_nxt increment before FIN state dispatch
old_1 = "        if seg.fin:\n            if self.state == State.ESTABLISHED:"
new_1 = (
    "        if seg.fin:\n"
    "            self.recv_nxt = (self.recv_nxt + 1) & MASK32\n"
    "            if self.state == State.ESTABLISHED:"
)
assert old_1 in code, "Fix 1: pattern not found in source"
code = code.replace(old_1, new_1, 1)

# ---- Fix 2: Simultaneous close (CLOSING state) ----
# Replace the pass in FIN_WAIT_1 with proper CLOSING transition
old_2 = (
    "            elif self.state == State.FIN_WAIT_1:\n"
    "                pass"
)
new_2 = (
    "            elif self.state == State.FIN_WAIT_1:\n"
    "                self.state = State.CLOSING\n"
    "                self._send_control(ack=True)"
)
assert old_2 in code, "Fix 2: pattern not found in source"
code = code.replace(old_2, new_2, 1)

# ---- Fix 3: Send window update ----
# After updating send_una, also update send_wnd from segment
old_3 = "                self.send_una = ackn\n"
new_3 = (
    "                self.send_una = ackn\n"
    "                self.send_wnd = seg.window\n"
)
assert old_3 in code, "Fix 3: pattern not found in source"
code = code.replace(old_3, new_3, 1)

# ---- Fix 4: Passive close (CLOSE_WAIT handling in close()) ----
# Add elif branch for CLOSE_WAIT after the ESTABLISHED/SYN_RCVD block
old_4 = (
    "            self._send_control(ack=True, fin=True)\n"
    "\n"
    "        return self._flush()\n"
    "\n"
    "    def read_data"
)
new_4 = (
    "            self._send_control(ack=True, fin=True)\n"
    "        elif self.state == State.CLOSE_WAIT:\n"
    "            self.state = State.LAST_ACK\n"
    "            self.closed_at = (self.send_una + len(self.unacked)) & MASK32\n"
    "            self._send_control(ack=True, fin=True)\n"
    "\n"
    "        return self._flush()\n"
    "\n"
    "    def read_data"
)
assert old_4 in code, "Fix 4: pattern not found in source"
code = code.replace(old_4, new_4, 1)

with open(filepath, "w") as f:
    f.write(code)

print("All 4 TCP bug fixes applied successfully.")
