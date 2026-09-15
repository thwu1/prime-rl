#!/usr/bin/env python3
"""Speed Daemon - Average Speed Check Enforcement Server

Coordinates enforcement of average speed limits via cameras and
ticket dispatchers communicating over a binary TCP protocol.
"""

import asyncio
import struct
from collections import defaultdict

MSG_ERROR = 0x10
MSG_PLATE = 0x20
MSG_TICKET = 0x21
MSG_WANT_HEARTBEAT = 0x40
MSG_HEARTBEAT = 0x41
MSG_IAMCAMERA = 0x80
MSG_IAMDISPATCHER = 0x81

PORT = 9000


class SpeedDaemonServer:

    def __init__(self):
        # road -> plate -> [(mile, timestamp)] sorted by timestamp
        self.observations = defaultdict(lambda: defaultdict(list))
        # road -> speed limit in mph
        self.road_limits = {}
        # plate -> set of day numbers already ticketed
        self.ticketed_days = defaultdict(set)
        # road -> set of dispatcher StreamWriters
        self.dispatchers = defaultdict(set)
        # road -> list of unsent ticket byte strings
        self.pending_tickets = defaultdict(list)
        self.lock = asyncio.Lock()

    async def run(self):
        server = await asyncio.start_server(
            self._handle_client, "0.0.0.0", PORT)
        print(f"Speed Daemon listening on port {PORT}", flush=True)
        async with server:
            await server.serve_forever()

    # ------------------------------------------------------------------ #
    #  Client handler                                                      #
    # ------------------------------------------------------------------ #

    async def _handle_client(self, reader, writer):
        client_type = None          # "camera" | "dispatcher" | None
        camera = None               # (road, mile, limit)
        heartbeat_task = None
        heartbeat_sent = False
        dispatcher_roads = []

        try:
            while True:
                msg_type = (await reader.readexactly(1))[0]

                if msg_type == MSG_IAMCAMERA:
                    if client_type is not None:
                        await self._send_error(writer, "already identified")
                        return
                    road = await self._read_u16(reader)
                    mile = await self._read_u16(reader)
                    limit = await self._read_u16(reader)
                    client_type = "camera"
                    camera = (road, mile, limit)
                    async with self.lock:
                        self.road_limits[road] = limit

                elif msg_type == MSG_PLATE:
                    if client_type != "camera":
                        await self._send_error(writer, "not a camera")
                        return
                    plate = await self._read_str(reader)
                    timestamp = await self._read_u32(reader)
                    await self._handle_plate(camera, plate, timestamp)

                elif msg_type == MSG_IAMDISPATCHER:
                    if client_type is not None:
                        await self._send_error(writer, "already identified")
                        return
                    numroads = (await reader.readexactly(1))[0]
                    roads = [await self._read_u16(reader)
                             for _ in range(numroads)]
                    client_type = "dispatcher"
                    dispatcher_roads = roads
                    await self._register_dispatcher(writer, roads)

                elif msg_type == MSG_WANT_HEARTBEAT:
                    interval = await self._read_u32(reader)
                    if interval > 0:
                        if heartbeat_sent:
                            await self._send_error(writer, "duplicate heartbeat")
                            return
                        heartbeat_sent = True
                        heartbeat_task = asyncio.create_task(
                            self._heartbeat_loop(writer, interval))

                else:
                    await self._send_error(writer, "unknown message type")
                    return

        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass
        finally:
            if heartbeat_task is not None:
                heartbeat_task.cancel()
            if client_type == "dispatcher":
                async with self.lock:
                    for rd in dispatcher_roads:
                        self.dispatchers[rd].discard(writer)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    #  Binary protocol helpers                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    async def _read_u16(reader):
        return struct.unpack("!H", await reader.readexactly(2))[0]

    @staticmethod
    async def _read_u32(reader):
        return struct.unpack("!I", await reader.readexactly(4))[0]

    async def _read_str(self, reader):
        length = (await reader.readexactly(1))[0]
        return (await reader.readexactly(length)).decode("ascii")

    @staticmethod
    async def _send_error(writer, msg):
        encoded = msg.encode("ascii")
        writer.write(bytes([MSG_ERROR, len(encoded)]) + encoded)
        await writer.drain()
        writer.close()

    # ------------------------------------------------------------------ #
    #  Heartbeat                                                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    async def _heartbeat_loop(writer, interval):
        """Send periodic heartbeats.  *interval* is in deciseconds."""
        try:
            while True:
                await asyncio.sleep(interval)
                writer.write(bytes([MSG_HEARTBEAT]))
                await writer.drain()
        except (asyncio.CancelledError, ConnectionError, OSError):
            pass

    # ------------------------------------------------------------------ #
    #  Plate / ticket logic                                                #
    # ------------------------------------------------------------------ #

    async def _handle_plate(self, camera, plate, timestamp):
        road, mile, limit = camera
        async with self.lock:
            obs = self.observations[road][plate]
            obs.append((mile, timestamp))
            obs.sort(key=lambda o: o[1])

            idx = next(i for i, o in enumerate(obs)
                       if o[0] == mile and o[1] == timestamp)

            # Check pairs formed by the new observation with its neighbours
            pairs = []
            if idx > 0:
                pairs.append((obs[idx - 1], obs[idx]))
            if idx < len(obs) - 1:
                pairs.append((obs[idx], obs[idx + 1]))

            for (m1, t1), (m2, t2) in pairs:
                if t1 == t2:
                    continue
                dt = t2 - t1
                dist = abs(m2 - m1)
                speed_100 = dist * 360000 // dt
                if speed_100 > limit * 100:
                    self._issue_ticket(plate, road, m1, t1, m2, t2,
                                       speed_100)

    def _issue_ticket(self, plate, road, om1, ot1, om2, ot2, speed):
        """Create and dispatch a ticket if the car is not already ticketed."""
        ticket_day = min(ot1, ot2) // 86400
        if ticket_day in self.ticketed_days[plate]:
            return

        # Arrange observation fields in the ticket
        if om1 <= om2:
            fm1, ft1, fm2, ft2 = om1, ot1, om2, ot2
        else:
            fm1, ft1, fm2, ft2 = om2, ot2, om1, ot1

        encoded_plate = plate.encode("ascii")
        ticket = (bytes([MSG_TICKET, len(encoded_plate)]) +
                  encoded_plate +
                  struct.pack("!HHIHIH", road, fm1, ft1, fm2, ft2, speed))

        self.ticketed_days[plate].add(ticket_day)
        self._dispatch_ticket(road, ticket)

    def _dispatch_ticket(self, road, ticket_data):
        """Send ticket to a connected dispatcher for *road*."""
        dispatchers = self.dispatchers.get(road)
        if not dispatchers:
            return
        writer = next(iter(dispatchers))
        try:
            writer.write(ticket_data)
        except (ConnectionError, OSError):
            dispatchers.discard(writer)

    # ------------------------------------------------------------------ #
    #  Dispatcher management                                               #
    # ------------------------------------------------------------------ #

    async def _register_dispatcher(self, writer, roads):
        async with self.lock:
            for road in roads:
                self.dispatchers[road].add(writer)


# ------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(SpeedDaemonServer().run())
