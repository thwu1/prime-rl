#!/usr/bin/env python3
"""
Fix all bugs in the DNS resolver at /app/dns_resolver.py.

Bugs to fix:
1. parse_record: CNAME data not decoded as domain name (raw bytes instead)
2. decode_name/decode_compressed_name: no compression pointer loop protection
3. DNSCache.get: compares against raw TTL instead of computed expires_at
4. resolve: does not follow CNAME answer chains
5. resolve: does not handle missing glue records (NS without additional A)
"""


import os
import sys

src_path = "/app/dns_resolver.py"
if not os.path.isfile(src_path):
    print(f"ERROR: {src_path} not found", file=sys.stderr)
    sys.exit(1)

with open(src_path, "r") as f:
    code = f.read()

# ── Fix 1: Handle CNAME records in parse_record ──
# CNAME data is a domain name that may use compression pointers.
# The else branch reads raw bytes; we need decode_name for CNAME.
old_parse_record = """\
    if type_ == TYPE_NS:
        data = decode_name(reader)
    elif type_ == TYPE_A:
        data = ip_to_string(reader.read(data_len))
    else:
        data = reader.read(data_len)"""

new_parse_record = """\
    if type_ == TYPE_NS:
        data = decode_name(reader)
    elif type_ == TYPE_CNAME:
        data = decode_name(reader)
    elif type_ == TYPE_A:
        data = ip_to_string(reader.read(data_len))
    else:
        data = reader.read(data_len)"""

if old_parse_record in code:
    code = code.replace(old_parse_record, new_parse_record)
    print("Fix 1 applied: CNAME parse handling")
else:
    print("Fix 1: pattern not found, may already be applied")

# ── Fix 2: Add compression pointer loop detection ──
old_decode = """\
def decode_name(reader):
    parts = []
    while (length := reader.read(1)[0]) != 0:
        if length & 0b1100_0000:
            parts.append(decode_compressed_name(length, reader))
            break
        else:
            parts.append(reader.read(length))
    return b".".join(parts)


def decode_compressed_name(length, reader):
    pointer_bytes = bytes([length & 0b0011_1111]) + reader.read(1)
    pointer = struct.unpack("!H", pointer_bytes)[0]
    current_pos = reader.tell()
    reader.seek(pointer)
    result = decode_name(reader)
    reader.seek(current_pos)
    return result"""

new_decode = """\
def decode_name(reader, _depth=0):
    if _depth > 15:
        raise ValueError("DNS name compression depth exceeded (possible loop)")
    parts = []
    while (length := reader.read(1)[0]) != 0:
        if length & 0b1100_0000:
            parts.append(decode_compressed_name(length, reader, _depth + 1))
            break
        else:
            parts.append(reader.read(length))
    return b".".join(parts)


def decode_compressed_name(length, reader, _depth=0):
    pointer_bytes = bytes([length & 0b0011_1111]) + reader.read(1)
    pointer = struct.unpack("!H", pointer_bytes)[0]
    current_pos = reader.tell()
    reader.seek(pointer)
    result = decode_name(reader, _depth)
    reader.seek(current_pos)
    return result"""

if old_decode in code:
    code = code.replace(old_decode, new_decode)
    print("Fix 2 applied: compression pointer loop detection")
else:
    print("Fix 2: pattern not found, may already be applied")

# ── Fix 3: Cache TTL comparison ──
if "if entry and time.time() < entry.ttl:" in code:
    code = code.replace(
        "if entry and time.time() < entry.ttl:",
        "if entry and time.time() < entry.expires_at:",
    )
    print("Fix 3 applied: cache TTL comparison")
else:
    print("Fix 3: pattern not found, may already be applied")

# ── Fix 4 & 5: CNAME following and missing-glue handling in resolve ──
old_resolve = """\
def resolve(domain_name, record_type=TYPE_A):
    cached = _cache.get(domain_name, record_type)
    if cached:
        return cached

    nameserver = ROOT_SERVER
    while True:
        response = send_query(nameserver, domain_name, record_type)
        if ip := get_answer(response):
            _cache.put(domain_name, record_type, ip, 300)
            return ip
        elif nsIP := get_nameserver_ip(response):
            nameserver = nsIP
        else:
            raise Exception("something went wrong")"""

new_resolve = """\
def get_cname(packet):
    for x in packet.answers:
        if x.type_ == TYPE_CNAME:
            return x.data
    return None


def resolve(domain_name, record_type=TYPE_A):
    cached = _cache.get(domain_name, record_type)
    if cached:
        return cached

    nameserver = ROOT_SERVER
    while True:
        response = send_query(nameserver, domain_name, record_type)
        if ip := get_answer(response):
            _cache.put(domain_name, record_type, ip, 300)
            return ip
        elif cname := get_cname(response):
            target = cname.decode("utf-8") if isinstance(cname, bytes) else cname
            return resolve(target, record_type)
        elif nsIP := get_nameserver_ip(response):
            nameserver = nsIP
        elif ns_domain := get_nameserver(response):
            nameserver = resolve(ns_domain, TYPE_A)
        else:
            raise Exception("something went wrong")"""

if old_resolve in code:
    code = code.replace(old_resolve, new_resolve)
    print("Fix 4/5 applied: CNAME following and missing-glue handling")
else:
    print("Fix 4/5: pattern not found, may already be applied")

with open(src_path, "w") as f:
    f.write(code)

print("All fixes processed successfully.")
