A custom VLIW SIMD processor simulator is provided at `/app/problem.py`. It models a single-core processor with multiple execution engines (12 scalar ALUs, 6 vector ALUs processing 8 elements each, 2 loads, 2 stores, 1 flow control) that execute in parallel within instruction bundles.

The file `/app/perf_takehome.py` contains a `KernelBuilder` class whose `build_kernel` method generates instructions for a batched tree traversal kernel. The baseline implementation uses one operation per instruction bundle and processes one batch element at a time, resulting in **147,734 cycles** for the standard test case (tree height 10, 16 rounds, batch size 256).

Your task: **modify `/app/perf_takehome.py`** to optimize the kernel so it completes in **fewer than 17,000 cycles** while producing bit-exact identical output to the reference kernel. You may not modify `/app/problem.py`.

A profiling tool is provided at `/app/vliw_profiler.py` with subcommands for execution profiling, trace generation (Chrome Trace Event Format), and report export. Run `python3 /app/vliw_profiler.py --help` to discover available subcommands. Use the profiler to analyze the baseline kernel, guide your optimizations, and generate a final profile report at `/app/profile_report.json`. The tool `jq` is also installed for post-processing execution traces.

Key architectural constraints discoverable from the simulator:
- All ALU/VALU operations read/write scratch space (1536 words); main memory requires load/store
- Writes take effect at end of cycle (read-before-write within a bundle)
- Vector operations (`valu`, `vload`, `vstore`) process `VLEN=8` contiguous scratch/memory words
- `vbroadcast` copies a scalar to all 8 vector lanes
- `vselect` provides branchless vector conditional
- Slot limits per bundle are enforced by the simulator

Validation: `python3 /app/run_tests.py` runs correctness checks across multiple random seeds and reports the cycle count.