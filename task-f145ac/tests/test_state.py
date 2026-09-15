
"""
Tests for the Speed Enforcement Server.
Each test uses unique road numbers and plate strings to avoid state conflicts
since all tests share a single server instance.
"""

import socket
import struct
import time
import pytest

HOST = '127.0.0.1'
PORT = 9999

MSG_ERROR = 0x10
MSG_PLATE = 0x20
MSG_TICKET = 0x21
MSG_WANT_HEARTBEAT = 0x40
MSG_HEARTBEAT = 0x41
MSG_IAM_CAMERA = 0x80
MSG_IAM_DISPATCHER = 0x81


def recv_exact(sock, n):
    """Receive exactly n bytes from socket."""
    buf = b''
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Connection closed prematurely")
        buf += chunk
    return buf


def build_camera(road, mile, limit):
    return struct.pack('!BHHH', MSG_IAM_CAMERA, road, mile, limit)


def build_plate(plate, timestamp):
    pb = plate.encode('ascii')
    return struct.pack('!BB', MSG_PLATE, len(pb)) + pb + struct.pack('!I', timestamp)


def build_dispatcher(roads):
    data = struct.pack('!BB', MSG_IAM_DISPATCHER, len(roads))
    for r in roads:
        data += struct.pack('!H', r)
    return data


def build_heartbeat_req(interval_deciseconds):
    return struct.pack('!BI', MSG_WANT_HEARTBEAT, interval_deciseconds)


def read_ticket(sock):
    mt = recv_exact(sock, 1)[0]
    assert mt == MSG_TICKET, f"Expected TICKET (0x21), got 0x{mt:02x}"
    plen = recv_exact(sock, 1)[0]
    plate = recv_exact(sock, plen).decode('ascii')
    rest = recv_exact(sock, 16)
    road, mile1, ts1, mile2, ts2, speed = struct.unpack('!HHIHIH', rest)
    return {
        'plate': plate, 'road': road,
        'mile1': mile1, 'ts1': ts1,
        'mile2': mile2, 'ts2': ts2,
        'speed': speed,
    }


def connect():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5)
    s.connect((HOST, PORT))
    return s


# ---------------------------------------------------------------------------
# Basic speed violation produces a ticket
# Road 100, plate "SPEED1"
# ---------------------------------------------------------------------------
def test_basic_speeding_ticket():
    cam1 = connect()
    cam1.sendall(build_camera(100, 8, 60))

    cam2 = connect()
    cam2.sendall(build_camera(100, 9, 60))

    # 1 mile in 45 seconds = 80 mph > 60
    cam1.sendall(build_plate("SPEED1", 1000))
    time.sleep(0.2)
    cam2.sendall(build_plate("SPEED1", 1045))
    time.sleep(0.3)

    disp = connect()
    disp.sendall(build_dispatcher([100]))
    time.sleep(0.5)

    ticket = read_ticket(disp)
    assert ticket['plate'] == "SPEED1"
    assert ticket['road'] == 100
    assert ticket['mile1'] == 8
    assert ticket['ts1'] == 1000
    assert ticket['mile2'] == 9
    assert ticket['ts2'] == 1045
    assert ticket['speed'] == 8000

    cam1.close()
    cam2.close()
    disp.close()


# ---------------------------------------------------------------------------
# Speed comparison must use strictly-greater-than
# Road 200, plate "EXACT1"
# ---------------------------------------------------------------------------
def test_no_ticket_at_exact_speed_limit():
    cam1 = connect()
    cam1.sendall(build_camera(200, 0, 60))
    cam2 = connect()
    cam2.sendall(build_camera(200, 60, 60))

    disp = connect()
    disp.settimeout(2)
    disp.sendall(build_dispatcher([200]))
    time.sleep(0.2)

    # 60 miles in 3600 seconds = exactly 60 mph = limit (NOT exceeding)
    cam1.sendall(build_plate("EXACT1", 10000))
    time.sleep(0.2)
    cam2.sendall(build_plate("EXACT1", 13600))
    time.sleep(0.5)

    with pytest.raises(socket.timeout):
        recv_exact(disp, 1)

    cam1.close()
    cam2.close()
    disp.close()


# ---------------------------------------------------------------------------
# Duplicate WantHeartbeat must be rejected with Error
# ---------------------------------------------------------------------------
def test_duplicate_heartbeat_rejected():
    s = connect()
    s.settimeout(3)
    # Use a very long interval so no heartbeats arrive during the test
    s.sendall(build_heartbeat_req(500))  # 50-second interval
    time.sleep(0.2)
    s.sendall(build_heartbeat_req(500))  # duplicate — must trigger error
    time.sleep(0.5)

    first_byte = recv_exact(s, 1)[0]
    assert first_byte == MSG_ERROR, (
        f"Expected ERROR (0x10) for duplicate WantHeartbeat, got 0x{first_byte:02x}"
    )
    mlen = recv_exact(s, 1)[0]
    msg = recv_exact(s, mlen).decode('ascii')
    assert len(msg) > 0, "Error message should not be empty"
    s.close()


# ---------------------------------------------------------------------------
# Ticket must normalize timestamp order (ts1 < ts2)
# Road 300, plate "REV01"
# ---------------------------------------------------------------------------
def test_ticket_ordering_reversed_observations():
    cam1 = connect()
    cam1.sendall(build_camera(300, 10, 60))
    cam2 = connect()
    cam2.sendall(build_camera(300, 20, 60))

    disp = connect()
    disp.sendall(build_dispatcher([300]))
    time.sleep(0.2)

    # Camera 2 reports first (later timestamp)
    cam2.sendall(build_plate("REV01", 20450))
    time.sleep(0.2)

    # Camera 1 reports second (earlier timestamp)
    cam1.sendall(build_plate("REV01", 20000))
    time.sleep(0.5)

    ticket = read_ticket(disp)
    assert ticket['plate'] == "REV01"
    assert ticket['road'] == 300
    # Ticket MUST have earlier observation first
    assert ticket['ts1'] == 20000, (
        f"ts1 should be the earlier timestamp 20000, got {ticket['ts1']}"
    )
    assert ticket['mile1'] == 10
    assert ticket['ts2'] == 20450, (
        f"ts2 should be the later timestamp 20450, got {ticket['ts2']}"
    )
    assert ticket['mile2'] == 20
    assert ticket['speed'] == 8000  # 10mi/450s = 80 mph

    cam1.close()
    cam2.close()
    disp.close()


# ---------------------------------------------------------------------------
# Pending tickets must be removed after delivery
# Road 400, plate "PEND1"
# ---------------------------------------------------------------------------
def test_pending_tickets_cleared_after_delivery():
    cam1 = connect()
    cam1.sendall(build_camera(400, 0, 60))
    cam2 = connect()
    cam2.sendall(build_camera(400, 1, 60))

    # Generate violation with no dispatcher connected
    cam1.sendall(build_plate("PEND1", 30000))
    time.sleep(0.2)
    cam2.sendall(build_plate("PEND1", 30045))
    time.sleep(0.5)

    # First dispatcher connects — should receive the queued ticket
    disp1 = connect()
    disp1.sendall(build_dispatcher([400]))
    time.sleep(0.5)

    t1 = read_ticket(disp1)
    assert t1['plate'] == "PEND1"
    assert t1['road'] == 400
    disp1.close()
    time.sleep(0.3)

    # Second dispatcher connects — must NOT receive the same ticket again
    disp2 = connect()
    disp2.settimeout(2)
    disp2.sendall(build_dispatcher([400]))
    time.sleep(0.5)

    with pytest.raises(socket.timeout):
        recv_exact(disp2, 1)

    disp2.close()
    cam1.close()
    cam2.close()


# ---------------------------------------------------------------------------
# Day-spanning ticket must block ALL covered days
# Road 500, plate "SPAN01"
# ---------------------------------------------------------------------------
def test_day_spanning_ticket_blocks_all_days():
    cam1 = connect()
    cam1.sendall(build_camera(500, 0, 60))
    cam2 = connect()
    cam2.sendall(build_camera(500, 50, 60))
    cam3 = connect()
    cam3.sendall(build_camera(500, 100, 60))

    disp = connect()
    disp.sendall(build_dispatcher([500]))
    time.sleep(0.2)

    # Violation spanning day 0 -> day 1
    # ts=84600 is day 0 (84600/86400=0), ts=86400 is day 1 (86400/86400=1)
    # 50 miles / 1800 seconds = 100 mph > 60
    cam1.sendall(build_plate("SPAN01", 84600))
    time.sleep(0.2)
    cam2.sendall(build_plate("SPAN01", 86400))
    time.sleep(0.5)

    ticket = read_ticket(disp)
    assert ticket['plate'] == "SPAN01"
    assert ticket['speed'] == 10000  # 100 mph

    # Another observation on day 1 — should NOT generate a new ticket
    # because day 1 is already blocked by the spanning ticket
    cam3.sendall(build_plate("SPAN01", 88200))
    time.sleep(0.5)

    disp.settimeout(2)
    with pytest.raises(socket.timeout):
        recv_exact(disp, 1)

    cam1.close()
    cam2.close()
    cam3.close()
    disp.close()


# ---------------------------------------------------------------------------
# Error on Plate before camera identification
# ---------------------------------------------------------------------------
def test_error_plate_before_camera():
    s = connect()
    s.sendall(build_plate("OOPS1", 0))
    time.sleep(0.3)

    mt = recv_exact(s, 1)[0]
    assert mt == MSG_ERROR, f"Expected ERROR (0x10), got 0x{mt:02x}"
    mlen = recv_exact(s, 1)[0]
    msg = recv_exact(s, mlen).decode('ascii')
    assert len(msg) > 0
    s.close()


# ---------------------------------------------------------------------------
# Error on duplicate identification
# Road 700
# ---------------------------------------------------------------------------
def test_error_duplicate_identification():
    s = connect()
    s.sendall(build_camera(700, 0, 60))
    time.sleep(0.1)
    s.sendall(build_camera(700, 0, 60))
    time.sleep(0.3)

    mt = recv_exact(s, 1)[0]
    assert mt == MSG_ERROR, f"Expected ERROR (0x10), got 0x{mt:02x}"
    mlen = recv_exact(s, 1)[0]
    msg = recv_exact(s, mlen).decode('ascii')
    assert len(msg) > 0
    s.close()


# ---------------------------------------------------------------------------
# Heartbeat messages arrive at correct interval
# ---------------------------------------------------------------------------
def test_heartbeat_timing():
    s = connect()
    s.settimeout(4)

    # Request heartbeat every 0.5 seconds (5 deciseconds)
    s.sendall(build_heartbeat_req(5))

    beats = []
    start = time.time()
    for _ in range(3):
        mt = recv_exact(s, 1)[0]
        assert mt == MSG_HEARTBEAT, f"Expected HEARTBEAT (0x41), got 0x{mt:02x}"
        beats.append(time.time() - start)

    for i, t in enumerate(beats):
        expected = 0.5 * (i + 1)
        assert abs(t - expected) < 0.4, (
            f"Heartbeat {i+1} at {t:.2f}s, expected ~{expected:.1f}s"
        )

    s.close()


# ---------------------------------------------------------------------------
# Ticket queueing before dispatcher connects
# Road 600, plate "QUE01"
# ---------------------------------------------------------------------------
def test_ticket_queueing_before_dispatcher():
    cam1 = connect()
    cam1.sendall(build_camera(600, 0, 60))
    cam2 = connect()
    cam2.sendall(build_camera(600, 1, 60))

    # 1 mile in 30 sec = 120 mph > 60
    cam1.sendall(build_plate("QUE01", 40000))
    time.sleep(0.2)
    cam2.sendall(build_plate("QUE01", 40030))
    time.sleep(0.5)

    # Dispatcher connects after violation — should get queued ticket
    disp = connect()
    disp.sendall(build_dispatcher([600]))
    time.sleep(0.5)

    ticket = read_ticket(disp)
    assert ticket['plate'] == "QUE01"
    assert ticket['road'] == 600
    assert ticket['speed'] == 12000  # 120 mph

    cam1.close()
    cam2.close()
    disp.close()


# ---------------------------------------------------------------------------
# Combined: reversed observations + day-spanning dedup interaction
# Road 800, plate "COMBO1"
# ---------------------------------------------------------------------------
def test_reversed_observations_with_day_dedup():
    cam1 = connect()
    cam1.sendall(build_camera(800, 0, 60))
    cam2 = connect()
    cam2.sendall(build_camera(800, 50, 60))
    cam3 = connect()
    cam3.sendall(build_camera(800, 100, 60))

    disp = connect()
    disp.sendall(build_dispatcher([800]))
    time.sleep(0.2)

    # Observations arrive in REVERSE order AND span a day boundary
    # ts=173000 is day 2 (173000/86400=2.00...), ts=172500 is day 1 (172500/86400=1.99...)
    # Camera 2 reports first (later timestamp, day 2)
    cam2.sendall(build_plate("COMBO1", 173000))
    time.sleep(0.2)
    # Camera 1 reports second (earlier timestamp, day 1)
    cam1.sendall(build_plate("COMBO1", 172500))
    time.sleep(0.5)

    ticket = read_ticket(disp)
    assert ticket['plate'] == "COMBO1"
    # Must be normalized: earlier observation first
    assert ticket['ts1'] == 172500, f"ts1 should be 172500, got {ticket['ts1']}"
    assert ticket['ts2'] == 173000, f"ts2 should be 173000, got {ticket['ts2']}"
    assert ticket['mile1'] == 0
    assert ticket['mile2'] == 50

    # Observation on day 2 — should be blocked by spanning ticket (days 1-2)
    cam3.sendall(build_plate("COMBO1", 174800))
    time.sleep(0.5)

    disp.settimeout(2)
    with pytest.raises(socket.timeout):
        recv_exact(disp, 1)

    cam1.close()
    cam2.close()
    cam3.close()
    disp.close()
