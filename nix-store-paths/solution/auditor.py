#!/usr/bin/env python3
"""
Nix Binary Cache Integrity Auditor — Solution

Parses narinfo files, verifies store path integrity, classifies entries.

"""

import hashlib
import base64
import json
import os
import glob

NIX32_CHARS = '0123456789abcdfghijklmnpqrsvwxyz'
NIX32_SET = set(NIX32_CHARS)
HEX_SET = set('0123456789abcdef')


def to_nix32(data: bytes) -> str:
    """Encode raw bytes as Nix base-32 string."""
    bit_count = len(data) * 8
    hash_len = (bit_count + 4) // 5
    result = []
    for n in range(hash_len - 1, -1, -1):
        b = 0
        for bit in range(5):
            src_bit = n * 5 + bit
            if src_bit < bit_count:
                byte_idx = src_bit // 8
                bit_idx = src_bit % 8
                if data[byte_idx] & (1 << bit_idx):
                    b |= 1 << bit
        result.append(NIX32_CHARS[b])
    return ''.join(result)


def from_nix32(s: str) -> bytes:
    """Decode Nix base-32 string to raw bytes."""
    hash_len = len(s)
    total_bits = hash_len * 5
    byte_count = total_bits // 8

    result = bytearray(byte_count)
    for i, c in enumerate(s):
        n = hash_len - 1 - i
        val = NIX32_CHARS.index(c)
        for bit in range(5):
            if val & (1 << bit):
                src_bit = n * 5 + bit
                if src_bit < byte_count * 8:
                    byte_idx = src_bit // 8
                    bit_idx = src_bit % 8
                    result[byte_idx] |= (1 << bit_idx)
    return bytes(result)


def compress_hash(digest: bytes, target_size: int = 20) -> bytes:
    """XOR-fold hash to target_size bytes."""
    result = bytearray(target_size)
    for i, b in enumerate(digest):
        result[i % target_size] ^= b
    return bytes(result)


def compute_store_path(content_hash_hex: str, name: str, dtype: str,
                       references: list = None) -> str:
    """Compute Nix store path for a given derivation type."""
    if references is None:
        references = []

    if dtype == 'flat':
        inner = hashlib.sha256(
            f'fixed:out:sha256:{content_hash_hex}:'.encode()
        ).hexdigest()
        fingerprint = f'output:out:sha256:{inner}:/nix/store:{name}'
    elif dtype == 'recursive':
        fingerprint = f'source:sha256:{content_hash_hex}:/nix/store:{name}'
    elif dtype == 'text':
        sorted_refs = sorted(references)
        refs_part = ':'.join(sorted_refs)
        if refs_part:
            fingerprint = f'text:{content_hash_hex}:{refs_part}:/nix/store:{name}'
        else:
            fingerprint = f'text:{content_hash_hex}:/nix/store:{name}'
    else:
        raise ValueError(f"Unknown derivation type: {dtype}")

    digest = hashlib.sha256(fingerprint.encode()).digest()
    compressed = compress_hash(digest, 20)
    store_hash = to_nix32(compressed)
    return f'/nix/store/{store_hash}-{name}'


def parse_narinfo(filepath: str) -> dict:
    """Parse a narinfo file into a dict of key-value pairs."""
    result = {}
    with open(filepath) as f:
        for line in f:
            line = line.rstrip('\n')
            if ':' in line:
                key, _, value = line.partition(':')
                result[key.strip()] = value.strip()
    return result


def decode_ca_field(ca_value: str):
    """
    Parse the CA field and return (derivation_type, hash_hex) or raise ValueError.
    """
    if ca_value.startswith('fixed:r:'):
        dtype = 'recursive'
        hash_spec = ca_value[len('fixed:r:'):]
    elif ca_value.startswith('fixed:'):
        dtype = 'flat'
        hash_spec = ca_value[len('fixed:'):]
    elif ca_value.startswith('text:'):
        dtype = 'text'
        hash_spec = ca_value[len('text:'):]
    else:
        raise ValueError(f"Unrecognized CA prefix: {ca_value}")

    if hash_spec.startswith('sha256-'):
        b64_value = hash_spec[len('sha256-'):]
        try:
            raw = base64.b64decode(b64_value, validate=True)
        except Exception as e:
            raise ValueError(f"Content hash is not valid base64 encoding: {e}")
        if len(raw) != 32:
            raise ValueError(f"Decoded hash is {len(raw)} bytes, expected 32")
        return dtype, raw.hex()

    elif hash_spec.startswith('sha256:'):
        value = hash_spec[len('sha256:'):]

        if len(value) == 64 and all(c in HEX_SET for c in value):
            return dtype, value

        if len(value) == 52 and all(c in NIX32_SET for c in value):
            raw = from_nix32(value)
            return dtype, raw.hex()

        if len(value) == 64:
            bad_chars = [c for c in value if c not in HEX_SET]
            raise ValueError(
                f"Content hash contains invalid hexadecimal characters: "
                f"{''.join(set(bad_chars))}"
            )
        if len(value) == 52:
            bad_chars = [c for c in value if c not in NIX32_SET]
            raise ValueError(
                f"Content hash contains characters not in Nix base-32 "
                f"alphabet: {''.join(set(bad_chars))}"
            )

        raise ValueError(f"Unrecognized hash format: length={len(value)}")
    else:
        raise ValueError(f"Unrecognized hash specification: {hash_spec}")


def hex_to_sri(hex_hash: str) -> str:
    return f'sha256-{base64.b64encode(bytes.fromhex(hex_hash)).decode()}'


def hex_to_nix32(hex_hash: str) -> str:
    return to_nix32(bytes.fromhex(hex_hash))


def audit_entry(filepath: str) -> dict:
    """Audit a single narinfo file and return the result entry."""
    filename = os.path.basename(filepath)
    fields = parse_narinfo(filepath)

    store_path = fields.get('StorePath', '')

    sp_suffix = store_path[len('/nix/store/'):]
    name = sp_suffix[33:]

    refs_str = fields.get('References', '').strip()
    if refs_str:
        ref_suffixes = refs_str.split()
        references = [f'/nix/store/{r}' for r in ref_suffixes]
    else:
        references = []

    if 'CA' not in fields or not fields['CA'].strip():
        return {
            "filename": filename,
            "status": "missing_field",
            "store_path": store_path,
            "computed_path": None,
            "content_hash_hex": None,
            "content_hash_nix32": None,
            "content_hash_sri": None,
            "derivation_type": None,
            "error_detail": "Required CA field is missing from narinfo file",
        }

    ca_value = fields['CA'].strip()

    try:
        dtype, content_hash_hex = decode_ca_field(ca_value)
    except ValueError as e:
        if ca_value.startswith('fixed:r:'):
            err_dtype = 'recursive'
        elif ca_value.startswith('fixed:'):
            err_dtype = 'flat'
        elif ca_value.startswith('text:'):
            err_dtype = 'text'
        else:
            err_dtype = None
        return {
            "filename": filename,
            "status": "hash_format_error",
            "store_path": store_path,
            "computed_path": None,
            "content_hash_hex": None,
            "content_hash_nix32": None,
            "content_hash_sri": None,
            "derivation_type": err_dtype,
            "error_detail": str(e),
        }

    computed_path = compute_store_path(content_hash_hex, name, dtype, references)

    hash_hex = content_hash_hex
    hash_nix32 = hex_to_nix32(content_hash_hex)
    hash_sri = hex_to_sri(content_hash_hex)

    if computed_path == store_path:
        return {
            "filename": filename,
            "status": "valid",
            "store_path": store_path,
            "computed_path": computed_path,
            "content_hash_hex": hash_hex,
            "content_hash_nix32": hash_nix32,
            "content_hash_sri": hash_sri,
            "derivation_type": dtype,
            "error_detail": None,
        }

    all_types = ['flat', 'recursive', 'text']
    matching_type = None
    for alt_type in all_types:
        if alt_type == dtype:
            continue
        alt_refs = references if alt_type == 'text' else []
        alt_path = compute_store_path(content_hash_hex, name, alt_type, alt_refs)
        if alt_path == store_path:
            matching_type = alt_type
            break

    if matching_type is not None:
        return {
            "filename": filename,
            "status": "type_inconsistency",
            "store_path": store_path,
            "computed_path": computed_path,
            "content_hash_hex": hash_hex,
            "content_hash_nix32": hash_nix32,
            "content_hash_sri": hash_sri,
            "derivation_type": dtype,
            "error_detail": (
                f"Claimed derivation type is '{dtype}' but store path "
                f"matches '{matching_type}' computation"
            ),
        }

    return {
        "filename": filename,
        "status": "path_mismatch",
        "store_path": store_path,
        "computed_path": computed_path,
        "content_hash_hex": hash_hex,
        "content_hash_nix32": hash_nix32,
        "content_hash_sri": hash_sri,
        "derivation_type": dtype,
        "error_detail": (
            "StorePath hash does not match recomputed path from CA content hash"
        ),
    }


def main():
    cache_dir = '/app/cache'
    narinfo_files = sorted(glob.glob(os.path.join(cache_dir, '*.narinfo')))

    results = []
    for filepath in narinfo_files:
        entry = audit_entry(filepath)
        results.append(entry)

    results.sort(key=lambda e: e['filename'])

    status_counts = {}
    for entry in results:
        s = entry['status']
        status_counts[s] = status_counts.get(s, 0) + 1

    summary = {
        "total": len(results),
        "valid": status_counts.get("valid", 0),
        "path_mismatch": status_counts.get("path_mismatch", 0),
        "hash_format_error": status_counts.get("hash_format_error", 0),
        "type_inconsistency": status_counts.get("type_inconsistency", 0),
        "missing_field": status_counts.get("missing_field", 0),
    }

    report = {
        "audit_results": results,
        "summary": summary,
    }

    with open('/app/audit_report.json', 'w') as f:
        json.dump(report, f, indent=2)

    print(f"Audited {len(results)} narinfo files -> /app/audit_report.json")
    print(f"Summary: {json.dumps(summary)}")


if __name__ == '__main__':
    main()
