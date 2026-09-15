Complete the C++ lattice weight library and binary arc processor at `/app/`.

The directory `/app/` contains:
- `lattice_weight.h` — class declarations and helper functions with TODO stubs for all operations
- `test_main.cpp` — randomized property tests defining required behavior through axiom checks
- `lattice_proc.cpp` — CLI tool skeleton with binary arc format specified in comments

Create `/app/Makefile` that builds both `test_main` and `lattice_proc` from their respective `.cpp` sources using C++17 with `-Wall -Wextra`.

Complete all TODO stubs in `lattice_weight.h`. The required semantics for every operation must be inferred from `test_main.cpp`, which exercises: semiring axioms (idempotent Plus, commutativity, identity, annihilation, distributivity), Compare/NaturalLess consistency, Divide as Times-inverse, Quantize stability, text and binary I/O roundtrips, CommonDivisor properties, and all `LatticeStringRepository` methods including `Rebuild` (garbage-collect entries unreachable from a keep-set). All `new Entry` allocations in `LatticeStringRepository` must be tracked; the implementation is verified under valgrind for zero leaks and zero errors.

Complete the `lattice_proc` commands as specified in its skeleton:
- `stats <file>` — print `arcs: <N>`, `times_fold: <CLW>`, `plus_fold: <CLW>`, `distinct_quantized: <N>` (one per line). Folds iterate the respective semiring operation over all arc weights starting from the identity element. Distinct counts unique weights after quantization.
- `text <file>` — convert binary to text: `<src> <dst> <CLW>` per line.
- `binary <outfile>` — read text lines from stdin, write binary to outfile.
- `normalize <file>` — compute the pairwise fold of the common-divisor operation across all arc weights (in file order), then output text where each arc's weight is left-divided by that accumulated divisor. Empty files produce no output.

Success criteria:
- `make -C /app` compiles both targets cleanly
- `/app/test_main` exits 0 printing "All tests passed!"
- `valgrind --leak-check=full --error-exitcode=1 /app/test_main` reports zero errors and zero leaks
- All `lattice_proc` commands produce correct output on valid inputs
