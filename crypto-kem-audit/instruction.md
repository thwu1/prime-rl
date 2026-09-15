A third-party security audit of `/app/` — a C library providing RSA-KEM key
encapsulation (NIST SP 800-56B) and PBMAC1/PBKDF2 key derivation (RFC 9579) —
has identified multiple security vulnerabilities that could lead to key material
disclosure or denial of service. The audit report indicates the issues are in
the key encapsulation and key derivation subsystems but does not disclose exact
locations or root causes.

Source code is in `/app/src/`, public API header in `/app/include/secops.h`,
build with `make -C /app`, existing tests in `/app/tests/test_basic.c`.

Find and fix all security vulnerabilities. Write regression tests in
`/app/tests/test_security.c` that verify each fix prevents the identified issue.
Ensure the project builds cleanly (`make -C /app clean all`) and all tests pass.