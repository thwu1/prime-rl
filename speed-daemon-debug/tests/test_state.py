"""
Tests for the LRCP Line Reversal server.

"""

import socket
import time
import pytest

PORT = 9000
ADDR = ("127.0.0.1", PORT)


# ------------------------------------------------------------------ #
#  LRCP helpers                                                       #
# ------------------------------------------------------------------ #

def lrcp_escape(data: bytes) -> bytes:
    out = bytearray()
    for b in data:
        if b == 0x5C:
            out.extend(b'\\\\')
        elif b == 0x2F:
            out.extend(b'\\/')
        else:
            out.append(b)
    return bytes(out)


def lrcp_unescape(data: bytes) -> bytes:
    out = bytearray()
    i = 0
    while i < len(data):
        if data[i] == 0x5C and i + 1 < len(data):
            out.append(data[i + 1])
            i += 2
        else:
            out.append(data[i])
            i += 1
    return bytes(out)


def parse_lrcp(raw: bytes):
    """Parse an LRCP message → (type, session, ...) or None."""
    if len(raw) < 3 or raw[0] != 0x2F or raw[-1] != 0x2F:
        return None
    parts, cur = [], bytearray()
    i, end = 1, len(raw) - 1
    while i < end:
        if raw[i] == 0x5C and i + 1 < end:
            cur.append(raw[i]); cur.append(raw[i + 1]); i += 2
        elif raw[i] == 0x2F:
            parts.append(bytes(cur)); cur = bytearray(); i += 1
        else:
            cur.append(raw[i]); i += 1
    parts.append(bytes(cur))
    if not parts:
        return None

    def _int(b):
        try:
            return int(b.decode())
        except Exception:
            return None

    t = parts[0]
    if t == b'ack' and len(parts) == 3:
        s, l = _int(parts[1]), _int(parts[2])
        return ('ack', s, l) if s is not None and l is not None else None
    if t == b'data' and len(parts) == 4:
        s, p = _int(parts[1]), _int(parts[2])
        if s is None or p is None:
            return None
        return ('data', s, p, lrcp_unescape(parts[3]))
    if t == b'close' and len(parts) == 2:
        s = _int(parts[1])
        return ('close', s) if s is not None else None
    return None


# ------------------------------------------------------------------ #
#  Socket / communication helpers                                      #
# ------------------------------------------------------------------ #

def make_client():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    return s


def do_connect(sock, sid, timeout=5):
    sock.sendto(f"/connect/{sid}/".encode(), ADDR)
    sock.settimeout(timeout)
    raw = sock.recv(2000)
    p = parse_lrcp(raw)
    assert p is not None, f"Unparseable connect response: {raw!r}"
    assert p == ('ack', sid, 0), f"Expected ack/{sid}/0/, got {raw!r}"


def send_data(sock, sid, pos, payload: bytes):
    esc = lrcp_escape(payload)
    sock.sendto(f"/data/{sid}/{pos}/".encode() + esc + b"/", ADDR)


def drain(sock, sid, timeout=3):
    """Drain messages for *sid*, returning (ack_lengths, data_chunks, close_count)."""
    acks, chunks, closes = [], [], 0
    deadline = time.time() + timeout
    while time.time() < deadline:
        sock.settimeout(max(0.01, deadline - time.time()))
        try:
            raw = sock.recv(2000)
            p = parse_lrcp(raw)
            if p is None or p[1] != sid:
                continue
            if p[0] == 'ack':
                acks.append(p[2])
            elif p[0] == 'data':
                chunks.append((p[2], p[3]))
            elif p[0] == 'close':
                closes += 1
        except socket.timeout:
            break
    return acks, chunks, closes


def reassemble(chunks):
    """Build contiguous byte stream from [(pos, payload), ...]."""
    stream = bytearray()
    for pos, payload in sorted(chunks, key=lambda c: c[0]):
        if pos <= len(stream):
            end = pos + len(payload)
            if end > len(stream):
                stream.extend(payload[len(stream) - pos:])
    return bytes(stream)


def full_exchange(sock, sid, input_bytes: bytes, timeout=10):
    """Send input_bytes, receive reversed output, ack everything.

    Returns the reassembled application-layer output.
    """
    send_data(sock, sid, 0, input_bytes)
    stream = bytearray()
    expected_lines = input_bytes.count(b'\n')
    deadline = time.time() + timeout
    while time.time() < deadline:
        sock.settimeout(max(0.01, deadline - time.time()))
        try:
            raw = sock.recv(2000)
            p = parse_lrcp(raw)
            if p is None or p[1] != sid:
                continue
            if p[0] == 'data':
                pos, payload = p[2], p[3]
                if pos <= len(stream):
                    end = pos + len(payload)
                    if end > len(stream):
                        stream.extend(payload[len(stream) - pos:])
                sock.sendto(f"/ack/{sid}/{len(stream)}/".encode(), ADDR)
                if stream.count(b'\n') >= expected_lines:
                    break
        except socket.timeout:
            break
    return bytes(stream)


# ------------------------------------------------------------------ #
#  Wait for server                                                     #
# ------------------------------------------------------------------ #

@pytest.fixture(scope="session", autouse=True)
def wait_for_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(1)
    for _ in range(30):
        sock.sendto(b"/connect/0/", ADDR)
        try:
            data = sock.recv(1000)
            if data == b"/ack/0/0/":
                sock.sendto(b"/close/0/", ADDR)
                sock.close()
                time.sleep(0.2)
                return
        except socket.timeout:
            pass
        time.sleep(0.5)
    sock.close()
    pytest.fail("Server did not respond within 15 seconds")


# ------------------------------------------------------------------ #
#  Tests                                                               #
# ------------------------------------------------------------------ #

class TestConnectAndClose:
    """Basic session lifecycle."""

    def test_connect_ack(self):
        sock = make_client()
        do_connect(sock, 10)
        sock.sendto(b"/close/10/", ADDR)
        sock.close()

    def test_close_response(self):
        sock = make_client()
        do_connect(sock, 11)
        sock.sendto(b"/close/11/", ADDR)
        sock.settimeout(3)
        raw = sock.recv(2000)
        p = parse_lrcp(raw)
        assert p == ('close', 11), f"Expected /close/11/, got {raw!r}"
        sock.close()

    def test_data_to_unknown_session(self):
        """Data for an unknown session must trigger /close/."""
        sock = make_client()
        send_data(sock, 99999, 0, b"nope\n")
        sock.settimeout(3)
        raw = sock.recv(2000)
        p = parse_lrcp(raw)
        assert p is not None and p[0] == 'close' and p[1] == 99999, \
            f"Expected /close/99999/, got {raw!r}"
        sock.close()


class TestLineReversal:
    """Core reversal functionality."""

    def test_simple_reversal(self):
        sock = make_client()
        do_connect(sock, 100)
        out = full_exchange(sock, 100, b"hello\n")
        assert out == b"olleh\n", f"Expected b'olleh\\n', got {out!r}"
        sock.sendto(b"/close/100/", ADDR)
        sock.close()

    def test_multiple_lines(self):
        sock = make_client()
        do_connect(sock, 101)
        out = full_exchange(sock, 101, b"abc\ndef\nghi\n")
        assert out == b"cba\nfed\nihg\n", f"Got {out!r}"
        sock.sendto(b"/close/101/", ADDR)
        sock.close()

    def test_partial_line_buffered(self):
        """No output should appear until a newline completes the line."""
        sock = make_client()
        do_connect(sock, 102)

        # Send "hello" without newline
        send_data(sock, 102, 0, b"hello")
        acks, chunks, _ = drain(sock, 102, timeout=2)
        assert len(acks) > 0, "Should at least ack the data"
        assert len(chunks) == 0, "No output before newline"

        # Complete the line
        send_data(sock, 102, 5, b"\n")
        stream = bytearray()
        deadline = time.time() + 5
        while time.time() < deadline:
            sock.settimeout(max(0.01, deadline - time.time()))
            try:
                raw = sock.recv(2000)
                p = parse_lrcp(raw)
                if p and p[0] == 'data' and p[1] == 102:
                    pos, payload = p[2], p[3]
                    if pos <= len(stream):
                        end = pos + len(payload)
                        if end > len(stream):
                            stream.extend(payload[len(stream) - pos:])
                    sock.sendto(f"/ack/102/{len(stream)}/".encode(), ADDR)
                    if b'\n' in stream:
                        break
            except socket.timeout:
                break
        assert bytes(stream) == b"olleh\n", f"Got {bytes(stream)!r}"
        sock.sendto(b"/close/102/", ADDR)
        sock.close()


class TestEscapeSequences:
    """Correct handling of \\/ and \\\\ escaping in data fields."""

    def test_forward_slash_in_data(self):
        """Send 'a/b\\n', expect 'b/a\\n' back, both properly escaped."""
        sock = make_client()
        do_connect(sock, 300)
        # "a/b\n" — 4 unescaped bytes
        out = full_exchange(sock, 300, b"a/b\n")
        assert out == b"b/a\n", f"Expected b'b/a\\n', got {out!r}"
        sock.sendto(b"/close/300/", ADDR)
        sock.close()

    def test_backslash_in_data(self):
        """Send 'a\\b\\n', expect 'b\\a\\n' back."""
        sock = make_client()
        do_connect(sock, 301)
        out = full_exchange(sock, 301, b"a\\b\n")
        assert out == b"b\\a\n", f"Expected b'b\\\\a\\n', got {out!r}"
        sock.sendto(b"/close/301/", ADDR)
        sock.close()

    def test_mixed_escapes(self):
        r"""Send 'x/y\z\n', expect 'z\y/x\n'."""
        sock = make_client()
        do_connect(sock, 302)
        out = full_exchange(sock, 302, b"x/y\\z\n")
        assert out == b"z\\y/x\n", f"Got {out!r}"
        sock.sendto(b"/close/302/", ADDR)
        sock.close()


class TestRetransmission:
    """Server must retransmit unacknowledged data within ~3 seconds."""

    def test_retransmit_on_no_ack(self):
        sock = make_client()
        do_connect(sock, 800)

        send_data(sock, 800, 0, b"rt\n")

        # Drain initial burst (ack + data), do NOT ack data
        first_data = None
        deadline = time.time() + 2
        while time.time() < deadline:
            sock.settimeout(max(0.01, deadline - time.time()))
            try:
                raw = sock.recv(2000)
                p = parse_lrcp(raw)
                if p and p[0] == 'data' and p[1] == 800:
                    first_data = p
            except socket.timeout:
                break

        assert first_data is not None, "Server must send reversed data"

        # Wait for retransmission (~3 s timeout)
        retransmitted = None
        sock.settimeout(5)
        try:
            while True:
                raw = sock.recv(2000)
                p = parse_lrcp(raw)
                if p and p[0] == 'data' and p[1] == 800:
                    retransmitted = p
                    break
        except socket.timeout:
            pass

        assert retransmitted is not None, \
            "Server must retransmit unacked data within ~3 s"
        assert retransmitted[3] == first_data[3], \
            "Retransmitted payload should match original"

        # Clean up
        sock.sendto(f"/ack/800/{len(retransmitted[3])}/".encode(), ADDR)
        sock.sendto(b"/close/800/", ADDR)
        sock.close()


class TestConcurrentSessions:
    """Server must handle >= 20 sessions simultaneously."""

    def test_twenty_five_sessions(self):
        N = 25
        socks = []
        for i in range(N):
            s = make_client()
            do_connect(s, 700 + i)
            socks.append(s)

        # Send a unique line to each session
        for i, s in enumerate(socks):
            line = f"sess{700+i}\n".encode()
            send_data(s, 700 + i, 0, line)

        # Collect reversed lines
        for i, s in enumerate(socks):
            sid = 700 + i
            original = f"sess{sid}"
            expected = original[::-1] + "\n"
            stream = bytearray()
            deadline = time.time() + 10
            while time.time() < deadline:
                s.settimeout(max(0.01, deadline - time.time()))
                try:
                    raw = s.recv(2000)
                    p = parse_lrcp(raw)
                    if p and p[0] == 'data' and p[1] == sid:
                        pos, payload = p[2], p[3]
                        if pos <= len(stream):
                            end = pos + len(payload)
                            if end > len(stream):
                                stream.extend(payload[len(stream) - pos:])
                        s.sendto(f"/ack/{sid}/{len(stream)}/".encode(), ADDR)
                        if b'\n' in stream:
                            break
                except socket.timeout:
                    break
            assert stream.decode('ascii') == expected, \
                f"Session {sid}: expected {expected!r}, got {stream!r}"

        for i, s in enumerate(socks):
            s.sendto(f"/close/{700+i}/".encode(), ADDR)
            s.close()


class TestLargePayload:
    """Responses exceeding 1000 bytes must be chunked correctly."""

    def test_long_line_chunked(self):
        sock = make_client()
        do_connect(sock, 900)

        # 2000-char line of varied characters
        chars = ''.join(chr(65 + (i % 26)) for i in range(2000))
        line = (chars + '\n').encode()

        # Client must also chunk its send
        pos = 0
        chunk_sz = 400
        while pos < len(line):
            chunk = line[pos:pos + chunk_sz]
            send_data(sock, 900, pos, chunk)
            pos += len(chunk)
            time.sleep(0.02)

        expected = (chars[::-1] + '\n').encode()
        stream = bytearray()
        deadline = time.time() + 15
        while time.time() < deadline and len(stream) < len(expected):
            sock.settimeout(max(0.01, deadline - time.time()))
            try:
                raw = sock.recv(2000)
                p = parse_lrcp(raw)
                if p is None or p[1] != 900:
                    continue
                if p[0] == 'data':
                    rpos, payload = p[2], p[3]
                    if rpos <= len(stream):
                        end = rpos + len(payload)
                        if end > len(stream):
                            stream.extend(payload[len(stream) - rpos:])
                    sock.sendto(f"/ack/900/{len(stream)}/".encode(), ADDR)
            except socket.timeout:
                break

        assert bytes(stream) == expected, \
            f"Got {len(stream)} bytes, expected {len(expected)}"
        sock.sendto(b"/close/900/", ADDR)
        sock.close()


class TestInvalidPackets:
    """Illegal packets must be silently ignored."""

    def test_server_survives_garbage(self):
        sock = make_client()

        # Establish a working session first
        do_connect(sock, 1100)

        # Send various invalid packets
        for garbage in [
            b"no leading slash",
            b"/unknown/123/",
            b"/data/abc/0/test/",       # non-numeric session
            b"/data/1100/",             # wrong field count
            b"/connect/2147483648/",    # session too large
            b"/" * 1001,               # message too long
            b"",                        # empty
            b"/data/1100/0/",           # missing data field (3 parts)
        ]:
            sock.sendto(garbage, ADDR)

        time.sleep(0.5)

        # Server should still work
        send_data(sock, 1100, 0, b"ok\n")
        acks, chunks, _ = drain(sock, 1100, timeout=5)
        assert len(chunks) > 0, \
            "Server should still function after receiving invalid packets"
        out = reassemble(chunks)
        assert out == b"ko\n", f"Expected b'ko\\n', got {out!r}"

        sock.sendto(f"/ack/1100/{len(out)}/".encode(), ADDR)
        sock.sendto(b"/close/1100/", ADDR)
        sock.close()


class TestAckBehavior:
    """Ack edge cases from the spec."""

    def test_ack_for_excess_length_closes_session(self):
        """Ack claiming more bytes than sent → close the session."""
        sock = make_client()
        do_connect(sock, 1200)

        # We haven't sent any data to the server; ack for 999 bytes is bogus
        sock.sendto(b"/ack/1200/999/", ADDR)

        # The server should close the session.
        # Subsequent data should get /close/ back.
        time.sleep(0.5)
        send_data(sock, 1200, 0, b"test\n")
        sock.settimeout(3)
        try:
            raw = sock.recv(2000)
            p = parse_lrcp(raw)
            assert p is not None and p[0] == 'close' and p[1] == 1200, \
                f"Expected /close/1200/ after excess ack, got {raw!r}"
        except socket.timeout:
            pytest.fail("No response after excess ack — session should be closed")
        finally:
            sock.close()

    def test_duplicate_connect_reacks(self):
        """Duplicate /connect/ must re-send /ack/SESSION/0/."""
        sock = make_client()
        do_connect(sock, 1300)

        # Send connect again
        sock.sendto(b"/connect/1300/", ADDR)
        sock.settimeout(3)
        raw = sock.recv(2000)
        p = parse_lrcp(raw)
        assert p == ('ack', 1300, 0), \
            f"Duplicate connect should re-ack with 0, got {raw!r}"

        sock.sendto(b"/close/1300/", ADDR)
        sock.close()
