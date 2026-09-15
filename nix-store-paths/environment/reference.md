# Nix Store Path Computation for Fixed-Output Derivations

## Overview

Every path in the Nix store (`/nix/store`) is identified by a 32-character hash
prefix derived from the content's cryptographic fingerprint. For Fixed-Output
Derivations (FODs), the store path can be computed entirely from the content hash,
the derivation name, and whether the content is a flat file or a recursive
(NAR-serialized) directory tree.

## Algorithm

### Step 1: Construct the Fingerprint

The fingerprint is a colon-separated string that identifies the content.

**For recursive (directory/NAR) mode:**

```
source:sha256:<content-hash-hex>:/nix/store:<name>
```

**For flat (single file) mode:**

Flat mode uses an additional indirection layer. First, compute an inner hash:

```
inner_hex = hex( SHA-256( "fixed:out:sha256:<content-hash-hex>:" ) )
```

Then construct the fingerprint using the hex digest of this inner hash:

```
output:out:sha256:<inner_hex>:/nix/store:<name>
```

Note: the trailing colon in the inner hash input (`"fixed:out:sha256:<hash>:"`)
is significant. The inner hash is computed over the exact string
`fixed:out:sha256:<hex-encoded-content-hash>:` with no newline.

### Step 2: Hash the Fingerprint

Compute SHA-256 of the UTF-8 encoded fingerprint string (no null terminator).

### Step 3: Compress the Hash

The 32-byte SHA-256 digest is compressed to 20 bytes using XOR folding:

```
compressed = [0] * 20
for i, byte in enumerate(digest):
    compressed[i % 20] ^= byte
```

This is a standard hash truncation technique that preserves entropy better
than simple truncation.

### Step 4: Encode as Nix Base-32

The 20-byte compressed hash is encoded as a 32-character string using Nix's
custom base-32 encoding.

**Nix base-32 alphabet:** `0123456789abcdfghijklmnpqrsvwxyz`

Important: this is **NOT** RFC 4648 base32 or base32hex. Nix uses its own
32-character alphabet consisting of digits 0-9 plus lowercase letters with
`e`, `o`, `t`, and `u` omitted.

**Encoding procedure:**

The 160 bits (20 bytes) are divided into 32 groups of 5 bits. Processing
proceeds from the most significant 5-bit group down to the least significant.

For group at position `n` (0 = least significant, 31 = most significant):
- Extract 5 bits starting at bit offset `n * 5` from the byte array
- Bit 0 of byte 0 is the global least significant bit (LSB-first byte order)
- Within each byte, bit 0 is the least significant bit

The 5-bit value indexes into the alphabet to produce one output character.
Groups are emitted from position 31 down to position 0 (most significant first
in the output string).

### Step 5: Construct the Store Path

```
/nix/store/<nix32-hash>-<name>
```

The hash is always exactly 32 characters, followed by a hyphen, followed by the
derivation name.

## Reference Examples

These known-correct store paths can be used to validate an implementation:

1. **Flat mode**: name=`hello-2.12.3.tar.gz`,
   sha256=`d9b56dd4fe1de178fce2f90dda0b46ce0c40e09da81a7938e49216caf7a4d02e`
   -> `/nix/store/xnayx5pbg2k0fhn1l8iqs8av5wwk7jzm-hello-2.12.3.tar.gz`

2. **Recursive mode**: name=`source`,
   sha256=`a9473adedffe44a24e5a3c0c6d3a6e83791ee3e5ef7294a2e23bd6c0f6f4aa5f`
   -> `/nix/store/hmld88jxy43d7k3s3i77d240idc401m7-source`

3. **Flat mode**: name=`zlib-1.3.1.tar.gz`,
   sha256=`9a93b2b7dfdac77ceba5a558a580e74667dd6fede4585b91eefb60f03b72df23`
   -> `/nix/store/n22iqgfwr3jr08f9hl4140y3sqmrzf2z-zlib-1.3.1.tar.gz`

## References

- Nix source: `src/libstore/store-api.cc` (`makeStorePath`, `makeFixedOutputPath`)
- Nix source: `src/libutil/hash.cc` (`printHash32`)
- NixOS Discourse thread: "Downloading Fixed-Output Derivations from cache.nixos.org"
