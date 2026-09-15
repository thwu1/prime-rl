#!/usr/bin/env python3
"""
Patch /app/server.py to fix all five protocol bugs.

"""

import sys

with open("/app/server.py") as f:
    src = f.read()

original = src

# ------------------------------------------------------------------ #
# Fix 1 — Heartbeat timing: interval is deciseconds, divide by 10    #
# ------------------------------------------------------------------ #
src = src.replace(
    "await asyncio.sleep(interval)",
    "await asyncio.sleep(interval / 10)",
)

# ------------------------------------------------------------------ #
# Fix 2a — Queue tickets when no dispatcher is connected              #
# ------------------------------------------------------------------ #
src = src.replace(
    "        dispatchers = self.dispatchers.get(road)\n"
    "        if not dispatchers:\n"
    "            return\n",
    "        dispatchers = self.dispatchers.get(road)\n"
    "        if not dispatchers:\n"
    "            self.pending_tickets[road].append(ticket_data)\n"
    "            return\n",
)

# ------------------------------------------------------------------ #
# Fix 2b — Flush pending tickets when a dispatcher registers          #
# ------------------------------------------------------------------ #
src = src.replace(
    "    async def _register_dispatcher(self, writer, roads):\n"
    "        async with self.lock:\n"
    "            for road in roads:\n"
    "                self.dispatchers[road].add(writer)\n",
    "    async def _register_dispatcher(self, writer, roads):\n"
    "        async with self.lock:\n"
    "            for road in roads:\n"
    "                self.dispatchers[road].add(writer)\n"
    "                for pending in self.pending_tickets.pop(road, []):\n"
    "                    try:\n"
    "                        writer.write(pending)\n"
    "                    except (ConnectionError, OSError):\n"
    "                        break\n"
    "            try:\n"
    "                await writer.drain()\n"
    "            except (ConnectionError, OSError):\n"
    "                pass\n",
)

# ------------------------------------------------------------------ #
# Fix 3a — Check ALL days in the ticket span, not just the start day  #
# ------------------------------------------------------------------ #
src = src.replace(
    "        ticket_day = min(ot1, ot2) // 86400\n"
    "        if ticket_day in self.ticketed_days[plate]:\n"
    "            return",
    "        day_start = min(ot1, ot2) // 86400\n"
    "        day_end = max(ot1, ot2) // 86400\n"
    "        for d in range(day_start, day_end + 1):\n"
    "            if d in self.ticketed_days[plate]:\n"
    "                return",
)

# ------------------------------------------------------------------ #
# Fix 3b — Mark ALL days in the ticket span as ticketed               #
# ------------------------------------------------------------------ #
src = src.replace(
    "        self.ticketed_days[plate].add(ticket_day)",
    "        for d in range(day_start, day_end + 1):\n"
    "            self.ticketed_days[plate].add(d)",
)

# ------------------------------------------------------------------ #
# Fix 4 — Order ticket fields by timestamp, not mile position         #
# ------------------------------------------------------------------ #
src = src.replace(
    "        if om1 <= om2:\n"
    "            fm1, ft1, fm2, ft2 = om1, ot1, om2, ot2\n"
    "        else:\n"
    "            fm1, ft1, fm2, ft2 = om2, ot2, om1, ot1",
    "        if ot1 <= ot2:\n"
    "            fm1, ft1, fm2, ft2 = om1, ot1, om2, ot2\n"
    "        else:\n"
    "            fm1, ft1, fm2, ft2 = om2, ot2, om1, ot1",
)

# ------------------------------------------------------------------ #
# Fix 5 — Track heartbeat requests even when interval is 0            #
# ------------------------------------------------------------------ #
src = src.replace(
    "                elif msg_type == MSG_WANT_HEARTBEAT:\n"
    "                    interval = await self._read_u32(reader)\n"
    "                    if interval > 0:\n"
    "                        if heartbeat_sent:\n"
    "                            await self._send_error(writer, \"duplicate heartbeat\")\n"
    "                            return\n"
    "                        heartbeat_sent = True\n"
    "                        heartbeat_task = asyncio.create_task(\n"
    "                            self._heartbeat_loop(writer, interval))",
    "                elif msg_type == MSG_WANT_HEARTBEAT:\n"
    "                    if heartbeat_sent:\n"
    "                        await self._send_error(writer, \"duplicate heartbeat\")\n"
    "                        return\n"
    "                    heartbeat_sent = True\n"
    "                    interval = await self._read_u32(reader)\n"
    "                    if interval > 0:\n"
    "                        heartbeat_task = asyncio.create_task(\n"
    "                            self._heartbeat_loop(writer, interval))",
)

# ------------------------------------------------------------------ #
# Verify all patches applied                                           #
# ------------------------------------------------------------------ #
if src == original:
    print("ERROR: no patches were applied — source may have changed", file=sys.stderr)
    sys.exit(1)

with open("/app/server.py", "w") as f:
    f.write(src)

print("All 5 bugs fixed in /app/server.py")
