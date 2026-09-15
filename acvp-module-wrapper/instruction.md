An ACVP (Automated Cryptographic Validation Protocol) module wrapper is deployed at `/app/acvp_module` with its C source at `/app/acvp_module.c`. The module implements the ACVP binary subprocess protocol over stdin/stdout for cryptographic algorithm validation, linked against OpenSSL 3's libcrypto.

The module's `getConfig` advertises six algorithms: SHA2-256, HMAC-SHA2-256, AES-256-GCM, HKDF/SHA2-256, CMAC-AES-256, and PBKDF2-HMAC-SHA256. However, several existing algorithm handlers produce incorrect output against published NIST and RFC reference test vectors, and two algorithms (CMAC-AES-256 and PBKDF2-HMAC-SHA256) have only placeholder stubs returning zero-filled output.

A protocol reference is at `/app/PROTOCOL.md` and a diagnostic script at `/app/check_module.py` exercises the module against a subset of known test vectors and reports per-algorithm results.

Diagnose and fix all correctness issues in the existing handlers, design and implement complete handlers for CMAC-AES-256 and PBKDF2-HMAC-SHA256 using OpenSSL 3's EVP APIs, and produce a fully correct binary at `/app/acvp_module` that passes validation against all standard reference vectors.