A security engagement recovered two firmware revisions from an ARM embedded device along with encrypted payloads from each. Audit notes are in `/app/context.txt`.

**Firmware V1** (legacy deployment):
- `/app/memdump.txt` — Memory dump captured via bootloader debug console (hex format)
- `/app/ciphertext.hex` — Encrypted payload

**Firmware V2** (manufacturer's "hardened" update):
- `/app/firmware_v2.bin` — Raw firmware binary
- `/app/ciphertext_v2.hex` — Encrypted payload

Reverse engineer both firmware images to identify the cipher implementation and key storage mechanism used by each. Recover the encryption keys, decrypt both payloads, and produce a comparative security assessment determining whether V2 actually improves on V1's key protection.

Write the decrypted V1 plaintext (no trailing newline) to `/app/answer.txt` and the V2 plaintext to `/app/answer_v2.txt`.

Write a comparative security assessment to `/app/assessment.json` with these fields:
- `v1_algorithm`: cipher algorithm and mode (e.g. `"AES-128-ECB"`)
- `v1_key_hex`: recovered V1 key as lowercase hex
- `v1_key_protection`: description of how V1 protects its key material
- `v1_attack_complexity`: `"low"`, `"medium"`, or `"high"`
- `v2_algorithm`: cipher algorithm and mode
- `v2_key_hex`: recovered V2 key as lowercase hex
- `v2_key_protection`: description of how V2 protects its key material
- `v2_attack_complexity`: `"low"`, `"medium"`, or `"high"`
- `more_secure_version`: `"v1"` or `"v2"` — your evaluation of which has stronger key protection
- `justification`: detailed explanation of your comparative assessment
- `rejected_candidates`: array of objects, each with `hex` (candidate key hex), `reason` (why rejected), and `firmware_version` (`"v1"` or `"v2"`)

Based on the weaknesses you identified in both firmware versions, design and implement a secure key wrapping module at `/app/v3_keywrap.py` that addresses these specific vulnerabilities. The module must define:

- `wrap_key(key: bytes) -> bytes` — accepts a 16-byte AES key, returns an opaque blob (≥512 bytes) that securely embeds the key
- `unwrap_key(blob: bytes) -> bytes` — recovers the original 16-byte key from a blob produced by `wrap_key`

Your design must demonstrably resist the attacks that defeated V1 and V2: the raw key bytes must not appear as a contiguous sequence anywhere in the blob, the key must not be recoverable by applying any single-byte XOR across the blob, and the scheme must detect tampering (corrupted blobs must not silently return incorrect keys). The module must round-trip correctly for arbitrary 16-byte inputs.