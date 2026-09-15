#!/usr/bin/env python3
"""Speed Enforcement Server.

Binary protocol server for coordinating speed limit enforcement across
a road network. Handles cameras, dispatchers, plates, tickets, and heartbeats.
"""

import asyncio
import struct
from collections import defaultdict

PORT = 9000

MSG_ERROR = 0x10
MSG_PLATE = 0x20
MSG_TICKET = 0x21
MSG_WANT_HEARTBEAT = 0x40
MSG_HEARTBEAT = 0x41
MSG_IAM_CAMERA = 0x80
MSG_IAM_DISPATCHER = 0x81


def _encode_error(text):
    b = text.encode("ascii")
    return bytes([MSG_ERROR, len(b)]) + b


def _encode_ticket(plate, road, m1, t1, m2, t2, speed):
    pb = plate.encode("ascii")
    buf = bytearray([MSG_TICKET, len(pb)])
    buf.extend(pb)
    buf.extend(struct.pack("!HHIHIH", road, m1, t1, m2, t2, speed))
    return bytes(buf)


class ServerState:
    def __init__(self):
        self.observations = defaultdict(lambda: defaultdict(list))
        self.dispatchers = defaultdict(list)
        self.pending_tickets = defaultdict(list)
        self.ticketed_days = defaultdict(set)
        self.lock = asyncio.Lock()

    async def add_observation(self, road, mile, limit, plate, timestamp):
        async with self.lock:
            obs = self.observations[road][plate]
            obs.append((mile, timestamp))

            for i in range(len(obs) - 1):
                om, ot = obs[i]
                if ot == timestamp:
                    continue

                m1, t1 = om, ot
                m2, t2 = mile, timestamp

                dt = abs(t2 - t1)
                dist = abs(m2 - m1)
                speed_mph = dist / dt * 3600.0

                if speed_mph < limit + 0.5:
                    continue

                day1 = t1 % 86400
                day2 = t2 % 86400
                days = set(range(min(day1, day2), max(day1, day2) + 1))
                if days & self.ticketed_days[plate]:
                    continue

                self.ticketed_days[plate] |= days
                speed100 = round(speed_mph * 100)
                tb = _encode_ticket(plate, road, m1, t1, m2, t2, speed100)

                dispatchers = self.dispatchers.get(road, [])
                if dispatchers:
                    try:
                        dispatchers[0].write(tb)
                        await dispatchers[0].drain()
                    except (ConnectionError, OSError):
                        pass

    async def register_dispatcher(self, roads, writer):
        async with self.lock:
            for rd in roads:
                self.dispatchers[rd].append(writer)
            for rd in roads:
                pending = self.pending_tickets[rd]
                while pending:
                    writer.write(pending.pop(0))
                try:
                    await writer.drain()
                except (ConnectionError, OSError):
                    pass

    async def unregister_dispatcher(self, roads, writer):
        async with self.lock:
            for rd in roads:
                try:
                    self.dispatchers[rd].remove(writer)
                except ValueError:
                    pass


async def _send_error_and_close(writer, text):
    try:
        writer.write(_encode_error(text))
        await writer.drain()
    except Exception:
        pass
    try:
        writer.close()
        await writer.wait_closed()
    except Exception:
        pass


async def _heartbeat_loop(writer, interval_sec):
    try:
        while True:
            await asyncio.sleep(interval_sec)
            writer.write(bytes([MSG_HEARTBEAT]))
            await writer.drain()
    except (asyncio.CancelledError, ConnectionError, OSError):
        pass


async def _handle_client(state, reader, writer):
    client_type = None
    camera_road = camera_mile = camera_limit = 0
    disp_roads = None
    hb_task = None
    hb_requested = False

    async def _cleanup():
        nonlocal hb_task
        if hb_task is not None:
            hb_task.cancel()
            try:
                await hb_task
            except asyncio.CancelledError:
                pass
        if disp_roads is not None:
            await state.unregister_dispatcher(disp_roads, writer)
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass

    try:
        while True:
            raw = await reader.readexactly(1)
            mtype = raw[0]

            if mtype == MSG_IAM_CAMERA:
                if client_type is not None:
                    await _send_error_and_close(writer, "already identified")
                    return
                data = await reader.readexactly(6)
                road, mile, limit = struct.unpack("!HHH", data)
                client_type = "camera"
                camera_road, camera_mile, camera_limit = road, mile, limit

            elif mtype == MSG_IAM_DISPATCHER:
                if client_type is not None:
                    await _send_error_and_close(writer, "already identified")
                    return
                n = (await reader.readexactly(1))[0]
                data = await reader.readexactly(n * 2)
                roads = list(struct.unpack(f"!{n}H", data))
                client_type = "dispatcher"
                disp_roads = roads
                await state.register_dispatcher(roads, writer)

            elif mtype == MSG_PLATE:
                if client_type != "camera":
                    await _send_error_and_close(writer, "not a camera")
                    return
                plen = (await reader.readexactly(1))[0]
                pname = (await reader.readexactly(plen)).decode("ascii")
                ts = struct.unpack("!I", await reader.readexactly(4))[0]
                await state.add_observation(
                    camera_road, camera_mile, camera_limit, pname, ts
                )

            elif mtype == MSG_WANT_HEARTBEAT:
                if client_type is not None:
                    await _send_error_and_close(
                        writer, "unexpected message type"
                    )
                    return
                if hb_requested:
                    await _send_error_and_close(writer, "duplicate heartbeat")
                    return
                hb_requested = True
                interval = struct.unpack("!I", await reader.readexactly(4))[0]
                if interval > 0:
                    hb_task = asyncio.create_task(
                        _heartbeat_loop(writer, interval / 100.0)
                    )

            else:
                await _send_error_and_close(
                    writer, f"bad msg type 0x{mtype:02x}"
                )
                return

    except (asyncio.IncompleteReadError, ConnectionError, OSError):
        pass
    finally:
        await _cleanup()


async def main():
    state = ServerState()
    server = await asyncio.start_server(
        lambda r, w: _handle_client(state, r, w),
        "0.0.0.0",
        PORT,
    )
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
