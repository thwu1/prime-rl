The `/app/` directory contains two TweetNaCl shared-library builds compiled from different source files: `libtweetnacl_reference.so` (known-correct) and `libtweetnacl_suspect.so` (contains an unknown number of subtle implementation bugs across its cryptographic primitives). Also provided: `tweetnacl.h`, `tweetnacl_reference.c`, `tweetnacl_suspect.c`, `randombytes.c`, a `Makefile`, and `/app/audit_schema.json` which defines the required JSON report format.

Create `/app/nacl_auditor.py` — a command-line tool that takes the path to any NaCl-compatible shared library as its sole argument and writes a JSON conformance audit report to stdout.

The report must conform to `/app/audit_schema.json` and cover these five primitive families:

- `crypto_hash_sha512`
- `crypto_core_salsa20`
- `crypto_onetimeauth_poly1305`
- `crypto_sign_ed25519`
- `crypto_scalarmult_curve25519`

For each primitive, the report must indicate `"pass"` or `"fail"`. For each failure, include an `evidence` object containing `input_hex`, `expected_hex`, and `actual_hex` showing the first divergent test case. The report must also include `library_path`, `symbol_count` (number of NaCl API symbols exported by the library), `overall_status` (`"pass"` or `"fail"`), and `bugs_found` (number of failing primitive families).

When run against `libtweetnacl_reference.so`, the auditor must report zero bugs. When run against `libtweetnacl_suspect.so`, it must correctly identify every buggy primitive. The auditor must exit 0 on a successful audit (regardless of bugs found) and non-zero only if the library path is invalid or the library cannot be loaded.