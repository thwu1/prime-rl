# ACVP Binary Subprocess Protocol Reference

## Message Framing

Each message (request or response) uses the following binary format:

1. A **uint32 little-endian** giving the number of byte strings *N*
2. *N* consecutive **uint32 little-endian** values, one per byte string, giving each string's length
3. The raw bytes of all *N* strings concatenated in order

For requests, the **first** byte string is always the UTF-8 command name. Responses use the same
framing but the first byte string has no special meaning.

The module loops, processing one request and emitting one response per iteration,
until stdin reaches EOF, then exits with status 0.

## Supported Commands

| Command | Input args (after command name) | Response args |
|---------|-------------------------------|---------------|
| `getConfig` | *(none)* | JSON listing supported algorithms |
| `SHA2-256` | Value to hash | 32-byte digest |
| `HMAC-SHA2-256` | Value to hash, key | 32-byte MAC |
| `AES-256-GCM/seal` | Tag length (4B uint32 LE), key (32B), plaintext, nonce (12B), ad | Ciphertext |
| `AES-256-GCM/open` | Tag length (4B uint32 LE), key (32B), ciphertext, nonce (12B), ad | Success flag (1B: 0x01/0x00), plaintext (empty on failure) |
| `HKDF/SHA2-256` | IKM, salt, info, output length (4B uint32 LE) | OKM |
| `CMAC-AES-256` | Output length (4B uint32 LE), key (32B), message | MAC |
| `PBKDF2-HMAC-SHA256` | Password, salt, iteration count (4B uint32 LE), output length (4B uint32 LE) | Derived key |

### Notes

- **HMAC-SHA2-256**: Per the ACVP specification, the argument order is **value to hash** (message)
  followed by **key**. This differs from the typical cryptographic API convention where key comes first.

- **AES-256-GCM/seal**: Output is a single byte string containing ciphertext concatenated with the
  authentication tag (ciphertext || tag). The tag length is specified in the first input argument.

- **AES-256-GCM/open**: Input ciphertext argument carries ciphertext || tag as a single byte string.
  The tag_length field specifies where to split: the last tag_length bytes are the authentication tag.

- **HKDF/SHA2-256**: Implements RFC 5869 HKDF with extract-and-expand. IKM is the input keying material,
  salt is used in the extract step, info in the expand step, and output length specifies the OKM size.

- **CMAC-AES-256**: Implements AES-256 CMAC per NIST SP 800-38B. The output length specifies the
  number of bytes of MAC to return (up to 16). The key must be exactly 32 bytes. The message may
  be any length including zero.

- **PBKDF2-HMAC-SHA256**: Implements PBKDF2 per RFC 8018 using HMAC-SHA-256 as the PRF. The
  iteration count specifies the number of PBKDF2 iterations. The output length specifies the
  derived key length in bytes. The module must handle arbitrary iteration counts and salt lengths
  as required by ACVP test vectors (i.e., not enforce NIST SP 800-132 minimums).
