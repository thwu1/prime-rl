A parameterized ALU design at `/app/alu.vhd` implements 10 operations (ADD, SUB, AND, OR, XOR, SHL, SHR, NOT, CMP, MUL) with a configurable `WIDTH` generic and four status flags (zero, carry, overflow, negative). A minimal testbench at `/app/tb_alu.vhd` only exercises basic addition and subtraction.

The ALU contains multiple functional defects that produce incorrect results or flag values for certain operations and operand combinations. Some defects are width-dependent and only surface at larger parameterizations.

NVC (a VHDL compiler and simulator) is available at `/usr/local/bin/nvc`.

Deliver the following under `/app/`:

- `alu.vhd` — fully corrected design where every operation and all four status flags are accurate for any valid input at any WIDTH.
- `tb_alu.vhd` — a comprehensive WIDTH-parameterized testbench that verifies all 10 operations with flag edge cases and passes at WIDTH=8, 16, and 32.
- `run_coverage.sh` — an executable script that performs multi-width code coverage analysis (WIDTH=8, 16, 32), merges results into `/app/merged.ncdb`, and produces an HTML report at `/app/coverage_report/`. The merged report must show at least 90% statement coverage.