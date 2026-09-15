#!/usr/bin/env python3
"""DNS Authoritative Server - initial implementation.
Handles UDP and TCP queries on a configurable port, loads zone files.
Uses raw sockets and struct only; no DNS libraries.
"""

import socket
import struct
import os
import sys
import threading

# DNS type constants
TYPE_A = 1
TYPE_NS = 2
TYPE_CNAME = 5
TYPE_SOA = 6
TYPE_MX = 15
TYPE_TXT = 16
TYPE_AAAA = 28

CLASS_IN = 1

RCODE_NOERROR = 0
RCODE_NXDOMAIN = 3
RCODE_REFUSED = 5


class RR:
    """A DNS Resource Record."""
    __slots__ = ('name', 'rtype', 'rclass', 'ttl', 'rdata')

    def __init__(self, name, rtype, rclass, ttl, rdata):
        self.name = name
        self.rtype = rtype
        self.rclass = rclass
        self.ttl = ttl
        self.rdata = rdata


class Zone:
    """Represents a DNS zone loaded from a zone file."""

    def __init__(self, origin, default_ttl=3600):
        self.origin = origin.lower()
        self.default_ttl = default_ttl
        self.soa = None
        self.records = {}   # name -> list of RR
        self.all_nodes = set()

    def add_record(self, rr):
        key = rr.name.lower()
        if key not in self.records:
            self.records[key] = []
        self.records[key].append(rr)
        if rr.rtype == TYPE_SOA and self.soa is None:
            self.soa = rr

    def compute_nodes(self):
        """Compute all zone nodes including empty non-terminals."""
        self.all_nodes = set(self.records.keys())
        self.all_nodes.add(self.origin)
        origin_labels = self.origin.rstrip('.').split('.')
        origin_len = len(origin_labels)
        for name in list(self.records.keys()):
            labels = name.rstrip('.').split('.')
            for i in range(1, len(labels) - origin_len + 1):
                ancestor = '.'.join(labels[i:]) + '.'
                self.all_nodes.add(ancestor)

    def get_records(self, name, rtype):
        key = name.lower()
        if key in self.records:
            return [rr for rr in self.records[key] if rr.rtype == rtype]
        return []

    def node_exists(self, name):
        return name.lower() in self.all_nodes

    def has_records(self, name):
        return name.lower() in self.records

    def find_delegation(self, qname):
        """Check if qname falls under a delegation point within this zone."""
        labels = qname.lower().rstrip('.').split('.')
        origin_labels = self.origin.rstrip('.').split('.')
        origin_len = len(origin_labels)
        for i in range(1, len(labels) - origin_len + 1):
            candidate = '.'.join(labels[i:]) + '.'
            if candidate == self.origin:
                break
            if candidate in self.records:
                ns_recs = [rr for rr in self.records[candidate]
                           if rr.rtype == TYPE_NS]
                if ns_recs:
                    return candidate, ns_recs
        return None, []

    def find_wildcard(self, qname):
        """Find wildcard match using closest-encloser algorithm (RFC 4592)."""
        labels = qname.lower().rstrip('.').split('.')
        for i in range(1, len(labels)):
            ancestor = '.'.join(labels[i:]) + '.'
            if ancestor in self.all_nodes:
                wildcard = '*.' + ancestor
                if wildcard in self.records:
                    return wildcard
                break
        return None

    def is_within_zone(self, name):
        n = name.lower()
        return n == self.origin or n.endswith('.' + self.origin)


def parse_zone_file(filepath):
    """Parse a standard DNS zone file."""
    with open(filepath, 'r') as f:
        content = f.read()

    # Strip comments and join parenthesized lines
    lines = []
    current_line = ''
    in_parens = False

    for raw_line in content.split('\n'):
        in_quote = False
        cleaned = ''
        for ch in raw_line:
            if ch == '"':
                in_quote = not in_quote
            if ch == ';' and not in_quote:
                break
            cleaned += ch
        stripped = cleaned.rstrip()

        if in_parens:
            current_line += ' ' + stripped
            if ')' in stripped:
                in_parens = False
                current_line = current_line.replace('(', '').replace(')', '')
                lines.append(current_line)
                current_line = ''
        else:
            if '(' in stripped and ')' not in stripped:
                in_parens = True
                current_line = stripped
            else:
                line = stripped.replace('(', '').replace(')', '')
                if line.strip():
                    lines.append(line)

    origin = ''
    default_ttl = 3600
    last_name = ''
    zone = None

    for line in lines:
        tokens = line.split()
        if not tokens:
            continue

        if tokens[0] == '$ORIGIN':
            origin = tokens[1]
            if zone is None:
                zone = Zone(origin, default_ttl)
            continue

        if tokens[0] == '$TTL':
            default_ttl = int(tokens[1])
            if zone:
                zone.default_ttl = default_ttl
            continue

        if tokens[0] == '$INCLUDE':
            continue

        idx = 0

        if line[0] in (' ', '\t'):
            name = last_name
        else:
            name = tokens[idx]
            idx += 1

        if name == '@':
            name = origin
        elif not name.endswith('.'):
            name = name + '.' + origin

        last_name = name

        ttl = default_ttl
        rclass = CLASS_IN

        while idx < len(tokens):
            upper = tokens[idx].upper()
            if upper == 'IN':
                rclass = CLASS_IN
                idx += 1
            elif tokens[idx].isdigit():
                ttl = int(tokens[idx])
                idx += 1
            else:
                break

        if idx >= len(tokens):
            continue

        rtype_str = tokens[idx].upper()
        idx += 1

        rtype_map = {
            'A': TYPE_A, 'NS': TYPE_NS, 'CNAME': TYPE_CNAME,
            'SOA': TYPE_SOA, 'MX': TYPE_MX, 'TXT': TYPE_TXT,
            'AAAA': TYPE_AAAA,
        }

        if rtype_str not in rtype_map:
            continue
        rtype = rtype_map[rtype_str]

        rdata_tokens = tokens[idx:]

        if rtype == TYPE_A:
            rdata = {'address': rdata_tokens[0]}
        elif rtype == TYPE_AAAA:
            rdata = {'address': rdata_tokens[0]}
        elif rtype == TYPE_NS:
            ns_name = rdata_tokens[0]
            if not ns_name.endswith('.'):
                ns_name = ns_name + '.' + origin
            rdata = {'nsdname': ns_name}
        elif rtype == TYPE_CNAME:
            cname = rdata_tokens[0]
            if not cname.endswith('.'):
                cname = cname + '.' + origin
            rdata = {'cname': cname}
        elif rtype == TYPE_MX:
            mx_pref = int(rdata_tokens[0])
            mx_name = rdata_tokens[1]
            if not mx_name.endswith('.'):
                mx_name = mx_name + '.' + origin
            rdata = {'preference': mx_pref, 'exchange': mx_name}
        elif rtype == TYPE_SOA:
            mname = rdata_tokens[0]
            rname = rdata_tokens[1]
            if not mname.endswith('.'):
                mname = mname + '.' + origin
            if not rname.endswith('.'):
                rname = rname + '.' + origin
            rdata = {
                'mname': mname, 'rname': rname,
                'serial': int(rdata_tokens[2]),
                'refresh': int(rdata_tokens[3]),
                'retry': int(rdata_tokens[4]),
                'expire': int(rdata_tokens[5]),
                'minimum': int(rdata_tokens[6]),
            }
        elif rtype == TYPE_TXT:
            txt_line = ' '.join(rdata_tokens)
            txt_strings = []
            in_quote = False
            current = ''
            for ch in txt_line:
                if ch == '"':
                    if in_quote:
                        txt_strings.append(current)
                        current = ''
                    in_quote = not in_quote
                elif in_quote:
                    current += ch
            rdata = {'strings': txt_strings}
        else:
            continue

        rr = RR(name, rtype, rclass, ttl, rdata)
        zone.add_record(rr)

    if zone:
        zone.compute_nodes()
    return zone


# ---------------------------------------------------------------------------
# DNS wire-format encoding / decoding
# ---------------------------------------------------------------------------

def encode_name(name):
    """Encode a DNS name into wire format."""
    result = b''
    name_lower = name.lower().rstrip('.')
    labels = name_lower.split('.') if name_lower else []
    for label in labels:
        encoded = label.encode('ascii')
        result += bytes([len(encoded)]) + encoded
    result += b'\x00'
    return result


def decode_name(data, offset):
    """Decode a DNS name from wire format, handling compression pointers."""
    labels = []
    visited = set()
    final_offset = None

    while True:
        if offset >= len(data):
            break
        if offset in visited:
            raise ValueError("Compression loop")
        visited.add(offset)

        length = data[offset]
        if length == 0:
            if final_offset is None:
                final_offset = offset + 1
            break
        elif (length & 0xC0) == 0xC0:
            pointer = struct.unpack('!H', data[offset:offset + 2])[0] & 0x3FFF
            if final_offset is None:
                final_offset = offset + 2
            offset = pointer
        else:
            offset += 1
            labels.append(data[offset:offset + length].decode('ascii'))
            offset += length

    return '.'.join(labels) + '.', final_offset or offset


def encode_rdata(rr, buf_offset):
    """Encode RDATA for a resource record."""
    rd = rr.rdata

    if rr.rtype == TYPE_A:
        return socket.inet_aton(rd['address'])
    elif rr.rtype == TYPE_AAAA:
        return socket.inet_pton(socket.AF_INET6, rd['address'])
    elif rr.rtype == TYPE_NS:
        return encode_name(rd['nsdname'])
    elif rr.rtype == TYPE_CNAME:
        return encode_name(rd['cname'])
    elif rr.rtype == TYPE_MX:
        result = struct.pack('!H', rd['preference'])
        result += encode_name(rd['exchange'])
        return result
    elif rr.rtype == TYPE_SOA:
        result = encode_name(rd['mname'])
        result += encode_name(rd['rname'])
        result += struct.pack('!IIIII',
                              rd['serial'], rd['refresh'], rd['retry'],
                              rd['expire'], rd['minimum'])
        return result
    elif rr.rtype == TYPE_TXT:
        result = b''
        for s in rd['strings']:
            encoded = s.encode('utf-8')
            result += bytes([len(encoded)]) + encoded
        return result
    return b''


def encode_rr(rr, buf_offset):
    """Encode a complete resource record."""
    name_bytes = encode_name(rr.name)
    rdata_bytes = encode_rdata(rr, buf_offset + len(name_bytes) + 10)
    header = struct.pack('!HHIH', rr.rtype, rr.rclass, rr.ttl, len(rdata_bytes))
    return name_bytes + header + rdata_bytes


# ---------------------------------------------------------------------------
# Response building
# ---------------------------------------------------------------------------

def build_response(query_data, zones):
    """Parse a DNS query and build the response."""
    if len(query_data) < 12:
        return None

    qid, flags, qdcount = struct.unpack('!HHH', query_data[:6])
    rd = (flags >> 8) & 1

    if qdcount < 1:
        return None

    qname, offset = decode_name(query_data, 12)
    if offset + 4 > len(query_data):
        return None
    qtype, qclass = struct.unpack('!HH', query_data[offset:offset + 4])

    # Find the authoritative zone for qname
    zone = None
    search = qname.lower()
    while search:
        if search in zones:
            zone = zones[search]
            break
        dot = search.find('.')
        if dot >= 0 and dot < len(search) - 1:
            search = search[dot + 1:]
        else:
            break

    if zone is None:
        resp_flags = 0x8000 | (rd << 8) | RCODE_REFUSED
        hdr = struct.pack('!HHHHHH', qid, resp_flags, 1, 0, 0, 0)
        q = encode_name(qname) + struct.pack('!HH', qtype, qclass)
        return hdr + q

    answers = []
    authority = []
    additional = []
    rcode = RCODE_NOERROR
    aa = 1

    # 1. Check for delegation
    deleg_name, deleg_ns = zone.find_delegation(qname)
    if deleg_name:
        authority = list(deleg_ns)
    else:
        # 2. Check for CNAME
        cname_recs = zone.get_records(qname, TYPE_CNAME)
        if cname_recs and qtype != TYPE_CNAME:
            answers.extend(cname_recs)
        elif cname_recs and qtype == TYPE_CNAME:
            answers = list(cname_recs)
        else:
            # 3. Exact lookup
            recs = zone.get_records(qname, qtype)
            if recs:
                answers = list(recs)
            else:
                # 4. NODATA vs wildcard vs NXDOMAIN
                if zone.node_exists(qname):
                    rcode = RCODE_NOERROR
                else:
                    wildcard = zone.find_wildcard(qname)
                    if wildcard:
                        wild_recs = zone.get_records(wildcard, qtype)
                        if wild_recs:
                            answers.extend(wild_recs)
                        else:
                            rcode = RCODE_NOERROR
                    else:
                        rcode = RCODE_NXDOMAIN

    # Build the wire-format response
    resp_flags = 0x8000 | (aa << 10) | (rd << 8) | rcode

    question_bytes = encode_name(qname) + struct.pack('!HH', qtype, qclass)

    cur = 12 + len(question_bytes)

    ans_bytes = b''
    for rr in answers:
        encoded = encode_rr(rr, cur)
        ans_bytes += encoded
        cur += len(encoded)

    auth_bytes = b''
    for rr in authority:
        encoded = encode_rr(rr, cur)
        auth_bytes += encoded
        cur += len(encoded)

    add_bytes = b''
    for rr in additional:
        encoded = encode_rr(rr, cur)
        add_bytes += encoded
        cur += len(encoded)

    header = struct.pack('!HHHHHH', qid, resp_flags,
                         1, len(answers), len(authority), len(additional))

    return header + question_bytes + ans_bytes + auth_bytes + add_bytes


# ---------------------------------------------------------------------------
# TCP DNS server
# ---------------------------------------------------------------------------

def handle_tcp_client(conn, addr, zones):
    """Handle a single TCP DNS connection."""
    try:
        while True:
            length_data = b''
            while len(length_data) < 2:
                chunk = conn.recv(2 - len(length_data))
                if not chunk:
                    return
                length_data += chunk
            msg_len = struct.unpack('!H', length_data)[0]
            if msg_len == 0 or msg_len > 65535:
                break
            data = b''
            while len(data) < msg_len:
                chunk = conn.recv(msg_len - len(data))
                if not chunk:
                    return
                data += chunk
            response = build_response(data, zones)
            if response:
                conn.sendall(response)
            else:
                break
    except Exception as e:
        print(f"TCP client error from {addr}: {e}", file=sys.stderr)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def tcp_server(zones, port):
    """Run threaded TCP DNS server."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('0.0.0.0', port))
    sock.listen(8)
    print(f"DNS server listening on TCP port {port}", file=sys.stderr)

    while True:
        try:
            conn, addr = sock.accept()
            t = threading.Thread(
                target=handle_tcp_client,
                args=(conn, addr, zones),
                daemon=True,
            )
            t.start()
        except Exception as e:
            print(f"TCP accept error: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main server loop
# ---------------------------------------------------------------------------

def main():
    zones = {}
    zone_dir = '/app/zones/'

    for filename in os.listdir(zone_dir):
        if filename.endswith('.zone'):
            filepath = os.path.join(zone_dir, filename)
            zone = parse_zone_file(filepath)
            if zone:
                zones[zone.origin] = zone
                print(f"Loaded zone: {zone.origin} "
                      f"({len(zone.records)} names, "
                      f"{len(zone.all_nodes)} nodes)",
                      file=sys.stderr)

    # Start TCP server in background thread
    tcp_thread = threading.Thread(target=tcp_server, args=(zones, 5300),
                                  daemon=True)
    tcp_thread.start()

    # UDP server in main thread
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('0.0.0.0', 5300))
    print("DNS server listening on UDP port 5300", file=sys.stderr)

    while True:
        try:
            data, addr = sock.recvfrom(4096)
            response = build_response(data, zones)
            if response:
                sock.sendto(response, addr)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"UDP error: {e}", file=sys.stderr)


if __name__ == '__main__':
    main()
