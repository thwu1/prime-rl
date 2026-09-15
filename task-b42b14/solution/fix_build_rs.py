#!/usr/bin/env python3
"""Fix the build.rs hash algorithm mismatch.

server/build.rs uses a polynomial rolling hash but the runtime
(foundation::hash::fnv1a) uses FNV-1a 64-bit. Replace the build-time
hash with FNV-1a so PROTOCOL_MAGIC matches at runtime.
"""
from pathlib import Path

build_rs = Path("/app/crates/server/build.rs")
text = build_rs.read_text()

old = (
    "/// Compute a hash for the protocol identifier.\n"
    "fn compute_magic(data: &[u8]) -> u64 {\n"
    "    // Simple polynomial rolling hash\n"
    "    let mut h: u64 = 0;\n"
    "    for &b in data {\n"
    "        h = h.wrapping_mul(31).wrapping_add(b as u64);\n"
    "    }\n"
    "    h\n"
    "}"
)

new = (
    "/// FNV-1a 64-bit hash matching foundation::hash::fnv1a.\n"
    "fn compute_magic(data: &[u8]) -> u64 {\n"
    "    let mut h: u64 = 0xcbf29ce484222325;\n"
    "    for &b in data {\n"
    "        h ^= b as u64;\n"
    "        h = h.wrapping_mul(0x100000001b3);\n"
    "    }\n"
    "    h\n"
    "}"
)

text = text.replace(old, new)
build_rs.write_text(text)
print("Fixed build.rs: replaced polynomial hash with FNV-1a 64-bit.")
