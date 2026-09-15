`/app/` contains a Csmith-inspired differential testing framework for C compiler correctness. It generates random C programs evaluating arithmetic expressions over `int32_t` variables using safe math wrappers, computes a CRC32 checksum of all variable values, and compares output across compilers and optimization levels.

**Components:**

- `/app/safe_math.h` — Inline wrappers for int32_t arithmetic. Must return `0` for any operation that would invoke undefined behavior; correct mathematical result otherwise.
- `/app/crc32.h` — CRC32 checksum infrastructure. **Read-only; do not modify.**
- `/app/expr_gen.c` — Deterministic random expression generator. Given a seed, outputs a C source file. The generator itself must be free of undefined behavior.
- `/app/harness.sh` — Cross-compiler differential testing script.
- `/app/Makefile` — Build system with multi-compiler and coverage support.

**Current state:** The framework has defects across multiple files. The safe math wrappers fail to guard against several categories of signed integer undefined behavior. The expression generator contains undefined behavior in its own code, causing non-deterministic output when built with different compilers or optimization levels. The harness script does not correctly perform cross-compiler differential testing despite claiming to. The Makefile's coverage target is non-functional.

**Requirements:**

1. `./harness.sh 200` must report zero mismatches. Every generated program (seeds 1-200) must produce identical checksums across all four configurations: `gcc -O0`, `gcc -O2`, `clang -O0`, `clang -O2`.
2. All generated programs must produce zero UBSan violations when compiled with either `gcc` or `clang` using `-fsanitize=undefined -fno-sanitize-recover=all`.
3. The expression generator itself must be UBSan-clean: building `expr_gen` with `-fsanitize=undefined -fno-sanitize-recover=all` and running it for any seed must produce zero violations.
4. `make coverage` must produce gcov coverage data. Line coverage of safe_math.h wrapper functions must reach at least 85%.
5. `make clean` must remove all generated artifacts including gcov data files (`.gcno`, `.gcda`, `.gcov`).
6. Do not modify `/app/crc32.h`.
