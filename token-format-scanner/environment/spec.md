# GitHub Authentication Token Format Specification

## Overview

GitHub authentication tokens use an identifiable format designed for efficient secret scanning.
Each token consists of three parts: an **identifiable prefix**, a **random body**, and a **CRC32 checksum**.

## Token Structure

A complete token is exactly **40 characters** long:

```
<prefix>_<body><checksum>
 3 chars  30 chars  6 chars
```

- **Prefix** (3 characters): Identifies the token type:
  - `ghp` - Personal access token
  - `gho` - OAuth access token
  - `ghu` - User-to-server token
  - `ghs` - Server-to-server token
  - `ghr` - Refresh token

- **Separator**: A single underscore `_` after the prefix.

- **Body** (30 characters): Random data encoded in Base62.

- **Checksum** (6 characters): A CRC32 checksum encoded in Base62.

## Base62 Encoding

The Base62 character set is ordered as follows:

```
0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz
```

Position 0 = `'0'`, position 9 = `'9'`, position 10 = `'A'`, position 35 = `'Z'`,
position 36 = `'a'`, position 61 = `'z'`.

Encoding: repeatedly divide the integer by 62 and map each remainder to the character
at that position. The result is padded with leading `'0'` characters to reach the
required length.

## CRC32 Checksum Computation

1. Take the **first 34 characters** of the token (prefix + underscore + body), e.g., `ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123`.
2. Compute the CRC32 checksum (ISO 3309 / ITU-T V.42, polynomial `0xEDB88320`) over the UTF-8 bytes of that string.
3. Treat the result as an **unsigned 32-bit integer** (0 to 4294967295).
4. Encode this integer in Base62, zero-padded to exactly 6 characters.
5. Append the 6-character checksum to form the complete 40-character token.

## Validation

To validate a token:
1. Verify total length is 40 characters.
2. Verify the first 3 characters are a known prefix (`ghp`, `gho`, `ghu`, `ghs`, `ghr`).
3. Verify character at position 3 is `_`.
4. Verify all characters from position 4 onward are valid Base62 characters.
5. Recompute the CRC32 checksum from the first 34 characters.
6. Compare the recomputed checksum (Base62-encoded, 6 chars) with the last 6 characters of the token.

## Token Entropy

The 30-character Base62 body provides approximately 178 bits of entropy:

```
log2(62) * 30 ≈ 178.4 bits
```

## Notes

- The underscore separator ensures tokens are not confused with Base64 strings or SHA hashes.
- Old-format GitHub tokens were 40-character hex strings and did NOT have identifiable prefixes or checksums.
- SHA-1 commit hashes are also 40-character hex strings but do not match the `gh[posur]_` prefix pattern.
