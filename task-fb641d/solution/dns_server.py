#!/usr/bin/env python3

"""DNS Authoritative Server — serves zone file data over UDP with wire format per RFC 1035."""

import argparse
import socket
import struct
import sys
from collections import defaultdict

# DNS record type numeric codes
TYPES = {
    "A": 1, "NS": 2, "CNAME": 5, "SOA": 6, "MX": 15,
    "TXT": 16, "AAAA": 28, "SRV": 33, "OPT": 41,
}

CLASS_IN = 1
RCODE_NOERROR = 0
RCODE_NXDOMAIN = 3
RCODE_REFUSED = 5


# ---------------------------------------------------------------------------
# DNS wire-format helpers
# ---------------------------------------------------------------------------

def encode_name(name, compression, offset):
    """Encode a DNS domain name into wire format with compression pointers."""
    result = b""
    labels = name.rstrip(".").split(".") if name != "." else []

    for i in range(len(labels)):
        suffix = ".".join(labels[i:]) + "."
        if suffix in compression:
            ptr = compression[suffix]
            result += struct.pack("!H", 0xC000 | ptr)
            return result
        compression[suffix] = offset + len(result)
        encoded_label = labels[i].encode("ascii")
        result += struct.pack("B", len(encoded_label)) + encoded_label

    result += b"\x00"
    return result


def decode_name(data, offset):
    """Decode a DNS domain name from wire format, following compression pointers."""
    labels = []
    jumped = False
    end_offset = offset

    while True:
        if offset >= len(data):
            break
        length = data[offset]

        if (length & 0xC0) == 0xC0:
            if not jumped:
                end_offset = offset + 2
            ptr = struct.unpack("!H", data[offset : offset + 2])[0] & 0x3FFF
            offset = ptr
            jumped = True
            continue

        if length == 0:
            if not jumped:
                end_offset = offset + 1
            break

        offset += 1
        labels.append(data[offset : offset + length].decode("ascii"))
        offset += length

    return ".".join(labels) + ".", end_offset


# ---------------------------------------------------------------------------
# Zone record model
# ---------------------------------------------------------------------------

class ZoneRecord:
    __slots__ = ("name", "ttl", "rclass", "rtype", "rdata")

    def __init__(self, name, ttl, rclass, rtype, rdata):
        self.name = name.lower()
        self.ttl = ttl
        self.rclass = rclass
        self.rtype = rtype
        self.rdata = rdata


# ---------------------------------------------------------------------------
# Zone file parser
# ---------------------------------------------------------------------------

def _expand_name(raw, origin):
    """Return a fully-qualified name given a raw token and the current $ORIGIN."""
    if raw == "@":
        return origin
    if raw.endswith("."):
        return raw
    return raw + "." + origin


def parse_zone_file(filepath):
    """Parse a standard DNS zone file and return (records_list, origin)."""
    records = []
    origin = ""
    default_ttl = 3600
    current_name = None

    with open(filepath) as fh:
        content = fh.read()

    # --- Phase 1: collapse multi-line records (parentheses) and strip comments
    lines = []
    in_parens = False
    buf = ""
    for raw_line in content.split("\n"):
        # Strip comments outside of quoted strings
        clean = ""
        in_quote = False
        for ch in raw_line:
            if ch == '"':
                in_quote = not in_quote
            if ch == ";" and not in_quote:
                break
            clean += ch
        clean = clean.rstrip()

        if not clean and not in_parens:
            continue

        if in_parens:
            buf += " " + clean
            if ")" in clean:
                in_parens = False
                lines.append(buf.replace("(", "").replace(")", ""))
                buf = ""
        else:
            if "(" in clean and ")" not in clean:
                in_parens = True
                buf = clean
            else:
                lines.append(clean.replace("(", "").replace(")", ""))

    # --- Phase 2: parse individual records
    for line in lines:
        if not line.strip():
            continue
        parts = line.split()
        if not parts:
            continue

        # Directives
        if parts[0] == "$ORIGIN":
            origin = parts[1]
            continue
        if parts[0] == "$TTL":
            default_ttl = int(parts[1])
            continue

        idx = 0

        # Owner name
        if line[0] in (" ", "\t"):
            name = current_name
        else:
            name = _expand_name(parts[0], origin)
            current_name = name
            idx = 1

        # Optional TTL / class
        ttl = default_ttl
        while idx < len(parts):
            if parts[idx].isdigit():
                ttl = int(parts[idx])
                idx += 1
            elif parts[idx].upper() == "IN":
                idx += 1
            else:
                break

        if idx >= len(parts):
            continue

        rtype_str = parts[idx].upper()
        idx += 1
        if rtype_str not in TYPES:
            continue
        rtype = TYPES[rtype_str]
        rdata_parts = parts[idx:]

        # --- Parse RDATA per type ---
        if rtype_str == "A":
            rdata = {"address": rdata_parts[0]}
        elif rtype_str == "AAAA":
            rdata = {"address": rdata_parts[0]}
        elif rtype_str in ("CNAME", "NS"):
            rdata = {"target": _expand_name(rdata_parts[0], origin)}
        elif rtype_str == "MX":
            rdata = {
                "preference": int(rdata_parts[0]),
                "exchange": _expand_name(rdata_parts[1], origin),
            }
        elif rtype_str == "SOA":
            rdata = {
                "mname": _expand_name(rdata_parts[0], origin),
                "rname": _expand_name(rdata_parts[1], origin),
                "serial": int(rdata_parts[2]),
                "refresh": int(rdata_parts[3]),
                "retry": int(rdata_parts[4]),
                "expire": int(rdata_parts[5]),
                "minimum": int(rdata_parts[6]),
            }
        elif rtype_str == "TXT":
            txt = " ".join(rdata_parts)
            if txt.startswith('"') and txt.endswith('"'):
                txt = txt[1:-1]
            rdata = {"text": txt}
        elif rtype_str == "SRV":
            rdata = {
                "priority": int(rdata_parts[0]),
                "weight": int(rdata_parts[1]),
                "port": int(rdata_parts[2]),
                "target": _expand_name(rdata_parts[3], origin),
            }
        else:
            continue

        records.append(ZoneRecord(name, ttl, CLASS_IN, rtype, rdata))

    return records, origin


# ---------------------------------------------------------------------------
# DNS authoritative server
# ---------------------------------------------------------------------------

class DNSServer:
    def __init__(self, zone_file, port):
        self.port = port
        records, self.origin = parse_zone_file(zone_file)

        # Index records by lowercase FQDN
        self.zone_data = defaultdict(list)
        self.names = set()
        for rec in records:
            key = rec.name.lower()
            self.zone_data[key].append(rec)
            self.names.add(key)

        # Add empty non-terminals (parent names implied by existing records)
        for name in list(self.names):
            parts = name.rstrip(".").split(".")
            for i in range(1, len(parts)):
                ent = ".".join(parts[i:]) + "."
                self.names.add(ent.lower())

    # -- lookup helpers --

    def _find(self, name, rtype):
        return [r for r in self.zone_data.get(name.lower(), []) if r.rtype == rtype]

    def _exists(self, name):
        return name.lower() in self.names

    def _wildcard(self, name):
        """Return the wildcard owner that matches *name*, or None."""
        labels = name.lower().rstrip(".").split(".")
        if len(labels) < 2:
            return None
        wc = "*." + ".".join(labels[1:]) + "."
        if wc.lower() in self.zone_data:
            return wc.lower()
        return None

    def _soa(self):
        recs = self._find(self.origin, TYPES["SOA"])
        return recs[0] if recs else None

    # -- RDATA encoding --

    def _encode_rdata(self, rtype, rdata, comp, off):
        if rtype == TYPES["A"]:
            return socket.inet_aton(rdata["address"])
        if rtype == TYPES["AAAA"]:
            return socket.inet_pton(socket.AF_INET6, rdata["address"])
        if rtype in (TYPES["CNAME"], TYPES["NS"]):
            return encode_name(rdata["target"], comp, off)
        if rtype == TYPES["MX"]:
            b = struct.pack("!H", rdata["preference"])
            b += encode_name(rdata["exchange"], comp, off + 2)
            return b
        if rtype == TYPES["SOA"]:
            b = encode_name(rdata["mname"], comp, off)
            b += encode_name(rdata["rname"], comp, off + len(b))
            b += struct.pack(
                "!IIIII",
                rdata["serial"],
                rdata["refresh"],
                rdata["retry"],
                rdata["expire"],
                rdata["minimum"],
            )
            return b
        if rtype == TYPES["TXT"]:
            raw = rdata["text"].encode("ascii")
            b = b""
            for i in range(0, len(raw), 255):
                chunk = raw[i : i + 255]
                b += struct.pack("B", len(chunk)) + chunk
            return b
        if rtype == TYPES["SRV"]:
            b = struct.pack("!HHH", rdata["priority"], rdata["weight"], rdata["port"])
            b += encode_name(rdata["target"], comp, off + 6)
            return b
        return b""

    def _build_rr(self, record, comp, msg_offset):
        """Serialize a single resource record at *msg_offset* in the message."""
        name_b = encode_name(record.name, comp, msg_offset)
        rdata_off = msg_offset + len(name_b) + 10  # past TYPE+CLASS+TTL+RDLEN
        rdata_b = self._encode_rdata(record.rtype, record.rdata, comp, rdata_off)
        return (
            name_b
            + struct.pack("!HHIH", record.rtype, record.rclass, record.ttl, len(rdata_b))
            + rdata_b
        )

    # -- query processing --

    def handle(self, data):
        if len(data) < 12:
            return None

        qid, flags, qdcount = struct.unpack("!HHH", data[:6])
        _, _, arcount = struct.unpack("!HHH", data[6:12])
        rd = (flags >> 8) & 1

        # Parse question
        off = 12
        questions = []
        for _ in range(qdcount):
            qname, off = decode_name(data, off)
            if off + 4 > len(data):
                return None
            qtype, qclass = struct.unpack("!HH", data[off : off + 4])
            off += 4
            questions.append((qname, qtype, qclass))

        # Detect EDNS0 OPT in additional section
        has_edns = False
        scan = off
        for _ in range(arcount):
            if scan >= len(data):
                break
            _, scan = decode_name(data, scan)
            if scan + 10 > len(data):
                break
            rr_type, rr_class, _, rr_rdlen = struct.unpack("!HHIH", data[scan : scan + 10])
            scan += 10
            if rr_type == TYPES["OPT"]:
                has_edns = True
            scan += rr_rdlen

        if not questions:
            return None
        qname, qtype, _ = questions[0]

        answers = []
        authority = []
        rcode = RCODE_NOERROR

        # Zone membership check
        qname_l = qname.lower()
        origin_l = self.origin.lower()
        in_zone = qname_l == origin_l or qname_l.endswith("." + origin_l)

        if not in_zone:
            rcode = RCODE_REFUSED
        else:
            found = self._find(qname, qtype)
            if found:
                answers.extend(found)
            else:
                cnames = self._find(qname, TYPES["CNAME"])
                if cnames:
                    visited = set()
                    cur = qname
                    while True:
                        cn = self._find(cur, TYPES["CNAME"])
                        if not cn or cur.lower() in visited:
                            break
                        visited.add(cur.lower())
                        answers.append(cn[0])
                        cur = cn[0].rdata["target"]
                    final = self._find(cur, qtype)
                    if final:
                        answers.extend(final)
                elif self._exists(qname):
                    # NODATA
                    soa = self._soa()
                    if soa:
                        authority.append(soa)
                else:
                    wc = self._wildcard(qname)
                    if wc:
                        wc_recs = self._find(wc, qtype)
                        if wc_recs:
                            for wr in wc_recs:
                                answers.append(
                                    ZoneRecord(qname, wr.ttl, wr.rclass, wr.rtype, wr.rdata)
                                )
                        else:
                            soa = self._soa()
                            if soa:
                                authority.append(soa)
                    else:
                        rcode = RCODE_NXDOMAIN
                        soa = self._soa()
                        if soa:
                            authority.append(soa)

        # Build response
        resp_flags = (1 << 15) | (1 << 10)  # QR + AA
        if rd:
            resp_flags |= 1 << 8
        resp_flags |= rcode

        extra_ar = 1 if has_edns else 0
        hdr = struct.pack(
            "!HHHHHH",
            qid,
            resp_flags,
            qdcount,
            len(answers),
            len(authority),
            extra_ar,
        )
        resp = hdr
        comp = {}

        # Echo question section
        for qn, qt, qc in questions:
            resp += encode_name(qn, comp, len(resp))
            resp += struct.pack("!HH", qt, qc)

        # Answer section
        for rec in answers:
            resp += self._build_rr(rec, comp, len(resp))

        # Authority section
        for rec in authority:
            resp += self._build_rr(rec, comp, len(resp))

        # EDNS0 OPT pseudo-RR
        if has_edns:
            resp += b"\x00"  # root name
            resp += struct.pack("!HHIH", TYPES["OPT"], 4096, 0, 0)

        return resp

    def run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", self.port))
        print(f"DNS server listening on port {self.port}", flush=True)

        while True:
            try:
                data, addr = sock.recvfrom(4096)
                resp = self.handle(data)
                if resp:
                    sock.sendto(resp, addr)
            except KeyboardInterrupt:
                break
            except Exception as exc:
                print(f"Error: {exc}", file=sys.stderr, flush=True)

        sock.close()


def main():
    ap = argparse.ArgumentParser(description="DNS Authoritative Server")
    ap.add_argument("--zone", required=True, help="Path to zone file")
    ap.add_argument("--port", type=int, default=1053, help="UDP port")
    args = ap.parse_args()
    DNSServer(args.zone, args.port).run()


if __name__ == "__main__":
    main()
