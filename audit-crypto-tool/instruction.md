A file encryption tool `cryptvault` is built and installed at `/app/cryptvault`. Its source is at `/app/cryptvault.c` with a `Makefile` at `/app/Makefile`. The tool uses libsodium for cryptographic operations.

The tool encrypts files using either a keyfile or a password. Small files (< 64 KB) use one code path; larger files use a different chunked path. The tool compiles, runs, and successfully round-trips data — but it contains multiple cryptographic vulnerabilities that undermine its security guarantees.

Audit the source code, identify **all** cryptographic vulnerabilities, fix them, and rebuild the binary at `/app/cryptvault`. The fixed tool must:

- Maintain the existing command-line interface
- Use cryptographically appropriate libsodium APIs for all operations
- Properly authenticate all encrypted data so tampering is always detected
- Use an appropriate memory-hard KDF for password-based key derivation
- Never reuse nonces across separate encryptions with the same key

Commands:
```
cryptvault keygen <keyfile>
cryptvault encrypt [-k <keyfile> | -p <password>] <input> <output>
cryptvault decrypt [-k <keyfile> | -p <password>] <input> <output>
```