#!/usr/bin/env python3
"""Generate synthetic RPKI repository (CMS-signed ROAs, certs) and MRT BGP dump."""

import subprocess
import json
import os
import struct
import socket
import ipaddress
import tempfile
import shutil

REPO_DIR = "/app/rpki_repo"
ROAS_DIR = "/app/rpki_repo/roas"
BGP_DIR = "/app/bgp_data"
RESULTS_DIR = "/app/results"

ROAS = [
    {"id": 1, "asID": 64512, "prefix": "10.0.0.0", "prefixLength": 16, "maxLength": 24},
    {"id": 2, "asID": 64513, "prefix": "10.1.0.0", "prefixLength": 16, "maxLength": 16},
    {"id": 3, "asID": 64520, "prefix": "172.16.0.0", "prefixLength": 12, "maxLength": 20},
    {"id": 4, "asID": 64514, "prefix": "10.2.0.0", "prefixLength": 15, "maxLength": 16},
    {"id": 5, "asID": 64710, "prefix": "192.168.0.0", "prefixLength": 20, "maxLength": 24},
    {"id": 6, "asID": 64711, "prefix": "192.168.16.0", "prefixLength": 20, "maxLength": 24},
    {"id": 7, "asID": 64720, "prefix": "203.0.113.0", "prefixLength": 24, "maxLength": 24},
    {"id": 8, "asID": 64730, "prefix": "2001:db8::", "prefixLength": 32, "maxLength": 64, "afi": "ipv6"},
    {"id": 9, "asID": 64512, "prefix": "10.0.0.0", "prefixLength": 8, "maxLength": 8},
    {"id": 10, "asID": 64515, "prefix": "10.3.0.0", "prefixLength": 16, "maxLength": 24},
]

ROGUE_ROA = {"id": 11, "asID": 64999, "prefix": "192.168.128.0", "prefixLength": 17, "maxLength": 24}

ASPA_RECORDS = [
    {"customer_as": 64512, "provider_set": [64500]},
    {"customer_as": 64513, "provider_set": [64500, 64501]},
    {"customer_as": 64514, "provider_set": [64500]},
    {"customer_as": 64710, "provider_set": [64700]},
    {"customer_as": 64711, "provider_set": [64700]},
    {"customer_as": 64720, "provider_set": [64700, 64710]},
    {"customer_as": 64730, "provider_set": [64700]},
    {"customer_as": 64500, "provider_set": []},
    {"customer_as": 64700, "provider_set": []},
]

BGP_ROUTES = [
    {"route_id": 1,  "prefix": "10.0.1.0/24",          "origin_as": 64512, "as_path": [64512, 64500]},
    {"route_id": 2,  "prefix": "10.1.0.0/16",           "origin_as": 64513, "as_path": [64513, 64500]},
    {"route_id": 3,  "prefix": "10.0.0.0/16",           "origin_as": 64999, "as_path": [64999]},
    {"route_id": 4,  "prefix": "10.1.0.0/24",           "origin_as": 64513, "as_path": [64513]},
    {"route_id": 5,  "prefix": "10.0.5.0/24",           "origin_as": 64512, "as_path": [64512, 64512, 64512, 64500]},
    {"route_id": 6,  "prefix": "172.16.0.0/20",          "origin_as": 64520, "as_path": [64520, 64500]},
    {"route_id": 7,  "prefix": "10.2.0.0/16",           "origin_as": 64514, "as_path": [64514, 64500]},
    {"route_id": 8,  "prefix": "192.168.0.0/24",        "origin_as": 64710, "as_path": [64710, 64700]},
    {"route_id": 9,  "prefix": "192.168.1.0/24",        "origin_as": 64710, "as_path": [64710, 64513, 64700]},
    {"route_id": 10, "prefix": "203.0.113.0/24",        "origin_as": 64720, "as_path": [64720, 64710, 64700]},
    {"route_id": 11, "prefix": "192.168.16.0/24",       "origin_as": 64711, "as_path": [64711, 64512, 64700]},
    {"route_id": 12, "prefix": "2001:db8:1::/64",       "origin_as": 64730, "as_path": [64730, 64700]},
    {"route_id": 13, "prefix": "10.3.0.0/24",           "origin_as": 64515, "as_path": [64515, 64500]},
    {"route_id": 14, "prefix": "10.5.0.0/16",           "origin_as": 64599, "as_path": [64599]},
    {"route_id": 15, "prefix": "2001:db8:2::/48",       "origin_as": 64730, "as_path": [64730, 64700]},
    {"route_id": 16, "prefix": "10.0.0.0/8",            "origin_as": 64512, "as_path": [64512, 64500]},
    {"route_id": 17, "prefix": "192.168.17.0/24",       "origin_as": 64711, "as_path": [64711, 64711, 64711, 64700]},
    {"route_id": 18, "prefix": "10.0.0.0/16",           "origin_as": 64514, "as_path": [64514, 64500]},
    {"route_id": 19, "prefix": "192.168.130.0/24",      "origin_as": 64750, "as_path": [64750, 64700]},
    {"route_id": 20, "prefix": "10.4.0.0/16",           "origin_as": 64516, "as_path": [64516, 64515, 64500]},
]


def run(cmd):
    result = subprocess.run(cmd, check=True, capture_output=True)
    return result


def generate_ca(name, cn, output_dir):
    key_file = os.path.join(output_dir, f"{name}.key")
    cert_file = os.path.join(output_dir, f"{name}.pem")
    run(["openssl", "genpkey", "-algorithm", "EC",
         "-pkeyopt", "ec_paramgen_curve:P-256", "-out", key_file])
    run(["openssl", "req", "-new", "-x509",
         "-key", key_file, "-out", cert_file,
         "-days", "3650", "-subj", f"/CN={cn}",
         "-addext", "basicConstraints=critical,CA:TRUE",
         "-addext", "keyUsage=critical,keyCertSign,cRLSign",
         "-addext", "subjectKeyIdentifier=hash"])
    der_file = os.path.join(output_dir, f"{name}.cer")
    run(["openssl", "x509", "-in", cert_file,
         "-outform", "DER", "-out", der_file])
    return key_file, cert_file


def sign_roa_cms(roa_data, ca_key, ca_cert, output_file, tmp_dir):
    ee_key = os.path.join(tmp_dir, f"ee_{roa_data['id']}.key")
    ee_csr = os.path.join(tmp_dir, f"ee_{roa_data['id']}.csr")
    ee_cert = os.path.join(tmp_dir, f"ee_{roa_data['id']}.pem")
    ext_file = os.path.join(tmp_dir, f"ee_{roa_data['id']}_ext.cnf")

    run(["openssl", "genpkey", "-algorithm", "EC",
         "-pkeyopt", "ec_paramgen_curve:P-256", "-out", ee_key])
    run(["openssl", "req", "-new", "-key", ee_key,
         "-out", ee_csr, "-subj", f"/CN=ROA-EE-{roa_data['id']}"])

    with open(ext_file, 'w') as f:
        f.write("basicConstraints = critical, CA:FALSE\n")
        f.write("keyUsage = critical, digitalSignature\n")

    run(["openssl", "x509", "-req", "-in", ee_csr,
         "-CA", ca_cert, "-CAkey", ca_key, "-CAcreateserial",
         "-out", ee_cert, "-days", "3650",
         "-extfile", ext_file])

    payload_file = os.path.join(tmp_dir, f"payload_{roa_data['id']}.json")
    with open(payload_file, 'w') as f:
        json.dump(roa_data, f)

    run(["openssl", "cms", "-sign",
         "-in", payload_file,
         "-signer", ee_cert, "-inkey", ee_key,
         "-outform", "DER", "-out", output_file,
         "-noattr", "-nodetach"])


def encode_origin_attr():
    return struct.pack('!BBB', 0x40, 1, 1) + struct.pack('!B', 0)


def encode_as_path_attr(as_path):
    segment = struct.pack('!BB', 2, len(as_path))
    for asn in as_path:
        segment += struct.pack('!I', asn)
    flags = 0x40
    attr_type = 2
    if len(segment) > 255:
        flags |= 0x10
        header = struct.pack('!BBH', flags, attr_type, len(segment))
    else:
        header = struct.pack('!BBB', flags, attr_type, len(segment))
    return header + segment


def write_mrt_message(f, timestamp, mrt_type, subtype, body):
    header = struct.pack('!IHHI', timestamp, mrt_type, subtype, len(body))
    f.write(header)
    f.write(body)


def generate_mrt(routes, output_file):
    TIMESTAMP = 1700000000

    with open(output_file, 'wb') as f:
        # PEER_INDEX_TABLE
        collector_id = socket.inet_aton('10.0.0.1')
        view_name = b''
        peer_type = 0x02  # IPv4, 4-byte AS
        peer_bgp_id = socket.inet_aton('10.0.0.2')
        peer_ip = socket.inet_aton('10.0.0.2')
        peer_as = struct.pack('!I', 64500)
        peer_entry = struct.pack('!B', peer_type) + peer_bgp_id + peer_ip + peer_as

        pit_body = (collector_id +
                    struct.pack('!H', len(view_name)) + view_name +
                    struct.pack('!H', 1) + peer_entry)
        write_mrt_message(f, TIMESTAMP, 13, 1, pit_body)

        # RIB entries
        seq = 0
        for route in routes:
            net = ipaddress.ip_network(route['prefix'], strict=False)
            prefix_len = net.prefixlen
            num_prefix_bytes = (prefix_len + 7) // 8
            prefix_bytes = net.network_address.packed[:num_prefix_bytes]

            attrs = encode_origin_attr() + encode_as_path_attr(route['as_path'])

            rib_entry = (struct.pack('!H', 0) +
                        struct.pack('!I', TIMESTAMP) +
                        struct.pack('!H', len(attrs)) +
                        attrs)

            body = (struct.pack('!I', seq) +
                   struct.pack('!B', prefix_len) +
                   prefix_bytes +
                   struct.pack('!H', 1) +
                   rib_entry)

            if isinstance(net, ipaddress.IPv6Network):
                subtype = 4  # RIB_IPV6_UNICAST
            else:
                subtype = 2  # RIB_IPV4_UNICAST

            write_mrt_message(f, TIMESTAMP, 13, subtype, body)
            seq += 1


def main():
    os.makedirs(REPO_DIR, exist_ok=True)
    os.makedirs(ROAS_DIR, exist_ok=True)
    os.makedirs(BGP_DIR, exist_ok=True)
    os.makedirs(RESULTS_DIR, exist_ok=True)

    tmp_dir = tempfile.mkdtemp()
    try:
        ta_key, ta_cert = generate_ca("ta", "RPKI Test Trust Anchor", REPO_DIR)
        rogue_key, rogue_cert = generate_ca("rogue", "ROGUE UNTRUSTED CA", tmp_dir)

        for roa in ROAS:
            output_file = os.path.join(ROAS_DIR, f"roa_{roa['id']:02d}.cms")
            sign_roa_cms(roa, ta_key, ta_cert, output_file, tmp_dir)

        rogue_output = os.path.join(ROAS_DIR, f"roa_{ROGUE_ROA['id']:02d}.cms")
        sign_roa_cms(ROGUE_ROA, rogue_key, rogue_cert, rogue_output, tmp_dir)

        # Remove CA private key and serial file from image
        os.remove(ta_key)
        srl_file = os.path.join(REPO_DIR, "ta.srl")
        if os.path.exists(srl_file):
            os.remove(srl_file)

        # Write ASPA records
        with open(os.path.join(REPO_DIR, "aspa_records.json"), 'w') as f:
            json.dump(ASPA_RECORDS, f, indent=2)

        # Generate MRT BGP dump
        generate_mrt(BGP_ROUTES, os.path.join(BGP_DIR, "rib.mrt"))

    finally:
        shutil.rmtree(tmp_dir)

    print("RPKI repository and BGP data generated successfully.")


if __name__ == '__main__':
    main()
