`/app/tweetnacl.c` is a modified [TweetNaCl](https://tweetnacl.cr.yp.to/) containing exactly 4 bugs across different cryptographic primitives. It compiles cleanly but produces incorrect output. `/app/challenge.json` provides test vectors for `crypto_core_salsa20`, `crypto_core_hsalsa20`, `crypto_onetimeauth`, and `crypto_scalarmult`, plus a `crypto_secretbox` ciphertext encrypted with a correct implementation. `/app/tweetnacl.h` is correct and unmodified.

`gcc` is available. A known-good reference implementation (libsodium) can be installed via `apt install libsodium-dev` for cross-validation.

When complete, the following must all exist:

- **`/app/tweetnacl.c`** — all 4 bugs fixed so outputs match every test vector in `/app/challenge.json` and `crypto_secretbox` roundtrip encryption/decryption succeeds (encrypt then decrypt yields the original plaintext).

- **`/app/plaintext.txt`** — the decrypted `crypto_secretbox` plaintext from the challenge (UTF-8, no trailing newline).

- **`/app/forgery_poc.c`** — a standalone C program demonstrating the Poly1305 clamping vulnerability. Must compile against the fixed TweetNaCl (`gcc -o forgery_poc forgery_poc.c tweetnacl.c`) and print to stdout, one per line:
  - `FORGERY_KEY=<64 hex chars>` — the 32-byte key must have bits 4-5 set in byte 11 (i.e., `key[11] & 0x30 != 0`) so the clamping difference between broken and correct implementations is triggered
  - `FORGERY_MSG=<hex-encoded message>` — non-empty, valid hex encoding of the authenticated message
  - `CORRECT_MAC=<32 hex chars>` — MAC computed with correct Poly1305 clamping
  - `BROKEN_MAC=<32 hex chars>` — MAC computed with the broken clamping; must differ from CORRECT_MAC
  - `DIVERGENT=YES`

- **`/app/bug_report.json`** — JSON array of exactly 4 objects (one per bug), each containing:
  - `"primitive"`: affected primitive name — the 4 bugs must span `"poly1305"`, `"curve25519"`, and at least 2 salsa20-related primitives (e.g., `"salsa20"`, `"hsalsa20"`)
  - `"description"`: one-sentence bug description
  - `"security_impact"`: one of `"authentication_bypass"`, `"encryption_failure"`, `"interop_failure"`, `"key_exchange_failure"`
  - `"exploitability"`: one of `"actively_exploitable"`, `"passive_failure"`

  The Poly1305 bug must be classified with `"exploitability": "actively_exploitable"` and `"security_impact": "authentication_bypass"`.