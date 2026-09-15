A Python RVFI (RISC-V Formal Interface) trace validator at `/app/rvfi_validator/` validates instruction-retirement traces against the RISC-V ISA specification. It has several compliance bugs in its RV32I implementation and is entirely missing M-extension (multiply/divide) support.

Verilog reference models for M-extension instructions are at `/app/reference_models/`, adapted from the riscv-formal framework. Compile and simulate them with `make -C /app/reference_models/` (uses `iverilog` and `vvp`) to study correct instruction behavior — particularly edge cases like MULHSU signed×unsigned semantics, signed division overflow, and division-by-zero return values.

Implement complete M-extension validation (MUL, MULH, MULHSU, MULHU, DIV, DIVU, REM, REMU) and fix all existing RV32I bugs so the validator correctly implements the full RV32IM specification and RVFI protocol.

Reference: `/app/rvfi_reference.md` (RVFI protocol, RV32I semantics), `/app/riscv_m_extension.md` (M-extension ISA specification).