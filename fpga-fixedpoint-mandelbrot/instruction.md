Three SystemVerilog modules implementing unsigned integer division, unsigned fixed-point division, and integer square root are provided in `/app/verilog/`. Their source code is the authoritative specification of each algorithm's behavior — no separate algorithm documentation is provided.

Produce bit-accurate outputs from each module for the test vectors listed in `/app/spec.md`. Then compute Mandelbrot set escape iterations on a coordinate grid using Q4.21 signed fixed-point arithmetic consistent with standard two's complement hardware conventions.

Write all results to `/app/results.json` in the format specified in `/app/spec.md`.