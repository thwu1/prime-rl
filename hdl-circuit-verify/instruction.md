A 4-bit ALU has been implemented using a Python HDL framework in `/app/`. The framework (`/app/hdl.py`) provides `Wire`, `Bus`, `mux`, `const`, and `simulate` primitives for combinational logic with operator overloading. Signals use LSB-first bit ordering.

The ALU design (`/app/design.py`) targets eight operations selected by a 3-bit opcode: ADD (000), SUB (001), AND (010), OR (011), XOR (100), NOT (101), SHL (110), SHR (111). The implementation has defects — run `/app/run_tests.py` to observe failures.

Produce the following deliverables in `/app/`, conforming to the specification in `/app/output_spec.json`:

- A corrected `/app/design.py`
- `/app/analysis.py` — circuit graph analysis tools
- `/app/fast_alu.py` — an architecturally optimized ALU variant
- `/app/report.json` — structured findings and evaluation