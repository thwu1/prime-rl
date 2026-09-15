Implement a C library at `/app/p256_mont.c` providing NIST P-256 Montgomery-domain field arithmetic, and create a build and verification toolchain around it.

Formal specifications in `/app/specs/` are excerpted from the s2n-bignum library's HOL Light machine-checked correctness proofs — extract the mathematical contracts from the formal notation.

Your library must implement all functions declared in `/app/p256_mont.h`: `p256_montmul`, `p256_montsqr`, `p256_montadd`, `p256_montsub`, `p256_tomont`, `p256_frommont`, `p256_inv`. All values are 4-element `uint64_t` arrays in little-endian limb order. Output buffers may alias input buffers. All outputs must be fully reduced (< p_256). Montgomery domain uses R = 2^256.

Write `/app/Makefile` (GNU Make) with these targets:

- `all` — compiles `libp256mont.so` (shared library, `-shared -fPIC -O2`)
- `static` — builds `libp256mont.a` using `ar rcs`
- `check-symbols` — uses `nm -D libp256mont.so` to identify the exported `p256_*` text symbols, writes their names alphabetically (one per line) to `/app/symbol_manifest.txt`
- `analyze` — uses `objdump -d libp256mont.so` to count x86 instructions in `p256_montmul`, and `size libp256mont.so` for section sizes; writes `/app/build_analysis.json` with integer keys: `montmul_instruction_count`, `text_size`, `data_size`, `bss_size`
- `verify-prime` — extracts the P-256 field prime from `openssl ecparam -name prime256v1 -param_enc explicit -text -noout`, compares against the prime in your implementation, writes `MATCH` or `MISMATCH` to `/app/prime_verification.txt`
- `clean` — removes all build artifacts

After writing all files, run `make all static check-symbols analyze verify-prime`.