A compiler optimization conformance testing framework at `/app/` is non-functional. It includes a test runner (`/app/runner.py`), a report generator (`/app/report.py`), a configuration file (`/app/config.toml`), and some pre-existing C test programs under `/app/tests/`. The infrastructure contains multiple interacting bugs across Python, TOML configuration, and C source files. Diagnose and fix all issues, then extend the framework into a fully working dual-compiler test suite.

The completed framework must satisfy:

- Five test categories under `/app/tests/`: `irr_flow` (irreducible control flow), `alias` (pointer aliasing), `volatile_opt` (volatile semantics), `int_promo` (integer promotion), `call_conv` (calling conventions)
- At least 10 self-checking C test programs per category (exit 0 = pass, non-zero = fail)
- Every test must compile and pass at `-O0` using both `gcc` and `clang`
- `call_conv` tests must use separate compilation: paired `*_caller.c` and `*_callee.c` files compiled as independent translation units then linked
- `irr_flow` tests must contain genuine `goto`-based irreducible control flow with at least 2 distinct labels targeted by `goto` statements
- The final report `/app/results.json` must reflect outcomes from both `gcc` and `clang` across `-O0` through `-O3`, and `compilers_tested` must list both compilers
- All tests must pass at `-O0` for both compilers