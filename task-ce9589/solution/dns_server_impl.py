#!/usr/bin/env python3
"""
Authoritative DNS server with EDNS(0) and TCP support.

Loads BIND-format zone files, answers UDP/TCP queries on a configurable port.
Supports EDNS(0) OPT record negotiation and TC-flag truncation.
"""

import socket
import struct
import sys
import os
import threading
import ipaddress
from collections import defaultdict

TYPE_A = 1
TYPE_NS = 2
TYPE_CNAME = 5
TYPE_SOA = 6
TYPE_MX = 15
TYPE_TXT = 16
TYPE_AAAA = 28
TYPE_OPT = 41
CLASS_IN = 1

RCODE_NOERROR = 0
RCODE_NXDOMAIN = 3
RCODE_REFUSED = 5

FLAG_QR = 0x8000
FLAG_AA = 0x0400
FLAG_TC = 0x0200

SERVER_UDP_SIZE = 4096

TYPE_NAME_MAP = {
    'A': TYPE_A, 'NS': TYPE_NS, 'CNAME': TYPE_CNAME,
    'SOA': TYPE_SOA, 'MX': TYPE_MX, 'TXT': TYPE_TXT, 'AAAA': TYPE_AAAA,
}


def normalize(name):
    name = name.lower().strip()
    if not name.endswith('.'):
        name += '.'
    return name


def encode_name(name):
    if name == '.':
        return b'\x00'
    out = b''
    for label in name.rstrip('.').split('.'):
        b = label.encode('ascii')
        out += bytes([len(b)]) + b
    return out + b'\x00'


def encode_ipv4(s):
    return bytes(int(x) for x in s.split('.'))


def encode_ipv6(s):
    return ipaddress.IPv6Address(s).packed


def abs_name(name, origin):
    name = name.strip()
    if name == '@':
        return normalize(origin)
    if name.endswith('.'):
        return normalize(name)
    return normalize(name + '.' + origin)


class Record:
    __slots__ = ('name', 'type_', 'class_', 'ttl', 'rdata')

    def __init__(self, name, type_, class_, ttl, rdata):
        self.name = name
        self.type_ = type_
        self.class_ = class_
        self.ttl = ttl
        self.rdata = rdata


def parse_zone(path):
    origin = ''
    default_ttl = 3600
    records = defaultdict(list)
    names = set()
    cur_name = None

    with open(path) as f:
        raw_lines = f.readlines()

    lines = []
    buf = ''
    in_parens = False
    for line in raw_lines:
        clean = ''
        in_q = False
        for ch in line:
            if ch == '"':
                in_q = not in_q
            elif ch == ';' and not in_q:
                break
            clean += ch
        clean = clean.rstrip()
        if not clean and not in_parens:
            continue
        buf = (buf + ' ' + clean) if buf else clean
        if '(' in buf and ')' not in buf:
            in_parens = True
            continue
        if in_parens and ')' in clean:
            in_parens = False
        if in_parens:
            continue
        buf = buf.replace('(', ' ').replace(')', ' ')
        lines.append(buf)
        buf = ''
    if buf:
        lines.append(buf.replace('(', ' ').replace(')', ' '))

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith('$ORIGIN'):
            origin = normalize(line.split()[1])
            continue
        if line.startswith('$TTL'):
            default_ttl = int(line.split()[1])
            continue

        parts = line.split()
        idx = 0

        if parts[0].upper() == 'IN' or parts[0].isdigit():
            name = cur_name
        elif parts[0].upper() in TYPE_NAME_MAP:
            name = cur_name
        else:
            name = abs_name(parts[0], origin)
            cur_name = name
            idx = 1

        if name is None:
            continue

        ttl = default_ttl
        if idx < len(parts) and parts[idx].isdigit() and parts[idx].upper() not in TYPE_NAME_MAP:
            ttl = int(parts[idx])
            idx += 1

        if idx < len(parts) and parts[idx].upper() == 'IN':
            idx += 1

        if idx >= len(parts) or parts[idx].upper() not in TYPE_NAME_MAP:
            continue
        rtype = TYPE_NAME_MAP[parts[idx].upper()]
        idx += 1

        rd = parts[idx:]
        rdata = None

        if rtype == TYPE_A:
            rdata = encode_ipv4(rd[0])
        elif rtype == TYPE_AAAA:
            rdata = encode_ipv6(rd[0])
        elif rtype == TYPE_NS:
            rdata = encode_name(abs_name(rd[0], origin))
        elif rtype == TYPE_CNAME:
            rdata = encode_name(abs_name(rd[0], origin))
        elif rtype == TYPE_MX:
            pref = int(rd[0])
            mx = abs_name(rd[1], origin)
            rdata = struct.pack('!H', pref) + encode_name(mx)
        elif rtype == TYPE_TXT:
            txt = ' '.join(rd)
            if txt.startswith('"') and txt.endswith('"'):
                txt = txt[1:-1]
            tb = txt.encode('ascii')
            rdata = b''
            while tb:
                chunk = tb[:255]
                rdata += bytes([len(chunk)]) + chunk
                tb = tb[255:]
        elif rtype == TYPE_SOA:
            mname = abs_name(rd[0], origin)
            rname = abs_name(rd[1], origin)
            vals = [int(x) for x in rd[2:7]]
            rdata = encode_name(mname) + encode_name(rname) + struct.pack('!IIIII', *vals)

        if rdata is None:
            continue

        rec = Record(name, rtype, CLASS_IN, ttl, rdata)
        records[name].append(rec)
        names.add(name)

    return origin, records, names


def decode_wire_name(data, offset):
    parts = []
    end = None
    jumps = 0
    pos = offset
    while pos < len(data):
        l = data[pos]
        if l == 0:
            pos += 1
            break
        if (l & 0xC0) == 0xC0:
            if jumps > 10:
                break
            if end is None:
                end = pos + 2
            ptr = ((l & 0x3F) << 8) | data[pos + 1]
            pos = ptr
            jumps += 1
        else:
            pos += 1
            parts.append(data[pos:pos + l].decode('ascii'))
            pos += l
    if end is None:
        end = pos
    return normalize('.'.join(parts)) if parts else '.', end


def name_from_rdata(rdata, start=0):
    parts = []
    i = start
    while i < len(rdata):
        l = rdata[i]
        if l == 0:
            break
        i += 1
        parts.append(rdata[i:i + l].decode('ascii'))
        i += l
    return normalize('.'.join(parts)) if parts else ''


class Server:
    def __init__(self, zones_dir, port=5353):
        self.port = port
        self.zones = {}
        for fn in sorted(os.listdir(zones_dir)):
            if fn.endswith('.zone'):
                origin, recs, names = parse_zone(os.path.join(zones_dir, fn))
                if origin:
                    self.zones[origin] = (recs, names)

    def find_zone(self, name):
        name = normalize(name)
        labels = name.rstrip('.').split('.')
        for i in range(len(labels)):
            candidate = '.'.join(labels[i:]) + '.'
            if candidate in self.zones:
                return candidate, self.zones[candidate]
        return None, None

    def lookup(self, qname, qtype):
        qname = normalize(qname)
        origin, zdata = self.find_zone(qname)
        if not zdata:
            return [], [], [], RCODE_REFUSED

        records, names = zdata
        name_exists = qname in names

        wc_name = None
        if not name_exists:
            labels = qname.rstrip('.').split('.')
            for i in range(1, len(labels)):
                wc = '*.' + '.'.join(labels[i:]) + '.'
                if wc in names:
                    wc_name = wc
                    name_exists = True
                    break

        if not name_exists:
            return [], [], [], RCODE_NXDOMAIN

        effective = wc_name or qname

        if qtype != TYPE_CNAME:
            cnames = [r for r in records.get(effective, []) if r.type_ == TYPE_CNAME]
            if cnames:
                answers = []
                cn = cnames[0]
                answers.append(Record(qname, TYPE_CNAME, cn.class_, cn.ttl, cn.rdata))
                target = name_from_rdata(cn.rdata)
                visited = {qname}
                while target and target not in visited:
                    visited.add(target)
                    _, tz = self.find_zone(target)
                    if not tz:
                        break
                    trecs, tnames = tz
                    tn = target
                    if target not in tnames:
                        tl = target.rstrip('.').split('.')
                        found_wc = False
                        for j in range(1, len(tl)):
                            w = '*.' + '.'.join(tl[j:]) + '.'
                            if w in tnames:
                                tn = w
                                found_wc = True
                                break
                        if not found_wc:
                            break

                    tc = [r for r in trecs.get(tn, []) if r.type_ == TYPE_CNAME]
                    ta = [r for r in trecs.get(tn, []) if r.type_ == qtype]

                    if tc:
                        c = tc[0]
                        answers.append(Record(target, TYPE_CNAME, c.class_, c.ttl, c.rdata))
                        target = name_from_rdata(c.rdata)
                    elif ta:
                        for r in ta:
                            answers.append(Record(target, r.type_, r.class_, r.ttl, r.rdata))
                        break
                    else:
                        break

                additional = self._get_additionals(answers)
                return answers, [], additional, RCODE_NOERROR

        recs = [r for r in records.get(effective, []) if r.type_ == qtype]
        if wc_name:
            recs = [Record(qname, r.type_, r.class_, r.ttl, r.rdata) for r in recs]

        authority = []
        if not recs:
            soa = [r for r in records.get(origin, []) if r.type_ == TYPE_SOA]
            authority = soa[:1]

        additional = self._get_additionals(recs)
        return recs, authority, additional, RCODE_NOERROR

    def _get_additionals(self, recs):
        adds = []
        seen = set()
        for r in recs:
            if r.type_ in (TYPE_NS, TYPE_MX):
                offset = 2 if r.type_ == TYPE_MX else 0
                target = name_from_rdata(r.rdata, offset)
                if target and target not in seen:
                    seen.add(target)
                    _, zd = self.find_zone(target)
                    if zd:
                        for ar in zd[0].get(target, []):
                            if ar.type_ in (TYPE_A, TYPE_AAAA):
                                adds.append(ar)
        return adds

    def _encode_records(self, recs):
        body = b''
        for r in recs:
            body += encode_name(r.name)
            body += struct.pack('!HHIH', r.type_, r.class_, r.ttl, len(r.rdata))
            body += r.rdata
        return body

    def handle(self, data, use_tcp=False):
        if len(data) < 12:
            return None

        qid, flags, qdcount, ancount, nscount, arcount = struct.unpack('!HHHHHH', data[:12])
        offset = 12

        if qdcount < 1:
            return None

        qname, offset = decode_wire_name(data, offset)
        if offset + 4 > len(data):
            return None
        qtype, qclass = struct.unpack('!HH', data[offset:offset + 4])
        offset += 4

        # Skip remaining questions
        for _ in range(max(0, qdcount - 1)):
            if offset >= len(data):
                break
            _, offset = decode_wire_name(data, offset)
            if offset + 4 <= len(data):
                offset += 4

        # Skip answer and authority (normally empty in queries)
        for _ in range(ancount + nscount):
            if offset >= len(data):
                break
            _, offset = decode_wire_name(data, offset)
            if offset + 10 > len(data):
                break
            _, _, _, rdlen = struct.unpack('!HHIH', data[offset:offset + 10])
            offset += 10 + rdlen

        # Parse additional for EDNS OPT
        edns_present = False
        client_udp_size = 512
        for _ in range(arcount):
            if offset >= len(data):
                break
            _, new_off = decode_wire_name(data, offset)
            if new_off + 10 > len(data):
                break
            rtype, rclass, _, rdlen = struct.unpack('!HHIH', data[new_off:new_off + 10])
            if rtype == TYPE_OPT:
                edns_present = True
                client_udp_size = rclass
            offset = new_off + 10 + rdlen

        # Lookup
        answers, authority, additional, rcode = self.lookup(qname, qtype)

        # Build response additional (include OPT if EDNS)
        resp_additional = list(additional)
        if edns_present:
            resp_additional.append(Record('.', TYPE_OPT, SERVER_UDP_SIZE, 0, b''))

        resp_flags = FLAG_QR | FLAG_AA | (flags & 0x0100) | rcode

        hdr = struct.pack('!HHHHHH', qid, resp_flags, 1,
                          len(answers), len(authority), len(resp_additional))
        q = encode_name(qname) + struct.pack('!HH', qtype, qclass)
        body = self._encode_records(answers) + \
               self._encode_records(authority) + \
               self._encode_records(resp_additional)

        full_response = hdr + q + body

        # TC check for UDP
        if not use_tcp:
            effective_limit = min(client_udp_size, SERVER_UDP_SIZE) if edns_present else 512
            if len(full_response) > effective_limit:
                tc_flags = FLAG_QR | FLAG_AA | FLAG_TC | (flags & 0x0100) | rcode
                tc_additional = []
                if edns_present:
                    tc_additional.append(Record('.', TYPE_OPT, SERVER_UDP_SIZE, 0, b''))
                tc_hdr = struct.pack('!HHHHHH', qid, tc_flags, 1,
                                     0, 0, len(tc_additional))
                tc_body = self._encode_records(tc_additional)
                return tc_hdr + q + tc_body

        return full_response

    def _handle_tcp_client(self, conn):
        try:
            conn.settimeout(10)
            length_data = b''
            while len(length_data) < 2:
                chunk = conn.recv(2 - len(length_data))
                if not chunk:
                    return
                length_data += chunk
            msg_len = struct.unpack('!H', length_data)[0]

            msg = b''
            while len(msg) < msg_len:
                chunk = conn.recv(msg_len - len(msg))
                if not chunk:
                    return
                msg += chunk

            resp = self.handle(msg, use_tcp=True)
            if resp:
                conn.sendall(struct.pack('!H', len(resp)) + resp)
        except Exception:
            pass
        finally:
            conn.close()

    def _tcp_loop(self, tcp_sock):
        while True:
            try:
                conn, _ = tcp_sock.accept()
                t = threading.Thread(target=self._handle_tcp_client, args=(conn,), daemon=True)
                t.start()
            except Exception:
                pass

    def run(self):
        udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        udp_sock.bind(('0.0.0.0', self.port))

        tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        tcp_sock.bind(('0.0.0.0', self.port))
        tcp_sock.listen(5)

        print(f'DNS server on port {self.port}, zones: {list(self.zones.keys())}',
              flush=True)

        tcp_thread = threading.Thread(target=self._tcp_loop, args=(tcp_sock,), daemon=True)
        tcp_thread.start()

        while True:
            try:
                data, addr = udp_sock.recvfrom(4096)
                resp = self.handle(data, use_tcp=False)
                if resp:
                    udp_sock.sendto(resp, addr)
            except KeyboardInterrupt:
                break
            except Exception:
                import traceback
                traceback.print_exc(file=sys.stderr)
                sys.stderr.flush()


if __name__ == '__main__':
    zones_dir = sys.argv[1] if len(sys.argv) > 1 else '/app/zones'
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 5353
    Server(zones_dir, port).run()
