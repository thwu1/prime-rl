Implement a multi-recipient file encryption CLI tool called `nacl_vault` in C, using the TweetNaCl cryptographic library provided at `/app/tweetnacl.c` and `/app/tweetnacl.h`.

The tool must implement the NaCl Vault binary format specified in `/app/SPEC.md`. Write your implementation to `/app/nacl_vault.c`; it must compile via the provided `/app/Makefile` (which links against `tweetnacl.c` and `randombytes.c`).

Required subcommands:

- `nacl_vault keygen <sk_file> <pk_file>` — Generate a Curve25519 keypair, writing 32-byte raw key files.
- `nacl_vault encrypt -r <pk_file> [-r <pk_file> ...] -o <outfile> <infile>` — Encrypt a file for one or more recipients using the hybrid scheme described in the spec.
- `nacl_vault decrypt -k <sk_file> -o <outfile> <infile>` — Decrypt a vault file using a recipient's secret key.

The spec prescribes the binary layout (header, per-recipient key-wrapping records, chunked ciphertext) but intentionally leaves the nonce derivation scheme unspecified. You must design a derivation method that guarantees no nonce is ever reused across recipients or content chunks, while remaining deterministic from the file nonce and an index. Consider how NaCl's `crypto_box` and `crypto_secretbox` zero-padding requirements translate to your stored record and chunk sizes.

The tool must correctly handle edge cases: empty files, files exactly aligned to the 65536-byte chunk boundary, and large multi-chunk files. Per-chunk authenticated encryption must detect data corruption, chunk reordering, and truncation. Exit 0 on success, non-zero on any error.