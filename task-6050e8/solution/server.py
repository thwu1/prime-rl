#!/usr/bin/env python3
"""
Speed Daemon Server - Complete Implementation

"""

import asyncio
import struct
from collections import defaultdict

# Message type constants
ERROR = 0x10
PLATE = 0x20
TICKET = 0x21
WANT_HEARTBEAT = 0x40
HEARTBEAT = 0x41
IAM_CAMERA = 0x80
IAM_DISPATCHER = 0x81


class SpeedDaemon:
    def __init__(self):
        # (road, plate) -> [(mile, timestamp), ...]
        self.observations = defaultdict(list)
        # road -> speed limit in mph
        self.road_limits = {}
        # road -> [Client, ...]
        self.dispatchers = defaultdict(list)
        # road -> [ticket_bytes, ...]
        self.pending_tickets = defaultdict(list)
        # plate -> set of ticketed day numbers
        self.ticketed_days = defaultdict(set)
        self.lock = asyncio.Lock()

    async def start(self, host='0.0.0.0', port=9000):
        server = await asyncio.start_server(self._on_connect, host, port)
        async with server:
            await server.serve_forever()

    async def _on_connect(self, reader, writer):
        client = Client(self, reader, writer)
        try:
            await client.run()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            await client.cleanup()
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def observe(self, road, mile, limit, plate, timestamp):
        async with self.lock:
            self.road_limits[road] = limit
            key = (road, plate)
            prev = self.observations[key]

            for (m, t) in prev:
                if t == timestamp:
                    continue
                dt = abs(timestamp - t)
                dd = abs(mile - m)
                # speed_x100 = speed_mph * 100
                speed_x100 = round(dd * 360000 / dt)

                if speed_x100 > limit * 100:
                    # Determine earlier and later observations
                    if t < timestamp:
                        t1, m1, t2, m2 = t, m, timestamp, mile
                    else:
                        t1, m1, t2, m2 = timestamp, mile, t, m

                    d1 = t1 // 86400
                    d2 = t2 // 86400
                    days = set(range(d1, d2 + 1))

                    # Check one-ticket-per-day constraint
                    if days & self.ticketed_days[plate]:
                        continue

                    # Mark days as ticketed
                    self.ticketed_days[plate] |= days

                    # Build and dispatch ticket
                    tkt = self._build_ticket(plate, road, m1, t1, m2, t2, speed_x100)
                    await self._dispatch_ticket(road, tkt)

            prev.append((mile, timestamp))

    def _build_ticket(self, plate, road, m1, t1, m2, t2, speed):
        pb = plate.encode('ascii')
        return (
            struct.pack('>BB', TICKET, len(pb)) + pb +
            struct.pack('>HHIHIH', road, m1, t1, m2, t2, speed)
        )

    async def _dispatch_ticket(self, road, ticket):
        dispatchers = self.dispatchers[road]
        for d in dispatchers:
            try:
                d.writer.write(ticket)
                await d.writer.drain()
                return
            except Exception:
                continue
        # No available dispatcher -> queue
        self.pending_tickets[road].append(ticket)

    async def register_dispatcher(self, client, roads):
        async with self.lock:
            for road in roads:
                self.dispatchers[road].append(client)
                # Flush pending tickets for this road
                pending = self.pending_tickets[road]
                delivered = []
                for tkt in pending:
                    try:
                        client.writer.write(tkt)
                        await client.writer.drain()
                        delivered.append(tkt)
                    except Exception:
                        break
                for t in delivered:
                    pending.remove(t)

    async def unregister_dispatcher(self, client, roads):
        async with self.lock:
            for road in roads:
                try:
                    self.dispatchers[road].remove(client)
                except ValueError:
                    pass


class Client:
    def __init__(self, server, reader, writer):
        self.server = server
        self.reader = reader
        self.writer = writer
        self.kind = None       # 'camera' or 'dispatcher'
        self.camera = None     # (road, mile, limit) if camera
        self.roads = None      # [road, ...] if dispatcher
        self.hb_task = None
        self.hb_requested = False

    async def run(self):
        while True:
            b = await self.reader.readexactly(1)
            t = b[0]

            if t == PLATE:
                plate = await self._read_str()
                ts = await self._read_u32()
                if self.kind != 'camera':
                    await self._send_error('client is not a camera')
                    return
                road, mile, limit = self.camera
                await self.server.observe(road, mile, limit, plate, ts)

            elif t == WANT_HEARTBEAT:
                interval = await self._read_u32()
                if self.hb_requested:
                    await self._send_error('heartbeat already requested')
                    return
                self.hb_requested = True
                if interval > 0:
                    self.hb_task = asyncio.create_task(
                        self._heartbeat_loop(interval / 10.0)
                    )

            elif t == IAM_CAMERA:
                road = await self._read_u16()
                mile = await self._read_u16()
                limit = await self._read_u16()
                if self.kind is not None:
                    await self._send_error('client already identified')
                    return
                self.kind = 'camera'
                self.camera = (road, mile, limit)

            elif t == IAM_DISPATCHER:
                numroads = (await self.reader.readexactly(1))[0]
                roads = [await self._read_u16() for _ in range(numroads)]
                if self.kind is not None:
                    await self._send_error('client already identified')
                    return
                self.kind = 'dispatcher'
                self.roads = roads
                await self.server.register_dispatcher(self, roads)

            else:
                await self._send_error('unknown message type')
                return

    async def _send_error(self, msg):
        mb = msg.encode('ascii')
        self.writer.write(struct.pack('>BB', ERROR, len(mb)) + mb)
        await self.writer.drain()
        self.writer.close()

    async def _read_u16(self):
        return struct.unpack('>H', await self.reader.readexactly(2))[0]

    async def _read_u32(self):
        return struct.unpack('>I', await self.reader.readexactly(4))[0]

    async def _read_str(self):
        n = (await self.reader.readexactly(1))[0]
        return (await self.reader.readexactly(n)).decode('ascii')

    async def _heartbeat_loop(self, interval):
        try:
            while True:
                await asyncio.sleep(interval)
                self.writer.write(bytes([HEARTBEAT]))
                await self.writer.drain()
        except (ConnectionError, asyncio.CancelledError):
            pass

    async def cleanup(self):
        if isinstance(self.hb_task, asyncio.Task):
            self.hb_task.cancel()
            try:
                await self.hb_task
            except asyncio.CancelledError:
                pass
        if self.kind == 'dispatcher' and self.roads:
            await self.server.unregister_dispatcher(self, self.roads)


if __name__ == '__main__':
    asyncio.run(SpeedDaemon().start())
