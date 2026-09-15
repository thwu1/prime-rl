A post-quantum cryptography deployment at `/app/pqc-migration/` is failing. The deployment uses liboqs (source at `/app/liboqs-src/`) to build a minimal PQC library, compile a C audit tool against it, and run a Python integration test. The deployment script is at `/app/pqc-migration/deploy.sh`, the C source at `/app/pqc-migration/pqc_audit.c`, and the Python script at `/app/pqc-migration/verify_migration.py`.

The deployment does not work. Diagnose all failures and fix them. The corrected deployment must:

- Build liboqs as a shared library installed at `/opt/liboqs/` with only the NIST-standardized ML-KEM (512/768/1024) and ML-DSA (44/65/87) algorithm families enabled. No other algorithm families (BIKE, HQC, Classic McEliece, Falcon, MAYO, SLH-DSA, CROSS, Kyber, etc.) may be present in the compiled library.
- Compile and successfully run the C audit tool, which enumerates all enabled algorithms, performs KEM encaps/decaps and SIG sign/verify round-trips.
- Successfully run the Python integration test using liboqs-python, which independently enumerates algorithms and cross-checks parameter agreement with the C output.

The deployment must produce these JSON files in `/app/output/`:

- `algorithm_audit.json`: array of `{name, type ("KEM"/"SIG"), nist_level, public_key_length, secret_key_length}` plus `ciphertext_length` and `shared_secret_length` for KEMs, or `signature_length` for SIGs
- `kem_verification.json`: array of `{name, success, shared_secrets_match}`
- `sig_verification.json`: array of `{name, success, signature_valid}`
- `py_audit.json`: same schema as `algorithm_audit.json`, produced by Python
- `cross_check.json`: `{all_parameters_match, kem_count, sig_count}`