#!/usr/bin/env python3
"""Solution: evaluate/fix bare-metal BCM2711 issues and design DT overlay.

Part 1 — Evaluate existing code for BCM2711 correctness:
  start.S   - Vector table alignment: .align 4 -> .balign 2048
  link.ld   - Base address: 0x8000 -> 0x80000 (AArch64 RPi4)
  link.ld   - BSS symbols: add __bss_start and __bss_end
  mmio.h    - Peripheral base: 0x3F000000 -> 0xFE000000 (BCM2711)
  mmio.h    - GPFSEL1 offset: 0x08 -> 0x04
  mmio.h    - Baud divisor: 270 -> 541 (500MHz system clock)

Part 2 — Design device tree overlay from hat_spec.md:
  Create hat-overlay.dts with:
    fragment@0: i2c1 with BME280 (0x76), ADS1115 (0x48), PCA9685 (0x40)
    fragment@1: spi0 with W5500 (CE0, 33.3MHz, GPIO25 interrupt)
"""

import re


def read_file(path):
    with open(path, 'r') as f:
        return f.read()


def write_file(path, content):
    with open(path, 'w') as f:
        f.write(content)


# ---- Part 1: Evaluate and fix bare-metal code for BCM2711 ----

def fix_start_s():
    """Fix exception vector table alignment.

    VBAR_EL1 requires bits [10:0] = 0, meaning 2048-byte alignment.
    The code uses .align 4 which gives only 2^4 = 16-byte alignment.
    Must use .balign 2048 for correct ARMv8-A vector table placement.
    """
    content = read_file('/app/start.S')
    content = content.replace('.align 4', '.balign 2048')
    write_file('/app/start.S', content)


def fix_link_ld():
    """Fix linker script for RPi4 AArch64.

    1. RPi4 AArch64 kernel loads at 0x80000 (not 0x8000 for RPi1 32-bit).
    2. Startup code references __bss_start/__bss_end for BSS clearing —
       these must be defined in the linker script.
    """
    content = read_file('/app/link.ld')
    content = content.replace('. = 0x8000;', '. = 0x80000;')
    content = content.replace(
        '        *(.bss)\n        *(COMMON)',
        '        __bss_start = .;\n'
        '        *(.bss)\n'
        '        *(COMMON)\n'
        '        __bss_end = .;'
    )
    write_file('/app/link.ld', content)


def fix_mmio_h():
    """Fix BCM2711 peripheral addresses and UART baud rate.

    1. BCM2711 peripheral base is 0xFE000000 (BCM2835 uses 0x3F000000).
    2. GPFSEL1 is at GPIO_BASE + 0x04 (0x08 is GPFSEL2).
    3. Baud divisor for 500MHz: 500000000/(8*115200)-1 = 541 (not 270 for 250MHz).
    """
    content = read_file('/app/mmio.h')
    content = content.replace('0x3F000000', '0xFE000000')
    content = re.sub(
        r'(#define\s+GPFSEL1\s+\(GPIO_BASE\s*\+\s*)0x08',
        r'\g<1>0x04', content
    )
    content = content.replace('AUX_MU_BAUD_VAL 270', 'AUX_MU_BAUD_VAL 541')
    write_file('/app/mmio.h', content)


# ---- Part 2: Design device tree overlay from hardware specification ----

def create_hat_overlay():
    """Design the device tree overlay from /app/hat_spec.md.

    Design decisions:
    - fragment@0 targets &i2c1 (user-accessible I2C on 40-pin header)
    - BME280: compatible="bosch,bme280", reg=<0x76> (SDO=GND)
    - ADS1115: compatible="ti,ads1115", reg=<0x48> (ADDR=GND),
      with #address-cells/#size-cells for channel sub-nodes
    - PCA9685: compatible="nxp,pca9685", reg=<0x40> (A0-A5=GND)
    - fragment@1 targets &spi0 (primary SPI on header)
    - W5500: compatible="wiznet,w5500", reg=<0> (CE0),
      spi-max-frequency=33333333 (33.3MHz from datasheet),
      interrupt-parent=&gpio, interrupts=<25 8> (GPIO25, IRQ_TYPE_LEVEL_LOW)
    - All enabled nodes use status="okay" per DT specification
    """
    dts_content = """\
/dts-v1/;
/plugin/;

/ {
    compatible = "brcm,bcm2711";

    fragment@0 {
        target = <&i2c1>;
        __overlay__ {
            status = "okay";
            #address-cells = <1>;
            #size-cells = <0>;

            bme280@76 {
                compatible = "bosch,bme280";
                reg = <0x76>;
            };

            ads1115@48 {
                compatible = "ti,ads1115";
                reg = <0x48>;
                #address-cells = <1>;
                #size-cells = <0>;
            };

            pca9685@40 {
                compatible = "nxp,pca9685";
                reg = <0x40>;
            };
        };
    };

    fragment@1 {
        target = <&spi0>;
        __overlay__ {
            status = "okay";
            #address-cells = <1>;
            #size-cells = <0>;

            w5500@0 {
                compatible = "wiznet,w5500";
                reg = <0>;
                spi-max-frequency = <33333333>;
                interrupt-parent = <&gpio>;
                interrupts = <25 8>;
            };
        };
    };
};
"""
    write_file('/app/hat-overlay.dts', dts_content)


if __name__ == '__main__':
    print("Part 1: Evaluating and fixing bare-metal code for BCM2711...")
    fix_start_s()
    fix_link_ld()
    fix_mmio_h()
    print("  Fixed start.S, link.ld, mmio.h")

    print("Part 2: Designing device tree overlay from hardware spec...")
    create_hat_overlay()
    print("  Created hat-overlay.dts")

    print("Done. Ready for 'make'.")
