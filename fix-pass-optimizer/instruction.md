`/app/src/` contains a six-module framework that uses a genetic algorithm with synergy-pair data to optimize LLVM pass sequences for instruction count minimization. The modules: `instrcount.py` (instruction counting), `synergy_graph.py` (synergy graph construction), `ga.py` (genetic algorithm operators), `optimizer.py` (pipeline), `passes.py` (pass/synergy data), and `evaluator.py` (cross-benchmark evaluation).

The framework has two problems:

1. **Interacting bugs across modules.** Multiple bugs in the instruction counting pipeline, synergy graph construction, GA operators, and improvement metric prevent the optimizer from producing correct results. The bugs mask each other across module boundaries — the instruction counting defect hides fitness evaluation bugs in the GA, and the synergy graph error corrupts population initialization. All bugs must be found and fixed.

2. **Unimplemented evaluator.** `/app/src/evaluator.py` contains only function stubs with docstrings specifying the required behavior. It must be implemented to: evaluate pass sequences across all benchmarks in `/app/benchmarks/`, aggregate per-benchmark improvements using arithmetic mean and the shifted-product geometric mean standard in compiler benchmarking, rank candidate sequences by cross-benchmark performance, and compare two strategies head-to-head with per-benchmark win/loss/tie analysis.

The LLVM toolchain (`opt`, `clang`) and pre-compiled benchmark `.ll` files in `/app/benchmarks/` are available. Fix all bugs and implement the evaluator so the test suite passes.