Complete the C++ implementation at `/app/` for a binary-format correlation tool fully specified in `/app/spec.md`. The tool reads a weighted data matrix from a custom binary format, computes pairwise row correlations, and outputs results in both text and binary formats.

The project provides:

- `/app/spec.md` — complete specification of binary I/O formats, mathematical definitions, and all required behavior
- `/app/main.cpp` — minimal skeleton with CLI argument parsing
- `/app/Makefile` — builds `./correlation` from `main.cpp`
- `/app/generate_data.py` — optional utility for generating test inputs

Build with `make` in `/app/`. Correctness is verified against a reference implementation (tolerance 1e-9) on matrices up to 200×80, including cases with substantial missing data, heterogeneous weights, and various degenerate conditions.