#!/usr/bin/env python3
"""
LRCP Line Reversal Server — Reference Implementation

"""

import asyncio
import sys

PORT = 9000
RETRANSMIT_SEC = 3.0
EXPIRY_SEC = 60.0
MAX_MSG = 999  # must be < 1000 bytes


# ---------------------------------------------------------------------------
# Escape / unescape helpers
# ---------------------------------------------------------------------------

def lrcp_escape(data: bytes) -> bytes:
    """Escape \\ and / for LRCP data fields."""
    out = bytearray()
    for b in data:
        if b == 0x5C:          # backslash
            out.extend(b'\\\\')
        elif b == 0x2F:        # forward slash
            out.extend(b'\\/')
        else:
            out.append(b)
    return bytes(out)


def lrcp_unescape(data: bytes) -> bytes:
    """Reverse LRCP escaping."""
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


# ---------------------------------------------------------------------------
# Message parser
# ---------------------------------------------------------------------------

def _parse_int(raw: bytes):
    """Non-negative int < 2^31 from ASCII, or None."""
    try:
        v = int(raw.decode('ascii'))
    except (ValueError, UnicodeDecodeError):
        return None
    if v < 0 or v >= 2147483648:
        return None
    return v


def parse_msg(raw: bytes):
    """Return (type, ...) tuple or None for invalid messages."""
    if len(raw) >= 1000 or len(raw) < 3:
        return None
    if raw[0] != 0x2F or raw[-1] != 0x2F:
        return None

    parts: list[bytes] = []
    cur = bytearray()
    i = 1
    end = len(raw) - 1
    while i < end:
        if raw[i] == 0x5C and i + 1 < end:
            cur.append(raw[i])
            cur.append(raw[i + 1])
            i += 2
        elif raw[i] == 0x2F:
            parts.append(bytes(cur))
            cur = bytearray()
            i += 1
        else:
            cur.append(raw[i])
            i += 1
    parts.append(bytes(cur))

    if not parts:
        return None

    t = parts[0]
    if t == b'connect' and len(parts) == 2:
        sid = _parse_int(parts[1])
        return ('connect', sid) if sid is not None else None

    if t == b'data' and len(parts) == 4:
        sid = _parse_int(parts[1])
        pos = _parse_int(parts[2])
        if sid is None or pos is None:
            return None
        return ('data', sid, pos, lrcp_unescape(parts[3]))

    if t == b'ack' and len(parts) == 3:
        sid = _parse_int(parts[1])
        length = _parse_int(parts[2])
        if sid is None or length is None:
            return None
        return ('ack', sid, length)

    if t == b'close' and len(parts) == 2:
        sid = _parse_int(parts[1])
        return ('close', sid) if sid is not None else None

    return None


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

class Session:
    def __init__(self, sid: int, addr: tuple, transport):
        self.sid = sid
        self.addr = addr
        self.transport = transport
        self.recv_total = 0          # contiguous bytes received
        self.send_buf = bytearray()  # application data to send
        self.acked = 0               # bytes peer has acked
        self.highest_ack = -1        # largest ack LENGTH received
        self.line_buf = ''           # partial line accumulator
        self.closed = False
        self.last_active = asyncio.get_event_loop().time()
        self._rt_handle = None       # retransmit timer handle

    def touch(self):
        self.last_active = asyncio.get_event_loop().time()

    # -- inbound handlers ---------------------------------------------------

    def on_connect(self):
        self.touch()
        self._raw_send(f'/ack/{self.sid}/0/')

    def on_data(self, pos: int, payload: bytes):
        self.touch()
        if pos > self.recv_total:
            # gap — ack what we have to provoke retransmission
            self._raw_send(f'/ack/{self.sid}/{self.recv_total}/')
            return

        new_start = self.recv_total - pos
        if new_start < len(payload):
            new_bytes = payload[new_start:]
            self.recv_total += len(new_bytes)
            self.line_buf += new_bytes.decode('ascii', errors='replace')
            while '\n' in self.line_buf:
                line, self.line_buf = self.line_buf.split('\n', 1)
                self.send_buf.extend((line[::-1] + '\n').encode('ascii'))

        self._raw_send(f'/ack/{self.sid}/{self.recv_total}/')
        self._flush()

    def on_ack(self, length: int):
        self.touch()
        if length <= self.highest_ack:
            return                              # stale / duplicate
        if length > len(self.send_buf):
            self._do_close()                    # misbehaving peer
            return
        self.highest_ack = length
        self.acked = length
        if length < len(self.send_buf):
            self._flush()                       # partial ack → retransmit
        else:
            self._cancel_rt()                   # fully acked

    def on_close(self):
        self._raw_send(f'/close/{self.sid}/')
        self._do_close()

    # -- outbound helpers ---------------------------------------------------

    def _raw_send(self, msg: str):
        self.transport.sendto(msg.encode('ascii'), self.addr)

    def _flush(self):
        if self.closed or self.acked >= len(self.send_buf):
            return
        self._send_chunks(self.acked)
        self._schedule_rt()

    def _send_chunks(self, start: int):
        """Send all unsent data from *start*, respecting the size limit."""
        data = bytes(self.send_buf[start:])
        pos = start
        off = 0
        while off < len(data):
            hdr = f'/data/{self.sid}/{pos}/'.encode()
            avail = MAX_MSG - len(hdr) - 1          # room for escaped data
            # binary-search the largest unescaped chunk that fits
            lo, hi, best = 1, min(len(data) - off, avail), 0
            while lo <= hi:
                mid = (lo + hi) // 2
                if len(lrcp_escape(data[off:off + mid])) <= avail:
                    best = mid
                    lo = mid + 1
                else:
                    hi = mid - 1
            if best == 0:
                best = 1          # always send at least one byte
            esc = lrcp_escape(data[off:off + best])
            self.transport.sendto(hdr + esc + b'/', self.addr)
            pos += best
            off += best

    # -- retransmission timer -----------------------------------------------

    def _schedule_rt(self):
        self._cancel_rt()
        if not self.closed:
            self._rt_handle = asyncio.get_event_loop().call_later(
                RETRANSMIT_SEC, self._on_rt)

    def _on_rt(self):
        if not self.closed and self.acked < len(self.send_buf):
            self._send_chunks(self.acked)
            self._schedule_rt()

    def _cancel_rt(self):
        if self._rt_handle is not None:
            self._rt_handle.cancel()
            self._rt_handle = None

    def _do_close(self):
        self.closed = True
        self._cancel_rt()


# ---------------------------------------------------------------------------
# Protocol / server
# ---------------------------------------------------------------------------

class LRCPProtocol(asyncio.DatagramProtocol):
    def __init__(self):
        self.sessions: dict[int, Session] = {}
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport
        asyncio.ensure_future(self._expiry_loop())

    async def _expiry_loop(self):
        while True:
            await asyncio.sleep(5)
            now = asyncio.get_event_loop().time()
            expired = [sid for sid, s in self.sessions.items()
                       if s.closed or now - s.last_active > EXPIRY_SEC]
            for sid in expired:
                s = self.sessions.pop(sid)
                s._cancel_rt()

    def datagram_received(self, data: bytes, addr: tuple):
        msg = parse_msg(data)
        if msg is None:
            return                     # silently ignore illegal packets

        kind, sid = msg[0], msg[1]

        if kind == 'connect':
            if sid not in self.sessions:
                self.sessions[sid] = Session(sid, addr, self.transport)
            self.sessions[sid].on_connect()

        elif kind == 'data':
            s = self.sessions.get(sid)
            if s is None or s.closed:
                self.transport.sendto(f'/close/{sid}/'.encode(), addr)
                return
            s.on_data(msg[2], msg[3])

        elif kind == 'ack':
            s = self.sessions.get(sid)
            if s is None or s.closed:
                self.transport.sendto(f'/close/{sid}/'.encode(), addr)
                return
            s.on_ack(msg[2])

        elif kind == 'close':
            s = self.sessions.get(sid)
            if s is not None:
                s.on_close()
            else:
                self.transport.sendto(f'/close/{sid}/'.encode(), addr)


async def main():
    loop = asyncio.get_event_loop()
    transport, _ = await loop.create_datagram_endpoint(
        LRCPProtocol, local_addr=('0.0.0.0', PORT))
    print(f'LRCP server listening on UDP port {PORT}', flush=True)
    await asyncio.Event().wait()


if __name__ == '__main__':
    asyncio.run(main())
