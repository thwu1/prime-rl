#!/usr/bin/env python3
"""
Fix the Cargo workspace feature-resolution and build-script bugs introduced
during the incomplete resolver v1 -> v2 migration.

Eight bugs are repaired across configuration and code:

1. foundation/Cargo.toml: serde not marked optional (dep:serde requires it)
2. foundation/Cargo.toml: serde_json not marked optional (dep:serde_json requires it)
3. Cargo.toml (workspace root): serde missing features = ["derive"]
4. codec/Cargo.toml: hash feature on foundation only in dev-dependencies;
   resolver v2 isolates dev-dep features from normal builds
5. validator/Cargo.toml: validate feature not enabled on foundation
6. server/Cargo.toml: serialize feature not enabled on foundation;
   was leaked from buildutil build-dep under resolver v1
7. server/Cargo.toml: logging feature is [] instead of ["foundation/logging"]
8. server/build.rs: compute_magic uses polynomial rolling hash instead of
   FNV-1a 64-bit, producing wrong PROTOCOL_MAGIC constant
"""

from pathlib import Path


def patch(path: str, old: str, new: str) -> None:
    """Replace the first occurrence of old with new in the file at path."""
    p = Path(path)
    text = p.read_text()
    if old not in text:
        return
    p.write_text(text.replace(old, new, 1))


# -- Bug 1: foundation serde not optional --
patch(
    "/app/crates/foundation/Cargo.toml",
    "serde = { workspace = true }",
    "serde = { workspace = true, optional = true }",
)

# -- Bug 2: foundation serde_json not optional --
patch(
    "/app/crates/foundation/Cargo.toml",
    "serde_json = { workspace = true }",
    "serde_json = { workspace = true, optional = true }",
)

# -- Bug 3: workspace serde missing derive feature --
patch(
    "/app/Cargo.toml",
    'serde = { version = "1.0.210" }',
    'serde = { version = "1.0.210", features = ["derive"] }',
)

# -- Bug 4: codec hash only in dev-deps --
patch(
    "/app/crates/codec/Cargo.toml",
    "foundation = { workspace = true }",
    'foundation = { workspace = true, features = ["hash"] }',
)

# -- Bug 5: validator validate not enabled --
patch(
    "/app/crates/validator/Cargo.toml",
    "foundation = { workspace = true }",
    'foundation = { workspace = true, features = ["validate"] }',
)

# -- Bug 6: server serialize not enabled --
patch(
    "/app/crates/server/Cargo.toml",
    "foundation = { workspace = true }",
    'foundation = { workspace = true, features = ["serialize"] }',
)

# -- Bug 7: server logging doesn't propagate --
patch(
    "/app/crates/server/Cargo.toml",
    "logging = []",
    'logging = ["foundation/logging"]',
)

# -- Bug 8: server build.rs uses wrong hash algorithm --
build_rs = Path("/app/crates/server/build.rs")
text = build_rs.read_text()
text = text.replace(
    "/// Compute a hash for the protocol identifier.\n"
    "fn compute_magic(data: &[u8]) -> u64 {\n"
    "    // Simple polynomial rolling hash\n"
    "    let mut h: u64 = 0;\n"
    "    for &b in data {\n"
    "        h = h.wrapping_mul(31).wrapping_add(b as u64);\n"
    "    }\n"
    "    h\n"
    "}",
    "/// FNV-1a 64-bit hash matching foundation::hash::fnv1a.\n"
    "fn compute_magic(data: &[u8]) -> u64 {\n"
    "    let mut h: u64 = 0xcbf29ce484222325;\n"
    "    for &b in data {\n"
    "        h ^= b as u64;\n"
    "        h = h.wrapping_mul(0x100000001b3);\n"
    "    }\n"
    "    h\n"
    "}",
)
build_rs.write_text(text)

print("All patches applied.")
