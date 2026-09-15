#!/usr/bin/env python3
"""Routing security audit solver.

Parses MRT TABLE_DUMP_V2 binary, decodes ASN.1 DER ROA payloads,
extracts ROAs from RRDP snapshot XML, and cross-references with
IRR and ASPA data.

"""

import struct
import sqlite3
import csv
import tarfile
import re
import json
import os
import base64
import ipaddress
import xml.etree.ElementTree as ET

DATA_DIR = "/opt/routing_data"


# ==================== MRT TABLE_DUMP_V2 PARSER ====================

def parse_mrt_rib(filepath, local_as):
    """Parse MRT TABLE_DUMP_V2 binary (RFC 6396) and extract routes."""
    with open(filepath, 'rb') as f:
        data = f.read()

    routes = []
    off = 0
    while off + 12 <= len(data):
        ts, mtype, stype, length = struct.unpack_from('!IHHI', data, off)
        off += 12
        payload = data[off:off + length]
        off += length

        if mtype != 13 or stype not in (2, 4):
            continue

        is_v6 = (stype == 4)
        p = 4  # skip sequence number

        plen = payload[p]; p += 1
        pbytes = (plen + 7) // 8
        raw = payload[p:p + pbytes]; p += pbytes

        if is_v6:
            padded = raw + b'\x00' * (16 - len(raw))
            addr = str(ipaddress.IPv6Address(padded))
        else:
            padded = raw + b'\x00' * (4 - len(raw))
            addr = str(ipaddress.IPv4Address(padded))
        prefix_str = f"{addr}/{plen}"

        entry_count = struct.unpack_from('!H', payload, p)[0]; p += 2

        for _ in range(entry_count):
            p += 6  # peer_index(2) + originated_time(4)
            attr_len = struct.unpack_from('!H', payload, p)[0]; p += 2
            attr_data = payload[p:p + attr_len]; p += attr_len

            as_path = _extract_as_path(attr_data)
            if as_path:
                routes.append({
                    'prefix': prefix_str,
                    'origin_asn': as_path[-1],
                    'as_path': [local_as] + as_path,
                })

    return routes


def _extract_as_path(attr_data):
    """Extract AS_PATH (type 2) from BGP path attribute bytes."""
    off = 0
    while off < len(attr_data):
        flags = attr_data[off]; off += 1
        tc = attr_data[off]; off += 1
        if flags & 0x10:
            alen = struct.unpack_from('!H', attr_data, off)[0]; off += 2
        else:
            alen = attr_data[off]; off += 1

        if tc == 2:
            path = []
            v = off
            end = off + alen
            while v < end:
                v += 1  # segment type
                seg_len = attr_data[v]; v += 1
                for _ in range(seg_len):
                    asn = struct.unpack_from('!I', attr_data, v)[0]
                    path.append(asn)
                    v += 4
            return path

        off += alen
    return []


# ==================== ASN.1 DER ROA PARSER ====================

def _parse_der_tlv(data, offset=0):
    """Parse one DER TLV: returns (tag, value_bytes, next_offset)."""
    tag = data[offset]; offset += 1
    length = data[offset]; offset += 1
    if length & 0x80:
        n = length & 0x7f
        length = int.from_bytes(data[offset:offset + n], 'big')
        offset += n
    value = data[offset:offset + length]
    return tag, value, offset + length


def _parse_der_items(data):
    """Parse all TLV items from a SEQUENCE body."""
    items = []
    off = 0
    while off < len(data):
        tag, val, off = _parse_der_tlv(data, off)
        items.append((tag, val))
    return items


def _decode_roa_der(der_data):
    """Decode a DER-encoded ROA payload (RFC 6482) into VRP dicts.

    RouteOriginAttestation ::= SEQUENCE {
       version [0] INTEGER DEFAULT 0,
       asID  ASNumber,
       ipAddrBlocks SEQUENCE OF ROAIPAddressFamily
    }
    """
    tag, outer, _ = _parse_der_tlv(der_data, 0)
    assert tag == 0x30, f"Expected SEQUENCE (0x30), got 0x{tag:02x}"
    items = _parse_der_items(outer)

    # Skip optional version field (context tag 0x80 or 0xA0)
    idx = 0
    if items[idx][0] in (0x80, 0xA0):
        idx += 1

    # asID (INTEGER)
    assert items[idx][0] == 0x02
    asid = int.from_bytes(items[idx][1], 'big')
    idx += 1

    # ipAddrBlocks (SEQUENCE OF ROAIPAddressFamily)
    assert items[idx][0] == 0x30
    families = _parse_der_items(items[idx][1])

    vrps = []
    for ftag, fval in families:
        assert ftag == 0x30
        fitems = _parse_der_items(fval)

        # addressFamily (OCTET STRING: 2 bytes for AFI)
        assert fitems[0][0] == 0x04
        afi = int.from_bytes(fitems[0][1], 'big')
        is_v6 = (afi == 2)

        # addresses (SEQUENCE OF ROAIPAddress)
        assert fitems[1][0] == 0x30
        addrs = _parse_der_items(fitems[1][1])

        for atag, aval in addrs:
            assert atag == 0x30
            aitems = _parse_der_items(aval)

            # address (BIT STRING)
            assert aitems[0][0] == 0x03
            bs = aitems[0][1]
            unused = bs[0]
            abytes = bs[1:]
            prefix_len = len(abytes) * 8 - unused

            if is_v6:
                padded = abytes + b'\x00' * (16 - len(abytes))
                addr = str(ipaddress.IPv6Address(padded))
            else:
                padded = abytes + b'\x00' * (4 - len(abytes))
                addr = str(ipaddress.IPv4Address(padded))

            # maxLength (INTEGER, optional)
            max_length = prefix_len
            if len(aitems) > 1 and aitems[1][0] == 0x02:
                max_length = int.from_bytes(aitems[1][1], 'big')

            vrps.append({
                "asn": asid,
                "prefix": f"{addr}/{prefix_len}",
                "max_length": max_length,
            })
    return vrps


# ==================== DATA LOADING ====================

def load_vrps_sqlite():
    """Load VRPs from the SQLite relying party cache."""
    conn = sqlite3.connect(f"{DATA_DIR}/rpki_cache.db")
    rows = conn.execute(
        "SELECT asn, ip_prefix, prefix_length, max_prefix_length "
        "FROM validated_roa_payloads"
    ).fetchall()
    conn.close()
    vrps = []
    for asn, ip_prefix, plen, maxlen in rows:
        vrps.append({
            "asn": asn,
            "prefix": f"{ip_prefix}/{plen}",
            "max_length": maxlen,
        })
    return vrps


def load_vrps_der():
    """Load VRPs from DER-encoded ROA payload files."""
    vrps = []
    roa_dir = f"{DATA_DIR}/rpki_objects"
    if not os.path.isdir(roa_dir):
        return vrps
    for fname in sorted(os.listdir(roa_dir)):
        if not fname.endswith('.roa'):
            continue
        with open(os.path.join(roa_dir, fname), 'rb') as f:
            der_data = f.read()
        vrps.extend(_decode_roa_der(der_data))
    return vrps


def load_vrps_rrdp():
    """Load VRPs from RRDP snapshot XML (RFC 8182)."""
    vrps = []
    rrdp_path = f"{DATA_DIR}/rrdp_snapshot.xml"
    if not os.path.exists(rrdp_path):
        return vrps

    ns = {'rrdp': 'http://www.ripe.net/rpki/rrdp'}
    tree = ET.parse(rrdp_path)
    root = tree.getroot()

    for pub in root.findall('rrdp:publish', ns):
        b64_text = pub.text
        if not b64_text:
            continue
        der_data = base64.b64decode(b64_text.strip())
        vrps.extend(_decode_roa_der(der_data))

    return vrps


def load_all_vrps():
    """Load and combine VRPs from all RPKI data sources."""
    vrps = load_vrps_sqlite()
    vrps += load_vrps_der()
    vrps += load_vrps_rrdp()
    return vrps


def load_irr_objects():
    irr = {}
    with tarfile.open(f"{DATA_DIR}/irr_objects.tar.gz", "r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            f = tar.extractfile(member)
            if f is None:
                continue
            content = f.read().decode("utf-8")
            prefix = None
            origin = None
            for line in content.split("\n"):
                if line.startswith("route:") or line.startswith("route6:"):
                    prefix = line.split(":", 1)[1].strip()
                elif line.startswith("origin:"):
                    origin_str = line.split(":", 1)[1].strip()
                    origin = int(re.sub(r"^AS", "", origin_str, flags=re.IGNORECASE))
            if prefix and origin is not None:
                irr[prefix] = origin
    return irr


def load_aspa():
    aspa_map = {}
    with open(f"{DATA_DIR}/aspa_authorizations.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            customer = int(row["customer_asn"])
            provider = int(row["provider_asn"])
            if customer not in aspa_map:
                aspa_map[customer] = set()
            aspa_map[customer].add(provider)
    return aspa_map


# ==================== VALIDATION LOGIC ====================

def parse_net(prefix_str):
    return ipaddress.ip_network(prefix_str, strict=False)


def prefix_covers(vrp_prefix_str, route_prefix_str):
    vrp_net = parse_net(vrp_prefix_str)
    route_net = parse_net(route_prefix_str)
    if vrp_net.version != route_net.version:
        return False
    if vrp_net.prefixlen > route_net.prefixlen:
        return False
    return route_net.subnet_of(vrp_net)


def rov_validate(route, vrps):
    """RFC 6811 Route Origin Validation."""
    route_prefix = route["prefix"]
    route_asn = route["origin_asn"]
    route_plen = parse_net(route_prefix).prefixlen

    covering = [v for v in vrps if prefix_covers(v["prefix"], route_prefix)]
    if not covering:
        return "not_found", None

    for vrp in covering:
        if vrp["asn"] == route_asn and route_plen <= vrp["max_length"]:
            return "valid", None

    has_matching_asn = any(v["asn"] == route_asn for v in covering)
    if has_matching_asn:
        return "invalid", "length"
    else:
        return "invalid", "as"


def aspa_validate(as_path, aspa_map):
    """ASPA path validation from origin toward observer."""
    if len(as_path) <= 1:
        return "valid"

    has_unknown = False
    for i in range(len(as_path) - 1, 0, -1):
        customer_asn = as_path[i]
        provider_asn = as_path[i - 1]
        if customer_asn in aspa_map:
            if provider_asn in aspa_map[customer_asn]:
                continue
            else:
                return "invalid"
        else:
            has_unknown = True

    return "unknown" if has_unknown else "valid"


# ==================== MAIN ====================

def main():
    with open(f"{DATA_DIR}/collector_info.json") as f:
        collector = json.load(f)
    local_as = collector["local_as"]

    routes = parse_mrt_rib(f"{DATA_DIR}/rib_dump.mrt", local_as)
    vrps = load_all_vrps()
    irr = load_irr_objects()
    aspa_map = load_aspa()

    rpki_valid = 0
    rpki_invalid = 0
    rpki_invalid_as = 0
    rpki_invalid_length = 0
    rpki_not_found = 0
    aspa_valid_count = 0
    aspa_invalid_count = 0
    aspa_unknown_count = 0
    irr_registered = 0
    irr_origin_match = 0
    irr_origin_mismatch = 0
    multi_signal = 0

    for route in routes:
        rov_status, rov_sub = rov_validate(route, vrps)
        if rov_status == "valid":
            rpki_valid += 1
        elif rov_status == "invalid":
            rpki_invalid += 1
            if rov_sub == "as":
                rpki_invalid_as += 1
            else:
                rpki_invalid_length += 1
        else:
            rpki_not_found += 1

        aspa_status = aspa_validate(route["as_path"], aspa_map)
        if aspa_status == "valid":
            aspa_valid_count += 1
        elif aspa_status == "invalid":
            aspa_invalid_count += 1
        else:
            aspa_unknown_count += 1

        prefix = route["prefix"]
        irr_mismatch = False
        if prefix in irr:
            irr_registered += 1
            if irr[prefix] == route["origin_asn"]:
                irr_origin_match += 1
            else:
                irr_origin_mismatch += 1
                irr_mismatch = True

        flags = sum([
            rov_status == "invalid",
            aspa_status == "invalid",
            irr_mismatch,
        ])
        if flags >= 2:
            multi_signal += 1

    unsafe_maxlen = sum(
        1 for v in vrps
        if v["max_length"] - parse_net(v["prefix"]).prefixlen >= 8
    )

    prefix_asns = {}
    for v in vrps:
        prefix_asns.setdefault(v["prefix"], set()).add(v["asn"])
    conflicting = sum(1 for asns in prefix_asns.values() if len(asns) > 1)

    redundant = 0
    for i, vrp in enumerate(vrps):
        for j, other in enumerate(vrps):
            if i == j:
                continue
            if vrp["asn"] != other["asn"]:
                continue
            if other["max_length"] < vrp["max_length"]:
                continue
            if prefix_covers(other["prefix"], vrp["prefix"]):
                vrp_plen = parse_net(vrp["prefix"]).prefixlen
                other_plen = parse_net(other["prefix"]).prefixlen
                if other_plen < vrp_plen:
                    redundant += 1
                    break
                elif other_plen == vrp_plen and other["max_length"] > vrp["max_length"]:
                    redundant += 1
                    break
                elif other_plen == vrp_plen and other["max_length"] == vrp["max_length"] and i > j:
                    redundant += 1
                    break

    results = {
        "total_routes": len(routes),
        "rpki_valid": rpki_valid,
        "rpki_invalid": rpki_invalid,
        "rpki_invalid_as": rpki_invalid_as,
        "rpki_invalid_length": rpki_invalid_length,
        "rpki_not_found": rpki_not_found,
        "rpki_unsafe_maxlength": unsafe_maxlen,
        "rpki_conflicting_prefixes": conflicting,
        "rpki_redundant_roas": redundant,
        "aspa_valid": aspa_valid_count,
        "aspa_invalid": aspa_invalid_count,
        "aspa_unknown": aspa_unknown_count,
        "irr_registered": irr_registered,
        "irr_origin_match": irr_origin_match,
        "irr_origin_mismatch": irr_origin_mismatch,
        "multi_signal_hijack_candidates": multi_signal,
    }

    with open("/app/analysis_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
