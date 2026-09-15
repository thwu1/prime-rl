#!/usr/bin/env python3
"""Mock Authority Server for Pest Control protocol testing.

Binary protocol server on TCP port 20547.
HTTP status/reset API on TCP port 20548.
"""

import asyncio
import json
import struct
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

BINARY_PORT = 20547
HTTP_PORT = 20548

# --------------- binary helpers ---------------

def _u8(v):
    return struct.pack('>B', v)

def _u32(v):
    return struct.pack('>I', v)

def _str(s):
    b = s.encode('ascii')
    return _u32(len(b)) + b

def _cksum(data):
    return (256 - sum(data) % 256) % 256

def _frame(mt, payload):
    ln = 1 + 4 + len(payload) + 1
    raw = _u8(mt) + _u32(ln) + payload
    return raw + _u8(_cksum(raw))

def _hello():
    return _frame(0x50, _str("pestcontrol") + _u32(1))

def _error(msg):
    return _frame(0x51, _str(msg))

def _ok():
    return _frame(0x52, b'')

def _target_pops(site, pops):
    body = _u32(site) + _u32(len(pops))
    for p in pops:
        body += _str(p["species"]) + _u32(p["min"]) + _u32(p["max"])
    return _frame(0x54, body)

def _policy_result(pid):
    return _frame(0x57, _u32(pid))

async def _recv_exact(reader, n):
    buf = b''
    while len(buf) < n:
        chunk = await reader.read(n - len(buf))
        if not chunk:
            raise ConnectionError("closed")
        buf += chunk
    return buf

async def _recv_msg(reader):
    t = await _recv_exact(reader, 1)
    lb = await _recv_exact(reader, 4)
    total = struct.unpack('>I', lb)[0]
    if total < 6:
        raise ValueError("msg too short")
    rest = await _recv_exact(reader, total - 5)
    full = t + lb + rest
    if sum(full) % 256 != 0:
        raise ValueError("bad checksum")
    return t[0], rest[:-1]

def _pu32(data, off):
    return struct.unpack('>I', data[off:off+4])[0], off + 4

def _pstr(data, off):
    n, off = _pu32(data, off)
    return data[off:off+n].decode('ascii'), off + n

def _pu8(data, off):
    return data[off], off + 1

# --------------- policy store ---------------

class PolicyStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._policies = {}   # {site: {pid: {"species": s, "action": a}}}
        self._counters = {}   # {site: next_pid}

    def reset(self):
        with self._lock:
            self._policies.clear()
            self._counters.clear()

    def create(self, site, species, action):
        with self._lock:
            self._policies.setdefault(site, {})
            self._counters.setdefault(site, 1)
            pid = self._counters[site]
            self._counters[site] += 1
            self._policies[site][pid] = {"species": species, "action": action}
            return pid

    def delete(self, site, pid):
        with self._lock:
            if site in self._policies and pid in self._policies[site]:
                del self._policies[site][pid]
                return True
            return False

    def dump(self, site=None):
        with self._lock:
            if site is not None:
                ps = self._policies.get(site, {})
                return [{"id": k, "species": v["species"], "action": v["action"]}
                        for k, v in sorted(ps.items())]
            result = {}
            for s, ps in self._policies.items():
                result[str(s)] = [
                    {"id": k, "species": v["species"], "action": v["action"]}
                    for k, v in sorted(ps.items())
                ]
            return result

store = PolicyStore()

# --------------- load config ---------------

def _load_targets():
    p = Path(__file__).parent / "site_config.json"
    with open(p) as f:
        raw = json.load(f)
    return {int(k): v for k, v in raw.items()}

TARGETS = {}

# --------------- binary protocol handler ---------------

async def _handle_conn(reader, writer):
    site = None
    try:
        # expect Hello from client
        mt, payload = await _recv_msg(reader)
        if mt != 0x50:
            writer.write(_error("expected Hello"))
            await writer.drain()
            return
        proto, off = _pstr(payload, 0)
        ver, off = _pu32(payload, off)
        if proto != "pestcontrol" or ver != 1:
            writer.write(_error("bad Hello values"))
            await writer.drain()
            return

        # send Hello back
        writer.write(_hello())
        await writer.drain()

        # expect DialAuthority
        mt, payload = await _recv_msg(reader)
        if mt != 0x53:
            writer.write(_error("expected DialAuthority"))
            await writer.drain()
            return
        site, _ = _pu32(payload, 0)

        # send TargetPopulations
        pops = TARGETS.get(site, [])
        writer.write(_target_pops(site, pops))
        await writer.drain()

        # handle CreatePolicy / DeletePolicy loop
        while True:
            mt, payload = await _recv_msg(reader)
            if mt == 0x55:  # CreatePolicy
                sp, off = _pstr(payload, 0)
                ab, off = _pu8(payload, off)
                if ab == 0x90:
                    act = "cull"
                elif ab == 0xa0:
                    act = "conserve"
                else:
                    writer.write(_error("bad action byte"))
                    await writer.drain()
                    return
                pid = store.create(site, sp, act)
                writer.write(_policy_result(pid))
                await writer.drain()
            elif mt == 0x56:  # DeletePolicy
                pid, _ = _pu32(payload, 0)
                if store.delete(site, pid):
                    writer.write(_ok())
                    await writer.drain()
                else:
                    writer.write(_error("no such policy"))
                    await writer.drain()
                    return
            else:
                writer.write(_error("unexpected message type"))
                await writer.drain()
                return
    except (ConnectionError, asyncio.IncompleteReadError):
        pass
    except Exception as e:
        try:
            writer.write(_error(str(e)[:200]))
            await writer.drain()
        except Exception:
            pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass

# --------------- HTTP API ---------------

class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_a):
        pass

    def do_GET(self):
        if self.path == '/policies':
            self._json(200, store.dump())
        elif self.path.startswith('/policies/'):
            try:
                sid = int(self.path.rsplit('/', 1)[1])
            except ValueError:
                self.send_response(400)
                self.end_headers()
                return
            self._json(200, store.dump(sid))
        elif self.path == '/targets':
            self._json(200, {str(k): v for k, v in TARGETS.items()})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == '/reset':
            store.reset()
            self.send_response(200)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

def _run_http():
    HTTPServer(('0.0.0.0', HTTP_PORT), _Handler).serve_forever()

# --------------- main ---------------

async def _amain():
    srv = await asyncio.start_server(_handle_conn, '0.0.0.0', BINARY_PORT)
    print(f"Authority binary server on :{BINARY_PORT}", flush=True)
    async with srv:
        await srv.serve_forever()

def main():
    global TARGETS
    TARGETS = _load_targets()
    print(f"Loaded targets for sites: {sorted(TARGETS.keys())}", flush=True)
    t = threading.Thread(target=_run_http, daemon=True)
    t.start()
    print(f"Authority HTTP API on :{HTTP_PORT}", flush=True)
    asyncio.run(_amain())

if __name__ == '__main__':
    main()
