#!/usr/bin/env python3
"""
Speed Daemon protocol server — reference implementation.

"""

import asyncio
import struct
from collections import defaultdict


class ServerState:
    """Shared mutable state across all client connections."""

    def __init__(self):
        # road -> [(plate, mile, timestamp)]
        self.observations: dict[int, list[tuple[str, int, int]]] = defaultdict(list)
        # road -> [asyncio.StreamWriter]  (connected dispatchers)
        self.dispatchers: dict[int, list[asyncio.StreamWriter]] = defaultdict(list)
        # road -> [ticket_dict]  (buffered for missing dispatchers)
        self.pending_tickets: dict[int, list[dict]] = defaultdict(list)
        # plate -> set of day numbers already ticketed
        self.ticketed_days: dict[str, set[int]] = defaultdict(set)
        self.lock = asyncio.Lock()


class ClientHandler:
    """Per-connection protocol handler."""

    def __init__(self, state: ServerState, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.state = state
        self.reader = reader
        self.writer = writer
        self.is_camera = False
        self.is_dispatcher = False
        self.camera_road: int = 0
        self.camera_mile: int = 0
        self.camera_limit: int = 0
        self.dispatcher_roads: list[int] = []
        self.heartbeat_requested = False
        self.heartbeat_task: asyncio.Task | None = None
        self.closed = False

    # --- low-level helpers ---

    async def _send_error(self, msg: str):
        encoded = msg.encode("ascii")
        data = struct.pack("!BB", 0x10, len(encoded)) + encoded
        try:
            self.writer.write(data)
            await self.writer.drain()
        except (ConnectionError, OSError):
            pass
        self.closed = True

    @staticmethod
    def _build_ticket_bytes(ticket: dict) -> bytes:
        plate_raw = ticket["plate"].encode("ascii")
        buf = struct.pack("!B", 0x21)
        buf += struct.pack("!B", len(plate_raw)) + plate_raw
        buf += struct.pack("!HH", ticket["road"], ticket["mile1"])
        buf += struct.pack("!I", ticket["timestamp1"])
        buf += struct.pack("!H", ticket["mile2"])
        buf += struct.pack("!I", ticket["timestamp2"])
        buf += struct.pack("!H", ticket["speed"])
        return buf

    async def _send_ticket(self, writer: asyncio.StreamWriter, ticket: dict):
        try:
            writer.write(self._build_ticket_bytes(ticket))
            await writer.drain()
        except (ConnectionError, OSError):
            pass

    # --- heartbeat ---

    async def _heartbeat_loop(self, interval_sec: float):
        try:
            while not self.closed:
                await asyncio.sleep(interval_sec)
                if self.closed:
                    break
                self.writer.write(b"\x41")
                await self.writer.drain()
        except (asyncio.CancelledError, ConnectionError, OSError):
            pass

    # --- message handlers ---

    async def _handle_plate(self):
        plate_len = (await self.reader.readexactly(1))[0]
        plate = (await self.reader.readexactly(plate_len)).decode("ascii")
        (timestamp,) = struct.unpack("!I", await self.reader.readexactly(4))

        if not self.is_camera:
            await self._send_error("plate from non-camera")
            return

        road = self.camera_road
        mile = self.camera_mile
        limit = self.camera_limit

        async with self.state.lock:
            for obs_plate, obs_mile, obs_timestamp in self.state.observations[road]:
                if obs_plate != plate or obs_timestamp == timestamp:
                    continue

                dist = abs(mile - obs_mile)
                time_diff = abs(int(timestamp) - int(obs_timestamp))
                if time_diff == 0:
                    continue

                speed_mph = dist / time_diff * 3600.0
                if speed_mph < limit + 0.5:
                    continue

                speed_100 = int(speed_mph * 100)

                if obs_timestamp < timestamp:
                    t_mile1, t_ts1, t_mile2, t_ts2 = obs_mile, obs_timestamp, mile, timestamp
                else:
                    t_mile1, t_ts1, t_mile2, t_ts2 = mile, timestamp, obs_mile, obs_timestamp

                day1 = t_ts1 // 86400
                day2 = t_ts2 // 86400
                days_covered = set(range(day1, day2 + 1))

                if days_covered & self.state.ticketed_days[plate]:
                    continue

                self.state.ticketed_days[plate] |= days_covered

                ticket = {
                    "plate": plate,
                    "road": road,
                    "mile1": t_mile1,
                    "timestamp1": t_ts1,
                    "mile2": t_mile2,
                    "timestamp2": t_ts2,
                    "speed": speed_100,
                }

                dispatchers = self.state.dispatchers.get(road, [])
                if dispatchers:
                    await self._send_ticket(dispatchers[0], ticket)
                else:
                    self.state.pending_tickets[road].append(ticket)

            self.state.observations[road].append((plate, mile, timestamp))

    async def _handle_want_heartbeat(self):
        (interval,) = struct.unpack("!I", await self.reader.readexactly(4))

        if self.heartbeat_requested:
            await self._send_error("duplicate heartbeat")
            return

        self.heartbeat_requested = True
        if interval > 0:
            self.heartbeat_task = asyncio.create_task(
                self._heartbeat_loop(interval / 10.0)
            )

    async def _handle_iam_camera(self):
        road, mile, limit = struct.unpack("!HHH", await self.reader.readexactly(6))

        if self.is_camera or self.is_dispatcher:
            await self._send_error("already identified")
            return

        self.is_camera = True
        self.camera_road = road
        self.camera_mile = mile
        self.camera_limit = limit

    async def _handle_iam_dispatcher(self):
        numroads = (await self.reader.readexactly(1))[0]
        roads: list[int] = []
        for _ in range(numroads):
            (r,) = struct.unpack("!H", await self.reader.readexactly(2))
            roads.append(r)

        if self.is_camera or self.is_dispatcher:
            await self._send_error("already identified")
            return

        self.is_dispatcher = True
        self.dispatcher_roads = roads

        async with self.state.lock:
            for road in roads:
                self.state.dispatchers[road].append(self.writer)
                pending = self.state.pending_tickets.pop(road, [])
                for ticket in pending:
                    await self._send_ticket(self.writer, ticket)

    # --- main loop ---

    async def run(self):
        while not self.closed:
            msg_type = (await self.reader.readexactly(1))[0]
            if msg_type == 0x20:
                await self._handle_plate()
            elif msg_type == 0x40:
                await self._handle_want_heartbeat()
            elif msg_type == 0x80:
                await self._handle_iam_camera()
            elif msg_type == 0x81:
                await self._handle_iam_dispatcher()
            else:
                await self._send_error("unknown message type")

    async def cleanup(self):
        self.closed = True
        if self.heartbeat_task is not None:
            self.heartbeat_task.cancel()
            try:
                await self.heartbeat_task
            except asyncio.CancelledError:
                pass
        if self.is_dispatcher:
            async with self.state.lock:
                for road in self.dispatcher_roads:
                    dlist = self.state.dispatchers.get(road, [])
                    if self.writer in dlist:
                        dlist.remove(self.writer)


async def handle_connection(
    state: ServerState, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
):
    handler = ClientHandler(state, reader, writer)
    try:
        await handler.run()
    except (asyncio.IncompleteReadError, ConnectionError, ConnectionResetError, OSError):
        pass
    finally:
        await handler.cleanup()
        try:
            writer.close()
            await writer.wait_closed()
        except (ConnectionError, OSError):
            pass


async def main():
    state = ServerState()
    server = await asyncio.start_server(
        lambda r, w: handle_connection(state, r, w),
        "0.0.0.0",
        9000,
    )
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
