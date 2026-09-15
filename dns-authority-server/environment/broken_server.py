#!/usr/bin/env python3
"""DNS authoritative server for a BIND-format zone file. Listens on UDP 5353."""

import socket
import struct

TYPE_A = 1
TYPE_NS = 2
TYPE_CNAME = 5
TYPE_SOA = 6
TYPE_MX = 15
TYPE_TXT = 16
TYPE_AAAA = 28
TYPE_SRV = 33
TYPE_OPT = 41
CLASS_IN = 1
PORT = 5353


class ZoneDB:
    def __init__(self):
        self.records = {}
        self.names = set()
        self.origin = ""

    def add(self, name, rtype, rdata):
        key = (name, rtype)
        self.records.setdefault(key, []).append(rdata)
        self.names.add(name)

    def get(self, name, rtype):
        return self.records.get((name, rtype), [])

    def name_exists(self, name):
        return name in self.names

    def find_wildcard(self, name, rtype):
        labels = name.split(".")
        for i in range(len(labels) - 1):
            wc = "*." + ".".join(labels[i + 1:])
            recs = self.records.get((wc, rtype), [])
            if recs:
                return recs
        return None

    def wildcard_name_exists(self, name):
        labels = name.split(".")
        for i in range(len(labels) - 1):
            wc = "*." + ".".join(labels[i + 1:])
            if wc in self.names:
                return True
        return False


def _qualify(name, origin):
    if name == "@":
        return origin
    if name.endswith("."):
        return name[:-1]
    return name + "." + origin


def _tokenize(line):
    tokens = []
    cur = ""
    in_q = False
    for ch in line:
        if ch == '"':
            in_q = not in_q
            cur += ch
        elif ch in (" ", "\t") and not in_q:
            if cur:
                tokens.append(cur)
                cur = ""
        else:
            cur += ch
    if cur:
        tokens.append(cur)
    return tokens


def _extract_quoted(s):
    parts = []
    in_q = False
    cur = ""
    for ch in s:
        if ch == '"':
            if in_q:
                parts.append(cur)
                cur = ""
            in_q = not in_q
        elif in_q:
            cur += ch
    return parts


def parse_zone(path):
    db = ZoneDB()
    origin = ""
    ttl_default = 3600
    cur_name = ""

    with open(path) as fh:
        raw = fh.read()

    cleaned = []
    for line in raw.split("\n"):
        out = ""
        in_q = False
        for ch in line:
            if ch == '"':
                in_q = not in_q
            if ch == ";" and not in_q:
                break
            out += ch
        cleaned.append(out.rstrip())

    joined = []
    buf = ""
    in_p = False
    for line in cleaned:
        if in_p:
            buf += " " + line.strip()
            if ")" in line:
                in_p = False
                joined.append(buf)
                buf = ""
        else:
            if "(" in line and ")" not in line:
                in_p = True
                buf = line
            else:
                joined.append(line)

    TYPE_KEYWORDS = {"A", "AAAA", "CNAME", "MX", "NS", "TXT", "SOA", "SRV", "PTR", "IN"}

    for line in joined:
        line = line.replace("(", "").replace(")", "").strip()
        if not line:
            continue
        if line.startswith("$ORIGIN"):
            origin = line.split()[1].rstrip(".")
            db.origin = origin
            continue
        if line.startswith("$TTL"):
            ttl_default = int(line.split()[1])
            continue

        toks = _tokenize(line)
        if not toks:
            continue

        i = 0
        if toks[0] not in TYPE_KEYWORDS and not toks[0].isdigit():
            cur_name = _qualify(toks[0], origin)
            i = 1
        name = cur_name

        ttl = ttl_default
        if i < len(toks) and toks[i].isdigit():
            ttl = int(toks[i])
            i += 1

        if i < len(toks) and toks[i] == "IN":
            i += 1

        if i >= len(toks):
            continue

        rtype_s = toks[i]
        i += 1

        if rtype_s == "A":
            db.add(name, TYPE_A, {"ip": toks[i], "ttl": ttl})
        elif rtype_s == "AAAA":
            db.add(name, TYPE_AAAA, {"ip": toks[i], "ttl": ttl})
        elif rtype_s == "NS":
            db.add(name, TYPE_NS, {"target": _qualify(toks[i], origin), "ttl": ttl})
        elif rtype_s == "CNAME":
            db.add(name, TYPE_CNAME, {"target": _qualify(toks[i], origin), "ttl": ttl})
        elif rtype_s == "MX":
            pri = int(toks[i])
            tgt = _qualify(toks[i + 1], origin)
            db.add(name, TYPE_MX, {"priority": pri, "target": tgt, "ttl": ttl})
        elif rtype_s == "TXT":
            remainder = " ".join(toks[i:])
            db.add(name, TYPE_TXT, {"strings": _extract_quoted(remainder), "ttl": ttl})
        elif rtype_s == "SOA":
            db.add(name, TYPE_SOA, {
                "mname": _qualify(toks[i], origin),
                "rname": _qualify(toks[i + 1], origin),
                "serial": int(toks[i + 2]),
                "refresh": int(toks[i + 3]),
                "retry": int(toks[i + 4]),
                "expire": int(toks[i + 5]),
                "minimum": int(toks[i + 6]),
                "ttl": ttl,
            })
        elif rtype_s == "SRV":
            db.add(name, TYPE_SRV, {
                "priority": int(toks[i]),
                "weight": int(toks[i + 1]),
                "port": int(toks[i + 2]),
                "target": _qualify(toks[i + 3], origin),
                "ttl": ttl,
            })

    return db


def encode_name(name):
    if not name:
        return b"\x00"
    out = b""
    for label in name.split("."):
        enc = label.encode("ascii")
        out += bytes([len(enc)]) + enc
    out += b"\x00"
    return out


def decode_name(data, offset):
    labels = []
    visited = set()
    end = None
    while True:
        if offset >= len(data) or offset in visited:
            break
        visited.add(offset)
        b = data[offset]
        if b == 0:
            if end is None:
                end = offset + 1
            break
        if (b & 0xC0) == 0xC0:
            if end is None:
                end = offset + 2
            ptr = struct.unpack("!H", data[offset:offset + 2])[0] & 0x3FFF
            offset = ptr
        else:
            offset += 1
            labels.append(data[offset:offset + b].decode("ascii"))
            offset += b
    return ".".join(labels), end


def encode_rdata(rtype, rec):
    if rtype == TYPE_A:
        return socket.inet_aton(rec["ip"])
    if rtype == TYPE_AAAA:
        return socket.inet_pton(socket.AF_INET6, rec["ip"])
    if rtype in (TYPE_NS, TYPE_CNAME):
        return encode_name(rec["target"])
    if rtype == TYPE_MX:
        return struct.pack("!H", rec["priority"]) + encode_name(rec["target"])
    if rtype == TYPE_TXT:
        return "".join(rec["strings"]).encode("utf-8")
    if rtype == TYPE_SOA:
        out = encode_name(rec["mname"])
        out += encode_name(rec["rname"])
        out += struct.pack("!IIIII", rec["serial"], rec["refresh"],
                           rec["retry"], rec["expire"], rec["minimum"])
        return out
    if rtype == TYPE_SRV:
        out = struct.pack("!HHH", rec["priority"], rec["weight"], rec["port"])
        out += encode_name(rec["target"])
        return out
    return b""


def make_rr(name, rtype, ttl, rdata_bytes):
    out = encode_name(name)
    out += struct.pack("!HHIH", rtype, CLASS_IN, ttl, len(rdata_bytes))
    out += rdata_bytes
    return out


def handle_query(data, db):
    if len(data) < 12:
        return None

    qid, flags, qdcount = struct.unpack("!HHH", data[:6])
    rd = (flags >> 8) & 1
    if qdcount < 1:
        return None

    offset = 12
    qname, offset = decode_name(data, offset)
    qtype, qclass = struct.unpack("!HH", data[offset:offset + 4])
    offset += 4

    current = qname
    answers = []
    rcode = 0

    cname_recs = db.get(current, TYPE_CNAME)
    if cname_recs and qtype != TYPE_CNAME:
        rec = cname_recs[0]
        answers.append(make_rr(current, TYPE_CNAME, rec["ttl"],
                               encode_rdata(TYPE_CNAME, rec)))

    if not answers:
        recs = db.get(current, qtype)
        if recs:
            for rec in recs:
                answers.append(make_rr(current, qtype, rec["ttl"],
                                       encode_rdata(qtype, rec)))
        else:
            wc_recs = db.find_wildcard(current, qtype)
            if wc_recs:
                for rec in wc_recs:
                    answers.append(make_rr(current, qtype, rec["ttl"],
                                           encode_rdata(qtype, rec)))
            elif db.name_exists(current):
                rcode = 0
            elif db.wildcard_name_exists(current):
                rcode = 0
            else:
                rcode = 3

    resp_flags = 0x8400
    if rd:
        resp_flags |= 0x0100
    resp_flags |= rcode

    header = struct.pack("!HHHHHH", qid, resp_flags, 1, len(answers), 0, 0)
    body = encode_name(qname) + struct.pack("!HH", qtype, CLASS_IN)
    for rr in answers:
        body += rr

    return header + body


def main():
    db = parse_zone("/app/zone.db")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", PORT))
    print(f"DNS server listening on port {PORT}", flush=True)

    while True:
        try:
            data, addr = sock.recvfrom(4096)
            resp = handle_query(data, db)
            if resp:
                sock.sendto(resp, addr)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}", flush=True)

    sock.close()


if __name__ == "__main__":
    main()
