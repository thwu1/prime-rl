Csmith source code is at `/app/csmith-src/`. Build it so the binary is at `/app/csmith-src/build/src/csmith`.

Build a compiler differential testing system at `/app/pipeline/` comprising these executable scripts:

**`/app/pipeline/fuzz.sh`** — Accepts `--seed N` (generates a program via Csmith and tests it) or `--file PATH` (tests an existing C file). Compiles and runs the program under multiple GCC and Clang configurations spanning unoptimized and optimized modes. Outputs a single JSON object to stdout with: `status` (exactly one of `pass`, `mismatch`, `crash`, `timeout`, `compile_error`, `ub`), `seed` or `file`, `outputs` (map of configuration name to output string), and `details`. Classification must correctly distinguish genuine output divergences from those caused by undefined behavior in the test program.

**`/app/pipeline/interestingness.sh`** — Takes a single argument: path to a C source file. Exits 0 if and only if the file demonstrates a genuine compiler behavioral divergence across GCC optimization levels — free from undefined behavior, compilation failure, and runtime abnormality. Exits non-zero otherwise.

**`/app/pipeline/batch.sh`** — Takes two arguments: `START_SEED` and `END_SEED`. Runs `fuzz.sh --seed N` for each seed in the inclusive range. Writes `/app/pipeline/report.json` with fields: `total`, `pass`, `mismatch`, `crash`, `timeout`, `compile_error`, `ub` (integer counts), and `results` (array of per-seed JSON objects).

A file at `/app/example_large.c` exhibits a genuine optimization-level behavioral divergence. Reduce it to fewer than 50 lines while preserving that property. Save the result to `/app/pipeline/example_reduced.c`.

Run `batch.sh 1 20` to produce `/app/pipeline/report.json`.