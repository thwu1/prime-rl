A mutation-based verification adequacy framework at `/app/` evaluates a RISC-V 32-bit ALU by applying predefined RTL mutations, compiling each mutant with Verilator, running the C++ testbench against it, and classifying whether the mutation is detected. The pipeline is currently broken and produces no valid results.

Debug and fix the entire pipeline to achieve a perfect mutation adequacy score of 1.0. The final report at `/app/results/report.json` must include:
- All 8 mutations from `/app/mutations/` with correct classifications
- Aggregate statistics under the `aggregate` key: `total_mutants`, `killed`, `equivalent`, `adequacy_score`

Equivalent mutations (those producing semantically identical behavior due to algebraic properties like commutativity) must be correctly identified and excluded from the adequacy denominator. All non-equivalent mutations must be detected (KILLED) by the testbench.

The adequacy score is defined as `killed / (total - equivalent)`.

Run the pipeline: `cd /app && python3 run_pipeline.py`

Key locations:
- Pipeline orchestrator: `/app/run_pipeline.py`
- Harness modules: `/app/harness/`
- ALU source: `/app/rtl/alu.v`
- Testbench: `/app/tb/tb_alu.cpp`
- Mutation definitions: `/app/mutations/`