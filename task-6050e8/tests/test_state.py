"""
Speed Daemon Server Protocol Tests

"""

import asyncio
import struct
import pytest

SERVER_HOST = '127.0.0.1'
SERVER_PORT = 9000

# Message type constants
MSG_ERROR = 0x10
MSG_PLATE = 0x20
MSG_TICKET = 0x21
MSG_WANT_HEARTBEAT = 0x40
MSG_HEARTBEAT = 0x41
MSG_IAM_CAMERA = 0x80
MSG_IAM_DISPATCHER = 0x81


# --- Encoding helpers ---

def encode_iam_camera(road, mile, limit):
    return struct.pack('>BHHH', MSG_IAM_CAMERA, road, mile, limit)


def encode_iam_dispatcher(roads):
    data = struct.pack('>BB', MSG_IAM_DISPATCHER, len(roads))
    for r in roads:
        data += struct.pack('>H', r)
    return data


def encode_plate(plate, timestamp):
    pb = plate.encode('ascii')
    return struct.pack('>BB', MSG_PLATE, len(pb)) + pb + struct.pack('>I', timestamp)


def encode_want_heartbeat(interval):
    return struct.pack('>BI', MSG_WANT_HEARTBEAT, interval)


# --- Decoding helpers ---

async def read_msg(reader, timeout=5.0):
    """Read a single message from the server. Returns None on timeout."""
    try:
        data = await asyncio.wait_for(reader.readexactly(1), timeout)
    except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionError, OSError):
        return None

    msg_type = data[0]

    try:
        if msg_type == MSG_ERROR:
            length = (await asyncio.wait_for(reader.readexactly(1), timeout))[0]
            msg = (await asyncio.wait_for(reader.readexactly(length), timeout)).decode('ascii')
            return ('error', msg)

        elif msg_type == MSG_TICKET:
            plate_len = (await asyncio.wait_for(reader.readexactly(1), timeout))[0]
            plate = (await asyncio.wait_for(reader.readexactly(plate_len), timeout)).decode('ascii')
            road, mile1 = struct.unpack('>HH', await asyncio.wait_for(reader.readexactly(4), timeout))
            ts1 = struct.unpack('>I', await asyncio.wait_for(reader.readexactly(4), timeout))[0]
            mile2 = struct.unpack('>H', await asyncio.wait_for(reader.readexactly(2), timeout))[0]
            ts2 = struct.unpack('>I', await asyncio.wait_for(reader.readexactly(4), timeout))[0]
            speed = struct.unpack('>H', await asyncio.wait_for(reader.readexactly(2), timeout))[0]
            return ('ticket', plate, road, mile1, ts1, mile2, ts2, speed)

        elif msg_type == MSG_HEARTBEAT:
            return ('heartbeat',)

        else:
            return ('unknown', msg_type)

    except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionError, OSError):
        return None


async def connect(timeout=5.0):
    """Connect to the server."""
    return await asyncio.wait_for(
        asyncio.open_connection(SERVER_HOST, SERVER_PORT), timeout
    )


def close_writers(*writers):
    for w in writers:
        try:
            w.close()
        except Exception:
            pass


# --- Tests ---

@pytest.mark.asyncio
async def test_basic_ticket():
    """Two cameras on same road, car exceeds speed limit -> ticket dispatched."""
    r1, w1 = await connect()
    r2, w2 = await connect()
    r3, w3 = await connect()
    try:
        # Camera 1: road 123, mile 8, limit 60
        w1.write(encode_iam_camera(123, 8, 60))
        await w1.drain()
        # Camera 2: road 123, mile 9, limit 60
        w2.write(encode_iam_camera(123, 9, 60))
        await w2.drain()
        # Dispatcher for road 123
        w3.write(encode_iam_dispatcher([123]))
        await w3.drain()

        await asyncio.sleep(0.3)

        # Car UN1X at camera 1, timestamp 0
        w1.write(encode_plate('UN1X', 0))
        await w1.drain()
        await asyncio.sleep(0.1)

        # Car UN1X at camera 2, timestamp 45 -> 1 mile / 45 sec = 80 mph
        w2.write(encode_plate('UN1X', 45))
        await w2.drain()

        msg = await read_msg(r3, timeout=5.0)
        assert msg is not None, "Expected ticket but got nothing"
        assert msg[0] == 'ticket'
        assert msg[1] == 'UN1X'
        assert msg[2] == 123      # road
        assert msg[3] == 8        # mile1
        assert msg[4] == 0        # timestamp1
        assert msg[5] == 9        # mile2
        assert msg[6] == 45       # timestamp2
        assert msg[7] == 8000     # speed: 80.00 mph * 100
    finally:
        close_writers(w1, w2, w3)


@pytest.mark.asyncio
async def test_no_ticket_under_limit():
    """Car under speed limit -> no ticket generated."""
    r1, w1 = await connect()
    r2, w2 = await connect()
    r3, w3 = await connect()
    try:
        w1.write(encode_iam_camera(200, 10, 60))
        await w1.drain()
        w2.write(encode_iam_camera(200, 11, 60))
        await w2.drain()
        w3.write(encode_iam_dispatcher([200]))
        await w3.drain()

        await asyncio.sleep(0.3)

        # Car SAFE1 at 30 mph: 1 mile in 120 seconds
        w1.write(encode_plate('SAFE1', 0))
        await w1.drain()
        await asyncio.sleep(0.1)
        w2.write(encode_plate('SAFE1', 120))
        await w2.drain()

        msg = await read_msg(r3, timeout=2.0)
        assert msg is None, f"Expected no ticket but got: {msg}"
    finally:
        close_writers(w1, w2, w3)


@pytest.mark.asyncio
async def test_ticket_queued_for_dispatcher():
    """Tickets generated before dispatcher connects are queued and delivered."""
    r1, w1 = await connect()
    r2, w2 = await connect()
    try:
        w1.write(encode_iam_camera(300, 5, 50))
        await w1.drain()
        w2.write(encode_iam_camera(300, 15, 50))
        await w2.drain()

        await asyncio.sleep(0.3)

        # Car FAST1 at 100 mph: 10 miles in 360 seconds
        w1.write(encode_plate('FAST1', 0))
        await w1.drain()
        await asyncio.sleep(0.1)
        w2.write(encode_plate('FAST1', 360))
        await w2.drain()

        # Wait for server to process and queue the ticket
        await asyncio.sleep(0.5)

        # NOW connect dispatcher - should receive queued ticket
        r3, w3 = await connect()
        try:
            w3.write(encode_iam_dispatcher([300]))
            await w3.drain()

            msg = await read_msg(r3, timeout=5.0)
            assert msg is not None, "Expected queued ticket but got nothing"
            assert msg[0] == 'ticket'
            assert msg[1] == 'FAST1'
            assert msg[2] == 300
            assert msg[3] == 5       # mile1
            assert msg[4] == 0       # timestamp1
            assert msg[5] == 15      # mile2
            assert msg[6] == 360     # timestamp2
            assert msg[7] == 10000   # 100.00 mph
        finally:
            close_writers(w3)
    finally:
        close_writers(w1, w2)


@pytest.mark.asyncio
async def test_one_ticket_per_day():
    """Multiple violations on same day for same car -> only one ticket."""
    r1, w1 = await connect()
    r2, w2 = await connect()
    r3, w3 = await connect()
    r4, w4 = await connect()
    try:
        w1.write(encode_iam_camera(400, 0, 60))
        await w1.drain()
        w2.write(encode_iam_camera(400, 10, 60))
        await w2.drain()
        w3.write(encode_iam_camera(400, 20, 60))
        await w3.drain()
        w4.write(encode_iam_dispatcher([400]))
        await w4.drain()

        await asyncio.sleep(0.3)

        # First violation: 10 miles / 60 sec = 600 mph (day 0)
        w1.write(encode_plate('MULTI', 0))
        await w1.drain()
        await asyncio.sleep(0.1)
        w2.write(encode_plate('MULTI', 60))
        await w2.drain()

        msg = await read_msg(r4, timeout=5.0)
        assert msg is not None, "Expected first ticket"
        assert msg[0] == 'ticket'
        assert msg[1] == 'MULTI'

        await asyncio.sleep(0.3)

        # Second violation on same day: 10 miles / 60 sec = 600 mph
        w3.write(encode_plate('MULTI', 120))
        await w3.drain()

        # Should NOT get a second ticket (same day 0)
        msg2 = await read_msg(r4, timeout=2.0)
        assert msg2 is None, f"Expected no second ticket but got: {msg2}"
    finally:
        close_writers(w1, w2, w3, w4)


@pytest.mark.asyncio
async def test_heartbeat():
    """Client can request heartbeats at a specific interval."""
    r, w = await connect()
    try:
        # Request heartbeat every 5 deciseconds = 0.5 seconds
        w.write(encode_want_heartbeat(5))
        await w.drain()

        # First heartbeat should arrive after ~0.5 seconds
        msg1 = await read_msg(r, timeout=3.0)
        assert msg1 is not None, "Expected first heartbeat"
        assert msg1[0] == 'heartbeat'

        # Second heartbeat after another ~0.5 seconds
        msg2 = await read_msg(r, timeout=3.0)
        assert msg2 is not None, "Expected second heartbeat"
        assert msg2[0] == 'heartbeat'
    finally:
        close_writers(w)


@pytest.mark.asyncio
async def test_error_plate_without_identity():
    """Sending Plate before identifying as camera is a protocol error."""
    r, w = await connect()
    try:
        w.write(encode_plate('BAD1', 0))
        await w.drain()

        msg = await read_msg(r, timeout=5.0)
        assert msg is not None, "Expected error message"
        assert msg[0] == 'error'
    finally:
        close_writers(w)


@pytest.mark.asyncio
async def test_error_duplicate_camera_identity():
    """Sending IAmCamera twice is a protocol error."""
    r, w = await connect()
    try:
        w.write(encode_iam_camera(100, 5, 60))
        await w.drain()
        await asyncio.sleep(0.2)

        w.write(encode_iam_camera(100, 10, 60))
        try:
            await w.drain()
        except (ConnectionError, OSError):
            pass

        msg = await read_msg(r, timeout=5.0)
        assert msg is not None, "Expected error message"
        assert msg[0] == 'error'
    finally:
        close_writers(w)


@pytest.mark.asyncio
async def test_error_camera_then_dispatcher():
    """Sending IAmDispatcher after IAmCamera is a protocol error."""
    r, w = await connect()
    try:
        w.write(encode_iam_camera(101, 5, 60))
        await w.drain()
        await asyncio.sleep(0.2)

        w.write(encode_iam_dispatcher([101]))
        try:
            await w.drain()
        except (ConnectionError, OSError):
            pass

        msg = await read_msg(r, timeout=5.0)
        assert msg is not None, "Expected error message"
        assert msg[0] == 'error'
    finally:
        close_writers(w)


@pytest.mark.asyncio
async def test_multiple_roads():
    """Tickets are routed to the correct road dispatcher."""
    # Road 500 cameras
    r1, w1 = await connect()
    r2, w2 = await connect()
    # Road 600 cameras
    r3, w3 = await connect()
    r4, w4 = await connect()
    # Dispatchers
    r5, w5 = await connect()
    r6, w6 = await connect()
    try:
        w1.write(encode_iam_camera(500, 0, 60))
        await w1.drain()
        w2.write(encode_iam_camera(500, 1, 60))
        await w2.drain()
        w3.write(encode_iam_camera(600, 0, 80))
        await w3.drain()
        w4.write(encode_iam_camera(600, 2, 80))
        await w4.drain()
        w5.write(encode_iam_dispatcher([500]))
        await w5.drain()
        w6.write(encode_iam_dispatcher([600]))
        await w6.drain()

        await asyncio.sleep(0.3)

        # Violation on road 500: 1 mile / 10 sec = 360 mph
        w1.write(encode_plate('R500C', 1000))
        await w1.drain()
        await asyncio.sleep(0.1)
        w2.write(encode_plate('R500C', 1010))
        await w2.drain()

        # Violation on road 600: 2 miles / 20 sec = 360 mph
        w3.write(encode_plate('R600C', 2000))
        await w3.drain()
        await asyncio.sleep(0.1)
        w4.write(encode_plate('R600C', 2020))
        await w4.drain()

        # Road 500 dispatcher gets ticket for R500C
        msg5 = await read_msg(r5, timeout=5.0)
        assert msg5 is not None, "Expected ticket on road 500"
        assert msg5[0] == 'ticket'
        assert msg5[1] == 'R500C'
        assert msg5[2] == 500

        # Road 600 dispatcher gets ticket for R600C
        msg6 = await read_msg(r6, timeout=5.0)
        assert msg6 is not None, "Expected ticket on road 600"
        assert msg6[0] == 'ticket'
        assert msg6[1] == 'R600C'
        assert msg6[2] == 600

        # No cross-contamination
        extra5 = await read_msg(r5, timeout=1.0)
        assert extra5 is None, f"Unexpected extra ticket on road 500 dispatcher: {extra5}"
        extra6 = await read_msg(r6, timeout=1.0)
        assert extra6 is None, f"Unexpected extra ticket on road 600 dispatcher: {extra6}"
    finally:
        close_writers(w1, w2, w3, w4, w5, w6)


@pytest.mark.asyncio
async def test_multi_day_ticket_blocks_future():
    """A ticket spanning days 0-1 blocks future tickets on day 1."""
    r1, w1 = await connect()
    r2, w2 = await connect()
    r3, w3 = await connect()
    r4, w4 = await connect()
    try:
        w1.write(encode_iam_camera(700, 0, 30))
        await w1.drain()
        w2.write(encode_iam_camera(700, 10, 30))
        await w2.drain()
        w3.write(encode_iam_camera(700, 20, 30))
        await w3.drain()
        w4.write(encode_iam_dispatcher([700]))
        await w4.drain()

        await asyncio.sleep(0.3)

        # Observation 1: mile 0, ts 86000 (day 0, near boundary)
        # Observation 2: mile 10, ts 86500 (day 1)
        # Speed: 10 miles / 500 sec * 3600 = 72 mph > 30 mph
        # Ticket spans day 0 to day 1
        w1.write(encode_plate('SPANX', 86000))
        await w1.drain()
        await asyncio.sleep(0.1)
        w2.write(encode_plate('SPANX', 86500))
        await w2.drain()

        msg = await read_msg(r4, timeout=5.0)
        assert msg is not None, "Expected spanning ticket"
        assert msg[0] == 'ticket'
        assert msg[1] == 'SPANX'

        await asyncio.sleep(0.3)

        # Observation 3: mile 20, ts 87000 (day 1)
        # vs obs 2: 10 miles / 500 sec = 72 mph -> violation, but day 1 already ticketed
        w3.write(encode_plate('SPANX', 87000))
        await w3.drain()

        msg2 = await read_msg(r4, timeout=2.0)
        assert msg2 is None, f"Expected no second ticket (day 1 blocked) but got: {msg2}"
    finally:
        close_writers(w1, w2, w3, w4)


@pytest.mark.asyncio
async def test_cross_road_day_limit():
    """One-ticket-per-day applies across different roads."""
    # Road 800 cameras
    r1, w1 = await connect()
    r2, w2 = await connect()
    # Road 900 cameras
    r3, w3 = await connect()
    r4, w4 = await connect()
    # Dispatchers
    r5, w5 = await connect()
    r6, w6 = await connect()
    try:
        w1.write(encode_iam_camera(800, 0, 60))
        await w1.drain()
        w2.write(encode_iam_camera(800, 1, 60))
        await w2.drain()
        w3.write(encode_iam_camera(900, 0, 60))
        await w3.drain()
        w4.write(encode_iam_camera(900, 1, 60))
        await w4.drain()
        w5.write(encode_iam_dispatcher([800]))
        await w5.drain()
        w6.write(encode_iam_dispatcher([900]))
        await w6.drain()

        await asyncio.sleep(0.3)

        # Car CROSSX violates on road 800, day 0: 1 mile / 36 sec = 100 mph
        w1.write(encode_plate('CROSSX', 0))
        await w1.drain()
        await asyncio.sleep(0.1)
        w2.write(encode_plate('CROSSX', 36))
        await w2.drain()

        msg_800 = await read_msg(r5, timeout=5.0)
        assert msg_800 is not None, "Expected ticket on road 800"
        assert msg_800[0] == 'ticket'
        assert msg_800[1] == 'CROSSX'
        assert msg_800[2] == 800

        await asyncio.sleep(0.3)

        # Same car violates on road 900, same day 0: 1 mile / 36 sec = 100 mph
        w3.write(encode_plate('CROSSX', 100))
        await w3.drain()
        await asyncio.sleep(0.1)
        w4.write(encode_plate('CROSSX', 136))
        await w4.drain()

        # Should NOT get ticket on road 900 (day 0 already ticketed via road 800)
        msg_900 = await read_msg(r6, timeout=2.0)
        assert msg_900 is None, f"Expected no ticket on road 900 (cross-road day limit) but got: {msg_900}"
    finally:
        close_writers(w1, w2, w3, w4, w5, w6)


@pytest.mark.asyncio
async def test_non_adjacent_cameras():
    """Speed violation detected even when car skips intermediate cameras."""
    r1, w1 = await connect()
    r2, w2 = await connect()
    r3, w3 = await connect()
    r4, w4 = await connect()
    try:
        # Three cameras on road 1000, but car only seen at first and third
        w1.write(encode_iam_camera(1000, 0, 60))
        await w1.drain()
        w2.write(encode_iam_camera(1000, 10, 60))
        await w2.drain()
        w3.write(encode_iam_camera(1000, 20, 60))
        await w3.drain()
        w4.write(encode_iam_dispatcher([1000]))
        await w4.drain()

        await asyncio.sleep(0.3)

        # Car SKIP1 seen at mile 0, then mile 20 (skips mile 10)
        # 20 miles / 720 sec = 100 mph
        w1.write(encode_plate('SKIP1', 0))
        await w1.drain()
        await asyncio.sleep(0.1)
        w3.write(encode_plate('SKIP1', 720))
        await w3.drain()

        msg = await read_msg(r4, timeout=5.0)
        assert msg is not None, "Expected ticket for non-adjacent camera detection"
        assert msg[0] == 'ticket'
        assert msg[1] == 'SKIP1'
        assert msg[2] == 1000
        assert msg[3] == 0       # mile1
        assert msg[5] == 20      # mile2
        assert msg[7] == 10000   # 100.00 mph
    finally:
        close_writers(w1, w2, w3, w4)
