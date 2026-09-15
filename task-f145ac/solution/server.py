#!/usr/bin/env python3

"""
Speed Enforcement Server — complete implementation.
"""

import asyncio
import struct
from collections import defaultdict

PORT = 9999

MSG_PLATE = 0x20
MSG_WANT_HEARTBEAT = 0x40
MSG_IAM_CAMERA = 0x80
MSG_IAM_DISPATCHER = 0x81

MSG_ERROR = 0x10
MSG_TICKET = 0x21
MSG_HEARTBEAT = 0x41


class SpeedDaemon:
    def __init__(self):
        self.observations = defaultdict(list)
        self.dispatchers = {}
        self.road_dispatchers = defaultdict(list)
        self.pending_tickets = defaultdict(list)
        self.ticketed_days = defaultdict(set)
        self.lock = asyncio.Lock()
        self._next_id = 0

    def _new_id(self):
        self._next_id += 1
        return self._next_id

    @staticmethod
    def _encode_error(msg: str) -> bytes:
        mb = msg.encode('ascii')
        return struct.pack('!BB', MSG_ERROR, len(mb)) + mb

    @staticmethod
    def _encode_ticket(plate, road, mile1, ts1, mile2, ts2, speed) -> bytes:
        pb = plate.encode('ascii')
        return (
            struct.pack('!BB', MSG_TICKET, len(pb)) + pb
            + struct.pack('!HHIHIH', road, mile1, ts1, mile2, ts2, speed)
        )

    @staticmethod
    def _encode_heartbeat() -> bytes:
        return struct.pack('!B', MSG_HEARTBEAT)

    async def _send(self, writer, data: bytes):
        writer.write(data)
        await writer.drain()

    async def _heartbeat_loop(self, writer, interval_sec):
        try:
            while True:
                await asyncio.sleep(interval_sec)
                await self._send(writer, self._encode_heartbeat())
        except (ConnectionError, asyncio.CancelledError, OSError):
            pass

    async def _try_issue_ticket(self, plate, road, m1, t1, m2, t2, speed100):
        """Issue a ticket, respecting the one-per-day rule."""
        # Normalize so (m1, t1) is the earlier observation
        if t1 > t2:
            m1, m2 = m2, m1
            t1, t2 = t2, t1

        day1 = t1 // 86400
        day2 = t2 // 86400
        # Block ALL days covered by the ticket
        ticket_days = set(range(day1, day2 + 1))

        if ticket_days & self.ticketed_days[plate]:
            return

        self.ticketed_days[plate] |= ticket_days
        ticket = (plate, road, m1, t1, m2, t2, speed100)

        for did in list(self.road_dispatchers.get(road, [])):
            if did in self.dispatchers:
                w = self.dispatchers[did][0]
                try:
                    await self._send(w, self._encode_ticket(*ticket))
                    return
                except (ConnectionError, OSError):
                    continue

        self.pending_tickets[road].append(ticket)

    async def _check_violations(self, plate, road, mile, ts, limit):
        """Check new observation against all prior observations on same road."""
        for r, m, t in self.observations[plate]:
            if r != road:
                continue
            dt = abs(ts - t)
            if dt == 0:
                continue
            dist = abs(mile - m)
            # Strictly-greater-than: only ticket if EXCEEDING limit
            if dist * 3600 > limit * dt:
                speed100 = dist * 360000 // dt
                await self._try_issue_ticket(plate, road, m, t, mile, ts, speed100)

    async def _handle_client(self, reader, writer):
        cid = self._new_id()
        ctype = None
        cam_info = None
        hb_requested = False
        hb_task = None

        try:
            while True:
                tb = await reader.readexactly(1)
                mt = tb[0]

                if mt == MSG_PLATE:
                    if ctype != 'camera':
                        await self._send(writer, self._encode_error("not identified"))
                        break
                    plen = (await reader.readexactly(1))[0]
                    plate = (await reader.readexactly(plen)).decode('ascii')
                    ts = struct.unpack('!I', await reader.readexactly(4))[0]
                    road, mile, limit = cam_info
                    async with self.lock:
                        await self._check_violations(plate, road, mile, ts, limit)
                        self.observations[plate].append((road, mile, ts))

                elif mt == MSG_WANT_HEARTBEAT:
                    interval = struct.unpack('!I', await reader.readexactly(4))[0]
                    if hb_requested:
                        await self._send(writer, self._encode_error("duplicate heartbeat"))
                        break
                    hb_requested = True
                    if interval > 0:
                        hb_task = asyncio.create_task(
                            self._heartbeat_loop(writer, interval / 10.0)
                        )

                elif mt == MSG_IAM_CAMERA:
                    if ctype is not None:
                        await self._send(writer, self._encode_error("already identified"))
                        break
                    data = await reader.readexactly(6)
                    road, mile, limit = struct.unpack('!HHH', data)
                    ctype = 'camera'
                    cam_info = (road, mile, limit)

                elif mt == MSG_IAM_DISPATCHER:
                    if ctype is not None:
                        await self._send(writer, self._encode_error("already identified"))
                        break
                    nr = (await reader.readexactly(1))[0]
                    roads = []
                    for _ in range(nr):
                        rd = struct.unpack('!H', await reader.readexactly(2))[0]
                        roads.append(rd)
                    ctype = 'dispatcher'
                    async with self.lock:
                        self.dispatchers[cid] = (writer, set(roads))
                        for rd in roads:
                            self.road_dispatchers[rd].append(cid)
                            # Remove tickets from queue after delivery
                            for ticket in self.pending_tickets.pop(rd, []):
                                try:
                                    await self._send(writer, self._encode_ticket(*ticket))
                                except (ConnectionError, OSError):
                                    pass

                else:
                    await self._send(
                        writer,
                        self._encode_error(f"unknown msg type 0x{mt:02x}"),
                    )
                    break

        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass
        finally:
            if hb_task is not None:
                hb_task.cancel()
            if ctype == 'dispatcher':
                async with self.lock:
                    if cid in self.dispatchers:
                        _, rds = self.dispatchers.pop(cid)
                        for rd in rds:
                            dl = self.road_dispatchers[rd]
                            if cid in dl:
                                dl.remove(cid)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def run(self):
        server = await asyncio.start_server(
            self._handle_client, '0.0.0.0', PORT,
        )
        async with server:
            await server.serve_forever()


if __name__ == '__main__':
    daemon = SpeedDaemon()
    asyncio.run(daemon.run())
