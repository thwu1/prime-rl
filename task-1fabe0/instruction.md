A bare-metal AArch64 kernel project for the Raspberry Pi 4 (BCM2711) is at `/app/`. It contains ARM64 startup assembly (`start.S`), a linker script (`link.ld`), an MMIO register header (`mmio.h`), a Mini UART driver (`uart.c`/`main.c`), and a `Makefile`.

The code was ported from an earlier Raspberry Pi model and the MMIO configuration, memory layout, and assembly directives have not been updated for the BCM2711 SoC. Evaluate the existing source files against BCM2711 hardware specifications and correct all SoC-revision errors so the kernel is valid for RPi4 AArch64 boot.

A hardware specification at `/app/hat_spec.md` describes a custom data acquisition HAT with four peripherals across I2C and SPI. No device tree overlay exists yet. Design and create `/app/hat-overlay.dts` from scratch based on the specification, using correct Linux kernel compatible strings, proper RPi 40-pin header bus targeting, accurate peripheral addresses derived from the pin connections documented in the spec, appropriate SPI and interrupt configuration, and Device Tree specification conventions.

Running `make` in `/app/` must succeed and produce both `kernel8.img` and `hat-overlay.dtbo`.