#!/usr/bin/env python3
"""Pest Control Server — reference solution.

Dual-role TCP system:
  - Inbound: accepts SiteVisit clients on port 9000 (binary protocol)
  - Outbound: connects to Authority Server at localhost:20547 to manage policies
"""

import asyncio
import struct

PORT = 9000
AUTH_HOST = '127.0.0.1'
AUTH_PORT = 20547

# ========== Binary protocol ==========

def _u8(v):
    return struct.pack('>B', v)

def _u32(v):
    return struct.pack('>I', v)

def _bstr(s):
    b = s.encode('ascii')
    return _u32(len(b)) + b

def _cksum(data):
    return (256 - sum(data) % 256) % 256

def _frame(mt, payload):
    ln = 1 + 4 + len(payload) + 1
    raw = _u8(mt) + _u32(ln) + payload
    return raw + _u8(_cksum(raw))

def _mk_hello():
    return _frame(0x50, _bstr("pestcontrol") + _u32(1))

def _mk_error(msg):
    return _frame(0x51, _bstr(msg))

def _mk_dial(site):
    return _frame(0x53, _u32(site))

def _mk_create(species, action_byte):
    return _frame(0x55, _bstr(species) + _u8(action_byte))

def _mk_delete(pid):
    return _frame(0x56, _u32(pid))

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
        raise ValueError("message too short")
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

# ========== State ==========

# Cached target populations per site: {site_id: [{species, min, max}]}
_targets_cache = {}

# Current policies per site: {site_id: {species: (policy_id, action_str)}}
_site_policies = {}

# Per-site locks to serialize policy reconciliation
_site_locks = {}

# Cached authority connections: {site_id: (reader, writer)}
_auth_conns = {}

# ========== Authority connection ==========

async def _get_auth(site_id):
    """Get or create an authority connection for a site."""
    if site_id in _auth_conns:
        r, w = _auth_conns[site_id]
        if not w.is_closing():
            return r, w
        del _auth_conns[site_id]

    r, w = await asyncio.open_connection(AUTH_HOST, AUTH_PORT)

    # Hello handshake (we are the client, so we send first)
    w.write(_mk_hello())
    await w.drain()
    mt, _ = await _recv_msg(r)
    if mt != 0x50:
        raise ValueError("authority did not Hello")

    # DialAuthority
    w.write(_mk_dial(site_id))
    await w.drain()
    mt, payload = await _recv_msg(r)
    if mt != 0x54:
        raise ValueError("authority did not send TargetPopulations")

    # Parse TargetPopulations
    _, off = _pu32(payload, 0)     # site
    count, off = _pu32(payload, off)
    pops = []
    for _ in range(count):
        sp, off = _pstr(payload, off)
        mn, off = _pu32(payload, off)
        mx, off = _pu32(payload, off)
        pops.append({"species": sp, "min": mn, "max": mx})

    _targets_cache[site_id] = pops
    _auth_conns[site_id] = (r, w)
    return r, w

# ========== Policy reconciliation ==========

async def _reconcile(site_id, observed):
    """Reconcile policies for a site after a SiteVisit."""
    if site_id not in _site_locks:
        _site_locks[site_id] = asyncio.Lock()

    async with _site_locks[site_id]:
        # Get authority connection (may create new one)
        try:
            r, w = await _get_auth(site_id)
        except Exception:
            _auth_conns.pop(site_id, None)
            r, w = await _get_auth(site_id)

        targets = _targets_cache.get(site_id, [])

        # Build observed-count map
        obs = {sp: cnt for sp, cnt in observed}

        # Determine desired policy per species
        desired = {}
        for t in targets:
            sp = t["species"]
            c = obs.get(sp, 0)
            if c < t["min"]:
                desired[sp] = "conserve"
            elif c > t["max"]:
                desired[sp] = "cull"
            else:
                desired[sp] = None   # in range

        current = _site_policies.get(site_id, {})

        # Phase 1: delete stale or wrong-action policies
        to_del = []
        for sp, (pid, act) in list(current.items()):
            d = desired.get(sp)
            if d is None or d != act:
                to_del.append((sp, pid))
        for sp, pid in to_del:
            w.write(_mk_delete(pid))
            await w.drain()
            mt, _ = await _recv_msg(r)
            if mt != 0x52:
                raise ValueError(f"DeletePolicy: expected OK, got 0x{mt:02x}")
            del current[sp]

        # Phase 2: create needed policies
        for sp, act in desired.items():
            if act is not None and sp not in current:
                ab = 0x90 if act == "cull" else 0xa0
                w.write(_mk_create(sp, ab))
                await w.drain()
                mt, payload = await _recv_msg(r)
                if mt != 0x57:
                    raise ValueError(f"CreatePolicy: expected PolicyResult, got 0x{mt:02x}")
                pid, _ = _pu32(payload, 0)
                current[sp] = (pid, act)

        _site_policies[site_id] = current

# ========== Client handler ==========

async def _handle_client(reader, writer):
    try:
        # Expect Hello from client
        mt, payload = await _recv_msg(reader)
        if mt != 0x50:
            writer.write(_mk_error("expected Hello"))
            await writer.drain()
            return
        proto, off = _pstr(payload, 0)
        ver, off = _pu32(payload, off)
        if proto != "pestcontrol" or ver != 1:
            writer.write(_mk_error("bad Hello"))
            await writer.drain()
            return

        # Send Hello back
        writer.write(_mk_hello())
        await writer.drain()

        # Message loop
        while True:
            mt, payload = await _recv_msg(reader)
            if mt == 0x58:   # SiteVisit
                site, off = _pu32(payload, 0)
                npops, off = _pu32(payload, off)
                pops = []
                for _ in range(npops):
                    sp, off = _pstr(payload, off)
                    cnt, off = _pu32(payload, off)
                    pops.append((sp, cnt))

                # Check for conflicting duplicates
                seen = {}
                conflict = False
                for sp, cnt in pops:
                    if sp in seen and seen[sp] != cnt:
                        conflict = True
                        break
                    seen[sp] = cnt

                if conflict:
                    writer.write(_mk_error("conflicting species counts"))
                    await writer.drain()
                    return

                deduped = list(seen.items())
                await _reconcile(site, deduped)
            else:
                writer.write(_mk_error("unexpected message type"))
                await writer.drain()
                return

    except (ConnectionError, asyncio.IncompleteReadError):
        pass
    except Exception as e:
        try:
            writer.write(_mk_error(str(e)[:200]))
            await writer.drain()
        except Exception:
            pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass

# ========== Main ==========

async def main():
    server = await asyncio.start_server(_handle_client, '0.0.0.0', PORT)
    async with server:
        await server.serve_forever()

if __name__ == '__main__':
    asyncio.run(main())
