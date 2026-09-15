An RSA-KEM (Key Encapsulation Mechanism) implementation lives in `/app/`. It provides RSASVE encapsulation and decapsulation following NIST SP 800-56B Rev 2 and uses OpenSSL's low-level RSA primitives internally.

A security researcher has reported that under certain conditions the encapsulation function incorrectly reports success and exposes generated secret key material. The report suspects additional issues in input validation and error-path hygiene but does not pinpoint specific locations.

Your task:

- Audit every source file under `/app/` and identify **all** security vulnerabilities.
- Fix every vulnerability while preserving functional correctness. After your fixes, `make clean && make all` must succeed and `/app/test_roundtrip` must print `PASS`.
- Write a security audit report to `/app/AUDIT.md`. For each vulnerability found, document its file and function, severity, root cause, security impact, and the fix you applied.

Focus your analysis on return-value semantics of OpenSSL API functions, error-path secret-material lifecycle, and input validation in both the encapsulation and decapsulation paths.