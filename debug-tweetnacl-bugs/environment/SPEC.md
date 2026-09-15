# NaCl Vault Format v1

## Overview

NaCl Vault encrypts a file for one or more recipients using a hybrid scheme:
a random 32-byte content key encrypts the file data with `crypto_secretbox`
(XSalsa20-Poly1305), and each recipient receives a copy of the content key
encrypted with `crypto_box` (Curve25519-XSalsa20-Poly1305) using a freshly
generated ephemeral keypair.

## Binary Format

### Header (40 bytes)

| Offset | Size | Field                                         |
|--------|------|-----------------------------------------------|
| 0      | 4    | Magic: ASCII `NV01`                           |
| 4      | 1    | Version: `0x01`                               |
| 5      | 1    | Reserved: `0x00`                              |
| 6      | 2    | Recipient count N (uint16 little-endian, 1–256)|
| 8      | 24   | File nonce (24 random bytes)                   |
| 32     | 8    | Plaintext length (uint64 little-endian)        |

### Recipient Records (N × 104 bytes each)

Each record wraps the 32-byte content key for one recipient:

| Offset | Size | Field                                                               |
|--------|------|---------------------------------------------------------------------|
| 0      | 32   | Ephemeral sender public key                                         |
| 32     | 24   | Box nonce (derived from file nonce — method chosen by implementer)  |
| 56     | 48   | Encrypted content key (crypto_box output bytes 16..63, i.e. skipping the `crypto_box_BOXZEROBYTES` leading zeros) |

Each recipient MUST use a freshly generated ephemeral keypair. The box nonce
for each recipient MUST be unique; the derivation method is left to the
implementer but must be deterministic given the file nonce and recipient index.

### Encrypted Content (chunked)

The plaintext is split into chunks of exactly **65536 bytes**, except the
final chunk which contains the remaining bytes (1 to 65536). Each chunk is
encrypted independently with `crypto_secretbox` using the content key and
a unique per-chunk nonce.

Each encrypted chunk stored in the file:

| Offset | Size       | Field                                                                     |
|--------|------------|---------------------------------------------------------------------------|
| 0      | 16         | Poly1305 authentication tag (crypto_secretbox output bytes 16..31)        |
| 16     | chunk_len  | Encrypted chunk data (crypto_secretbox output bytes 32 onward)            |

The per-chunk nonce MUST be unique across all chunks and MUST be deterministic
from the file nonce and chunk index. The derivation method is left to the
implementer.

For empty files (plaintext length = 0), no encrypted chunk data is written.

### Padding Reminder

NaCl's C API has specific padding requirements:

- `crypto_box` / `crypto_box_open`: input must have `crypto_box_ZEROBYTES` (32)
  leading zero bytes; output has `crypto_box_BOXZEROBYTES` (16) leading zero bytes.
- `crypto_secretbox` / `crypto_secretbox_open`: input must have
  `crypto_secretbox_ZEROBYTES` (32) leading zero bytes; output has
  `crypto_secretbox_BOXZEROBYTES` (16) leading zero bytes.

## Key File Format

- Secret key file: 32 raw bytes (Curve25519 secret scalar)
- Public key file: 32 raw bytes (Curve25519 public point)

## Security Properties

The scheme must provide:

1. **Confidentiality** — only a holder of a recipient secret key can recover the plaintext.
2. **Per-chunk integrity** — any bit flip in a chunk is detected during decryption.
3. **Chunk ordering** — reordering chunks causes decryption failure (because each chunk is encrypted with a nonce tied to its index).
4. **Truncation detection** — the header's plaintext length lets the decryptor verify all expected data was received.

## Error Handling

Exit 0 on success, non-zero on any error. Decryption MUST fail if:

- Magic bytes do not match `NV01`
- No recipient record decrypts successfully with the given key
- Any chunk fails Poly1305 authentication
- Total decrypted length does not match the header's plaintext length field
