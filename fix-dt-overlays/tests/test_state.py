
"""
Tests for Industrial Monitoring HAT device tree overlay task.
Verifies all overlay DTBOs compile, decompile correctly, and contain
properties matching the hardware specification.
"""

import subprocess
import os
import re
import pytest

OVERLAY_DIR = "/app/overlays"


def decompile_dtbo(name):
    """Decompile a .dtbo file and return the DTS text."""
    path = os.path.join(OVERLAY_DIR, f"{name}.dtbo")
    assert os.path.isfile(path), f"{path} does not exist"
    result = subprocess.run(
        ["dtc", "-I", "dtb", "-O", "dts", path],
        capture_output=True, text=True
    )
    assert result.returncode == 0, f"Failed to decompile {path}: {result.stderr}"
    return result.stdout


# =============================================================================
# SPI Devices Overlay Tests
# =============================================================================

class TestSpiDevicesOverlay:
    """Tests for the fixed spi-devices.dtbo overlay."""

    def test_dtbo_exists(self):
        assert os.path.isfile(f"{OVERLAY_DIR}/spi-devices.dtbo"), \
            "spi-devices.dtbo not found — did you compile the overlay?"

    def test_decompiles_successfully(self):
        dts = decompile_dtbo("spi-devices")
        assert len(dts) > 100, "Decompiled output too short"

    def test_source_has_plugin_directive(self):
        """Fixed DTS source must have /plugin/ directive for overlay compilation."""
        with open(f"{OVERLAY_DIR}/spi-devices.dts") as f:
            content = f.read()
        assert '/plugin/' in content, \
            "spi-devices.dts must have /plugin/ directive"

    def test_mcp2515_compatible_string(self):
        """Must have correct MCP2515 compatible string."""
        dts = decompile_dtbo("spi-devices")
        assert '"microchip,mcp2515"' in dts

    def test_mcp3008_compatible_string(self):
        """Must have correct MCP3008 compatible string with vendor prefix."""
        dts = decompile_dtbo("spi-devices")
        assert '"microchip,mcp3008"' in dts, \
            "MCP3008 should use 'microchip,mcp3008' compatible string"
        assert '"mcp320x"' not in dts, \
            "mcp320x is the kernel module name, not a valid DT compatible string"

    def test_spi_max_frequency_10mhz(self):
        """SPI max frequency for CAN must be 10 MHz, not 125 MHz."""
        dts = decompile_dtbo("spi-devices").lower()
        # 10000000 = 0x989680
        assert re.search(r'0x0*989680', dts), \
            "spi-max-frequency should be 10000000 (0x989680)"
        # Must NOT have broken 125 MHz value (0x7735940)
        assert not re.search(r'0x0*7735940', dts), \
            "spi-max-frequency still has broken 125 MHz value"

    def test_clock_frequency_16mhz(self):
        """Oscillator clock frequency must be 16 MHz, not 8 MHz."""
        dts = decompile_dtbo("spi-devices").lower()
        # 16000000 = 0xf42400
        assert re.search(r'0x0*f42400', dts), \
            "clock-frequency should be 16000000 (0xf42400)"
        # Must NOT have broken 8 MHz value (0x7a1200)
        assert not re.search(r'0x0*7a1200', dts), \
            "clock-frequency still has broken 8 MHz value"

    def test_can_chip_select_zero(self):
        """CAN device must be on chip select 0, not 1."""
        dts = decompile_dtbo("spi-devices")
        assert 'can@1' not in dts, \
            "can@1 still present — CAN controller must be at CS0"

    def test_interrupt_falling_edge(self):
        """Interrupt must be GPIO25 with falling edge trigger (0x2)."""
        dts = decompile_dtbo("spi-devices")
        match = re.search(
            r'interrupts\s*=\s*<\s*(0x[0-9a-fA-F]+)\s+(0x[0-9a-fA-F]+)\s*>',
            dts
        )
        assert match is not None, "Could not find interrupts property"
        gpio_num = int(match.group(1), 16)
        trigger = int(match.group(2), 16)
        assert gpio_num == 25, f"Expected GPIO25 (0x19), got {gpio_num}"
        assert trigger == 2, \
            f"Expected falling edge (0x2), got 0x{trigger:x} — MCP2515 INT is active-low"

    def test_spi_bus_enabled(self):
        """SPI bus overlay must have status = 'okay'."""
        dts = decompile_dtbo("spi-devices")
        assert 'status = "okay"' in dts, \
            "SPI bus must be enabled with status = \"okay\""

    def test_spi_bus_address_cells(self):
        """SPI bus must declare #address-cells and #size-cells."""
        dts = decompile_dtbo("spi-devices")
        assert '#address-cells' in dts, "Missing #address-cells on SPI bus"
        assert '#size-cells' in dts, "Missing #size-cells on SPI bus"


# =============================================================================
# I2C Sensors Overlay Tests
# =============================================================================

class TestI2cSensorsOverlay:
    """Tests for the fixed i2c-sensors.dtbo overlay."""

    def test_dtbo_exists(self):
        assert os.path.isfile(f"{OVERLAY_DIR}/i2c-sensors.dtbo"), \
            "i2c-sensors.dtbo not found — did you compile the overlay?"

    def test_decompiles_successfully(self):
        dts = decompile_dtbo("i2c-sensors")
        assert len(dts) > 100

    def test_mcp23017_compatible_i2c_variant(self):
        """Must use I2C variant (mcp23017), NOT SPI variant (mcp23s17)."""
        dts = decompile_dtbo("i2c-sensors")
        assert '"microchip,mcp23017"' in dts, \
            "Should use microchip,mcp23017 (I2C variant)"
        assert '"microchip,mcp23s17"' not in dts, \
            "mcp23s17 is the SPI variant — wrong for I2C bus"

    def test_mcp23017_address_0x20(self):
        """MCP23017 address must be 0x20 (A2=A1=A0=GND), not 0x27."""
        dts = decompile_dtbo("i2c-sensors")
        assert 'mcp23017@20' in dts, \
            "MCP23017 node should be mcp23017@20 (address 0x20)"
        assert 'mcp23017@27' not in dts, \
            "mcp23017@27 still present — address should be 0x20"

    def test_mcp23017_gpio_controller(self):
        """MCP23017 must be declared as a gpio-controller with #gpio-cells."""
        dts = decompile_dtbo("i2c-sensors")
        assert re.search(r'^\s*gpio-controller\s*;', dts, re.MULTILINE), \
            "Missing gpio-controller boolean property"
        assert '#gpio-cells' in dts, \
            "Missing #gpio-cells property"

    def test_mcp23017_interrupt_controller(self):
        """MCP23017 must be declared as an interrupt-controller."""
        dts = decompile_dtbo("i2c-sensors")
        assert re.search(r'^\s*interrupt-controller\s*;', dts, re.MULTILINE), \
            "Missing interrupt-controller boolean property"
        assert '#interrupt-cells' in dts, \
            "Missing #interrupt-cells property"

    def test_ds3231_compatible_maxim(self):
        """DS3231 must use 'maxim' vendor prefix, not 'dallas'."""
        dts = decompile_dtbo("i2c-sensors")
        assert '"maxim,ds3231"' in dts, \
            "DS3231 should use maxim,ds3231 compatible string"
        assert '"dallas,ds3231"' not in dts, \
            "dallas,ds3231 is not the correct upstream binding"

    def test_ds3231_address_0x68(self):
        """DS3231 address must be 0x68, not 0x57."""
        dts = decompile_dtbo("i2c-sensors")
        assert 'ds3231@68' in dts, \
            "DS3231 node should be ds3231@68 (address 0x68)"
        assert 'ds3231@57' not in dts, \
            "ds3231@57 still present — address should be 0x68"

    def test_bme280_compatible_bosch(self):
        """BME280 must use 'bosch,bme280' compatible string with vendor prefix."""
        dts = decompile_dtbo("i2c-sensors")
        assert '"bosch,bme280"' in dts, \
            "BME280 should use bosch,bme280 compatible string"

    def test_bme280_address_0x76(self):
        """BME280 address must be 0x76 (SDO=GND), not 0x77."""
        dts = decompile_dtbo("i2c-sensors")
        assert 'bme280@76' in dts, \
            "BME280 node should be bme280@76 (address 0x76)"
        assert 'bme280@77' not in dts, \
            "bme280@77 still present — SDO is tied to GND so address is 0x76"

    def test_targets_i2c1_not_i2c0(self):
        """Overlay must target i2c1 (user bus), NOT i2c0 (reserved)."""
        dts = decompile_dtbo("i2c-sensors")
        fixups_match = re.search(
            r'__fixups__\s*\{([^}]+)\}', dts, re.DOTALL
        )
        assert fixups_match is not None, "No __fixups__ section found"
        fixups = fixups_match.group(1)
        has_i2c1 = 'i2c1' in fixups or 'i2c_arm' in fixups
        has_i2c0 = 'i2c0' in fixups or 'i2c_vc' in fixups
        assert has_i2c1, \
            "Overlay should target i2c1 (user-accessible I2C bus)"
        assert not has_i2c0, \
            "Overlay targets i2c0 (reserved for HAT EEPROM/camera) — use i2c1"


# =============================================================================
# GPIO IO Overlay Tests
# =============================================================================

class TestGpioIoOverlay:
    """Tests for the fixed gpio-io.dtbo overlay."""

    def test_dtbo_exists(self):
        assert os.path.isfile(f"{OVERLAY_DIR}/gpio-io.dtbo"), \
            "gpio-io.dtbo not found"

    def test_decompiles_successfully(self):
        dts = decompile_dtbo("gpio-io")
        assert len(dts) > 100

    def test_source_has_plugin_directive(self):
        """Source DTS must have /plugin/ directive."""
        with open(f"{OVERLAY_DIR}/gpio-io.dts") as f:
            content = f.read()
        assert '/plugin/' in content

    def test_has_gpio_leds(self):
        """Must have a gpio-leds compatible node."""
        dts = decompile_dtbo("gpio-io")
        assert '"gpio-leds"' in dts

    def test_led_on_gpio17(self):
        """LED must be on GPIO17 (0x11), not GPIO27 (0x1b)."""
        dts = decompile_dtbo("gpio-io").lower()
        assert '0x11' in dts, "GPIO17 (0x11) not found in overlay"
        assert '0x1b' not in dts, \
            "GPIO27 (0x1b) still present — LED should be on GPIO17"

    def test_led_heartbeat_trigger(self):
        """LED must use heartbeat trigger, not default-on."""
        dts = decompile_dtbo("gpio-io")
        assert '"heartbeat"' in dts, "heartbeat trigger not found"
        assert '"default-on"' not in dts, \
            "default-on trigger still present — should be heartbeat"

    def test_led_active_high(self):
        """LED must use active-high polarity (flag 0), not active-low (flag 1)."""
        with open(f"{OVERLAY_DIR}/gpio-io.dts") as f:
            src = f.read()
        # Verify GPIO 17 with active-high flag (0)
        assert re.search(
            r'gpios\s*=\s*<\s*&gpio\s+(?:17|0x11)\s+(?:0|0x0+)\s*>',
            src
        ), "LED must have gpios = <&gpio 17 0> (GPIO17, active-high)"

    def test_has_gpio_keys(self):
        """Must have a gpio-keys compatible node."""
        dts = decompile_dtbo("gpio-io")
        assert '"gpio-keys"' in dts

    def test_button_gpio22_key_power(self):
        """Button must be on GPIO22 (0x16) with KEY_POWER (0x74 = 116)."""
        dts = decompile_dtbo("gpio-io").lower()
        assert '0x16' in dts, "GPIO22 (0x16) not found in overlay"
        assert '0x74' in dts, "KEY_POWER code 116 (0x74) not found"
        assert '0x198' not in dts, \
            "KEY_RESTART (0x198) still present — should be KEY_POWER (0x74)"

    def test_has_w1_gpio(self):
        """Must have a w1-gpio compatible node for 1-Wire bus."""
        dts = decompile_dtbo("gpio-io")
        assert '"w1-gpio"' in dts

    def test_w1_on_gpio4(self):
        """1-Wire bus must be on GPIO4, not GPIO14 (UART TX conflict)."""
        dts = decompile_dtbo("gpio-io").lower()
        assert re.search(r'0x0*4[>\s;]', dts), \
            "GPIO4 not found in overlay"
        assert '0x0e' not in dts, \
            "GPIO14 (0x0e) still present — conflicts with UART TX, use GPIO4"


# =============================================================================
# Combined HAT Overlay Tests
# =============================================================================

class TestCombinedOverlay:
    """Tests for the combined-hat.dtbo overlay merging all peripherals."""

    def test_dtbo_exists(self):
        assert os.path.isfile(f"{OVERLAY_DIR}/combined-hat.dtbo"), \
            "combined-hat.dtbo not found"

    def test_decompiles_successfully(self):
        dts = decompile_dtbo("combined-hat")
        assert len(dts) > 300

    def test_source_has_plugin_directive(self):
        """Source DTS must have /plugin/ directive."""
        with open(f"{OVERLAY_DIR}/combined-hat.dts") as f:
            content = f.read()
        assert '/plugin/' in content

    def test_contains_all_peripheral_types(self):
        """Combined overlay must include all 8 peripheral types."""
        dts = decompile_dtbo("combined-hat")
        assert '"microchip,mcp2515"' in dts, "Missing CAN controller"
        assert '"microchip,mcp3008"' in dts, "Missing ADC"
        assert '"microchip,mcp23017"' in dts, "Missing GPIO expander"
        assert '"maxim,ds3231"' in dts, "Missing RTC"
        assert '"bosch,bme280"' in dts, "Missing environmental sensor"
        assert '"gpio-leds"' in dts, "Missing LED controller"
        assert '"gpio-keys"' in dts, "Missing button controller"
        assert '"w1-gpio"' in dts, "Missing 1-Wire bus"

    def test_combined_spi_frequency(self):
        """Combined overlay must have correct SPI max frequency (10 MHz)."""
        dts = decompile_dtbo("combined-hat").lower()
        assert re.search(r'0x0*989680', dts), \
            "SPI max frequency should be 10 MHz"

    def test_combined_clock_frequency(self):
        """Combined overlay must have correct clock frequency (16 MHz)."""
        dts = decompile_dtbo("combined-hat").lower()
        assert re.search(r'0x0*f42400', dts), \
            "Clock frequency should be 16 MHz"

    def test_combined_i2c_addresses(self):
        """Combined overlay must have correct I2C device addresses."""
        dts = decompile_dtbo("combined-hat")
        assert 'mcp23017@20' in dts, "MCP23017 should be at address 0x20"
        assert 'ds3231@68' in dts, "DS3231 should be at address 0x68"
        assert 'bme280@76' in dts, "BME280 should be at address 0x76"

    def test_combined_can_at_cs0(self):
        """CAN controller in combined overlay must be at CS0."""
        dts = decompile_dtbo("combined-hat")
        assert 'can@1' not in dts, "CAN should be at CS0, not CS1"

    def test_has_overrides_section(self):
        """Combined overlay source must have __overrides__ for variant wiring."""
        with open(f"{OVERLAY_DIR}/combined-hat.dts") as f:
            content = f.read()
        assert '__overrides__' in content, \
            "Missing __overrides__ section for variant wiring support"

    def test_overrides_for_variant_interrupts(self):
        """__overrides__ must define at least 2 interrupt-related parameters."""
        with open(f"{OVERLAY_DIR}/combined-hat.dts") as f:
            content = f.read()
        override_match = re.search(
            r'__overrides__\s*\{([^}]+)\}', content, re.DOTALL
        )
        assert override_match, "Could not parse __overrides__ section"
        body = override_match.group(1)
        # Must have at least 2 parameters
        params = re.findall(r'(\w+)\s*=', body)
        assert len(params) >= 2, \
            f"Expected at least 2 override parameters for variant wiring, found {len(params)}"
        # Must reference interrupt properties
        assert 'interrupt' in body.lower(), \
            "__overrides__ must reference interrupt properties for GPIO reassignment"

    def test_compiled_dtb_has_overrides(self):
        """Compiled combined DTB must contain __overrides__ node."""
        dts = decompile_dtbo("combined-hat")
        assert '__overrides__' in dts, \
            "Compiled combined-hat.dtbo missing __overrides__ node"


# =============================================================================
# Compilation Tests — verify all DTS source files compile with dtc
# =============================================================================

class TestCompilation:
    """Verify that all DTS source files compile successfully with dtc."""

    @pytest.mark.parametrize("name", [
        "spi-devices", "i2c-sensors", "gpio-io", "combined-hat"
    ])
    def test_dts_compiles_with_dtc(self, name):
        dts_path = f"{OVERLAY_DIR}/{name}.dts"
        assert os.path.isfile(dts_path), f"{dts_path} does not exist"
        result = subprocess.run(
            ["dtc", "-I", "dts", "-O", "dtb", "-@",
             "-o", "/dev/null", dts_path],
            capture_output=True, text=True
        )
        assert result.returncode == 0, \
            f"Failed to compile {name}.dts:\n{result.stderr}"
