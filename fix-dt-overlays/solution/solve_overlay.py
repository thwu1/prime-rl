#!/usr/bin/env python3

"""
Solve the device tree overlay task.

Reads the hardware specification, derives correct property values,
generates fixed and new DTS overlay files, and compiles them with dtc.
"""

import subprocess
import sys
import os

OVERLAY_DIR = "/app/overlays"

# ---------------------------------------------------------------------------
# Hardware parameters derived from /app/hardware_spec.md
# ---------------------------------------------------------------------------

# CAN bus controller (MCP2515) on SPI
CAN_SPI_TARGET = "spi0"
CAN_CHIP_SELECT = 0               # CE0
CAN_COMPATIBLE = "microchip,mcp2515"
CAN_CRYSTAL_HZ = 16_000_000       # 16 MHz crystal
CAN_MAX_SPI_HZ = 10_000_000       # 10 MHz max SPI clock
CAN_INT_GPIO = 25
CAN_INT_TRIGGER = 0x2              # IRQ_TYPE_EDGE_FALLING

# ADC (MCP3008) on SPI
ADC_CHIP_SELECT = 1                # CE1
ADC_COMPATIBLE = "microchip,mcp3008"
ADC_MAX_SPI_HZ = 1_350_000        # 1.35 MHz max SPI clock

# GPIO expander (MCP23017) on I2C
EXPANDER_I2C_TARGET = "i2c1"
EXPANDER_COMPATIBLE = "microchip,mcp23017"  # I2C variant (NOT mcp23s17)
EXPANDER_ADDR = 0x20               # A2=A1=A0=GND
EXPANDER_INT_GPIO = 24
EXPANDER_INT_TRIGGER = 0x2         # IRQ_TYPE_EDGE_FALLING

# RTC (DS3231) on I2C
RTC_COMPATIBLE = "maxim,ds3231"    # 'maxim' vendor prefix
RTC_ADDR = 0x68

# Environmental sensor (BME280) on I2C
BME_COMPATIBLE = "bosch,bme280"
BME_ADDR = 0x76                    # SDO=GND

# Status LED
LED_GPIO = 17
LED_FLAGS = 0                      # GPIO_ACTIVE_HIGH
LED_TRIGGER = "heartbeat"

# Reset button
BUTTON_GPIO = 22
BUTTON_FLAGS = 1                   # GPIO_ACTIVE_LOW
BUTTON_KEYCODE = 116               # KEY_POWER
BUTTON_DEBOUNCE_MS = 50

# 1-Wire bus
W1_GPIO = 4
W1_FLAGS = 0                       # GPIO_ACTIVE_HIGH


def generate_spi_devices_dts():
    """Generate the fixed SPI devices overlay DTS."""
    return f"""\
/dts-v1/;
/plugin/;

/ {{
    compatible = "brcm,bcm2711";

    fragment@0 {{
        target = <&{CAN_SPI_TARGET}>;
        __overlay__ {{
            status = "okay";
            #address-cells = <1>;
            #size-cells = <0>;

            can0: can@{CAN_CHIP_SELECT} {{
                compatible = "{CAN_COMPATIBLE}";
                reg = <{CAN_CHIP_SELECT}>;
                spi-max-frequency = <{CAN_MAX_SPI_HZ}>;
                interrupt-parent = <&gpio>;
                interrupts = <{CAN_INT_GPIO} {CAN_INT_TRIGGER:#x}>;
                clocks = <&can0_osc>;
            }};

            adc0: adc@{ADC_CHIP_SELECT} {{
                compatible = "{ADC_COMPATIBLE}";
                reg = <{ADC_CHIP_SELECT}>;
                spi-max-frequency = <{ADC_MAX_SPI_HZ}>;
            }};
        }};
    }};

    fragment@1 {{
        target-path = "/";
        __overlay__ {{
            can0_osc: can0_osc {{
                compatible = "fixed-clock";
                #clock-cells = <0>;
                clock-frequency = <{CAN_CRYSTAL_HZ}>;
            }};
        }};
    }};
}};
"""


def generate_i2c_sensors_dts():
    """Generate the fixed I2C sensors overlay DTS."""
    return f"""\
/dts-v1/;
/plugin/;

/ {{
    compatible = "brcm,bcm2711";

    fragment@0 {{
        target = <&{EXPANDER_I2C_TARGET}>;
        __overlay__ {{
            status = "okay";
            #address-cells = <1>;
            #size-cells = <0>;

            gpio_expander: mcp23017@{EXPANDER_ADDR:x} {{
                compatible = "{EXPANDER_COMPATIBLE}";
                reg = <{EXPANDER_ADDR:#x}>;
                gpio-controller;
                #gpio-cells = <2>;
                interrupt-parent = <&gpio>;
                interrupts = <{EXPANDER_INT_GPIO} {EXPANDER_INT_TRIGGER:#x}>;
                interrupt-controller;
                #interrupt-cells = <2>;
                microchip,irq-mirror;
            }};

            rtc: ds3231@{RTC_ADDR:x} {{
                compatible = "{RTC_COMPATIBLE}";
                reg = <{RTC_ADDR:#x}>;
            }};

            env_sensor: bme280@{BME_ADDR:x} {{
                compatible = "{BME_COMPATIBLE}";
                reg = <{BME_ADDR:#x}>;
            }};
        }};
    }};
}};
"""


def generate_gpio_io_dts():
    """Generate the fixed GPIO IO overlay DTS."""
    return f"""\
/dts-v1/;
/plugin/;

/ {{
    compatible = "brcm,bcm2711";

    fragment@0 {{
        target-path = "/";
        __overlay__ {{
            hat_leds {{
                compatible = "gpio-leds";

                status_led: status-led {{
                    label = "hat:green:status";
                    gpios = <&gpio {LED_GPIO} {LED_FLAGS}>;
                    linux,default-trigger = "{LED_TRIGGER}";
                }};
            }};
        }};
    }};

    fragment@1 {{
        target-path = "/";
        __overlay__ {{
            hat_keys {{
                compatible = "gpio-keys";

                power_btn: power-button {{
                    label = "power";
                    linux,code = <{BUTTON_KEYCODE}>;
                    gpios = <&gpio {BUTTON_GPIO} {BUTTON_FLAGS}>;
                    debounce-interval = <{BUTTON_DEBOUNCE_MS}>;
                }};
            }};
        }};
    }};

    fragment@2 {{
        target-path = "/";
        __overlay__ {{
            onewire {{
                compatible = "w1-gpio";
                gpios = <&gpio {W1_GPIO} {W1_FLAGS}>;
            }};
        }};
    }};
}};
"""


def generate_combined_hat_dts():
    """Generate the combined overlay with all peripherals and __overrides__."""
    return f"""\
/dts-v1/;
/plugin/;

/ {{
    compatible = "brcm,bcm2711";

    /* SPI0: MCP2515 CAN bus controller + MCP3008 ADC */
    fragment@0 {{
        target = <&{CAN_SPI_TARGET}>;
        __overlay__ {{
            status = "okay";
            #address-cells = <1>;
            #size-cells = <0>;

            can0: can@{CAN_CHIP_SELECT} {{
                compatible = "{CAN_COMPATIBLE}";
                reg = <{CAN_CHIP_SELECT}>;
                spi-max-frequency = <{CAN_MAX_SPI_HZ}>;
                interrupt-parent = <&gpio>;
                interrupts = <{CAN_INT_GPIO} {CAN_INT_TRIGGER:#x}>;
                clocks = <&can0_osc>;
            }};

            adc0: adc@{ADC_CHIP_SELECT} {{
                compatible = "{ADC_COMPATIBLE}";
                reg = <{ADC_CHIP_SELECT}>;
                spi-max-frequency = <{ADC_MAX_SPI_HZ}>;
            }};
        }};
    }};

    /* Fixed clock source for MCP2515 + GPIO peripherals */
    fragment@1 {{
        target-path = "/";
        __overlay__ {{
            can0_osc: can0_osc {{
                compatible = "fixed-clock";
                #clock-cells = <0>;
                clock-frequency = <{CAN_CRYSTAL_HZ}>;
            }};

            hat_leds {{
                compatible = "gpio-leds";

                status-led {{
                    label = "hat:green:status";
                    gpios = <&gpio {LED_GPIO} {LED_FLAGS}>;
                    linux,default-trigger = "{LED_TRIGGER}";
                }};
            }};

            hat_keys {{
                compatible = "gpio-keys";

                power-button {{
                    label = "power";
                    linux,code = <{BUTTON_KEYCODE}>;
                    gpios = <&gpio {BUTTON_GPIO} {BUTTON_FLAGS}>;
                    debounce-interval = <{BUTTON_DEBOUNCE_MS}>;
                }};
            }};

            onewire {{
                compatible = "w1-gpio";
                gpios = <&gpio {W1_GPIO} {W1_FLAGS}>;
            }};
        }};
    }};

    /* I2C1: MCP23017 GPIO expander + DS3231 RTC + BME280 sensor */
    fragment@2 {{
        target = <&{EXPANDER_I2C_TARGET}>;
        __overlay__ {{
            status = "okay";
            #address-cells = <1>;
            #size-cells = <0>;

            gpio_expander: mcp23017@{EXPANDER_ADDR:x} {{
                compatible = "{EXPANDER_COMPATIBLE}";
                reg = <{EXPANDER_ADDR:#x}>;
                gpio-controller;
                #gpio-cells = <2>;
                interrupt-parent = <&gpio>;
                interrupts = <{EXPANDER_INT_GPIO} {EXPANDER_INT_TRIGGER:#x}>;
                interrupt-controller;
                #interrupt-cells = <2>;
                microchip,irq-mirror;
            }};

            rtc: ds3231@{RTC_ADDR:x} {{
                compatible = "{RTC_COMPATIBLE}";
                reg = <{RTC_ADDR:#x}>;
            }};

            env_sensor: bme280@{BME_ADDR:x} {{
                compatible = "{BME_COMPATIBLE}";
                reg = <{BME_ADDR:#x}>;
            }};
        }};
    }};

    /* Runtime parameters for variant wiring configuration */
    __overrides__ {{
        can_int_pin = <&can0>,"interrupts:0";
        expander_int_pin = <&gpio_expander>,"interrupts:0";
    }};
}};
"""


def write_and_compile(name, dts_content):
    """Write a DTS file and compile it to DTBO."""
    dts_path = os.path.join(OVERLAY_DIR, f"{name}.dts")
    dtbo_path = os.path.join(OVERLAY_DIR, f"{name}.dtbo")

    with open(dts_path, 'w') as f:
        f.write(dts_content)
    print(f"Wrote {dts_path}")

    result = subprocess.run(
        ["dtc", "-I", "dts", "-O", "dtb", "-@", "-o", dtbo_path, dts_path],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"ERROR compiling {name}.dts:", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        return False

    if result.stderr:
        print(f"Warnings for {name}.dts: {result.stderr.strip()}")

    print(f"Compiled {dtbo_path}")
    return True


def main():
    os.makedirs(OVERLAY_DIR, exist_ok=True)

    overlays = [
        ("spi-devices", generate_spi_devices_dts()),
        ("i2c-sensors", generate_i2c_sensors_dts()),
        ("gpio-io", generate_gpio_io_dts()),
        ("combined-hat", generate_combined_hat_dts()),
    ]

    success = True
    for name, content in overlays:
        if not write_and_compile(name, content):
            success = False

    if success:
        print("\nAll overlays compiled successfully.")
    else:
        print("\nSome overlays failed to compile.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
