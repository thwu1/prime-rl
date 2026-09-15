The specification at `/app/spec.md` defines XAES-256-GCM, an extended-nonce AEAD built on AES-256-GCM via a CMAC-based KDF, including the full CMAC-AES256 algorithm (Appendix A).

The Go implementation at `/app/go_impl/xaes.go` compiles and runs without errors but produces incorrect ciphertexts. Multiple bugs span the AES cipher instantiation, GF(2^128) subkey derivation, KDF block construction, and nonce derivation. A CLI wrapper exists at `/app/go_impl/cmd/xaesgcm/`. Fix all bugs so the implementation matches the specification.

The Python module at `/app/py_impl/xaes256gcm.py` has a partial `cmac_aes256()` implementation with bugs and an unimplemented `XAES256GCM` class. Fix the CMAC function and implement the AEAD class from scratch. Only raw AES-ECB block operations (`cryptography.hazmat.primitives.ciphers` with `modes.ECB()`) and `AESGCM` for the final GCM step are permitted — no CMAC library imports.

Create a file encryption CLI tool at `/app/file_tool/xaes_file.py` with this binary format:

| Offset | Size | Field |
|--------|------|-------|
| 0 | 8 | Magic: `XAESFILE` (ASCII) |
| 8 | 1 | Version: `0x01` |
| 9 | 24 | Nonce (randomly generated on encrypt) |
| 33 | 4 | AAD length (uint32, big-endian) |
| 37 | N | AAD bytes |
| 37+N | * | XAES-256-GCM ciphertext ‖ 16-byte tag |

    python3 /app/file_tool/xaes_file.py encrypt --key <hex> [--aad <text>] <input> <output>
    python3 /app/file_tool/xaes_file.py decrypt --key <hex> <input> <output>

Both implementations must produce byte-identical ciphertexts for the same inputs.