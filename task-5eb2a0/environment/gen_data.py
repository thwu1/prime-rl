#!/usr/bin/env python3
"""Generate routing security audit data.

Produces:
- MRT TABLE_DUMP_V2 binary RIB snapshot (RFC 6396)
- SQLite RPKI relying party cache (partial VRP set)
- ASN.1 DER-encoded ROA payload files (RFC 6482)
- RRDP snapshot XML with base64-encoded ROA objects (RFC 8182)
- Gzipped tarball of IRR RPSL route objects
- ASPA authorization CSV

"""

import struct, socket, sqlite3, csv, tarfile, io, os, json, ipaddress, sys
import hashlib, base64
from collections import defaultdict

DATA_DIR = "/opt/routing_data"
LOCAL_AS = 64600

# ========== VRPs split across three RPKI data sources ==========

# VRPs in the SQLite relying party validator cache
VRPS_SQLITE = [
    (64500, "192.0.2.0", 24, 24),
    (64501, "198.51.100.0", 24, 24),
    (64502, "203.0.113.0", 24, 28),
    (64510, "10.0.0.0", 8, 24),
    (64511, "10.128.0.0", 16, 24),
    (64520, "10.10.0.0", 16, 16),
    (64521, "10.10.0.0", 16, 24),
    (64522, "10.20.0.0", 16, 20),
    (64523, "10.20.0.0", 16, 20),
    (64524, "10.20.0.0", 16, 20),
    (64530, "10.30.0.0", 16, 24),
    (64530, "10.30.1.0", 24, 24),
    (64530, "10.30.2.0", 24, 24),
    (64540, "2001:db8::", 32, 48),
    (64541, "2001:db8:1::", 48, 48),
    (64540, "2001:db8:2::", 48, 48),
    (64550, "10.40.0.0", 16, 16),
    (64551, "10.50.0.0", 16, 20),
    (64552, "10.60.0.0", 14, 24),
    (64555, "10.90.0.0", 16, 16),
    (64590, "2001:db8:a000::", 36, 48),
    (64591, "2001:db8:b000::", 36, 36),
]

# VRPs available ONLY as DER-encoded ROA payload files
VRPS_DER = [
    (64553, "10.70.0.0", 16, 24),
    (64554, "10.80.0.0", 16, 16),
    (64560, "10.200.0.0", 16, 24),
    (64561, "10.200.0.0", 24, 24),
]

# VRPs available ONLY in the RRDP snapshot XML
VRPS_RRDP = [
    (64570, "10.210.0.0", 15, 16),
    (64571, "10.210.0.0", 16, 24),
    (64580, "10.220.0.0", 16, 16),
    (64581, "10.230.0.0", 16, 16),
]

# ========== BGP Routes ==========

BGP_ROUTES = [
    ("192.0.2.0/24", 64500, [64700, 64500]),
    ("198.51.100.0/24", 64501, [64501]),
    ("203.0.113.0/24", 64502, [64800, 64502]),
    ("203.0.113.0/28", 64502, [64502]),
    ("203.0.113.0/28", 64999, [64999]),
    ("203.0.113.128/28", 64502, [64502]),
    ("192.0.2.0/25", 64500, [64500]),
    ("192.0.2.0/24", 64999, [64800, 64999]),
    ("10.0.0.0/8", 64510, [64510]),
    ("10.0.0.0/16", 64510, [64510]),
    ("10.0.0.0/24", 64510, [64510]),
    ("10.0.0.0/24", 64999, [64700, 64999]),
    ("10.0.0.0/25", 64510, [64510]),
    ("10.128.0.0/16", 64511, [64511]),
    ("10.128.1.0/24", 64511, [64511]),
    ("10.128.1.0/24", 64510, [64510]),
    ("10.128.1.0/24", 64999, [64800, 64900, 64999]),
    ("10.10.0.0/16", 64520, [64520]),
    ("10.10.0.0/16", 64521, [64521]),
    ("10.10.1.0/24", 64520, [64520]),
    ("10.10.1.0/24", 64521, [64521]),
    ("10.20.0.0/16", 64522, [64522]),
    ("10.20.0.0/20", 64523, [64523]),
    ("10.20.0.0/20", 64999, [64700, 64800, 64999]),
    ("10.30.0.0/16", 64530, [64530]),
    ("10.30.1.0/24", 64530, [64530]),
    ("10.30.3.0/24", 64530, [64530]),
    ("10.30.1.0/24", 64999, [64999]),
    ("2001:db8::/32", 64540, [64540]),
    ("2001:db8:1::/48", 64541, [64541]),
    ("2001:db8:1::/48", 64540, [64540]),
    ("2001:db8:1::/48", 64999, [64800, 64999]),
    ("2001:db8:3::/48", 64540, [64540]),
    ("2001:db8:3::/48", 64999, [64700, 64999]),
    ("10.40.0.0/16", 64550, [64550]),
    ("10.40.1.0/24", 64550, [64550]),
    ("10.50.0.0/16", 64551, [64551]),
    ("10.50.0.0/20", 64551, [64551]),
    ("10.50.0.0/24", 64551, [64551]),
    ("10.60.0.0/16", 64552, [64552]),
    ("10.60.0.0/24", 64552, [64552]),
    ("10.63.255.0/24", 64552, [64552]),
    ("10.70.0.0/16", 64553, [64553]),
    ("10.80.0.0/16", 64554, [64554]),
    ("10.200.0.0/16", 64560, [64560]),
    ("10.200.0.0/24", 64561, [64561]),
    ("10.200.1.0/24", 64560, [64560]),
    ("10.200.1.0/24", 64561, [64700, 64561]),
    ("10.210.0.0/16", 64571, [64571]),
    ("10.211.0.0/16", 64570, [64570]),
    ("10.211.0.0/16", 64999, [64800, 64900, 64999]),
    ("10.220.0.0/16", 64580, [64580]),
    ("10.230.0.0/16", 64581, [64581]),
    ("172.16.0.0/12", 64999, [64999]),
    ("172.20.0.0/24", 64999, [64800, 64999]),
    ("100.64.0.0/10", 65000, [65000]),
    ("2001:db8:c000::/36", 64999, [64700, 64800, 64999]),
    ("10.90.0.0/16", 64555, [64555]),
    ("2001:db8:a000::/36", 64590, [64590]),
    ("2001:db8:b000::/36", 64591, [64591]),
]

ASPA_OBJECTS = [
    (64500, [64600, 64700]),
    (64501, [64600]),
    (64502, [64600, 64800]),
    (64510, [64600]),
    (64511, [64600, 64700]),
    (64520, [64600]),
    (64521, [64600]),
    (64522, [64600]),
    (64523, [64600]),
    (64524, [64600]),
    (64530, [64600]),
    (64540, [64600]),
    (64541, [64600, 64800]),
    (64550, [64600]),
    (64551, [64600]),
    (64552, [64600]),
    (64553, [64600]),
    (64554, [64600]),
    (64555, [64600]),
    (64560, [64600]),
    (64561, [64600, 64700]),
    (64570, [64600]),
    (64571, [64600]),
    (64580, [64600]),
    (64581, [64600]),
    (64590, [64600]),
    (64591, [64600]),
    (64700, [64600]),
    (64800, [64600]),
    (64900, [64800]),
    (64999, [64900]),
]

IRR_OBJECTS = [
    ("192.0.2.0/24", 64500, "RIPE"),
    ("198.51.100.0/24", 64501, "RIPE"),
    ("203.0.113.0/24", 64502, "RIPE"),
    ("203.0.113.0/28", 64502, "RIPE"),
    ("203.0.113.128/28", 64502, "RIPE"),
    ("192.0.2.0/25", 64500, "RIPE"),
    ("10.0.0.0/8", 64510, "RIPE"),
    ("10.0.0.0/16", 64510, "ARIN"),
    ("10.0.0.0/24", 64510, "ARIN"),
    ("10.0.0.0/25", 64510, "ARIN"),
    ("10.128.0.0/16", 64511, "RIPE"),
    ("10.128.1.0/24", 64511, "RIPE"),
    ("10.10.0.0/16", 64520, "APNIC"),
    ("10.10.1.0/24", 64521, "APNIC"),
    ("10.20.0.0/16", 64522, "RIPE"),
    ("10.20.0.0/20", 64523, "RIPE"),
    ("10.30.0.0/16", 64530, "ARIN"),
    ("10.30.1.0/24", 64530, "ARIN"),
    ("10.30.3.0/24", 64530, "ARIN"),
    ("2001:db8::/32", 64540, "RIPE"),
    ("2001:db8:1::/48", 64541, "RIPE"),
    ("2001:db8:3::/48", 64540, "RIPE"),
    ("10.40.0.0/16", 64550, "RIPE"),
    ("10.40.1.0/24", 64550, "RIPE"),
    ("10.50.0.0/16", 64551, "APNIC"),
    ("10.50.0.0/20", 64551, "APNIC"),
    ("10.50.0.0/24", 64551, "APNIC"),
    ("10.60.0.0/16", 64552, "RIPE"),
    ("10.60.0.0/24", 64552, "RIPE"),
    ("10.63.255.0/24", 64552, "RIPE"),
    ("10.70.0.0/16", 64553, "ARIN"),
    ("10.80.0.0/16", 64554, "ARIN"),
    ("10.200.0.0/16", 64560, "RIPE"),
    ("10.200.0.0/24", 64561, "RIPE"),
    ("10.200.1.0/24", 64560, "RIPE"),
    ("10.210.0.0/16", 64571, "APNIC"),
    ("10.211.0.0/16", 64570, "APNIC"),
    ("10.220.0.0/16", 64580, "RIPE"),
    ("10.230.0.0/16", 64581, "RIPE"),
    ("10.90.0.0/16", 64555, "ARIN"),
    ("2001:db8:a000::/36", 64590, "RIPE"),
    ("2001:db8:b000::/36", 64591, "RIPE"),
]


# ===================== ASN.1 DER ENCODING =====================

def _der_length(n):
    """Encode DER length field."""
    if n < 128:
        return bytes([n])
    elif n < 256:
        return bytes([0x81, n])
    else:
        return bytes([0x82, (n >> 8) & 0xff, n & 0xff])


def _der_tlv(tag, value):
    """Build a DER tag-length-value."""
    return bytes([tag]) + _der_length(len(value)) + value


def _der_integer(val):
    """DER-encode a non-negative INTEGER."""
    if val == 0:
        return _der_tlv(0x02, b'\x00')
    buf = []
    n = val
    while n > 0:
        buf.append(n & 0xff)
        n >>= 8
    buf.reverse()
    if buf[0] & 0x80:
        buf.insert(0, 0)
    return _der_tlv(0x02, bytes(buf))


def _der_sequence(*items):
    """DER-encode a SEQUENCE."""
    return _der_tlv(0x30, b''.join(items))


def _der_octet_string(data):
    """DER-encode an OCTET STRING."""
    return _der_tlv(0x04, data)


def _der_bit_string(data, unused_bits=0):
    """DER-encode a BIT STRING."""
    return _der_tlv(0x03, bytes([unused_bits]) + data)


def _encode_roa_payload(asn, prefix_str, max_length):
    """Encode a ROA payload per RFC 6482 RouteOriginAttestation.

    RouteOriginAttestation ::= SEQUENCE {
       version [0] INTEGER DEFAULT 0,  -- omitted (DER default)
       asID  ASNumber,
       ipAddrBlocks SEQUENCE OF ROAIPAddressFamily
    }
    """
    net = ipaddress.ip_network(prefix_str, strict=False)
    afi = b'\x00\x01' if net.version == 4 else b'\x00\x02'

    plen = net.prefixlen
    nbytes = (plen + 7) // 8
    addr_bytes = net.network_address.packed[:nbytes]
    unused = nbytes * 8 - plen

    # ROAIPAddress ::= SEQUENCE { address BIT STRING, maxLength INTEGER OPTIONAL }
    roa_addr_items = [_der_bit_string(addr_bytes, unused)]
    if max_length != plen:
        roa_addr_items.append(_der_integer(max_length))
    roa_addr = _der_sequence(*roa_addr_items)

    # ROAIPAddressFamily ::= SEQUENCE { addressFamily OCTET STRING, addresses SEQUENCE OF }
    addr_family = _der_sequence(
        _der_octet_string(afi),
        _der_sequence(roa_addr),
    )

    # Top-level SEQUENCE (version omitted per DER default-value rule)
    return _der_sequence(
        _der_integer(asn),
        _der_sequence(addr_family),
    )


# ===================== MRT TABLE_DUMP_V2 GENERATION =====================

def _mrt_record(fh, ts, mtype, stype, payload):
    """Write one MRT common-header + payload (RFC 6396 Section 2)."""
    fh.write(struct.pack('!IHHI', ts, mtype, stype, len(payload)))
    fh.write(payload)


def _bgp_attr(flags, tc, val):
    """Encode a single BGP path attribute (RFC 4271 Section 4.3)."""
    if len(val) > 255:
        return struct.pack('!BBH', flags | 0x10, tc, len(val)) + val
    return struct.pack('!BBB', flags, tc, len(val)) + val


def _as_path_value(path):
    """Build AS_PATH attribute value: one AS_SEQUENCE with 4-byte ASNs."""
    seg = struct.pack('!BB', 2, len(path))
    for a in path:
        seg += struct.pack('!I', a)
    return seg


def _attrs_v4(path, nh_int):
    """BGP attributes for an IPv4 RIB entry."""
    a = _bgp_attr(0x40, 1, b'\x00')
    a += _bgp_attr(0x40, 2, _as_path_value(path))
    a += _bgp_attr(0x40, 3, struct.pack('!I', nh_int))
    a += _bgp_attr(0x40, 5, struct.pack('!I', 100))
    return a


def _attrs_v6(path, nh_packed):
    """BGP attributes for an IPv6 RIB entry (next hop via MP_REACH_NLRI)."""
    a = _bgp_attr(0x40, 1, b'\x00')
    a += _bgp_attr(0x40, 2, _as_path_value(path))
    mp = struct.pack('!HBB', 2, 1, 16) + nh_packed + b'\x00'
    a += _bgp_attr(0x80, 14, mp)
    a += _bgp_attr(0x40, 5, struct.pack('!I', 100))
    return a


def gen_mrt():
    """Generate MRT TABLE_DUMP_V2 binary file (RFC 6396) and collector JSON."""
    ts = 1706745600  # 2024-02-01T00:00:00Z

    peer_asns = sorted(set(asp[0] for _, _, asp in BGP_ROUTES))
    pidx = {a: i for i, a in enumerate(peer_asns)}

    mrt_path = os.path.join(DATA_DIR, "rib_dump.mrt")
    with open(mrt_path, "wb") as fh:
        # PEER_INDEX_TABLE (type=13 subtype=1)
        pit = socket.inet_aton('10.255.0.1')
        pit += struct.pack('!H', 0)
        pit += struct.pack('!H', len(peer_asns))
        for i, a in enumerate(peer_asns):
            pit += struct.pack('!B', 0x02)
            pit += struct.pack('!I', 0xC6120001 + i)
            pit += struct.pack('!I', 0xC6120001 + i)
            pit += struct.pack('!I', a)
        _mrt_record(fh, ts, 13, 1, pit)

        v4grp = defaultdict(list)
        v6grp = defaultdict(list)
        for pfx, orig, asp in BGP_ROUTES:
            (v6grp if ':' in pfx else v4grp)[pfx].append((orig, asp))

        seq = 0

        # RIB_IPV4_UNICAST (type=13 subtype=2)
        for pfx in sorted(v4grp, key=lambda p: ipaddress.ip_network(p, strict=False)):
            net = ipaddress.ip_network(pfx, strict=False)
            ents = v4grp[pfx]
            r = struct.pack('!I', seq); seq += 1
            r += struct.pack('!B', net.prefixlen)
            r += net.network_address.packed[:(net.prefixlen + 7) // 8]
            r += struct.pack('!H', len(ents))
            for _, asp in ents:
                pi = pidx[asp[0]]
                at = _attrs_v4(asp, 0xC6120001 + pi)
                r += struct.pack('!HIH', pi, ts, len(at)) + at
            _mrt_record(fh, ts, 13, 2, r)

        # RIB_IPV6_UNICAST (type=13 subtype=4)
        for pfx in sorted(v6grp, key=lambda p: ipaddress.ip_network(p, strict=False)):
            net = ipaddress.ip_network(pfx, strict=False)
            ents = v6grp[pfx]
            r = struct.pack('!I', seq); seq += 1
            r += struct.pack('!B', net.prefixlen)
            r += net.network_address.packed[:(net.prefixlen + 7) // 8]
            r += struct.pack('!H', len(ents))
            for _, asp in ents:
                pi = pidx[asp[0]]
                nh = ipaddress.IPv6Address(f"fd00::{pi + 1}").packed
                at = _attrs_v6(asp, nh)
                r += struct.pack('!HIH', pi, ts, len(at)) + at
            _mrt_record(fh, ts, 13, 4, r)

    info_path = os.path.join(DATA_DIR, "collector_info.json")
    with open(info_path, "w") as f:
        json.dump({
            "collector_id": "rtr-border-01.example.net",
            "collector_bgp_id": "10.255.0.1",
            "local_as": LOCAL_AS,
            "dump_time": "2024-02-01T00:00:00Z",
        }, f, indent=2)


def gen_sqlite():
    """Generate SQLite RPKI cache with PARTIAL VRP set."""
    path = os.path.join(DATA_DIR, "rpki_cache.db")
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute("""CREATE TABLE validated_roa_payloads (
        asn INTEGER NOT NULL,
        ip_prefix TEXT NOT NULL,
        prefix_length INTEGER NOT NULL,
        max_prefix_length INTEGER NOT NULL,
        trust_anchor TEXT NOT NULL,
        not_before TEXT,
        not_after TEXT,
        serial_number INTEGER
    )""")
    c.execute("CREATE INDEX idx_vrp_prefix ON validated_roa_payloads(ip_prefix, prefix_length)")
    serial = 1000
    for asn, prefix, plen, maxlen in VRPS_SQLITE:
        c.execute(
            "INSERT INTO validated_roa_payloads VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (asn, prefix, plen, maxlen, "RIPE NCC",
             "2024-01-01T00:00:00Z", "2025-12-31T23:59:59Z", serial),
        )
        serial += 1
    conn.commit()
    conn.close()


def gen_roa_der():
    """Generate ASN.1 DER-encoded ROA payload files (RFC 6482)."""
    roa_dir = os.path.join(DATA_DIR, "rpki_objects")
    os.makedirs(roa_dir, exist_ok=True)
    for asn, prefix, plen, maxlen in VRPS_DER:
        prefix_str = f"{prefix}/{plen}"
        der_data = _encode_roa_payload(asn, prefix_str, maxlen)
        h = hashlib.sha256(der_data).hexdigest()[:8]
        fname = f"{h}.roa"
        with open(os.path.join(roa_dir, fname), "wb") as f:
            f.write(der_data)
        print(f"  ROA DER: {fname} (AS{asn}, {prefix_str}, maxLen={maxlen})")


def gen_rrdp():
    """Generate RRDP snapshot XML (RFC 8182) with base64-encoded ROA payloads."""
    session_id = "9df4b597-af9e-4dca-bdda-719cce2c4e28"

    xml_parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<snapshot xmlns="http://www.ripe.net/rpki/rrdp"'
        ' version="1"'
        ' session_id="' + session_id + '"'
        ' serial="42">',
    ]

    for asn, prefix, plen, maxlen in VRPS_RRDP:
        prefix_str = f"{prefix}/{plen}"
        der_data = _encode_roa_payload(asn, prefix_str, maxlen)
        b64_data = base64.b64encode(der_data).decode('ascii')
        safe_prefix = prefix_str.replace("/", "-").replace(":", "_")
        uri = f"rsync://rpki.example.net/repo/AS{asn}/{safe_prefix}.roa"
        xml_parts.append(f'  <publish uri="{uri}">')
        xml_parts.append(f'    {b64_data}')
        xml_parts.append('  </publish>')

    xml_parts.append('</snapshot>')

    rrdp_path = os.path.join(DATA_DIR, "rrdp_snapshot.xml")
    with open(rrdp_path, "w") as f:
        f.write('\n'.join(xml_parts) + '\n')


def gen_irr():
    path = os.path.join(DATA_DIR, "irr_objects.tar.gz")
    with tarfile.open(path, "w:gz") as tar:
        for prefix, asn, source in IRR_OBJECTS:
            is_ipv6 = ":" in prefix
            obj_type = "route6" if is_ipv6 else "route"
            origin_str = f"AS{asn}"
            content = (
                f"{obj_type}:          {prefix}\n"
                f"descr:          {origin_str} address block\n"
                f"origin:         {origin_str}\n"
                f"mnt-by:         MAINT-{origin_str}\n"
                f"created:        2024-01-15T10:30:00Z\n"
                f"last-modified:  2024-06-01T14:20:00Z\n"
                f"source:         {source}\n"
            )
            data = content.encode("utf-8")
            safe = prefix.replace("/", "_").replace(":", "-")
            fname = f"irr_export/{obj_type}_{safe}.rpsl"
            info = tarfile.TarInfo(name=fname)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


def gen_aspa():
    path = os.path.join(DATA_DIR, "aspa_authorizations.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["customer_asn", "provider_asn", "afi", "registration_date"])
        for customer, providers in ASPA_OBJECTS:
            for prov in providers:
                w.writerow([customer, prov, "ipv4/ipv6", "2024-03-15"])


if __name__ == "__main__":
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        gen_mrt()
        gen_sqlite()
        gen_roa_der()
        gen_rrdp()
        gen_irr()
        gen_aspa()
    except Exception as e:
        print(f"ERROR generating data: {e}", file=sys.stderr)
        sys.exit(1)

    # Verify all expected files exist
    expected = ["rib_dump.mrt", "collector_info.json", "rpki_cache.db",
                "irr_objects.tar.gz", "aspa_authorizations.csv",
                "rrdp_snapshot.xml"]
    for fname in expected:
        fpath = os.path.join(DATA_DIR, fname)
        if not os.path.exists(fpath):
            print(f"MISSING: {fpath}", file=sys.stderr)
            sys.exit(1)
        size = os.path.getsize(fpath)
        print(f"  {fname}: {size} bytes")

    roa_dir = os.path.join(DATA_DIR, "rpki_objects")
    roa_count = len([f for f in os.listdir(roa_dir) if f.endswith('.roa')])
    if roa_count != len(VRPS_DER):
        print(f"MISSING ROA files: expected {len(VRPS_DER)}, found {roa_count}",
              file=sys.stderr)
        sys.exit(1)
    print(f"  rpki_objects/: {roa_count} ROA files")

    print("Data generated successfully.")
