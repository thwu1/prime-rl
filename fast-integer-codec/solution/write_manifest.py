#!/usr/bin/env python3
"""
write_manifest.py — Generate /app/bug_manifest.json documenting all
conformance issues found in the fastnum library.
"""

import json

manifest = [
    {
        "function": "uint64_to_dec",
        "category": "data-error",
        "impact": "The powers-of-10 table entry for 10^19 is a duplicate of 10^18, causing all 19-digit numbers to be formatted with an incorrect digit count"
    },
    {
        "function": "dec_to_uint64",
        "category": "off-by-one",
        "impact": "The overflow threshold is set one too high, allowing certain 20-digit inputs near UINT64_MAX to silently wrap around instead of being rejected"
    },
    {
        "function": "bytes_to_hex",
        "category": "wrong-constant",
        "impact": "The nibble-to-hex arithmetic uses an incorrect offset constant, producing wrong characters for hex digits a through f"
    },
    {
        "function": "hex_to_bytes",
        "category": "missing-case",
        "impact": "The hex digit parser only handles uppercase A-F, returning an error for any input containing lowercase hex letters a-f"
    },
    {
        "function": "uint64_mul_overflow",
        "category": "unimplemented",
        "impact": "The function is a stub that always returns 0, failing to detect any multiplication overflow"
    }
]

with open("/app/bug_manifest.json", "w") as f:
    json.dump(manifest, f, indent=2)

print("Bug manifest written to /app/bug_manifest.json")
