#!/usr/bin/env python3
"""
Multi-provider secret token scanner.
Reads provider definitions from providers.json, scans a file corpus,
validates token checksums, and outputs structured results.
"""

import binascii
import hashlib
import hmac
import json
import os
import re
import struct


BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def base62_encode(num, length=6):
    """Encode an unsigned integer as a Base62 string, zero-padded to `length`."""
    if num == 0:
        return BASE62[0] * length
    result = []
    while num > 0:
        result.append(BASE62[num % 62])
        num //= 62
    result.reverse()
    return "".join(result).rjust(length, BASE62[0])


def validate_crc32_base62(prefix_and_body, checksum, cs_length):
    """CRC32 of prefix+body, encoded as Base62."""
    crc = binascii.crc32(prefix_and_body.encode("utf-8")) & 0xFFFFFFFF
    expected = base62_encode(crc, cs_length)
    return expected == checksum


def validate_hmac_sha256_trunc(prefix_and_body, checksum, hmac_key, cs_length):
    """HMAC-SHA256, first `cs_length` hex chars."""
    h = hmac.new(
        hmac_key.encode("utf-8"),
        prefix_and_body.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    expected = h[:cs_length]
    return expected == checksum


def validate_sha256_base62(prefix_and_body, checksum, cs_length):
    """SHA-256, first 4 bytes as big-endian uint32, encoded as Base62."""
    digest = hashlib.sha256(prefix_and_body.encode("utf-8")).digest()
    num = struct.unpack(">I", digest[:4])[0]
    expected = base62_encode(num, cs_length)
    return expected == checksum


def charset_to_regex_class(charset):
    """Convert a charset string to a regex character class."""
    # For alphanumeric charsets, just use the chars directly inside []
    # Escape any regex-special chars that might appear
    escaped = charset.replace("\\", "\\\\").replace("]", "\\]").replace("^", "\\^").replace("-", "\\-")
    return f"[{escaped}]"


def build_provider_scanner(provider):
    """Build regex pattern and validator for a provider."""
    prefixes = provider["prefixes"]
    body_charset = provider["body_charset"]
    body_length = provider["body_length"]
    cs_info = provider["checksum"]
    cs_length = cs_info["length"]
    algorithm = cs_info["algorithm"]

    # Determine checksum charset
    if algorithm in ("crc32_base62", "sha256_base62"):
        cs_charset = BASE62
    elif algorithm == "hmac_sha256_trunc":
        cs_charset = "0123456789abcdef"
    else:
        cs_charset = body_charset

    # Build regex
    prefix_alt = "|".join(re.escape(p) for p in prefixes)
    body_cc = charset_to_regex_class(body_charset)
    cs_cc = charset_to_regex_class(cs_charset)

    pattern = re.compile(
        f"({prefix_alt})"
        f"({body_cc}{{{body_length}}})"
        f"({cs_cc}{{{cs_length}}})"
    )

    return pattern, algorithm, cs_info


def validate_checksum(algorithm, cs_info, prefix, body, checksum):
    """Validate a token's checksum using the provider's algorithm."""
    prefix_and_body = prefix + body
    cs_length = cs_info["length"]

    if algorithm == "crc32_base62":
        return validate_crc32_base62(prefix_and_body, checksum, cs_length)
    elif algorithm == "hmac_sha256_trunc":
        return validate_hmac_sha256_trunc(
            prefix_and_body, checksum, cs_info["hmac_key"], cs_length
        )
    elif algorithm == "sha256_base62":
        return validate_sha256_base62(prefix_and_body, checksum, cs_length)
    else:
        return False


def scan_file(file_path, rel_path, providers_config):
    """Scan a single file for tokens from all providers."""
    findings = []
    try:
        with open(file_path, "r", errors="ignore") as f:
            for line_num, line in enumerate(f, 1):
                for provider, (pattern, algorithm, cs_info) in providers_config:
                    for match in pattern.finditer(line):
                        prefix = match.group(1)
                        body = match.group(2)
                        checksum = match.group(3)

                        valid = validate_checksum(
                            algorithm, cs_info, prefix, body, checksum
                        )

                        body_length = len(body)
                        redacted = prefix + "*" * body_length + checksum

                        findings.append({
                            "file": rel_path,
                            "line": line_num,
                            "provider": provider["name"],
                            "token_redacted": redacted,
                            "checksum_valid": valid,
                        })
    except (IOError, OSError):
        pass
    return findings


def main():
    providers_path = "/app/providers.json"
    corpus_dir = "/app/corpus"
    output_path = "/app/results.json"

    with open(providers_path) as f:
        providers_data = json.load(f)

    providers_config = []
    for provider in providers_data["providers"]:
        pattern, algorithm, cs_info = build_provider_scanner(provider)
        providers_config.append((provider, (pattern, algorithm, cs_info)))

    all_findings = []
    for root, dirs, files in os.walk(corpus_dir):
        for fname in sorted(files):
            fpath = os.path.join(root, fname)
            rel_path = os.path.relpath(fpath, corpus_dir)
            findings = scan_file(fpath, rel_path, providers_config)
            all_findings.extend(findings)

    all_findings.sort(key=lambda x: (x["file"], x["line"]))

    with open(output_path, "w") as f:
        json.dump(all_findings, f, indent=2)

    valid_count = sum(1 for r in all_findings if r["checksum_valid"])
    invalid_count = len(all_findings) - valid_count
    print(f"Scan complete: {len(all_findings)} findings ({valid_count} valid, {invalid_count} invalid)")


if __name__ == "__main__":
    main()
