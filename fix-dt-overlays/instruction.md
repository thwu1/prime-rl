An industrial monitoring HAT for Raspberry Pi 4B (BCM2711) is failing to initialize at boot. The design files are:

- Hardware specification: `/app/hardware_spec.md`
- Device tree overlay sources: `/app/overlays/spi-devices.dts`, `/app/overlays/i2c-sensors.dts`, `/app/overlays/gpio-io.dts`
- Boot diagnostic log captured from the failing system: `/app/boot_log.txt`

The HAT has eight peripherals across SPI, I2C, and GPIO buses. None of them are working. The overlay files were written by a junior engineer and contain numerous errors — some prevent compilation entirely, others compile but produce incorrect runtime behavior that manifests as silent probe failures or wrong device bindings.

Your objectives:

1. Diagnose and fix all three overlay source files so that every peripheral described in the hardware specification is correctly configured. All fixed `.dts` files must compile to `.dtbo` binaries in `/app/overlays/` using `dtc`.

2. Create a unified overlay at `/app/overlays/combined-hat.dts` (compiled to `combined-hat.dtbo`) that integrates all eight peripherals into a single overlay. This overlay must support the variant wiring configuration described in the hardware specification through Device Tree runtime parameters, allowing the interrupt GPIO assignments to be changed at overlay load time without recompilation.