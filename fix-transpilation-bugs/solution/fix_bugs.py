#!/usr/bin/env python3
"""Fix semantic bugs in the auto-transpiled Rust code and produce audit report.

"""

import json

RUST_SRC = "/app/rust_src/src/main.rs"

with open(RUST_SRC, "r") as f:
    code = f.read()

audit_entries = []

# Bug 1: rolling_hash XOR shift amount
code = code.replace("h ^= h >> 15;", "h ^= h >> 16;")
audit_entries.append({
    "location": "rolling_hash",
    "root_cause": "Off-by-one in bit shift constant: transpiler converted the C shift-right operand 16 as 15, likely a constant transcription error",
    "severity": "critical",
    "fix_description": "Changed XOR right-shift from 15 to 16 to match C reference hash diffusion step"
})

# Bug 2: decode_varint shift increment
code = code.replace("shift += 8;", "shift += 7;")
audit_entries.append({
    "location": "decode_varint",
    "root_cause": "Transpiler used byte-width (8) instead of varint group-width (7) for the shift increment, misunderstanding the variable-length encoding scheme",
    "severity": "critical",
    "fix_description": "Changed shift increment from 8 to 7 to correctly decode 7-bit groups in variable-length integer encoding"
})

# Bug 3: read_be16 byte order
code = code.replace(
    "((buf[1] as u16) << 8) | buf[0] as u16",
    "((buf[0] as u16) << 8) | buf[1] as u16",
)
audit_entries.append({
    "location": "read_be16",
    "root_cause": "Transpiler swapped byte indices, converting big-endian read into little-endian read — likely defaulting to native x86 byte order",
    "severity": "minor",
    "fix_description": "Swapped buf[0] and buf[1] positions to correctly read big-endian 16-bit values"
})

# Bug 4: negative average cast
code = code.replace(
    "let abs_avg = avg as u64;",
    "let abs_avg = if avg >= 0 { avg as u64 } else { (-avg) as u64 };",
)
audit_entries.append({
    "location": "main (global_hash computation)",
    "root_cause": "Transpiler dropped the conditional abs-value logic from the C ternary expression, casting signed to unsigned directly which wraps negative values",
    "severity": "major",
    "fix_description": "Added conditional absolute value computation before u64 cast to handle negative weighted averages correctly"
})

# Bug 5: sort tiebreak direction
code = code.replace(
    ".then(b.category.cmp(&a.category))",
    ".then(a.category.cmp(&b.category))",
)
audit_entries.append({
    "location": "main (stats sort comparator)",
    "root_cause": "Transpiler reversed the tiebreak comparison operands, sorting categories descending instead of ascending when weighted averages are equal",
    "severity": "major",
    "fix_description": "Reversed category comparison operand order in sort tiebreak to match C ascending behavior"
})

# Bug 6: zigzag_encode uses OR instead of XOR
code = code.replace(
    "((n << 1) | (n >> 63)) as u64",
    "((n << 1) ^ (n >> 63)) as u64",
)
audit_entries.append({
    "location": "zigzag_encode",
    "root_cause": "Transpiler substituted bitwise OR for XOR in the sign-folding expression, causing all negative values to encode incorrectly",
    "severity": "critical",
    "fix_description": "Changed bitwise OR to XOR in zigzag encoding to correctly fold sign bit into the least significant position"
})

# Bug 7: wrong polynomial fingerprint parameters (prime and multiplier)
code = code.replace(
    "const POLY_MOD: u64 = 1000000007;",
    "const POLY_MOD: u64 = 998244353;",
)
code = code.replace(
    "h.wrapping_mul(256).wrapping_add",
    "h.wrapping_mul(257).wrapping_add",
)
audit_entries.append({
    "location": "compute_fingerprint / POLY_MOD constant",
    "root_cause": "Transpiler substituted a common competitive-programming prime (10^9+7) for the actual modulus and used 256 instead of 257 as the base multiplier — likely heuristic constant replacement",
    "severity": "critical",
    "fix_description": "Corrected POLY_MOD from 1000000007 to 998244353 and fingerprint multiplier from 256 to 257"
})

# Bug 8: compact serialization missing delta encoding
code = code.replace(
    '    println!("---\\nCOMPACT_SERIAL:");\n    for s in &stats {',
    '    println!("---\\nCOMPACT_SERIAL:");\n    let mut prev_wavg: i64 = 0;\n    for s in &stats {',
)
code = code.replace(
    "        let zz = zigzag_encode(avg);",
    "        let delta = avg - prev_wavg;\n        prev_wavg = avg;\n        let zz = zigzag_encode(delta);",
)
code = code.replace(
    "            s.category, avg, zz, vlen,",
    "            s.category, delta, zz, vlen,",
)
code = code.replace(
    "        let dec_val = zigzag_decode(dec_zz);\n        if dec_val != avg {\n            println!(\"  ROUNDTRIP_FAIL: expected {} got {}\", avg, dec_val);",
    "        let dec_delta = zigzag_decode(dec_zz);\n        if dec_delta != delta {\n            println!(\"  ROUNDTRIP_FAIL: expected {} got {}\", delta, dec_delta);",
)
audit_entries.append({
    "location": "main (COMPACT_SERIAL loop)",
    "root_cause": "Transpiler completely dropped the delta-encoding stage: it encodes raw weighted averages instead of computing successive differences, omitting the prev_wavg tracking variable and delta computation",
    "severity": "critical",
    "fix_description": "Added prev_wavg state variable and delta computation so compact serialization encodes differences between consecutive weighted averages"
})

with open(RUST_SRC, "w") as f:
    f.write(code)

with open("/app/transpilation_audit.json", "w") as f:
    json.dump(audit_entries, f, indent=2)

print(f"Fixed {len(audit_entries)} semantic bugs and wrote audit report.")
