#!/usr/bin/env python3
"""
TLV Factory Data Manager

Implements a barebox-inspired Tag-Length-Value binary format for embedded
factory data, with ECDSA-P256 signing, device binding, and security policies.

"""

import argparse
import base64
import binascii
import json
import struct
import sys

import yaml
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

FORMAT_VERSION = 1
HEADER_SIZE = 16
FLAG_SIGNED = 0x0001
FLAG_DEVICE_BOUND = 0x0002


def crc32(data: bytes) -> int:
    return binascii.crc32(data) & 0xFFFFFFFF


def load_yaml(path: str) -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)


# ---- Field type codecs ----

def encode_field(ftype: str, value) -> bytes:
    if ftype == "string":
        return str(value).encode("utf-8")
    if ftype == "mac":
        return bytes(int(p, 16) for p in value.split(":"))
    if ftype == "hex":
        h = value
        if h.startswith(("0x", "0X")):
            h = h[2:]
        return bytes.fromhex(h)
    if ftype == "uint16":
        return struct.pack("<H", int(value))
    if ftype == "uint32":
        return struct.pack("<I", int(value))
    if ftype == "binary":
        return base64.b64decode(value)
    raise ValueError(f"Unknown field type: {ftype}")


def decode_field(ftype: str, data: bytes):
    if ftype == "string":
        return data.decode("utf-8")
    if ftype == "mac":
        return ":".join(f"{b:02X}" for b in data)
    if ftype == "hex":
        return "0x" + data.hex().upper()
    if ftype == "uint16":
        return struct.unpack("<H", data)[0]
    if ftype == "uint32":
        return struct.unpack("<I", data)[0]
    if ftype == "binary":
        return base64.b64encode(data).decode("ascii")
    raise ValueError(f"Unknown field type: {ftype}")


# ---- TLV entry serialization ----

def serialize_entries(schema: dict, data: dict) -> bytes:
    fields = schema["fields"]
    for f in fields:
        if f.get("required", False) and f["name"] not in data:
            raise ValueError(f"Required field '{f['name']}' missing")

    buf = bytearray()
    for f in sorted(fields, key=lambda x: x["tag"]):
        if f["name"] in data:
            val = encode_field(f["type"], data[f["name"]])
            buf.extend(struct.pack("<HH", f["tag"], len(val)))
            buf.extend(val)
    return bytes(buf)


def deserialize_entries(payload: bytes, schema: dict) -> dict:
    by_tag = {f["tag"]: f for f in schema["fields"]}
    result = {}
    off = 0
    while off < len(payload):
        if off + 4 > len(payload):
            raise ValueError(f"Truncated TLV at offset {off}")
        tag, length = struct.unpack("<HH", payload[off:off + 4])
        off += 4
        if off + length > len(payload):
            raise ValueError(f"TLV value overflows payload at offset {off}")
        raw = payload[off:off + length]
        off += length
        if tag in by_tag:
            f = by_tag[tag]
            result[f["name"]] = decode_field(f["type"], raw)
        else:
            result[f"unknown_0x{tag:04X}"] = "0x" + raw.hex().upper()
    return result


# ---- Header helpers ----

def make_header(magic: int, flags: int, payload: bytes) -> bytes:
    return struct.pack("<IHHII", magic, FORMAT_VERSION, flags, len(payload), crc32(payload))


def parse_header(blob: bytes):
    if len(blob) < HEADER_SIZE:
        raise ValueError("Blob shorter than header")
    return struct.unpack("<IHHII", blob[:HEADER_SIZE])


# ---- Signing helpers ----

def sign_data(data: bytes, key_path: str) -> bytes:
    with open(key_path, "rb") as f:
        priv = serialization.load_pem_private_key(f.read(), password=None)
    return priv.sign(data, ec.ECDSA(hashes.SHA256()))


def verify_sig(data: bytes, signature: bytes, key_path: str):
    with open(key_path, "rb") as f:
        pub = serialization.load_pem_public_key(f.read())
    pub.verify(signature, data, ec.ECDSA(hashes.SHA256()))


# ---- High-level operations ----

def cmd_encode(args):
    schema = load_yaml(args.schema)
    with open(args.data, "r") as f:
        data = json.load(f)

    magic = schema["magic"]
    flags = 0

    # Check device binding
    for fld in schema["fields"]:
        if fld.get("device_bind") and fld["name"] in data:
            flags |= FLAG_DEVICE_BOUND
            break

    if args.sign_key:
        flags |= FLAG_SIGNED

    payload = serialize_entries(schema, data)
    header = make_header(magic, flags, payload)
    blob = header + payload

    if args.sign_key:
        sig = sign_data(blob, args.sign_key)
        blob += struct.pack("<H", len(sig)) + sig

    with open(args.output, "wb") as f:
        f.write(blob)


def cmd_decode(args):
    schema = load_yaml(args.schema)
    with open(args.input, "rb") as f:
        blob = f.read()

    magic, version, flags, plen, exp_crc = parse_header(blob)

    if magic != schema["magic"]:
        raise ValueError(f"Magic mismatch: expected 0x{schema['magic']:08X}, got 0x{magic:08X}")
    if version != FORMAT_VERSION:
        raise ValueError(f"Unsupported version: {version}")

    payload_end = HEADER_SIZE + plen
    if payload_end > len(blob):
        raise ValueError("Blob too short for payload")

    payload = blob[HEADER_SIZE:payload_end]
    if crc32(payload) != exp_crc:
        raise ValueError("CRC-32 mismatch")

    # Signature verification
    if flags & FLAG_SIGNED and args.verify_key:
        if payload_end + 2 > len(blob):
            raise ValueError("Missing signature block")
        sig_len = struct.unpack("<H", blob[payload_end:payload_end + 2])[0]
        sig = blob[payload_end + 2:payload_end + 2 + sig_len]
        try:
            verify_sig(blob[:payload_end], sig, args.verify_key)
        except InvalidSignature:
            raise ValueError("Signature verification failed")

    result = deserialize_entries(payload, schema)

    # Device binding
    if args.bind_soc_id:
        if not (flags & FLAG_DEVICE_BOUND):
            raise ValueError("Blob not device-bound")
        bind_field = next((f for f in schema["fields"] if f.get("device_bind")), None)
        if bind_field is None:
            raise ValueError("No device_bind field in schema")
        if bind_field["name"] not in result:
            raise ValueError(f"Bind field '{bind_field['name']}' not in blob")
        def norm(h):
            s = h.lower()
            if s.startswith("0x"):
                s = s[2:]
            return s
        if norm(result[bind_field["name"]]) != norm(args.bind_soc_id):
            raise ValueError("Device binding failed: SoC ID mismatch")

    print(json.dumps(result, indent=2))


def cmd_sign(args):
    with open(args.input, "rb") as f:
        blob = f.read()

    magic, version, flags, plen, exp_crc = parse_header(blob)
    if flags & FLAG_SIGNED:
        raise ValueError("Blob is already signed")

    flags |= FLAG_SIGNED
    new_header = struct.pack("<IHHII", magic, version, flags, plen, exp_crc)
    payload = blob[HEADER_SIZE:HEADER_SIZE + plen]
    data_to_sign = new_header + payload

    sig = sign_data(data_to_sign, args.key)

    with open(args.output, "wb") as f:
        f.write(data_to_sign + struct.pack("<H", len(sig)) + sig)


def cmd_verify(args):
    with open(args.input, "rb") as f:
        blob = f.read()

    magic, version, flags, plen, exp_crc = parse_header(blob)
    if not (flags & FLAG_SIGNED):
        raise ValueError("Blob is not signed")

    payload_end = HEADER_SIZE + plen
    sig_len = struct.unpack("<H", blob[payload_end:payload_end + 2])[0]
    sig = blob[payload_end + 2:payload_end + 2 + sig_len]

    try:
        verify_sig(blob[:payload_end], sig, args.key)
    except InvalidSignature:
        print("Signature INVALID", file=sys.stderr)
        sys.exit(2)

    print("Signature valid")


def cmd_policy_filter(args):
    schema = load_yaml(args.schema)
    policy = load_yaml(args.policy)
    with open(args.input, "rb") as f:
        blob = f.read()

    _, _, flags, plen, _ = parse_header(blob)
    rules = policy["rules"]

    if not rules.get("allow_unsigned", False) and not (flags & FLAG_SIGNED):
        raise ValueError(f"Policy '{policy['name']}' rejects unsigned blobs")

    if not rules.get("allow_unbound_device", False) and not (flags & FLAG_DEVICE_BOUND):
        raise ValueError(f"Policy '{policy['name']}' rejects unbound blobs")

    # Signature check if applicable
    if (flags & FLAG_SIGNED) and args.verify_key:
        payload_end = HEADER_SIZE + plen
        sig_len = struct.unpack("<H", blob[payload_end:payload_end + 2])[0]
        sig = blob[payload_end + 2:payload_end + 2 + sig_len]
        try:
            verify_sig(blob[:payload_end], sig, args.verify_key)
        except InvalidSignature:
            raise ValueError("Signature verification failed under policy check")

    payload = blob[HEADER_SIZE:HEADER_SIZE + plen]
    all_fields = deserialize_entries(payload, schema)

    visible = rules.get("visible_fields", [])
    if visible == "all":
        print(json.dumps(all_fields, indent=2))
        return

    filtered = {k: v for k, v in all_fields.items() if k in visible}
    print(json.dumps(filtered, indent=2))


def cmd_policy_transition(args):
    from_pol = load_yaml(args.from_policy)
    to_pol = load_yaml(args.to_policy)

    if to_pol.get("priority", 0) < from_pol.get("priority", 0):
        print("Transition DENIED", file=sys.stderr)
        sys.exit(3)

    if from_pol["name"] not in to_pol.get("transitions_from", []):
        print("Transition DENIED", file=sys.stderr)
        sys.exit(3)

    print("Transition ALLOWED")


def main():
    parser = argparse.ArgumentParser(description="TLV Factory Data Manager")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("encode")
    p.add_argument("--schema", required=True)
    p.add_argument("--data", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--sign-key", default=None)

    p = sub.add_parser("decode")
    p.add_argument("--schema", required=True)
    p.add_argument("--input", required=True)
    p.add_argument("--verify-key", default=None)
    p.add_argument("--bind-soc-id", default=None)

    p = sub.add_parser("sign")
    p.add_argument("--input", required=True)
    p.add_argument("--key", required=True)
    p.add_argument("--output", required=True)

    p = sub.add_parser("verify")
    p.add_argument("--input", required=True)
    p.add_argument("--key", required=True)

    p = sub.add_parser("policy-filter")
    p.add_argument("--schema", required=True)
    p.add_argument("--input", required=True)
    p.add_argument("--policy", required=True)
    p.add_argument("--verify-key", default=None)

    p = sub.add_parser("policy-transition")
    p.add_argument("--from-policy", required=True)
    p.add_argument("--to-policy", required=True)
    p.add_argument("--policy-dir", required=True)

    args = parser.parse_args()

    try:
        {"encode": cmd_encode,
         "decode": cmd_decode,
         "sign": cmd_sign,
         "verify": cmd_verify,
         "policy-filter": cmd_policy_filter,
         "policy-transition": cmd_policy_transition}[args.command](args)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
