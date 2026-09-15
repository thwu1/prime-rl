#!/usr/bin/env python3

"""
Apply all fixes to the buggy speed daemon server at /app/server.py.

Bugs fixed:
1. Speed calculation: premature integer truncation loses sub-mph precision
2. Day deduplication: subset check instead of intersection allows overlapping tickets
3. Heartbeat interval: divided by 100 (centiseconds) instead of 10 (deciseconds)
4. Dispatcher identity: only rejects double-dispatcher, not camera->dispatcher
5. Pending ticket flush: only delivers queued tickets for first road in list
"""

with open("/app/server.py") as f:
    code = f.read()

# --- Fix 1: Speed calculation precision + threshold ---
# The buggy code truncates mph to integer before multiplying by 100,
# and uses the truncated value for the threshold check.
# Fix: use full-precision integer arithmetic and proper 0.5 mph threshold.
code = code.replace(
    "            mph_times_100 = (distance * 3600 // elapsed) * 100\n"
    "            if mph_times_100 <= limit * 100:\n"
    "                continue",
    "            if distance * 360000 < (limit * 100 + 50) * elapsed:\n"
    "                continue\n"
    "            mph_times_100 = distance * 360000 // elapsed"
)

# --- Fix 2: Day deduplication uses intersection, not subset ---
# Buggy: covered_days <= ticketed (blocks only if ALL days already ticketed)
# Fixed: covered_days & ticketed (blocks if ANY day overlaps)
code = code.replace(
    "if covered_days <= self.ticketed[plate]:",
    "if covered_days & self.ticketed[plate]:"
)

# --- Fix 3: Heartbeat interval is in deciseconds (÷10), not centiseconds (÷100) ---
code = code.replace(
    "interval_ds / 100.0",
    "interval_ds / 10.0"
)

# --- Fix 4: Dispatcher identity check must reject ANY prior identification ---
# Buggy: only checks role == "dispatcher", allowing camera→dispatcher
# Fixed: checks role is not None
code = code.replace(
    '                elif msg_type == DISPATCHER:\n'
    '                    if role == "dispatcher":',
    '                elif msg_type == DISPATCHER:\n'
    '                    if role is not None:'
)

# --- Fix 5: Flush pending tickets for ALL dispatcher roads ---
# Buggy: only flushes roads[0]
# Fixed: loop over all roads
code = code.replace(
    "                        if roads:\n"
    "                            for ticket_data in self.queued.pop(roads[0], []):\n"
    "                                writer.write(ticket_data)\n"
    "                            await writer.drain()",
    "                        for r in roads:\n"
    "                            for ticket_data in self.queued.pop(r, []):\n"
    "                                writer.write(ticket_data)\n"
    "                        await writer.drain()"
)

with open("/app/server.py", "w") as f:
    f.write(code)

print("Applied 5 fixes to /app/server.py")
