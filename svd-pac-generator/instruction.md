Write a Python code generator at `/app/generate.py` that reads the CMSIS-SVD XML file at `/app/device.svd` and produces a complete, compilable Rust crate at `/app/generated-pac/`.

The SVD file describes a fictional microcontroller "TBMCU-001" with four peripherals (GPIOA, GPIOB, SPI1, TIM2) exercising key CMSIS-SVD features: peripheral derivation (`derivedFrom` with register inheritance and merging), dimensioned register arrays (`dim`/`dimIncrement`/`dimIndex` with `%s` expansion), mixed access modes, non-zero reset values, and enumerated fields. The generated crate must conform to the API specification in `/app/reference.md` and compile as a `#![no_std]` Rust crate with no external dependencies (edition 2021, package name `tbmcu001-pac`).

Key requirements:
- GPIOB uses `derivedFrom="GPIOA"` and must inherit all parent registers at its own base address, with its own additional AFRL register merged in.
- TIM2 has a dimensioned CCR register (`dim=4`, `dimIndex="1-4"`) that must expand into CCR1-CCR4 with correct addresses.
- Access restrictions must be enforced: read-only registers produce only `R`/reader types, write-only registers produce only `W`/writer types.
- `write()` initializes from the register's reset value; `modify()` initializes from the current value.
- Each peripheral gets its own `.rs` module file: `gpioa.rs`, `gpiob.rs`, `spi1.rs`, `tim2.rs`.

Verify correctness by running: `cd /app/test_harness && cargo test -- --test-threads=1`