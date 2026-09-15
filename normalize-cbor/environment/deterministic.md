# RFC 8949 — Deterministically Encoded CBOR

This document excerpts the normative requirements for Core Deterministic
Encoding from RFC 8949 (CBOR, Internet Standard STD 94).

## Section 4.2: Deterministically Encoded CBOR

CBOR allows encoding the same data in multiple ways. A deterministic
encoding profile removes this ambiguity so that two encoders given the
same input always produce byte-identical output.

## Section 4.2.1: Core Deterministic Encoding Requirements

A CBOR encoder producing Core Deterministic Encoded data items MUST
satisfy all of the following:

### Preferred Serialization of Arguments

The argument encoding (initial byte + any following argument bytes)
MUST use the shortest form:

| Argument range       | Additional info | Argument bytes |
|----------------------|-----------------|----------------|
| 0 to 23             | value itself    | 0              |
| 24 to 255           | 24              | 1 (uint8)      |
| 256 to 65535        | 25              | 2 (uint16 BE)  |
| 65536 to 4294967295 | 26              | 4 (uint32 BE)  |
| >= 4294967296        | 27              | 8 (uint64 BE)  |

This applies to all argument uses: integer values (major types 0, 1),
string/array/map lengths (major types 2–5), and tag numbers (major
type 6).

### Preferred Serialization of Floating-Point Values

Floating-point values MUST use the shortest IEEE 754 binary encoding
that preserves the value exactly:

1. If the value roundtrips through binary16 (half-precision),
   encode as half (initial byte 0xF9 + 2 bytes).
2. Otherwise, if it roundtrips through binary32 (single-precision),
   encode as single (initial byte 0xFA + 4 bytes).
3. Otherwise, encode as binary64 (double-precision)
   (initial byte 0xFB + 8 bytes).

The roundtrip test MUST be bit-exact. In particular:

- **Negative zero** (−0.0) MUST be preserved; −0.0 and +0.0 are
  distinct values despite comparing equal in IEEE 754. After encoding
  −0.0 as half-precision and decoding, the sign bit must still be set.

- **NaN** (Not a Number): All NaN values, regardless of payload or
  signaling status, MUST be replaced by the single canonical quiet NaN
  encoded in half-precision: `0xF9 0x7E 0x00`. This holds even if the
  original was single- or double-precision.

### No Indefinite-Length Items

Indefinite-length encoding (additional info = 31) MUST NOT appear in
the output. Convert:
- Indefinite byte/text strings → concatenate chunks into a single
  definite-length string
- Indefinite arrays/maps → definite-length with the counted items

### Map Key Ordering

Map keys MUST be sorted by **bytewise lexicographic order** of their
deterministic encodings:

1. Encode each key into its deterministic (shortest) form
2. Compare the resulting byte strings byte-by-byte, left to right
3. The key whose byte string is a proper prefix of another sorts first

This is a pure byte-level comparison, independent of CBOR type or
semantic meaning. Example deterministic key order:

    0x0A          (unsigned 10, 1 byte)
    0x1864        (unsigned 100, 2 bytes)
    0x20          (negative −1, 1 byte)
    0x617A        (text "z", 2 bytes)
    0x626161      (text "aa", 3 bytes)
    0x811864      (array [100], 3 bytes)
    0x8120        (array [−1], 2 bytes)
    0xF4          (false, 1 byte)

Note that 0x1864 sorts before 0x20 because 0x18 < 0x20 at the first
byte, even though the first encoding is longer than the second.

## Section 4.2.3: Length-First Map Key Ordering (ALTERNATIVE)

Some protocols use an alternative ordering where keys are sorted first
by the length of their deterministic encoding, then bytewise within
keys of equal length. Under length-first, the example above would
instead sort as:

    0x0A          (1 byte)
    0x20          (1 byte)
    0xF4          (1 byte)
    0x1864        (2 bytes)
    0x617A        (2 bytes)
    0x8120        (2 bytes)
    0x626161      (3 bytes)
    0x811864      (3 bytes)

**Length-first ordering is NOT part of Core Deterministic Encoding.**
It is defined separately in Section 4.2.3 for protocols that choose to
use it. Applications implementing Core Deterministic Encoding MUST use
the bytewise lexicographic ordering from Section 4.2.1.
