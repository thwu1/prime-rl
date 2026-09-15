"""
Tests for the Speed Daemon binary protocol server — verifies protocol compliance.

"""

import socket
import struct
import time
import pytest

HOST = "localhost"
PORT = 9000


class Client:
    """TCP client that speaks the Speed Daemon binary protocol."""

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(5.0)
        self.sock.connect((HOST, PORT))

    def close(self):
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass

    def _send(self, data: bytes):
        self.sock.sendall(data)

    def _recv_exact(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("Connection closed while reading")
            buf += chunk
        return buf

    @staticmethod
    def _encode_str(s: str) -> bytes:
        raw = s.encode("ascii")
        return struct.pack("!B", len(raw)) + raw

    # --- send helpers ---

    def send_iamcamera(self, road: int, mile: int, limit: int):
        self._send(struct.pack("!BHHH", 0x80, road, mile, limit))

    def send_iamdispatcher(self, roads: list):
        msg = struct.pack("!BB", 0x81, len(roads))
        for r in roads:
            msg += struct.pack("!H", r)
        self._send(msg)

    def send_plate(self, plate: str, timestamp: int):
        self._send(
            struct.pack("!B", 0x20) + self._encode_str(plate) + struct.pack("!I", timestamp)
        )

    def send_wantheartbeat(self, interval_deciseconds: int):
        self._send(struct.pack("!BI", 0x40, interval_deciseconds))

    # --- recv helpers ---

    def recv_message(self, timeout: float = 5.0) -> dict:
        self.sock.settimeout(timeout)
        msg_type = self._recv_exact(1)[0]

        if msg_type == 0x10:  # Error
            str_len = self._recv_exact(1)[0]
            msg = self._recv_exact(str_len).decode("ascii")
            return {"type": "error", "msg": msg}

        if msg_type == 0x21:  # Ticket
            plate_len = self._recv_exact(1)[0]
            plate = self._recv_exact(plate_len).decode("ascii")
            road, mile1 = struct.unpack("!HH", self._recv_exact(4))
            (timestamp1,) = struct.unpack("!I", self._recv_exact(4))
            (mile2,) = struct.unpack("!H", self._recv_exact(2))
            (timestamp2,) = struct.unpack("!I", self._recv_exact(4))
            (speed,) = struct.unpack("!H", self._recv_exact(2))
            return {
                "type": "ticket",
                "plate": plate,
                "road": road,
                "mile1": mile1,
                "timestamp1": timestamp1,
                "mile2": mile2,
                "timestamp2": timestamp2,
                "speed": speed,
            }

        if msg_type == 0x41:  # Heartbeat
            return {"type": "heartbeat"}

        raise ValueError(f"Unknown server message type: 0x{msg_type:02x}")

    def try_recv_message(self, timeout: float = 2.0):
        """Receive a message or return None on timeout / disconnect."""
        try:
            return self.recv_message(timeout=timeout)
        except (socket.timeout, TimeoutError, ConnectionError, OSError):
            return None

    def recv_raw(self, nbytes: int, timeout: float = 5.0) -> bytes:
        """Receive up to nbytes of raw data."""
        self.sock.settimeout(timeout)
        buf = b""
        deadline = time.time() + timeout
        while len(buf) < nbytes and time.time() < deadline:
            try:
                self.sock.settimeout(max(0.1, deadline - time.time()))
                chunk = self.sock.recv(nbytes - len(buf))
                if not chunk:
                    break
                buf += chunk
            except (socket.timeout, TimeoutError):
                break
        return buf


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_ticket_raw_encoding():
    """Verify raw ticket bytes match the spec field order:
    type(1) plate_len(1) plate(N) road(2) mile1(2) ts1(4) mile2(2) ts2(4) speed(2)"""
    cam1 = Client()
    cam2 = Client()
    disp = Client()
    try:
        cam1.send_iamcamera(66, 100, 50)
        cam2.send_iamcamera(66, 110, 50)
        disp.send_iamdispatcher([66])
        time.sleep(0.3)

        cam1.send_plate("UN1X", 123456)
        cam2.send_plate("UN1X", 123816)

        # Expected ticket size: 1+1+4+2+2+4+2+4+2 = 22 bytes
        raw = disp.recv_raw(22, timeout=5.0)
        assert len(raw) >= 22, f"Expected at least 22 bytes, got {len(raw)}"

        pos = 0
        assert raw[pos] == 0x21, f"Expected ticket type 0x21, got 0x{raw[pos]:02x}"
        pos += 1
        plen = raw[pos]
        pos += 1
        assert raw[pos:pos + plen] == b"UN1X"
        pos += plen

        road = struct.unpack("!H", raw[pos:pos + 2])[0]
        pos += 2
        mile1 = struct.unpack("!H", raw[pos:pos + 2])[0]
        pos += 2
        ts1 = struct.unpack("!I", raw[pos:pos + 4])[0]
        pos += 4
        mile2 = struct.unpack("!H", raw[pos:pos + 2])[0]
        pos += 2
        ts2 = struct.unpack("!I", raw[pos:pos + 4])[0]
        pos += 4
        speed = struct.unpack("!H", raw[pos:pos + 2])[0]

        assert road == 66, f"road: expected 66, got {road}"
        assert mile1 == 100, f"mile1: expected 100, got {mile1}"
        assert ts1 == 123456, f"ts1: expected 123456, got {ts1}"
        assert mile2 == 110, f"mile2: expected 110, got {mile2}"
        assert ts2 == 123816, f"ts2: expected 123816, got {ts2}"
        assert speed == 10000, f"speed: expected 10000, got {speed}"
    finally:
        cam1.close()
        cam2.close()
        disp.close()


def test_reverse_direction_ticket_ordering():
    """When a car drives from a higher mile to a lower mile, ticket fields
    must be ordered by timestamp (earlier first), not by mile position."""
    cam_high = Client()
    cam_low = Client()
    disp = Client()
    try:
        cam_high.send_iamcamera(200, 20, 50)
        cam_low.send_iamcamera(200, 10, 50)
        disp.send_iamdispatcher([200])
        time.sleep(0.3)

        # Car seen at mile 20 first (ts=0), then mile 10 (ts=100)
        cam_high.send_plate("REV1", 0)
        time.sleep(0.2)
        cam_low.send_plate("REV1", 100)

        msg = disp.recv_message(timeout=5.0)
        assert msg["type"] == "ticket", f"Expected ticket, got {msg}"
        assert msg["road"] == 200, f"road: expected 200, got {msg['road']}"
        # Earlier timestamp (0) must come first, even though mile 20 > mile 10
        assert msg["mile1"] == 20, f"mile1: expected 20 (earlier ts), got {msg['mile1']}"
        assert msg["timestamp1"] == 0, f"ts1: expected 0, got {msg['timestamp1']}"
        assert msg["mile2"] == 10, f"mile2: expected 10 (later ts), got {msg['mile2']}"
        assert msg["timestamp2"] == 100, f"ts2: expected 100, got {msg['timestamp2']}"
        assert msg["speed"] == 36000, f"speed: expected 36000, got {msg['speed']}"
    finally:
        cam_high.close()
        cam_low.close()
        disp.close()


def test_multiday_span_blocks_end_day():
    """A ticket spanning day 0 to day 1 must block further tickets on day 1."""
    cam_a = Client()
    cam_b = Client()
    cam_c = Client()
    disp = Client()
    try:
        cam_a.send_iamcamera(500, 0, 10)
        cam_b.send_iamcamera(500, 10, 10)
        cam_c.send_iamcamera(500, 20, 10)

        disp.send_iamdispatcher([500])
        time.sleep(0.3)

        # Day boundary at 86400
        cam_a.send_plate("SPAN1", 86350)   # day 0
        time.sleep(0.2)
        cam_b.send_plate("SPAN1", 86450)   # day 1  -> ticket spans day 0 & 1
        time.sleep(1.0)

        # First ticket should arrive (any parsed fields, just check type)
        msg1 = disp.recv_message(timeout=5.0)
        assert msg1["type"] == "ticket", f"Expected ticket, got {msg1}"

        # Third observation, also day 1 -> should NOT trigger second ticket
        cam_c.send_plate("SPAN1", 86550)
        time.sleep(1.5)

        msg2 = disp.try_recv_message(timeout=2.0)
        assert msg2 is None, f"Day 1 already ticketed by spanning ticket, but got: {msg2}"
    finally:
        cam_a.close()
        cam_b.close()
        cam_c.close()
        disp.close()


def test_heartbeat_interval_deciseconds():
    """WantHeartbeat interval is in deciseconds (10/sec).
    Interval=10 means 1 heartbeat per second, not per 0.1 seconds."""
    client = Client()
    try:
        client.send_wantheartbeat(10)  # 10 deciseconds = 1 second

        # Count heartbeats over 2.5 seconds
        count = 0
        start = time.time()
        deadline = start + 2.5
        while time.time() < deadline:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            msg = client.try_recv_message(timeout=min(0.5, remaining))
            if msg and msg["type"] == "heartbeat":
                count += 1

        # Correct (1s interval): ~2-3 heartbeats in 2.5s
        # Bug (0.1s interval): ~25 heartbeats in 2.5s
        assert 1 <= count <= 5, (
            f"Expected 1-5 heartbeats in 2.5s (1s interval), got {count}. "
            f"If {count} >> 5, the interval unit may be wrong (centiseconds vs deciseconds)."
        )
    finally:
        client.close()


def test_dispatcher_plate_produces_error():
    """A dispatcher sending a Plate message must receive an Error response.
    Only cameras may send Plate messages."""
    client = Client()
    try:
        client.send_iamdispatcher([100])
        time.sleep(0.2)
        client.send_plate("BAD1", 0)

        msg = client.recv_message(timeout=3.0)
        assert msg["type"] == "error", (
            f"Expected error when dispatcher sends plate, got: {msg}"
        )
    finally:
        client.close()


def test_error_on_plate_from_unidentified_client():
    """Sending Plate without identifying as camera -> Error."""
    client = Client()
    try:
        client.send_plate("NOIDENT", 0)

        msg = client.recv_message(timeout=3.0)
        assert msg["type"] == "error"
    finally:
        client.close()


def test_error_on_duplicate_camera_identity():
    """Sending IAmCamera twice on the same connection -> Error."""
    client = Client()
    try:
        client.send_iamcamera(100, 0, 60)
        time.sleep(0.1)
        client.send_iamcamera(100, 0, 60)

        msg = client.recv_message(timeout=3.0)
        assert msg["type"] == "error"
    finally:
        client.close()


def test_ticket_buffering_for_unavailable_dispatcher():
    """Tickets generated before any dispatcher connects must be buffered
    and delivered once a dispatcher for that road connects."""
    cam1 = Client()
    cam2 = Client()
    try:
        cam1.send_iamcamera(400, 0, 60)
        cam2.send_iamcamera(400, 10, 60)

        # Observations arrive with no dispatcher for road 400
        cam1.send_plate("BUF1", 0)
        time.sleep(0.2)
        cam2.send_plate("BUF1", 100)  # 360 mph
        time.sleep(1.0)

        # Now connect a dispatcher
        disp = Client()
        try:
            disp.send_iamdispatcher([400])
            msg = disp.recv_message(timeout=5.0)
            assert msg["type"] == "ticket"
            assert msg["plate"] == "BUF1"
        finally:
            disp.close()
    finally:
        cam1.close()
        cam2.close()


def test_concurrent_multi_road():
    """Multiple roads with concurrent cameras produce correct tickets."""
    cameras = []
    disp = Client()
    try:
        roads = list(range(1000, 1005))

        for road in roads:
            c1 = Client()
            c2 = Client()
            c1.send_iamcamera(road, 0, 60)
            c2.send_iamcamera(road, 10, 60)
            cameras.extend([c1, c2])

        disp.send_iamdispatcher(roads)
        time.sleep(0.3)

        for i, road in enumerate(roads):
            cameras[2 * i].send_plate(f"MC{i:02d}", 0)
            cameras[2 * i + 1].send_plate(f"MC{i:02d}", 100)  # 360 mph

        time.sleep(2.0)

        tickets = []
        for _ in range(5):
            msg = disp.recv_message(timeout=5.0)
            assert msg["type"] == "ticket"
            tickets.append(msg)

        # No extra tickets
        assert disp.try_recv_message(timeout=1.5) is None
    finally:
        for c in cameras:
            c.close()
        disp.close()


def test_speed_threshold_boundary():
    """Cars at exactly the speed limit must NOT be ticketed.
    Cars exceeding by >= 0.5 mph MUST be ticketed (per spec rounding rules)."""
    # Part 1: exactly at limit — no ticket
    cam1 = Client()
    cam2 = Client()
    disp1 = Client()
    try:
        cam1.send_iamcamera(300, 0, 60)
        cam2.send_iamcamera(300, 60, 60)
        disp1.send_iamdispatcher([300])
        time.sleep(0.3)

        # 60 miles / 3600 seconds = exactly 60 mph = limit, no ticket
        cam1.send_plate("EXACT", 0)
        time.sleep(0.2)
        cam2.send_plate("EXACT", 3600)
        time.sleep(1.5)

        msg = disp1.try_recv_message(timeout=2.0)
        assert msg is None, f"Car at exactly the speed limit should NOT be ticketed: {msg}"
    finally:
        cam1.close()
        cam2.close()
        disp1.close()

    # Part 2: 0.5 mph over limit — must ticket
    cam3 = Client()
    cam4 = Client()
    disp2 = Client()
    try:
        cam3.send_iamcamera(301, 0, 100)
        cam4.send_iamcamera(301, 201, 100)
        disp2.send_iamdispatcher([301])
        time.sleep(0.3)

        # 201 miles / 7200 seconds = 100.5 mph (exactly 0.5 over limit of 100)
        cam3.send_plate("HALF", 0)
        time.sleep(0.2)
        cam4.send_plate("HALF", 7200)

        msg = disp2.recv_message(timeout=5.0)
        assert msg["type"] == "ticket", f"0.5 mph over limit must produce ticket: {msg}"
        # speed = 100.5 * 100 = 10050
        assert msg["speed"] == 10050, f"Speed should be 10050, got {msg['speed']}"
    finally:
        cam3.close()
        cam4.close()
        disp2.close()


def test_dispatcher_disconnect_cleanup():
    """After a dispatcher disconnects, its writer must be removed from the
    registry. Tickets generated while no dispatcher is available must be
    buffered and delivered to a subsequently-connected dispatcher."""
    cam1 = Client()
    cam2 = Client()
    try:
        cam1.send_iamcamera(700, 0, 60)
        cam2.send_iamcamera(700, 10, 60)

        # First dispatcher connects then disconnects
        disp1 = Client()
        disp1.send_iamdispatcher([700])
        time.sleep(0.3)
        disp1.close()
        time.sleep(0.5)

        # Generate a violation while no functioning dispatcher is connected
        cam1.send_plate("CLEAN", 0)
        time.sleep(0.2)
        cam2.send_plate("CLEAN", 100)  # 360 mph
        time.sleep(1.0)

        # New dispatcher connects — should receive the buffered ticket
        disp2 = Client()
        try:
            disp2.send_iamdispatcher([700])
            msg = disp2.recv_message(timeout=5.0)
            assert msg["type"] == "ticket", f"Expected buffered ticket, got: {msg}"
            assert msg["plate"] == "CLEAN", f"Expected plate CLEAN, got: {msg['plate']}"
        finally:
            disp2.close()
    finally:
        cam1.close()
        cam2.close()


def test_multiple_observations_dedup():
    """Three observations of the same car speeding on one road (same day).
    Only one ticket should be generated due to per-car-per-day dedup."""
    cam1 = Client()
    cam2 = Client()
    cam3 = Client()
    disp = Client()
    try:
        cam1.send_iamcamera(600, 0, 60)
        cam2.send_iamcamera(600, 10, 60)
        cam3.send_iamcamera(600, 20, 60)
        disp.send_iamdispatcher([600])
        time.sleep(0.3)

        # All on day 0, all speeding (360 mph between each pair)
        cam1.send_plate("DUP1", 0)
        time.sleep(0.2)
        cam2.send_plate("DUP1", 100)   # 10mi/100s*3600 = 360 mph
        time.sleep(0.2)
        cam3.send_plate("DUP1", 200)   # still speeding vs both prior obs
        time.sleep(2.0)

        # Should get exactly 1 ticket (day 0 consumed by first violation)
        msg1 = disp.recv_message(timeout=5.0)
        assert msg1["type"] == "ticket"
        assert msg1["plate"] == "DUP1"

        msg2 = disp.try_recv_message(timeout=2.0)
        assert msg2 is None, f"Only 1 ticket per car per day, but got second: {msg2}"
    finally:
        cam1.close()
        cam2.close()
        cam3.close()
        disp.close()


def test_cross_road_same_day_dedup():
    """A car ticketed on one road on day 0 must NOT be ticketed again
    on a different road on the same day. Dedup is per-car globally
    across the entire road network, not per-road."""
    cam_a1 = Client()
    cam_a2 = Client()
    cam_b1 = Client()
    cam_b2 = Client()
    disp = Client()
    try:
        # Road 800, limit 60
        cam_a1.send_iamcamera(800, 0, 60)
        cam_a2.send_iamcamera(800, 10, 60)
        # Road 801, limit 60
        cam_b1.send_iamcamera(801, 0, 60)
        cam_b2.send_iamcamera(801, 10, 60)

        disp.send_iamdispatcher([800, 801])
        time.sleep(0.3)

        # Car speeds on road 800 (day 0)
        cam_a1.send_plate("XROAD", 0)
        time.sleep(0.2)
        cam_a2.send_plate("XROAD", 100)  # 360 mph
        time.sleep(1.0)

        # First ticket should arrive (road 800)
        msg1 = disp.recv_message(timeout=5.0)
        assert msg1["type"] == "ticket", f"Expected ticket for road 800, got {msg1}"
        assert msg1["plate"] == "XROAD"
        assert msg1["road"] == 800

        # Same car speeds on road 801 (same day 0)
        cam_b1.send_plate("XROAD", 200)
        time.sleep(0.2)
        cam_b2.send_plate("XROAD", 300)  # 360 mph
        time.sleep(1.5)

        # Second ticket must NOT arrive (day 0 already covered globally)
        msg2 = disp.try_recv_message(timeout=2.0)
        assert msg2 is None, (
            f"Cross-road dedup failed: car XROAD already ticketed on day 0 "
            f"(road 800), but got second ticket on road 801: {msg2}"
        )
    finally:
        cam_a1.close()
        cam_a2.close()
        cam_b1.close()
        cam_b2.close()
        disp.close()
