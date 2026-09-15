"""Tests for the RPi4 bare-metal project and custom HAT device tree overlay.

Verifies that:
  - The bare-metal kernel cross-compiles correctly for BCM2711 AArch64
  - MMIO register addresses and baud rate match the BCM2711 SoC
  - A device tree overlay was designed from the hardware specification
    with correct compatible strings, bus targeting, addresses, interrupt
    configuration, and DT specification compliance
"""

import subprocess
import re
import os
import pytest


def run(cmd, **kwargs):
    """Run a shell command and return the CompletedProcess."""
    return subprocess.run(
        cmd, shell=True, capture_output=True, text=True,
        cwd='/app', **kwargs
    )


def eval_c_macro(macro_name):
    """Evaluate a C preprocessor macro from mmio.h using the cross-compiler."""
    code = '#include "mmio.h"\nMACRO_EVAL_RESULT ' + macro_name + '\n'
    result = subprocess.run(
        ['aarch64-linux-gnu-cpp', '-I', '/app', '-x', 'c', '-'],
        input=code, capture_output=True, text=True,
        cwd='/app'
    )
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith('MACRO_EVAL_RESULT'):
            expr = line[len('MACRO_EVAL_RESULT'):].strip()
            expr = re.sub(
                r'\(\s*(?:unsigned\s+)?(?:long\s+)*(?:long|int|short|char)\s*\)',
                '', expr
            )
            expr = re.sub(r'(?<=[0-9a-fA-F])[UuLl]+\b', '', expr)
            try:
                val = eval(expr)
                return int(val)
            except Exception:
                return None
    return None


# ---------------------------------------------------------------------------
# Kernel cross-compilation tests (evaluate existing code for BCM2711)
# ---------------------------------------------------------------------------

class TestKernelBuild:
    """Verify that the bare-metal kernel cross-compiles correctly for RPi4."""

    def _build_kernel(self):
        return run('make clean && make kernel8.img')

    def test_kernel_build_succeeds(self):
        """Kernel must cross-compile successfully."""
        result = self._build_kernel()
        assert result.returncode == 0, (
            f"Kernel build failed:\nstdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

    def test_entry_point(self):
        """ELF entry point must be 0x80000 for RPi4 AArch64 boot."""
        build = self._build_kernel()
        assert build.returncode == 0, f"Build failed:\n{build.stderr}"
        result = run('aarch64-linux-gnu-readelf -h kernel8.elf')
        assert result.returncode == 0, "readelf failed"
        match = re.search(
            r'Entry point address:\s+(0x[0-9a-fA-F]+)', result.stdout
        )
        assert match, "Could not find entry point in readelf output"
        entry = int(match.group(1), 16)
        assert entry == 0x80000, (
            f"Entry point is {hex(entry)}, should be 0x80000. "
            "RPi4 loads AArch64 kernel at 0x80000 (not 0x8000 for RPi1 32-bit)."
        )

    def test_bss_symbols_defined(self):
        """Linker script must define __bss_start and __bss_end."""
        build = self._build_kernel()
        assert build.returncode == 0, f"Build failed:\n{build.stderr}"
        result = run('aarch64-linux-gnu-nm kernel8.elf')
        assert result.returncode == 0, "nm failed"
        symbols = result.stdout
        assert '__bss_start' in symbols, (
            "__bss_start not defined in linker script .bss section."
        )
        assert '__bss_end' in symbols, (
            "__bss_end not defined in linker script .bss section."
        )

    def test_vector_table_alignment(self):
        """Exception vector table must be 2048-byte aligned (VBAR_EL1)."""
        build = self._build_kernel()
        assert build.returncode == 0, f"Build failed:\n{build.stderr}"
        result = run('aarch64-linux-gnu-nm kernel8.elf')
        assert result.returncode == 0, "nm failed"
        for line in result.stdout.splitlines():
            parts = line.strip().split()
            if len(parts) >= 3 and parts[2] == 'vectors':
                addr = int(parts[0], 16)
                assert addr % 2048 == 0, (
                    f"vectors at {hex(addr)} is not 2048-byte aligned. "
                    "VBAR_EL1 requires bits [10:0] = 0. Use .balign 2048."
                )
                return
        pytest.fail("vectors symbol not found in kernel8.elf")


# ---------------------------------------------------------------------------
# BCM2711 peripheral configuration tests (evaluate SoC-revision correctness)
# ---------------------------------------------------------------------------

class TestPeripheralConfig:
    """Verify BCM2711 MMIO base addresses and register offsets."""

    def test_mmio_base_bcm2711(self):
        """MMIO_BASE must be 0xFE000000 for BCM2711."""
        val = eval_c_macro('MMIO_BASE')
        assert val is not None, "Could not evaluate MMIO_BASE macro"
        assert val == 0xFE000000, (
            f"MMIO_BASE is {hex(val)}, should be 0xFE000000 for BCM2711."
        )

    def test_gpfsel1_offset(self):
        """GPFSEL1 must be at GPIO_BASE + 0x04."""
        gpfsel1 = eval_c_macro('GPFSEL1')
        gpio_base = eval_c_macro('GPIO_BASE')
        assert gpfsel1 is not None and gpio_base is not None, (
            "Could not evaluate GPFSEL1 or GPIO_BASE macros"
        )
        offset = gpfsel1 - gpio_base
        assert offset == 0x04, (
            f"GPFSEL1 offset from GPIO_BASE is {hex(offset)}, should be 0x04."
        )

    def test_uart_baud_divisor(self):
        """Mini UART baud divisor must be 541 for 500MHz clock at 115200."""
        val = eval_c_macro('AUX_MU_BAUD_VAL')
        assert val is not None, "Could not evaluate AUX_MU_BAUD_VAL macro"
        assert val == 541, (
            f"AUX_MU_BAUD_VAL is {val}, should be 541. "
            "Formula: 500000000 / (8 * 115200) - 1 = 541."
        )


# ---------------------------------------------------------------------------
# Device tree overlay design tests (verify overlay created from spec)
# ---------------------------------------------------------------------------

class TestDeviceTreeOverlay:
    """Verify the custom HAT device tree overlay designed from hat_spec.md."""

    @pytest.fixture(autouse=True)
    def compile_dtbo(self):
        """Compile the overlay before each test."""
        result = run(
            'dtc -@ -I dts -O dtb -o hat-overlay.dtbo hat-overlay.dts 2>&1'
        )
        self._dtc_result = result

    def _decompile(self):
        """Decompile the built overlay for structural inspection."""
        assert self._dtc_result.returncode == 0, (
            f"DTC compilation failed:\n{self._dtc_result.stdout}\n"
            f"{self._dtc_result.stderr}\n"
            "Ensure hat-overlay.dts exists with /dts-v1/; and /plugin/;."
        )
        result = run('dtc -I dtb -O dts hat-overlay.dtbo')
        assert result.returncode == 0, (
            f"Failed to decompile DTB:\n{result.stderr}"
        )
        return result.stdout

    def _get_fixups(self, dts):
        """Extract the __fixups__ section from decompiled DTS."""
        idx = dts.find('__fixups__')
        if idx < 0:
            return ""
        return dts[idx:]

    def test_dtbo_compiles(self):
        """Device tree overlay must compile with dtc -@."""
        assert self._dtc_result.returncode == 0, (
            f"DTC compilation failed:\n{self._dtc_result.stdout}\n"
            f"{self._dtc_result.stderr}\n"
            "Create hat-overlay.dts with /dts-v1/; and /plugin/; directives."
        )

    def test_i2c_targets_i2c1(self):
        """I2C fragment must target i2c1 (user-accessible bus), not i2c0."""
        dts = self._decompile()
        fixups = self._get_fixups(dts)
        assert 'i2c1' in fixups, (
            "I2C fragment does not target i2c1. The user I2C bus on the RPi "
            "40-pin header is i2c1. i2c0 is reserved for HAT EEPROM."
        )

    def test_spi_targets_spi0(self):
        """SPI fragment must target spi0 (primary SPI bus on header)."""
        dts = self._decompile()
        fixups = self._get_fixups(dts)
        assert 'spi0' in fixups, (
            "SPI fragment does not target spi0. The primary SPI bus on the "
            "RPi 40-pin header is spi0."
        )

    def test_bme280_compatible(self):
        """BME280 must use Linux kernel compatible string 'bosch,bme280'."""
        dts = self._decompile()
        assert 'bosch,bme280' in dts, (
            "BME280 compatible 'bosch,bme280' not found in overlay. "
            "This is the upstream Linux kernel binding for the Bosch BME280."
        )

    def test_bme280_address(self):
        """BME280 I2C address must be 0x76 (SDO pin tied to GND)."""
        dts = self._decompile()
        idx = dts.find('bosch,bme280')
        assert idx >= 0, "BME280 node not found"
        context = dts[max(0, idx - 300):idx + 300]
        assert re.search(r'reg\s*=\s*<0x76>', context), (
            "BME280 must have reg = <0x76>. Per the spec, SDO is tied to GND "
            "which selects I2C address 0x76."
        )

    def test_ads1115_compatible(self):
        """ADS1115 must use Linux kernel compatible string 'ti,ads1115'."""
        dts = self._decompile()
        assert 'ti,ads1115' in dts, (
            "ADS1115 compatible 'ti,ads1115' not found in overlay. "
            "This is the upstream Linux kernel binding for the TI ADS1115."
        )

    def test_ads1115_address(self):
        """ADS1115 I2C address must be 0x48 (ADDR pin tied to GND)."""
        dts = self._decompile()
        idx = dts.find('ti,ads1115')
        assert idx >= 0, "ADS1115 node not found"
        context = dts[max(0, idx - 300):idx + 300]
        assert re.search(r'reg\s*=\s*<0x48>', context), (
            "ADS1115 must have reg = <0x48>. Per the spec, ADDR is tied to GND "
            "which selects I2C address 0x48."
        )

    def test_pca9685_compatible(self):
        """PCA9685 must use Linux kernel compatible string 'nxp,pca9685'."""
        dts = self._decompile()
        assert 'nxp,pca9685' in dts, (
            "PCA9685 compatible 'nxp,pca9685' not found in overlay. "
            "This is the upstream Linux kernel binding for the NXP PCA9685."
        )

    def test_pca9685_address(self):
        """PCA9685 I2C address must be 0x40 (A0-A5 all tied to GND)."""
        dts = self._decompile()
        idx = dts.find('nxp,pca9685')
        assert idx >= 0, "PCA9685 node not found"
        context = dts[max(0, idx - 300):idx + 300]
        assert re.search(r'reg\s*=\s*<0x40>', context), (
            "PCA9685 must have reg = <0x40>. Per the spec, A0-A5 are all GND "
            "which selects I2C address 0x40."
        )

    def test_w5500_compatible(self):
        """W5500 must use Linux kernel compatible string 'wiznet,w5500'."""
        dts = self._decompile()
        assert 'wiznet,w5500' in dts, (
            "W5500 compatible 'wiznet,w5500' not found in overlay. "
            "This is the upstream Linux kernel binding for the WIZnet W5500."
        )

    def test_w5500_chip_select(self):
        """W5500 SPI device must have reg = <0> for chip select CE0."""
        dts = self._decompile()
        idx = dts.find('wiznet,w5500')
        assert idx >= 0, "W5500 node not found"
        context = dts[max(0, idx - 300):idx + 300]
        has_reg = re.search(r'reg\s*=\s*<(0x0+|0)\s*>', context)
        assert has_reg, (
            "W5500 must have reg = <0> for chip select CE0."
        )

    def test_w5500_spi_frequency(self):
        """W5500 must have a spi-max-frequency property."""
        dts = self._decompile()
        assert 'spi-max-frequency' in dts, (
            "W5500 must have spi-max-frequency property specifying "
            "the maximum SPI clock rate."
        )

    def test_w5500_interrupt_spec(self):
        """W5500 interrupt must specify GPIO25 with IRQ_TYPE_LEVEL_LOW (8)."""
        dts = self._decompile()
        # GPIO25 = 0x19, IRQ_TYPE_LEVEL_LOW = 8
        has_irq = re.search(r'interrupts\s*=\s*<0x19\s+0x0*8\s*>', dts)
        assert has_irq, (
            "W5500 must have interrupts = <25 8> specifying GPIO25 with "
            "IRQ_TYPE_LEVEL_LOW (active-low level-triggered, type value 8)."
        )

    def test_w5500_interrupt_parent(self):
        """W5500 interrupt-parent must reference the SoC GPIO controller."""
        dts = self._decompile()
        fixups = self._get_fixups(dts)
        assert re.search(r'gpio\s*=', fixups), (
            "W5500 interrupt-parent must reference &gpio. The GPIO interrupt "
            "controller phandle should appear in __fixups__."
        )

    def test_status_okay_not_ok(self):
        """All status properties must use 'okay' per DT specification."""
        dts = self._decompile()
        assert re.search(r'status\s*=\s*"okay"', dts), (
            'No status = "okay" found in overlay. Enabled nodes must set '
            'status = "okay".'
        )
        assert not re.search(r'status\s*=\s*"ok"\s*;', dts), (
            'Found status = "ok" which is non-standard. The Device Tree '
            'Specification requires "okay" for the enabled state.'
        )

    def test_no_stale_peripherals(self):
        """Overlay must only contain devices from hat_spec.md."""
        dts = self._decompile()
        stale_devices = ['mcp23017', 'ds3231', 'mcp3008', 'dallas,ds']
        for stale in stale_devices:
            assert stale not in dts.lower(), (
                f"Found '{stale}' which is not in the HAT specification. "
                "The overlay must be designed from hat_spec.md only."
            )


# ---------------------------------------------------------------------------
# Full build integration test
# ---------------------------------------------------------------------------

class TestFullBuild:
    """Verify the complete project builds successfully."""

    def test_make_produces_all_artifacts(self):
        """make must produce both kernel8.img and hat-overlay.dtbo."""
        result = run('make clean && make')
        assert result.returncode == 0, (
            f"Full build failed:\nstdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
        assert os.path.exists('/app/kernel8.img'), (
            "kernel8.img not produced by make"
        )
        assert os.path.exists('/app/hat-overlay.dtbo'), (
            "hat-overlay.dtbo not produced by make"
        )
