A POSIX Extended Regular Expression engine at `/app/regex_engine.c` implements `regcomp()`, `regexec()`, `regfree()`, and `regerror()` per IEEE Std 1003.1-2017. The implementation has multiple defects and missing features. The API is declared in `/app/regex_engine.h` (do not modify).

A test harness at `/app/test_driver.c` reads `/app/test_vectors.txt` (derived from the rxspencer/AT&T POSIX conformance suite) and validates the engine against ~130 test cases. Build and run:

```
cd /app && make clean && make && ./test_driver > /app/results.json
```

The driver outputs JSON: `{"total": N, "passed": M, "failed": F, "details": [...]}`.

**Requirements for `/app/regex_engine.c`:**

- `regcomp()` must accept `REG_EXTENDED | REG_ICASE | REG_NEWLINE | REG_NOSUB` and return specific POSIX error codes (`REG_EPAREN`, `REG_EBRACK`, `REG_BADRPT`, `REG_EBRACE`, `REG_BADBR`, `REG_ERANGE`, `REG_EESCAPE`, `REG_ECTYPE`, `REG_ECOLLATE`, `REG_BADPAT`) for malformed patterns.
- `regexec()` must implement leftmost-longest match semantics, populate `pmatch[]` with subexpression byte offsets, and honor `REG_NOTBOL`/`REG_NOTEOL`.
- Interval expressions `{m,n}`, `{m,}`, `{m}`, bracket expression character classes (`[:alnum:]`–`[:xdigit:]`), collating symbols (`[.x.]`), equivalence classes (`[=x=]`), `REG_NEWLINE`, and `REG_ICASE` must all work correctly.
- `regfree()` must release all resources allocated by `regcomp()`. The engine must have zero definitely-lost memory when checked under `valgrind`.

**Shared library requirement:**

Produce `/app/libposixre.so` — a position-independent shared library exporting `regcomp`, `regexec`, `regfree`, and `regerror` as dynamic text symbols. The provided Makefile does not include a shared library target; determine the correct compilation and linking flags.

**Constraints:** Do not modify `/app/regex_engine.h`, `/app/test_driver.c`, `/app/test_vectors.txt`, or the existing Makefile targets.

**Success criteria (all must pass):**
- `./test_driver` reports 0 failures across all test vectors.
- `/app/libposixre.so` exists with the 4 required symbols exported as dynamic text symbols (verifiable via `nm -D`).
- `valgrind --leak-check=full --errors-for-leak-kinds=definite --error-exitcode=99 ./test_driver` exits with code 0.
