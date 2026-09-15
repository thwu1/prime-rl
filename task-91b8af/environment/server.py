#!/usr/bin/env python3
"""Speed Daemon server — binary protocol for average-speed enforcement."""

import asyncio
import struct
from collections import defaultdict

ERROR = 0x10
PLATE = 0x20
TICKET = 0x21
WANT_HEARTBEAT = 0x40
HEARTBEAT = 0x41
CAMERA = 0x80
DISPATCHER = 0x81


class Server:
    def __init__(self):
        self.sightings = defaultdict(list)
        self.ticketed = defaultdict(set)
        self.queued = defaultdict(list)
        self.dispatchers = defaultdict(list)
        self._lock = asyncio.Lock()

    async def _read_u8(self, r):
        return (await r.readexactly(1))[0]

    async def _read_u16(self, r):
        return struct.unpack("!H", await r.readexactly(2))[0]

    async def _read_u32(self, r):
        return struct.unpack("!I", await r.readexactly(4))[0]

    async def _read_str(self, r):
        length = await self._read_u8(r)
        return (await r.readexactly(length)).decode("ascii")

    def _make_error(self, msg):
        encoded = msg.encode("ascii")
        return struct.pack("!BB", ERROR, len(encoded)) + encoded

    def _make_ticket(self, plate, road, m1, t1, m2, t2, speed):
        encoded = plate.encode("ascii")
        return (struct.pack("!BB", TICKET, len(encoded))
                + encoded
                + struct.pack("!HHIHIH", road, m1, t1, m2, t2, speed))

    def _check_speed(self, road, plate, limit):
        """Check newest observation against all prior for speed violations."""
        records = self.sightings[(road, plate)]
        if len(records) < 2:
            return []

        latest_mile, latest_ts = records[-1]
        violations = []

        for mile, ts in records[:-1]:
            if ts == latest_ts:
                continue

            if latest_ts < ts:
                early_mile, early_ts = latest_mile, latest_ts
                late_mile, late_ts = mile, ts
            else:
                early_mile, early_ts = mile, ts
                late_mile, late_ts = latest_mile, latest_ts

            distance = abs(late_mile - early_mile)
            elapsed = late_ts - early_ts

            mph_times_100 = (distance * 3600 // elapsed) * 100
            if mph_times_100 <= limit * 100:
                continue

            start_day = early_ts // 86400
            end_day = late_ts // 86400
            covered_days = set(range(start_day, end_day + 1))

            if covered_days <= self.ticketed[plate]:
                continue

            self.ticketed[plate] |= covered_days
            violations.append(
                self._make_ticket(plate, road, early_mile, early_ts,
                                  late_mile, late_ts, mph_times_100)
            )

        return violations

    async def _send_ticket(self, road, ticket_data):
        for w in list(self.dispatchers.get(road, [])):
            if w.is_closing():
                self.dispatchers[road].remove(w)
                continue
            try:
                w.write(ticket_data)
                await w.drain()
                return
            except (ConnectionError, OSError):
                if w in self.dispatchers[road]:
                    self.dispatchers[road].remove(w)
        self.queued[road].append(ticket_data)

    async def _heartbeat_sender(self, writer, interval):
        try:
            while True:
                await asyncio.sleep(interval)
                writer.write(bytes([HEARTBEAT]))
                await writer.drain()
        except (asyncio.CancelledError, ConnectionError, OSError):
            pass

    async def handle(self, reader, writer):
        role = None
        cam_info = None
        heartbeat_set = False
        hb_task = None
        roads = []

        try:
            while True:
                msg_type = (await reader.readexactly(1))[0]

                if msg_type == CAMERA:
                    if role is not None:
                        writer.write(self._make_error("already identified"))
                        await writer.drain()
                        return
                    road = await self._read_u16(reader)
                    mile = await self._read_u16(reader)
                    limit = await self._read_u16(reader)
                    role = "camera"
                    cam_info = (road, mile, limit)

                elif msg_type == DISPATCHER:
                    if role == "dispatcher":
                        writer.write(self._make_error("already identified"))
                        await writer.drain()
                        return
                    count = await self._read_u8(reader)
                    roads = [await self._read_u16(reader) for _ in range(count)]
                    role = "dispatcher"
                    async with self._lock:
                        for r in roads:
                            self.dispatchers[r].append(writer)
                        if roads:
                            for ticket_data in self.queued.pop(roads[0], []):
                                writer.write(ticket_data)
                            await writer.drain()

                elif msg_type == PLATE:
                    if role != "camera":
                        writer.write(self._make_error("not a camera"))
                        await writer.drain()
                        return
                    plate = await self._read_str(reader)
                    timestamp = await self._read_u32(reader)
                    road, mile, limit = cam_info
                    async with self._lock:
                        self.sightings[(road, plate)].append((mile, timestamp))
                        for ticket_data in self._check_speed(road, plate, limit):
                            await self._send_ticket(road, ticket_data)

                elif msg_type == WANT_HEARTBEAT:
                    if heartbeat_set:
                        writer.write(self._make_error("duplicate heartbeat"))
                        await writer.drain()
                        return
                    interval_ds = await self._read_u32(reader)
                    heartbeat_set = True
                    if interval_ds > 0:
                        hb_task = asyncio.create_task(
                            self._heartbeat_sender(writer, interval_ds / 100.0)
                        )

                else:
                    writer.write(self._make_error("unknown message type"))
                    await writer.drain()
                    return

        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass
        finally:
            if hb_task:
                hb_task.cancel()
                try:
                    await hb_task
                except asyncio.CancelledError:
                    pass
            async with self._lock:
                if role == "dispatcher":
                    for r in roads:
                        try:
                            self.dispatchers[r].remove(writer)
                        except ValueError:
                            pass
            try:
                writer.close()
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    async def start(self):
        server = await asyncio.start_server(self.handle, "0.0.0.0", 9000)
        async with server:
            await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(Server().start())
