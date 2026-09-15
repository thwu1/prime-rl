#!/usr/bin/env python3
"""Fix all bugs in the bare-metal RPi4 project.

Bugs fixed:
  start.S   - Vector table alignment: .align 4 -> .balign 2048
  link.ld   - Base address: 0x8000 -> 0x80000
  link.ld   - BSS symbols: add __bss_start and __bss_end
  mmio.h    - Peripheral base: 0x3F000000 -> 0xFE000000 (BCM2711)
  mmio.h    - GPFSEL1 offset: 0x08 -> 0x04
  mmio.h    - Baud divisor: 270 -> 541 (500MHz clock)
  hat-overlay.dts - Add /plugin/ directive
  hat-overlay.dts - I2C target: i2c0 -> i2c1
  hat-overlay.dts - RTC compatible: dallas -> maxim
  hat-overlay.dts - SPI reg: add reg = <0>
  hat-overlay.dts - Status: "ok" -> "okay"
"""

import re


def read_file(path):
    with open(path, 'r') as f:
        return f.read()


def write_file(path, content):
    with open(path, 'w') as f:
        f.write(content)


def fix_start_s():
    """Fix exception vector table alignment in start.S."""
    content = read_file('/app/start.S')
    # The vector table needs 2048-byte alignment (VBAR_EL1 bits [10:0] = 0).
    # .align 4 gives only 16-byte alignment (2^4); need .balign 2048.
    content = content.replace('.align 4', '.balign 2048')
    write_file('/app/start.S', content)


def fix_link_ld():
    """Fix linker script base address and BSS symbol definitions."""
    content = read_file('/app/link.ld')

    # Fix 1: RPi4 AArch64 kernel loads at 0x80000, not 0x8000 (RPi1 32-bit).
    content = content.replace('. = 0x8000;', '. = 0x80000;')

    # Fix 2: The startup code references __bss_start and __bss_end to clear
    # the BSS section. These must be defined in the linker script.
    content = content.replace(
        '        *(.bss)\n        *(COMMON)',
        '        __bss_start = .;\n        *(.bss)\n        *(COMMON)\n        __bss_end = .;'
    )

    write_file('/app/link.ld', content)


def fix_mmio_h():
    """Fix BCM2711 peripheral addresses and UART baud rate in mmio.h."""
    content = read_file('/app/mmio.h')

    # Fix 1: BCM2711 peripheral base is 0xFE000000 (not BCM2835's 0x3F000000).
    content = content.replace('0x3F000000', '0xFE000000')

    # Fix 2: GPFSEL1 is at GPIO_BASE + 0x04, not 0x08 (which is GPFSEL2).
    # Use regex to target only the GPFSEL1 definition line.
    content = re.sub(
        r'(#define\s+GPFSEL1\s+\(GPIO_BASE\s*\+\s*)0x08',
        r'\g<1>0x04',
        content
    )

    # Fix 3: Baud divisor for 500MHz: 500000000/(8*115200)-1 = 541.
    # Value 270 assumes RPi3's 250MHz clock.
    content = content.replace('AUX_MU_BAUD_VAL 270', 'AUX_MU_BAUD_VAL 541')

    write_file('/app/mmio.h', content)


def fix_hat_overlay_dts():
    """Fix device tree overlay bugs."""
    content = read_file('/app/hat-overlay.dts')

    # Fix 1: Overlay requires /plugin/; directive for dtc to generate fixups
    # for unresolved phandle references.
    content = content.replace('/dts-v1/;', '/dts-v1/;\n/plugin/;')

    # Fix 2: I2C peripherals should target i2c1 (user-accessible bus on the
    # 40-pin header), not i2c0 (reserved for HAT EEPROM).
    content = content.replace('<&i2c0>', '<&i2c1>')

    # Fix 3: DS3231 RTC kernel driver uses 'maxim,ds3231' compatible string,
    # not 'dallas,ds3231' (Dallas Semiconductor was acquired by Maxim).
    content = content.replace('"dallas,ds3231"', '"maxim,ds3231"')

    # Fix 4: SPI child nodes must have a reg property for chip select.
    content = content.replace(
        'compatible = "microchip,mcp3008";\n                spi-max-frequency',
        'compatible = "microchip,mcp3008";\n                reg = <0>;\n                spi-max-frequency'
    )

    # Fix 5: DT spec requires status = "okay" (not "ok") for enabled state.
    content = content.replace('status = "ok"', 'status = "okay"')

    write_file('/app/hat-overlay.dts', content)


if __name__ == '__main__':
    fix_start_s()
    fix_link_ld()
    fix_mmio_h()
    fix_hat_overlay_dts()
    print("All 11 bugs fixed.")
