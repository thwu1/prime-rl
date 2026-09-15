A Unicode Collation Algorithm (UCA) implementation at `/app/` is split across three interoperating components, all of which contain bugs:

1. **C shared library** (`/app/src/implicit_weights.c`) — Computes implicit collation element weights for code points not in the DUCET. Must be compiled into `/app/lib/libimplicit.so` using the Makefile at `/app/Makefile`.

2. **Python collator** (`/app/collator.py`) — Uses `ctypes` to call the C library for implicit weight computation, and implements DUCET trie lookup, collation element array construction with discontiguous match handling, variable weighting (NON_IGNORABLE and SHIFTED modes), and multi-level sort key formation.

3. **SQLite3 integration** (`/app/register_collation.py`) — Registers the UCA collation as a SQLite3 custom collation function and sorts a multilingual dataset.

The Makefile, C source, Python collator, and SQLite3 registration script each contain bugs that prevent correct operation. Fix all components so that:

- `/app/lib/libimplicit.so` builds successfully via `make -C /app`
- The collator passes official UCA conformance tests for both `NON_IGNORABLE` and `SHIFTED` variable weighting modes with zero ordering violations
- A correctly UCA-sorted version of `/app/data/multilingual_dataset.txt` is produced at `/app/output/sorted_multilingual.txt` using the SQLite3 custom collation

Resources in the environment:
- `/app/data/allkeys.txt` — DUCET (Default Unicode Collation Element Table)
- `/app/data/CollationTest_NON_IGNORABLE_SHORT.txt` — Official conformance test data (NON_IGNORABLE mode)
- `/app/data/CollationTest_SHIFTED_SHORT.txt` — Official conformance test data (SHIFTED mode)
- `/app/data/multilingual_dataset.txt` — Multilingual text to sort via SQLite3
- `/app/run_conformance.py` — Conformance test runner (`python3 /app/run_conformance.py --limit 5000 --verbose`)

The implementation must use only Python standard library modules plus the C shared library. External collation libraries (pyuca, PyICU, etc.) are not permitted.