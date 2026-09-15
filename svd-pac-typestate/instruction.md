The file `/app/tb-mcu.svd` contains a CMSIS-SVD specification for the TB-MCU32 -- a fictional Cortex-M3 microcontroller with seven peripherals: RCC, GPIOA, GPIOB, GPIOC, USART1, SPI1, and DMA1. GPIOB and GPIOC are `derivedFrom` GPIOA. A skeleton Rust library crate exists at `/app/` with `Cargo.toml` and an empty `src/lib.rs`.

Implement a complete `#![no_std]` Peripheral Access Crate under `/app/src/` that satisfies all of the following:

- The crate compiles for `thumbv7m-none-eabi` via `cargo build --target thumbv7m-none-eabi`. It is a library crate -- no entry point, no panic handler, no linker script.

- Every peripheral defined in the SVD is represented at its correct base address. Register block structs must be memory-layout-compatible with the hardware, including reserved gaps between non-contiguous register offsets. Access modes (read-only, write-only, read-write) from the SVD must be respected.

- All hardware register reads and writes use volatile memory operations.

- GPIO pins enforce their electrical mode at compile time. The SVD's enumerated values define the available modes and sub-configurations. Performing an output operation (driving a pin high or low) on a pin configured as input, or an input operation (reading pin level) on a pin configured as output, must be a compile-time error. Mode transitions must consume the pin handle so the previous handle cannot be reused.

- A top-level peripheral container is obtainable at most once; subsequent attempts return `None`. This guarantee must hold even if an interrupt pre-empts between the check and the claim.