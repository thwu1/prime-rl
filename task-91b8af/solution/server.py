#!/usr/bin/env python3

"""
Speed Daemon server — average-speed enforcement over a custom binary TCP protocol.

Handles cameras (which report plate sightings) and ticket dispatchers (which receive
speeding tickets for their assigned roads).  Supports heartbeats, queued ticket
delivery, day-based deduplication, and protocol error handling.
"""

import asyncio
import struct
from collections import defaultdict

# -- message type constants --------------------------------------------------
MSG_ERROR = 0x10
MSG_PLATE = 0x20
MSG_TICKET = 0x21
MSG_WANT_HEARTBEAT = 0x40
MSG_HEARTBEAT = 0x41
MSG_IAM_CAMERA = 0x80
MSG_IAM_DISPATCHER = 0x81


class SpeedDaemonServer:
    def __init__(self):
        # (road, plate) -> [(mile, timestamp), ...]
        self.observations = defaultdict(list)
        # plate -> {day_number, ...}
        self.ticketed_days = defaultdict(set)
        # road -> [ticket_bytes, ...]
        self.pending_tickets = defaultdict(list)
        # road -> [writer, ...]
        self.dispatchers = defaultdict(list)
        # Protects shared state against interleaved coroutine access
        self.lock = asyncio.Lock()

    # -- binary helpers -------------------------------------------------------

    @staticmethod
    async def read_u8(r):
        return (await r.readexactly(1))[0]

    @staticmethod
    async def read_u16(r):
        return struct.unpack("!H", await r.readexactly(2))[0]

    @staticmethod
    async def read_u32(r):
        return struct.unpack("!I", await r.readexactly(4))[0]

    async def read_str(self, r):
        n = await self.read_u8(r)
        return (await r.readexactly(n)).decode("ascii")

    @staticmethod
    def encode_error(msg: str) -> bytes:
        b = msg.encode("ascii")
        return bytes([MSG_ERROR, len(b)]) + b

    @staticmethod
    def encode_ticket(plate, road, m1, t1, m2, t2, spd) -> bytes:
        b = plate.encode("ascii")
        return (
            bytes([MSG_TICKET, len(b)])
            + b
            + struct.pack("!HHIHIH", road, m1, t1, m2, t2, spd)
        )

    # -- speed-violation logic ------------------------------------------------

    def find_violations(self, road, plate, limit):
        """Check the newest observation against every earlier one.

        Returns a list of encoded ticket messages for any speed violations
        that don't conflict with already-ticketed days.
        """
        obs = self.observations[(road, plate)]
        if len(obs) < 2:
            return []
        new_mile, new_ts = obs[-1]
        results = []
        for i in range(len(obs) - 1):
            old_mile, old_ts = obs[i]
            if new_ts == old_ts:
                continue
            # Order by timestamp (mile1/ts1 = earlier)
            if new_ts < old_ts:
                m1, t1, m2, t2 = new_mile, new_ts, old_mile, old_ts
            else:
                m1, t1, m2, t2 = old_mile, old_ts, new_mile, new_ts

            dist = abs(m2 - m1)
            tdiff = t2 - t1

            # Must ticket when speed >= limit + 0.5 mph
            # Equivalent integer check: dist * 360000 >= (limit*100 + 50) * tdiff
            if dist * 360000 < (limit * 100 + 50) * tdiff:
                continue

            speed_100x = dist * 360000 // tdiff

            # Day-based deduplication
            day1 = t1 // 86400
            day2 = t2 // 86400
            ticket_days = set(range(day1, day2 + 1))
            if ticket_days & self.ticketed_days[plate]:
                continue  # already ticketed on one of these days

            self.ticketed_days[plate] |= ticket_days
            results.append(
                self.encode_ticket(plate, road, m1, t1, m2, t2, speed_100x)
            )
        return results

    # -- ticket dispatch ------------------------------------------------------

    async def dispatch_ticket(self, road, data):
        """Send *data* to a connected dispatcher for *road*, or queue it."""
        for w in list(self.dispatchers.get(road, [])):
            if w.is_closing():
                self.dispatchers[road].remove(w)
                continue
            try:
                w.write(data)
                await w.drain()
                return
            except (ConnectionError, OSError):
                if w in self.dispatchers[road]:
                    self.dispatchers[road].remove(w)
        # No available dispatcher — queue for later
        self.pending_tickets[road].append(data)

    # -- heartbeat task -------------------------------------------------------

    async def heartbeat_loop(self, w, interval_secs):
        try:
            while True:
                await asyncio.sleep(interval_secs)
                w.write(bytes([MSG_HEARTBEAT]))
                await w.drain()
        except (asyncio.CancelledError, ConnectionError, OSError):
            pass

    # -- per-connection handler -----------------------------------------------

    async def handle_client(self, reader, writer):
        client_type = None  # None | 'C' | 'D'
        camera_info = None  # (road, mile, limit)
        hb_requested = False
        hb_task = None
        disp_roads = []

        try:
            while True:
                mt = (await reader.readexactly(1))[0]

                if mt == MSG_IAM_CAMERA:
                    if client_type is not None:
                        writer.write(self.encode_error("already identified"))
                        await writer.drain()
                        return
                    rd = await self.read_u16(reader)
                    mi = await self.read_u16(reader)
                    li = await self.read_u16(reader)
                    client_type = "C"
                    camera_info = (rd, mi, li)

                elif mt == MSG_IAM_DISPATCHER:
                    if client_type is not None:
                        writer.write(self.encode_error("already identified"))
                        await writer.drain()
                        return
                    nr = await self.read_u8(reader)
                    rds = [await self.read_u16(reader) for _ in range(nr)]
                    client_type = "D"
                    disp_roads = rds
                    async with self.lock:
                        for r in rds:
                            self.dispatchers[r].append(writer)
                        # Deliver any queued tickets
                        for r in rds:
                            pending = self.pending_tickets.pop(r, [])
                            for td in pending:
                                writer.write(td)
                        await writer.drain()

                elif mt == MSG_PLATE:
                    if client_type != "C":
                        writer.write(self.encode_error("not a camera"))
                        await writer.drain()
                        return
                    pl = await self.read_str(reader)
                    ts = await self.read_u32(reader)
                    rd, mi, li = camera_info
                    async with self.lock:
                        self.observations[(rd, pl)].append((mi, ts))
                        for td in self.find_violations(rd, pl, li):
                            await self.dispatch_ticket(rd, td)

                elif mt == MSG_WANT_HEARTBEAT:
                    if hb_requested:
                        writer.write(self.encode_error("duplicate heartbeat"))
                        await writer.drain()
                        return
                    iv = await self.read_u32(reader)
                    hb_requested = True
                    if iv > 0:
                        hb_task = asyncio.create_task(
                            self.heartbeat_loop(writer, iv / 10.0)
                        )

                else:
                    writer.write(self.encode_error("unknown message type"))
                    await writer.drain()
                    return

        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass
        finally:
            if hb_task is not None:
                hb_task.cancel()
                try:
                    await hb_task
                except asyncio.CancelledError:
                    pass
            async with self.lock:
                if client_type == "D":
                    for r in disp_roads:
                        try:
                            self.dispatchers[r].remove(writer)
                        except ValueError:
                            pass
            try:
                writer.close()
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    # -- entry point ----------------------------------------------------------

    async def run(self, host="0.0.0.0", port=9000):
        srv = await asyncio.start_server(self.handle_client, host, port)
        async with srv:
            await srv.serve_forever()


if __name__ == "__main__":
    asyncio.run(SpeedDaemonServer().run())
