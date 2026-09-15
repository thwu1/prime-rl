#!/usr/bin/env python3
"""RPKI security audit: CMS ROA extraction, MRT parsing, ROV + ASPA verification."""

import subprocess
import json
import os
import struct
import ipaddress


def extract_verified_roas(roas_dir, ta_cert):
    """Verify each CMS-signed ROA against trust anchor and extract payloads."""
    valid_roas = []
    invalid_files = []

    for fname in sorted(os.listdir(roas_dir)):
        if not fname.endswith('.cms'):
            continue
        cms_path = os.path.join(roas_dir, fname)
        result = subprocess.run(
            ['openssl', 'cms', '-verify',
             '-CAfile', ta_cert,
             '-inform', 'DER',
             '-in', cms_path],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            invalid_files.append(fname)
            continue
        try:
            roa = json.loads(result.stdout)
            valid_roas.append(roa)
        except json.JSONDecodeError:
            invalid_files.append(fname)

    return valid_roas, invalid_files


def parse_mrt(mrt_file):
    """Parse MRT TABLE_DUMP_V2 binary dump to extract BGP routes."""
    with open(mrt_file, 'rb') as f:
        data = f.read()

    routes = []
    pos = 0
    route_id = 1

    while pos < len(data):
        if pos + 12 > len(data):
            break
        timestamp, mrt_type, subtype, length = struct.unpack_from('!IHHI', data, pos)
        pos += 12
        if pos + length > len(data):
            break
        msg = data[pos:pos + length]
        pos += length

        if mrt_type != 13:
            continue
        if subtype == 1:  # PEER_INDEX_TABLE
            continue
        if subtype not in (2, 4):
            continue

        is_ipv6 = (subtype == 4)
        mpos = 0

        seq = struct.unpack_from('!I', msg, mpos)[0]
        mpos += 4

        prefix_len = msg[mpos]
        mpos += 1
        num_prefix_bytes = (prefix_len + 7) // 8
        prefix_bytes = msg[mpos:mpos + num_prefix_bytes]
        mpos += num_prefix_bytes

        if is_ipv6:
            padded = prefix_bytes + b'\x00' * (16 - len(prefix_bytes))
            prefix_addr = str(ipaddress.IPv6Address(padded))
        else:
            padded = prefix_bytes + b'\x00' * (4 - len(prefix_bytes))
            prefix_addr = str(ipaddress.IPv4Address(padded))

        prefix_str = f"{prefix_addr}/{prefix_len}"

        entry_count = struct.unpack_from('!H', msg, mpos)[0]
        mpos += 2
        mpos += 2  # peer index
        mpos += 4  # originated time
        attr_length = struct.unpack_from('!H', msg, mpos)[0]
        mpos += 2
        attrs = msg[mpos:mpos + attr_length]

        as_path = _parse_as_path(attrs)
        origin_as = as_path[0] if as_path else 0

        routes.append({
            'route_id': route_id,
            'prefix': prefix_str,
            'origin_as': origin_as,
            'as_path': as_path,
        })
        route_id += 1

    return routes


def _parse_as_path(attrs):
    """Extract AS_PATH from BGP path attributes (4-byte ASNs)."""
    pos = 0
    while pos < len(attrs):
        flags = attrs[pos]
        attr_type = attrs[pos + 1]
        pos += 2

        if flags & 0x10:
            attr_len = struct.unpack_from('!H', attrs, pos)[0]
            pos += 2
        else:
            attr_len = attrs[pos]
            pos += 1

        if attr_type == 2:
            as_path = []
            spos = pos
            while spos < pos + attr_len:
                seg_type = attrs[spos]
                seg_count = attrs[spos + 1]
                spos += 2
                for _ in range(seg_count):
                    asn = struct.unpack_from('!I', attrs, spos)[0]
                    as_path.append(asn)
                    spos += 4
            return as_path

        pos += attr_len

    return []


def rov(route, roas):
    """Route Origin Validation per RFC 6811."""
    route_net = ipaddress.ip_network(route['prefix'], strict=False)
    origin_as = route['origin_as']

    covering = []
    for roa in roas:
        roa_prefix_str = f"{roa['prefix']}/{roa['prefixLength']}"
        roa_net = ipaddress.ip_network(roa_prefix_str, strict=False)

        if route_net.version != roa_net.version:
            continue
        if not route_net.subnet_of(roa_net):
            continue
        covering.append(roa)

    if not covering:
        return "NotFound"

    for roa in covering:
        if roa['asID'] == origin_as and route_net.prefixlen <= roa['maxLength']:
            return "Valid"

    return "Invalid"


def aspa_upstream(route, aspa_records):
    """ASPA upstream path verification."""
    as_path = route['as_path']

    deduped = [as_path[0]]
    for asn in as_path[1:]:
        if asn != deduped[-1]:
            deduped.append(asn)

    if len(deduped) <= 1:
        return "Valid"

    aspa_map = {}
    for rec in aspa_records:
        aspa_map[rec['customer_as']] = set(rec['provider_set'])

    has_no_attestation = False

    for i in range(len(deduped) - 1):
        customer_as = deduped[i]
        next_as = deduped[i + 1]

        if customer_as not in aspa_map:
            has_no_attestation = True
            continue

        providers = aspa_map[customer_as]
        if next_as not in providers:
            return "Invalid"

    if has_no_attestation:
        return "Unknown"

    return "Valid"


def main():
    ta_cert = '/app/rpki_repo/ta.pem'
    mrt_file = '/app/bgp_data/rib.mrt'
    aspa_file = '/app/rpki_repo/aspa_records.json'

    roas, invalid_files = extract_verified_roas('/app/rpki_repo/roas', ta_cert)
    routes = parse_mrt(mrt_file)

    with open(aspa_file) as f:
        aspa_records = json.load(f)

    validations = []
    for route in routes:
        rov_status = rov(route, roas)
        aspa_status = aspa_upstream(route, aspa_records)
        policy = "REJECT" if rov_status == "Invalid" or aspa_status == "Invalid" else "ACCEPT"

        validations.append({
            'route_id': route['route_id'],
            'prefix': route['prefix'],
            'origin_as': route['origin_as'],
            'as_path': route['as_path'],
            'rov_status': rov_status,
            'aspa_status': aspa_status,
            'policy': policy,
        })

    total_roas = len(roas) + len(invalid_files)
    report = {
        'roa_verification': {
            'total': total_roas,
            'valid': len(roas),
            'invalid': len(invalid_files),
            'invalid_files': invalid_files,
        },
        'route_validations': validations,
    }

    os.makedirs('/app/results', exist_ok=True)
    with open('/app/results/audit_report.json', 'w') as f:
        json.dump(report, f, indent=2)

    print(f"Audit complete: {len(roas)} valid ROAs, {len(invalid_files)} invalid, "
          f"{len(validations)} routes validated.")


if __name__ == '__main__':
    main()
