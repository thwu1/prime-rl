Assembly sources for seven RV32I programs are in `/app/src/`. Machine-code hex files should exist in `/app/programs/` for each program — produce any that are missing. Execution traces from a reference processor are in `/app/traces/`.

A linker script is provided at `/app/link.ld`. The RISC-V cross-compilation toolchain is installed. `/app/api_contract.py` defines the function signatures your module must export; `/app/spec.md` describes the interface contract and data formats.

Create `/app/rv32i_analyzer.py` implementing all four functions defined in the contract. The module must correctly handle the complete RV32I base integer instruction set.