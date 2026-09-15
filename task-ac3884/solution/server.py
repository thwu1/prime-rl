#!/usr/bin/env python3
"""
DNS Zone Snapshot with HMAC-Verified Piece Distribution

"""

import hashlib
import hmac as hmac_mod
import ipaddress
import json
import socket
import struct
import threading
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse

# Task DNA
HMAC_KEY = bytes.fromhex("a3f7c9e1d2b4685f")
PIECE_LENGTH = 384

# ============================================================
# Bencoding (from scratch)
# ============================================================

def bencode(obj):
    if isinstance(obj, int):
        return b'i' + str(obj).encode() + b'e'
    elif isinstance(obj, bytes):
        return str(len(obj)).encode() + b':' + obj
    elif isinstance(obj, str):
        encoded = obj.encode('utf-8')
        return str(len(encoded)).encode() + b':' + encoded
    elif isinstance(obj, list):
        return b'l' + b''.join(bencode(i) for i in obj) + b'e'
    elif isinstance(obj, dict):
        items = sorted(obj.items(), key=lambda x: x[0] if isinstance(x[0], bytes) else x[0].encode())
        result = b'd'
        for k, v in items:
            result += bencode(k if isinstance(k, bytes) else k.encode()) + bencode(v)
        result += b'e'
        return result
    raise ValueError(f"Cannot bencode {type(obj)}")


def bdecode(data):
    def _next(data, i):
        c = data[i:i+1]
        if c == b'i':
            end = data.index(b'e', i+1)
            return int(data[i+1:end]), end+1
        elif c == b'l':
            result, i = [], i+1
            while data[i:i+1] != b'e':
                val, i = _next(data, i)
                result.append(val)
            return result, i+1
        elif c == b'd':
            result, i = {}, i+1
            while data[i:i+1] != b'e':
                k, i = _next(data, i)
                v, i = _next(data, i)
                result[k] = v
            return result, i+1
        else:
            colon = data.index(b':', i)
            length = int(data[i:colon])
            s = colon + 1
            return data[s:s+length], s+length
    return _next(data, 0)[0]


# ============================================================
# DNS wire format constants
# ============================================================

RTYPE_MAP = {'A': 1, 'NS': 2, 'CNAME': 5, 'SOA': 6, 'MX': 15, 'TXT': 16, 'AAAA': 28}
RTYPE_REV = {v: k for k, v in RTYPE_MAP.items()}


# ============================================================
# DNS wire format encoding / decoding
# ============================================================

def encode_dns_name(name, comp_tbl=None, offset=0):
    """Encode a domain name with optional label compression."""
    if name.endswith('.'):
        name = name[:-1]
    labels = name.lower().split('.')
    if not labels or labels == ['']:
        return b'\x00'

    if comp_tbl is not None:
        for i in range(len(labels)):
            suffix = '.'.join(labels[i:])
            if suffix in comp_tbl:
                result = b''
                cur = offset
                for j in range(i):
                    sfx_j = '.'.join(labels[j:])
                    if sfx_j not in comp_tbl:
                        comp_tbl[sfx_j] = cur
                    enc = labels[j].encode('ascii')
                    result += struct.pack('B', len(enc)) + enc
                    cur += 1 + len(enc)
                result += struct.pack('>H', 0xC000 | comp_tbl[suffix])
                return result

        result = b''
        cur = offset
        for j, lbl in enumerate(labels):
            sfx = '.'.join(labels[j:])
            if sfx not in comp_tbl:
                comp_tbl[sfx] = cur
            enc = lbl.encode('ascii')
            result += struct.pack('B', len(enc)) + enc
            cur += 1 + len(enc)
        result += b'\x00'
        return result

    result = b''
    for lbl in labels:
        enc = lbl.encode('ascii')
        result += struct.pack('B', len(enc)) + enc
    result += b'\x00'
    return result


def parse_dns_name(data, offset):
    """Parse a DNS name from wire format, handling compression pointers."""
    labels = []
    end_offset = None
    jumped = False
    seen = set()

    while True:
        if offset in seen:
            raise ValueError("Compression loop")
        seen.add(offset)
        if offset >= len(data):
            break
        b = data[offset]
        if b == 0:
            if not jumped:
                end_offset = offset + 1
            break
        if (b & 0xC0) == 0xC0:
            if not jumped:
                end_offset = offset + 2
            ptr = struct.unpack('>H', data[offset:offset+2])[0] & 0x3FFF
            offset = ptr
            jumped = True
            continue
        offset += 1
        labels.append(data[offset:offset+b].decode('ascii'))
        offset += b

    return '.'.join(labels), end_offset if end_offset else offset + 1


def encode_rdata(rtype, rdata_str, comp_tbl=None, offset=0):
    """Encode RDATA based on record type."""
    tname = RTYPE_REV.get(rtype, '')

    if tname == 'A':
        parts = rdata_str.split('.')
        return struct.pack('4B', *(int(p) for p in parts))

    if tname == 'AAAA':
        return ipaddress.IPv6Address(rdata_str).packed

    if tname in ('NS', 'CNAME'):
        return encode_dns_name(rdata_str, comp_tbl, offset)

    if tname == 'MX':
        parts = rdata_str.split(None, 1)
        prio = int(parts[0])
        exchange = parts[1]
        result = struct.pack('>H', prio)
        result += encode_dns_name(exchange, comp_tbl, offset + 2)
        return result

    if tname == 'TXT':
        raw = rdata_str.encode('utf-8')
        result = b''
        for i in range(0, len(raw), 255):
            chunk = raw[i:i+255]
            result += struct.pack('B', len(chunk)) + chunk
        return result

    if tname == 'SOA':
        parts = rdata_str.split()
        result = encode_dns_name(parts[0], comp_tbl, offset)
        result += encode_dns_name(parts[1], comp_tbl, offset + len(result))
        result += struct.pack('>5I', *(int(p) for p in parts[2:7]))
        return result

    return rdata_str.encode('utf-8')


# ============================================================
# Snapshot serialization — sorted by (type_code, name, rdata)
# ============================================================

def serialize_zone_records(records):
    """Serialize records into DNS wire format, sorted by (type_code, name, rdata),
    with label compression on name fields only (not RDATA)."""
    sorted_recs = sorted(
        records,
        key=lambda r: (RTYPE_MAP.get(r['type'].upper(), 0), r['name'].lower(), r['rdata']),
    )
    result = b''
    comp_tbl = {}
    offset = 0

    for rec in sorted_recs:
        rtype = RTYPE_MAP.get(rec['type'].upper(), 0)
        if rtype == 0:
            continue

        name_bytes = encode_dns_name(rec['name'], comp_tbl, offset)
        offset += len(name_bytes)

        # RDATA without compression for snapshot determinism
        rdata = encode_rdata(rtype, rec['rdata'])

        hdr = struct.pack('>HHIH', rtype, 1, rec.get('ttl', 300), len(rdata))
        offset += 10 + len(rdata)
        result += name_bytes + hdr + rdata

    return result


# ============================================================
# DNS response builder (for authoritative server)
# ============================================================

def build_dns_response(query_data, zone_records):
    """Build a DNS response for a query."""
    if len(query_data) < 12:
        return None
    qid = struct.unpack('>H', query_data[:2])[0]
    qname, qname_end = parse_dns_name(query_data, 12)
    if qname_end + 4 > len(query_data):
        return None
    qtype, qclass = struct.unpack('>HH', query_data[qname_end:qname_end+4])

    matching = [
        r for r in zone_records
        if r['name'].lower().rstrip('.') == qname.lower().rstrip('.')
        and RTYPE_MAP.get(r['type'].upper(), 0) == qtype
    ]

    name_exists = any(
        r['name'].lower().rstrip('.') == qname.lower().rstrip('.')
        for r in zone_records
    )
    if not matching and not name_exists:
        flags = 0x8403  # QR+AA+NXDOMAIN
    else:
        flags = 0x8400  # QR+AA+NOERROR

    header = struct.pack('>HHHHHH', qid, flags, 1, len(matching), 0, 0)
    question = query_data[12:qname_end+4]

    # Build compression table from question
    comp_tbl = {}
    q_labels = qname.lower().rstrip('.').split('.')
    cur = 12
    for i in range(len(q_labels)):
        sfx = '.'.join(q_labels[i:])
        if sfx and sfx not in comp_tbl:
            comp_tbl[sfx] = cur
        cur += 1 + len(q_labels[i])

    answers = b''
    ans_offset = 12 + len(question)

    for rec in matching:
        rtype_num = RTYPE_MAP[rec['type'].upper()]
        nb = encode_dns_name(rec['name'], comp_tbl, ans_offset)
        ans_offset += len(nb)
        rd = encode_rdata(rtype_num, rec['rdata'], comp_tbl, ans_offset + 10)
        rhdr = struct.pack('>HHIH', rtype_num, 1, rec.get('ttl', 300), len(rd))
        ans_offset += 10 + len(rd)
        answers += nb + rhdr + rd

    return header + question + answers


# ============================================================
# Zone store (thread-safe)
# ============================================================

class ZoneStore:
    def __init__(self):
        self.zones = {}
        self.lock = threading.Lock()

    def create(self, name, records):
        zid = uuid.uuid4().hex[:8]
        with self.lock:
            self.zones[zid] = {
                'name': name,
                'records': records,
                'snapshot': None,
                'manifest': None,
                'pieces': [],
            }
        return zid

    def get(self, zid):
        with self.lock:
            return self.zones.get(zid)

    def snapshot(self, zid):
        with self.lock:
            z = self.zones.get(zid)
            if not z:
                return None
            serialized = serialize_zone_records(z['records'])
            pieces = []
            piece_hashes = b''
            for i in range(0, max(len(serialized), 1), PIECE_LENGTH):
                pc = serialized[i:i+PIECE_LENGTH]
                if not pc:
                    break
                pieces.append(pc)
                piece_hashes += hmac_mod.new(HMAC_KEY, pc, hashlib.sha1).digest()

            manifest = bencode({
                b'algorithm': b'hmac-sha1',
                b'fingerprint': HMAC_KEY,
                b'piece length': PIECE_LENGTH,
                b'pieces': piece_hashes,
                b'record count': len(z['records']),
                b'total length': len(serialized),
                b'zone': z['name'].encode(),
            })
            z['snapshot'] = serialized
            z['manifest'] = manifest
            z['pieces'] = pieces
            return manifest

    def get_piece(self, zid, n):
        with self.lock:
            z = self.zones.get(zid)
            if not z or not z['pieces']:
                return None
            if 0 <= n < len(z['pieces']):
                return z['pieces'][n]
            return None

    def verify(self, zid):
        with self.lock:
            z = self.zones.get(zid)
            if not z or not z['manifest']:
                return None
            m = bdecode(z['manifest'])
            ph = m[b'pieces']
            results = []
            for i, pc in enumerate(z['pieces']):
                exp = ph[i*20:(i+1)*20]
                act = hmac_mod.new(HMAC_KEY, pc, hashlib.sha1).digest()
                results.append({'piece': i, 'valid': exp == act,
                                'expected': exp.hex(), 'actual': act.hex()})
            return results

    def find_zone_for_query(self, qname):
        """Return the zone whose name matches qname as a suffix."""
        qn = qname.lower().rstrip('.')
        with self.lock:
            for zid, z in self.zones.items():
                zn = z['name'].lower().rstrip('.')
                if qn == zn or qn.endswith('.' + zn):
                    return z
        return None


_store = ZoneStore()


# ============================================================
# HTTP handler
# ============================================================

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _raw(self, data, ctype, status=200):
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _parts(self):
        return urlparse(self.path).path.strip('/').split('/')

    def do_GET(self):
        p = self._parts()

        # GET /zones/<id>/records
        if len(p) == 3 and p[0] == 'zones' and p[2] == 'records':
            z = _store.get(p[1])
            if not z:
                return self._json({'error': 'not found'}, 404)
            return self._json({'records': z['records']})

        # GET /zones/<id>/snapshot/manifest
        if len(p) == 4 and p[0] == 'zones' and p[2] == 'snapshot' and p[3] == 'manifest':
            z = _store.get(p[1])
            if not z or not z['manifest']:
                return self._json({'error': 'not found'}, 404)
            return self._raw(z['manifest'], 'application/x-bittorrent')

        # GET /zones/<id>/snapshot/piece/<n>
        if len(p) == 5 and p[0] == 'zones' and p[2] == 'snapshot' and p[3] == 'piece':
            try:
                n = int(p[4])
            except ValueError:
                return self._json({'error': 'bad piece num'}, 400)
            pc = _store.get_piece(p[1], n)
            if pc is None:
                return self._json({'error': 'not found'}, 404)
            return self._raw(pc, 'application/octet-stream')

        # GET /zones/<id>/snapshot/verify
        if len(p) == 4 and p[0] == 'zones' and p[2] == 'snapshot' and p[3] == 'verify':
            res = _store.verify(p[1])
            if res is None:
                return self._json({'error': 'not found'}, 404)
            ok = all(r['valid'] for r in res)
            return self._json({'valid': ok, 'pieces': res})

        self._json({'error': 'not found'}, 404)

    def do_POST(self):
        p = self._parts()
        cl = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(cl) if cl else b''

        # POST /zones
        if len(p) == 1 and p[0] == 'zones':
            try:
                data = json.loads(body)
                zid = _store.create(data['name'], data['records'])
                return self._json({'zone_id': zid}, 201)
            except (json.JSONDecodeError, KeyError) as e:
                return self._json({'error': str(e)}, 400)

        # POST /zones/<id>/snapshot
        if len(p) == 3 and p[0] == 'zones' and p[2] == 'snapshot':
            m = _store.snapshot(p[1])
            if m is None:
                return self._json({'error': 'not found'}, 404)
            return self._raw(m, 'application/x-bittorrent', 201)

        self._json({'error': 'not found'}, 404)


class ThreadedServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


# ============================================================
# DNS authoritative server (UDP)
# ============================================================

class DNSServer:
    def __init__(self, store, port=5353):
        self.store = store
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('0.0.0.0', port))
        self.running = True

    def serve(self):
        while self.running:
            try:
                self.sock.settimeout(1.0)
                data, addr = self.sock.recvfrom(4096)
                resp = self._handle(data)
                if resp:
                    self.sock.sendto(resp, addr)
            except socket.timeout:
                continue
            except Exception:
                continue

    def _handle(self, data):
        try:
            qname, qend = parse_dns_name(data, 12)
            qtype, _ = struct.unpack('>HH', data[qend:qend+4])
            zone = self.store.find_zone_for_query(qname)
            if zone:
                return build_dns_response(data, zone['records'])
            qid = struct.unpack('>H', data[:2])[0]
            return struct.pack('>HHHHHH', qid, 0x8005, 1, 0, 0, 0) + data[12:qend+4]
        except Exception:
            return None


# ============================================================
# Main
# ============================================================

def main():
    dns = DNSServer(_store, 5353)
    threading.Thread(target=dns.serve, daemon=True).start()
    print("DNS server on UDP 5353", flush=True)

    http = ThreadedServer(('0.0.0.0', 8080), Handler)
    print("HTTP server on port 8080", flush=True)
    http.serve_forever()


if __name__ == '__main__':
    main()
