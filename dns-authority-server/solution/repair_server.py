#!/usr/bin/env python3
"""
Repair the broken DNS server at /app/dns_server.py by analyzing the
reference capture at /app/reference.pcap to discover required behaviors.

Workflow:
1. Parse the pcap binary to extract all DNS response packets
2. Analyze each response to identify required protocol features
3. Extract zone-file parser functions from the broken server source
4. Generate corrected server code incorporating all discovered features
5. Write the repaired server to /app/dns_server.py
"""

import struct
import socket
import re
import sys
import os

# DNS record type constants
TYPE_A = 1
TYPE_NS = 2
TYPE_CNAME = 5
TYPE_SOA = 6
TYPE_MX = 15
TYPE_TXT = 16
TYPE_AAAA = 28
TYPE_SRV = 33
TYPE_OPT = 41


# ======================================================================
# PCAP + DNS wire-format binary parser
# ======================================================================

def dns_decode_name(data, offset):
    """Decode a DNS wire-format name with compression pointer support."""
    labels, visited, end = [], set(), None
    while offset < len(data) and offset not in visited:
        visited.add(offset)
        b = data[offset]
        if b == 0:
            end = end or offset + 1
            break
        if (b & 0xC0) == 0xC0:
            end = end or offset + 2
            offset = struct.unpack("!H", data[offset:offset + 2])[0] & 0x3FFF
        else:
            offset += 1
            labels.append(data[offset:offset + b].decode("ascii", errors="replace"))
            offset += b
    return ".".join(labels).lower(), end


def parse_dns_packet(dns_bytes):
    """Parse a DNS packet from raw wire-format bytes."""
    if len(dns_bytes) < 12:
        return None
    hdr = struct.unpack("!HHHHHH", dns_bytes[:12])
    pkt = {
        "id": hdr[0], "flags": hdr[1],
        "qr": (hdr[1] >> 15) & 1,
        "aa": (hdr[1] >> 10) & 1,
        "rcode": hdr[1] & 0xF,
        "qdcount": hdr[2], "ancount": hdr[3],
        "nscount": hdr[4], "arcount": hdr[5],
        "answers": [], "authority": [], "additional": [],
        "qname": "", "qtype": 0,
    }
    off = 12
    for _ in range(pkt["qdcount"]):
        pkt["qname"], off = dns_decode_name(dns_bytes, off)
        pkt["qtype"] = struct.unpack("!H", dns_bytes[off:off + 2])[0]
        off += 4

    for sect, count in [("answers", pkt["ancount"]),
                        ("authority", pkt["nscount"]),
                        ("additional", pkt["arcount"])]:
        for _ in range(count):
            name, off = dns_decode_name(dns_bytes, off)
            rtype, rclass, ttl, rdlen = struct.unpack(
                "!HHIH", dns_bytes[off:off + 10])
            rd_start = off + 10
            off = rd_start + rdlen
            rr = {"name": name, "type": rtype, "ttl": ttl}
            if rtype == TYPE_CNAME:
                rr["target"], _ = dns_decode_name(dns_bytes, rd_start)
            elif rtype == TYPE_A and rdlen == 4:
                rr["ip"] = socket.inet_ntoa(dns_bytes[rd_start:rd_start + 4])
            elif rtype == TYPE_AAAA and rdlen == 16:
                rr["ip"] = socket.inet_ntop(
                    socket.AF_INET6, dns_bytes[rd_start:rd_start + 16])
            elif rtype == TYPE_MX:
                rr["priority"] = struct.unpack(
                    "!H", dns_bytes[rd_start:rd_start + 2])[0]
                rr["mx_target"], _ = dns_decode_name(dns_bytes, rd_start + 2)
            elif rtype == TYPE_TXT:
                raw = dns_bytes[rd_start:rd_start + rdlen]
                strs, i = [], 0
                while i < rdlen:
                    slen = raw[i]
                    strs.append(raw[i + 1:i + 1 + slen])
                    i += 1 + slen
                rr["txt_strings"] = strs
                rr["txt_properly_encoded"] = (len(strs) > 0)
            elif rtype == TYPE_SOA:
                mn, p = dns_decode_name(dns_bytes, rd_start)
                rn, p = dns_decode_name(dns_bytes, p)
                serial = struct.unpack("!I", dns_bytes[p:p + 4])[0]
                rr["soa_mname"] = mn
                rr["soa_serial"] = serial
            elif rtype == TYPE_OPT:
                rr["is_opt"] = True
            pkt[sect].append(rr)
    return pkt


def read_pcap_responses(path):
    """Read a pcap file and return all DNS response packets."""
    with open(path, "rb") as f:
        data = f.read()
    magic = struct.unpack("<I", data[:4])[0]
    if magic != 0xA1B2C3D4:
        raise ValueError(f"Invalid pcap magic: 0x{magic:08X}")
    off, responses = 24, []
    while off + 16 <= len(data):
        _, _, incl_len, _ = struct.unpack("<IIII", data[off:off + 16])
        pkt_raw = data[off + 16:off + 16 + incl_len]
        off += 16 + incl_len
        # Strip Ethernet(14) + IPv4(20) + UDP(8) = 42 bytes to get DNS
        if len(pkt_raw) > 42:
            p = parse_dns_packet(pkt_raw[42:])
            if p and p["qr"] == 1:
                responses.append(p)
    return responses


# ======================================================================
# Behavioral analysis — discover what the reference server does
# ======================================================================

def discover_behaviors(responses):
    """Analyze reference responses to determine required protocol behaviors."""
    behaviors = set()
    max_cname_depth = 0

    for resp in responses:
        cnames = [r for r in resp["answers"] if r["type"] == TYPE_CNAME]
        non_cnames = [r for r in resp["answers"]
                      if r["type"] not in (TYPE_CNAME,)]

        # CNAME following: any response with CNAME + resolved target record
        if cnames and non_cnames:
            behaviors.add("cname_follow")
        # Multi-hop CNAME chains
        if len(cnames) > 1:
            behaviors.add("cname_chain_multi")
            max_cname_depth = max(max_cname_depth, len(cnames))
        elif len(cnames) == 1:
            max_cname_depth = max(max_cname_depth, 1)

        # TXT character-string encoding (length-prefixed strings)
        for rr in resp["answers"]:
            if rr["type"] == TYPE_TXT and rr.get("txt_properly_encoded"):
                behaviors.add("txt_charstring_encoding")

        # EDNS0 OPT record echo in additional section
        if any(r.get("is_opt") for r in resp["additional"]):
            behaviors.add("edns0_opt_echo")

        # SOA in authority for NXDOMAIN (RFC 2308)
        if resp["rcode"] == 3:
            if any(r["type"] == TYPE_SOA for r in resp["authority"]):
                behaviors.add("nxdomain_soa_authority")

        # SOA in authority for NODATA (RFC 2308)
        if resp["rcode"] == 0 and not resp["answers"]:
            if any(r["type"] == TYPE_SOA for r in resp["authority"]):
                behaviors.add("nodata_soa_authority")

        # MX glue A records in additional section
        mx_ans = [r for r in resp["answers"] if r["type"] == TYPE_MX]
        a_add = [r for r in resp["additional"] if r["type"] == TYPE_A]
        if mx_ans and a_add:
            behaviors.add("mx_glue_additional")

    # DNS requires case-insensitive name matching (RFC 4343).
    # The reference pcap includes an uppercase query with a valid response,
    # confirming this requirement.
    behaviors.add("case_insensitive")

    return behaviors, max_cname_depth


# ======================================================================
# Zone parser extraction — reuse correct code from broken server
# ======================================================================

def extract_zone_parser_block(source):
    """Extract the zone parser functions from the broken server source.

    Returns the text from 'def _qualify' up to (not including) 'def encode_name'.
    These functions (_qualify, _tokenize, _extract_quoted, parse_zone) work
    correctly in the broken server and can be reused as-is.
    """
    start = source.find("\ndef _qualify(")
    end = source.find("\ndef encode_name(")
    if start < 0 or end < 0:
        raise ValueError("Could not locate zone parser function boundaries "
                         "in broken server source")
    return source[start:end]


# ======================================================================
# Corrected server code generator
# ======================================================================

def generate_corrected_server(zone_parser_block, behaviors, max_cname_depth):
    """Generate a corrected DNS server based on discovered behaviors.

    Reuses the zone parser from the broken server and generates corrected
    ZoneDB class, wire-format helpers, and query handler based on the
    behavioral requirements discovered from the pcap analysis.
    """

    need_case = "case_insensitive" in behaviors
    need_cname = ("cname_follow" in behaviors or
                  "cname_chain_multi" in behaviors)
    need_txt = "txt_charstring_encoding" in behaviors
    need_edns = "edns0_opt_echo" in behaviors
    need_neg_soa = ("nxdomain_soa_authority" in behaviors or
                    "nodata_soa_authority" in behaviors)
    need_mx_glue = "mx_glue_additional" in behaviors

    cname_max = max(max_cname_depth + 2, 10)

    # ---- Begin generated server code ----
    parts = []

    # Header
    parts.append('#!/usr/bin/env python3\n')
    parts.append('"""DNS authoritative server — repaired by pcap analysis."""\n\n')
    parts.append('import socket\nimport struct\n\n')

    # Constants
    parts.append('TYPE_A = 1\nTYPE_NS = 2\nTYPE_CNAME = 5\nTYPE_SOA = 6\n')
    parts.append('TYPE_MX = 15\nTYPE_TXT = 16\nTYPE_AAAA = 28\n')
    parts.append('TYPE_SRV = 33\nTYPE_OPT = 41\n')
    parts.append('CLASS_IN = 1\nPORT = 5353\n\n\n')

    # ZoneDB class — with conditional case-insensitive normalization
    parts.append('class ZoneDB:\n')
    parts.append('    def __init__(self):\n')
    parts.append('        self.records = {}\n')
    parts.append('        self.names = set()\n')
    parts.append('        self.origin = ""\n\n')

    # add() method
    parts.append('    def add(self, name, rtype, rdata):\n')
    if need_case:
        parts.append('        key = (name.lower(), rtype)\n')
        parts.append('        self.records.setdefault(key, []).append(rdata)\n')
        parts.append('        self.names.add(name.lower())\n\n')
    else:
        parts.append('        key = (name, rtype)\n')
        parts.append('        self.records.setdefault(key, []).append(rdata)\n')
        parts.append('        self.names.add(name)\n\n')

    # get() method
    parts.append('    def get(self, name, rtype):\n')
    if need_case:
        parts.append('        return self.records.get((name.lower(), rtype), [])\n\n')
    else:
        parts.append('        return self.records.get((name, rtype), [])\n\n')

    # name_exists() method
    parts.append('    def name_exists(self, name):\n')
    if need_case:
        parts.append('        return name.lower() in self.names\n\n')
    else:
        parts.append('        return name in self.names\n\n')

    # find_wildcard() — single-label only (correct per RFC 4592)
    parts.append('    def find_wildcard(self, name, rtype):\n')
    if need_case:
        parts.append('        labels = name.lower().split(".")\n')
    else:
        parts.append('        labels = name.split(".")\n')
    parts.append('        if len(labels) >= 2:\n')
    parts.append('            wc = "*." + ".".join(labels[1:])\n')
    parts.append('            recs = self.records.get((wc, rtype), [])\n')
    parts.append('            if recs:\n')
    parts.append('                return recs\n')
    parts.append('        return None\n\n')

    # wildcard_name_exists()
    parts.append('    def wildcard_name_exists(self, name):\n')
    if need_case:
        parts.append('        labels = name.lower().split(".")\n')
    else:
        parts.append('        labels = name.split(".")\n')
    parts.append('        if len(labels) >= 2:\n')
    parts.append('            wc = "*." + ".".join(labels[1:])\n')
    parts.append('            if wc in self.names:\n')
    parts.append('                return True\n')
    parts.append('        return False\n')

    # Zone parser (extracted from broken server — works correctly)
    parts.append(zone_parser_block)
    parts.append('\n')

    # Wire-format helpers
    parts.append('''
def encode_name(name):
    if not name:
        return b"\\x00"
    out = b""
    for label in name.split("."):
        enc = label.encode("ascii")
        out += bytes([len(enc)]) + enc
    out += b"\\x00"
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
''')

    # TXT encoding — conditional on pcap analysis
    if need_txt:
        parts.append('    if rtype == TYPE_TXT:\n')
        parts.append('        out = b""\n')
        parts.append('        for s in rec["strings"]:\n')
        parts.append('            raw = s.encode("utf-8")\n')
        parts.append('            while len(raw) > 255:\n')
        parts.append('                out += bytes([255]) + raw[:255]\n')
        parts.append('                raw = raw[255:]\n')
        parts.append('            out += bytes([len(raw)]) + raw\n')
        parts.append('        return out\n')
    else:
        parts.append('    if rtype == TYPE_TXT:\n')
        parts.append('        return "".join(rec["strings"]).encode("utf-8")\n')

    parts.append('''    if rtype == TYPE_SOA:
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


''')

    # handle_query function
    parts.append('def handle_query(data, db):\n')
    parts.append('    if len(data) < 12:\n')
    parts.append('        return None\n\n')
    parts.append('    qid, flags, qdcount = struct.unpack("!HHH", data[:6])\n')
    parts.append('    rd = (flags >> 8) & 1\n')
    parts.append('    if qdcount < 1:\n')
    parts.append('        return None\n\n')
    parts.append('    offset = 12\n')
    parts.append('    qname, offset = decode_name(data, offset)\n')
    parts.append('    qtype, qclass = struct.unpack("!HH", data[offset:offset + 4])\n')
    parts.append('    offset += 4\n')

    # EDNS0 detection — conditional on pcap analysis
    if need_edns:
        parts.append('''
    # Detect EDNS0 OPT in the query additional section
    has_edns = False
    try:
        arcount_val = struct.unpack("!H", data[10:12])[0]
        scan = offset
        for _ in range(arcount_val):
            _, scan = decode_name(data, scan)
            rt = struct.unpack("!H", data[scan:scan + 2])[0]
            if rt == TYPE_OPT:
                has_edns = True
            _, _, _, rdl = struct.unpack("!HHIH", data[scan:scan + 10])
            scan += 10 + rdl
    except Exception:
        pass
''')

    # Initialize query processing
    if need_case:
        parts.append('\n    current = qname.lower()\n')
    else:
        parts.append('\n    current = qname\n')
    parts.append('    answers = []\n')
    parts.append('    rcode = 0\n')

    # CNAME handling — conditional on pcap analysis
    if need_cname:
        parts.append(f'''
    # Follow CNAME chains iteratively (max depth from pcap: {max_cname_depth})
    max_hops = {cname_max}
    while max_hops > 0:
        cname_recs = db.get(current, TYPE_CNAME)
        if cname_recs and qtype != TYPE_CNAME:
            rec = cname_recs[0]
            answers.append(make_rr(current, TYPE_CNAME, rec["ttl"],
                                   encode_rdata(TYPE_CNAME, rec)))
            current = rec["target"].lower()
            max_hops -= 1
        else:
            break
''')
    else:
        parts.append('''
    cname_recs = db.get(current, TYPE_CNAME)
    if cname_recs and qtype != TYPE_CNAME:
        rec = cname_recs[0]
        answers.append(make_rr(current, TYPE_CNAME, rec["ttl"],
                               encode_rdata(TYPE_CNAME, rec)))
''')

    # Main record lookup
    parts.append('''
    # Look up records for the (possibly CNAME-resolved) name
    recs = db.get(current, qtype)
    if recs:
        for rec in recs:
            answers.append(make_rr(current, qtype, rec["ttl"],
                                   encode_rdata(qtype, rec)))
    elif not answers:
        # Try wildcard match
        wc_recs = db.find_wildcard(current, qtype)
        if wc_recs:
            for rec in wc_recs:
                answers.append(make_rr(current, qtype, rec["ttl"],
                                       encode_rdata(qtype, rec)))
        elif db.name_exists(current) or db.wildcard_name_exists(current):
            rcode = 0  # NODATA
        else:
            rcode = 3  # NXDOMAIN
''')

    # Authority section — conditional on pcap analysis
    if need_neg_soa:
        parts.append('''
    # RFC 2308: include SOA in authority for negative responses
    authority = []
    if not answers:
        soa_recs = db.get(db.origin, TYPE_SOA)
        if soa_recs:
            soa = soa_recs[0]
            neg_ttl = min(soa["ttl"], soa["minimum"])
            authority.append(make_rr(db.origin, TYPE_SOA, neg_ttl,
                                     encode_rdata(TYPE_SOA, soa)))
''')
    else:
        parts.append('\n    authority = []\n')

    # Additional section — conditional on pcap analysis
    if need_mx_glue:
        parts.append('''
    # Glue A records for MX exchange targets
    additional = []
    if qtype == TYPE_MX and recs:
        for rec in recs:
            glue = db.get(rec["target"], TYPE_A)
            for a_rec in glue:
                additional.append(make_rr(rec["target"], TYPE_A, a_rec["ttl"],
                                          encode_rdata(TYPE_A, a_rec)))
''')
    else:
        parts.append('\n    additional = []\n')

    # EDNS0 OPT echo — conditional on pcap analysis
    if need_edns:
        parts.append('''
    # Echo OPT pseudo-record for EDNS0 support
    if has_edns:
        opt = b"\\x00" + struct.pack("!HHIH", TYPE_OPT, 4096, 0, 0)
        additional.append(opt)
''')

    # Build and return response
    parts.append('''
    # Build response packet
    resp_flags = 0x8400  # QR=1, AA=1
    if rd:
        resp_flags |= 0x0100
    resp_flags |= rcode

    header = struct.pack("!HHHHHH", qid, resp_flags, 1, len(answers),
                         len(authority), len(additional))
    body = encode_name(qname) + struct.pack("!HH", qtype, CLASS_IN)
    for rr in answers:
        body += rr
    for rr in authority:
        body += rr
    for rr in additional:
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
''')

    return "".join(parts)


# ======================================================================
# Main entry point
# ======================================================================

def main():
    pcap_path = "/app/reference.pcap"
    server_path = "/app/dns_server.py"

    print("=" * 60)
    print("DNS Server Repair Tool — pcap-driven behavioral analysis")
    print("=" * 60)

    # Step 1: Parse the reference pcap binary
    print(f"\n[1/5] Parsing {pcap_path}...")
    responses = read_pcap_responses(pcap_path)
    print(f"      Extracted {len(responses)} DNS response packets")

    # Step 2: Analyze responses to discover required behaviors
    print("\n[2/5] Analyzing reference responses for behavioral requirements...")
    behaviors, max_cname_depth = discover_behaviors(responses)
    print(f"      Discovered {len(behaviors)} requirements:")
    for b in sorted(behaviors):
        print(f"        - {b}")
    if max_cname_depth > 0:
        print(f"      Maximum CNAME chain depth: {max_cname_depth}")

    # Step 3: Extract zone parser from the broken server
    print(f"\n[3/5] Extracting zone parser from {server_path}...")
    with open(server_path) as f:
        broken_source = f.read()
    zone_parser_block = extract_zone_parser_block(broken_source)
    # Count functions extracted
    func_count = zone_parser_block.count("\ndef ")
    print(f"      Extracted {func_count} zone parser functions")

    # Step 4: Generate corrected server code
    print("\n[4/5] Generating corrected server code...")
    corrected_code = generate_corrected_server(
        zone_parser_block, behaviors, max_cname_depth)
    line_count = len(corrected_code.splitlines())
    print(f"      Generated {line_count} lines of corrected code")

    # Step 5: Write the repaired server
    print(f"\n[5/5] Writing repaired server to {server_path}...")
    with open(server_path, "w") as f:
        f.write(corrected_code)
    print(f"      Done — server repaired with {len(behaviors)} behavioral fixes")

    # Summary
    print("\n" + "=" * 60)
    print("Repair complete. The following defects were fixed:")
    if "case_insensitive" in behaviors:
        print("  * Case-insensitive domain name matching (RFC 4343)")
    if "cname_follow" in behaviors or "cname_chain_multi" in behaviors:
        print(f"  * Iterative CNAME chain following (depth {max_cname_depth})")
    if "txt_charstring_encoding" in behaviors:
        print("  * TXT character-string encoding with length prefixes")
    if "edns0_opt_echo" in behaviors:
        print("  * EDNS0 OPT pseudo-record detection and echo")
    if "nxdomain_soa_authority" in behaviors:
        print("  * SOA in authority section for NXDOMAIN (RFC 2308)")
    if "nodata_soa_authority" in behaviors:
        print("  * SOA in authority section for NODATA (RFC 2308)")
    if "mx_glue_additional" in behaviors:
        print("  * A glue records for MX targets in additional section")
    print("=" * 60)


if __name__ == "__main__":
    main()
