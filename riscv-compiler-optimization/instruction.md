A RISC-V firmware application in `/app/src/` has a baseline build at `/app/baseline/`. Object sizes are in `/app/baseline/sizes.txt`. The RISC-V GCC/binutils cross-toolchain, LLVM/Clang, and QEMU user-mode emulator are pre-installed.

Produce:

1. `/app/results/comparison.csv` — `.text` section sizes from cross-compiling each of the four source files with both GCC and Clang across at least three optimization configurations. Columns: `file,compiler,flags,text_size`.

2. `/app/optimized/Makefile` with a `clean` target — builds optimized `.o` files (standard ELF relocatable objects) and a statically-linked `firmware.elf` in `/app/optimized/`. Total `.text` size of the four `.o` files must be at least 35% smaller than the baseline.

3. `/app/results/report.json` with keys: `baseline_total_text` (int), `optimized_total_text` (int), `reduction_pct` (float), `per_file` (object mapping each `.c` filename to `{"compiler", "flags", "text_size"}`), `techniques_used` (string list), `bug_description` (string explaining the bug found and how it was fixed).

4. One of the source files contains a correctness bug that manifests at higher optimization levels but not at `-O0`. Find and fix it so the program produces correct output at all optimization levels.