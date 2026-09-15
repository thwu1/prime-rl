# Custom Data Acquisition HAT -- Hardware Specification
# Revision 1.0 -- Target: Raspberry Pi 4 Model B (BCM2711)

## Overview

Multi-sensor data acquisition HAT for the Raspberry Pi 4, providing environmental
monitoring, high-precision analog input, PWM output, and wired Ethernet connectivity.
This document specifies the peripheral connections and addressing for device tree
overlay development.

## Bus Allocation

### I2C Bus
All I2C peripherals connect to the user-accessible I2C bus on the 40-pin header
(SDA1 = GPIO2 / pin 3, SCL1 = GPIO3 / pin 5). This is the standard user I2C bus.
I2C-0 is reserved by the Raspberry Pi for HAT EEPROM identification and must NOT
be used for user peripherals.

### SPI Bus
The SPI peripheral uses the primary SPI bus available on the 40-pin header (SPI0):
MOSI = GPIO10, MISO = GPIO9, SCLK = GPIO11.

## Peripheral Definitions

### 1. Bosch BME280 -- Environmental Sensor
- **Bus**: I2C
- **Address configuration**: SDO pin tied to GND
  - SDO = GND gives 7-bit I2C slave address **0x76**
  - (SDO = VDDIO would give 0x77, but is not used on this board)
- **Function**: Temperature, humidity, barometric pressure

### 2. Texas Instruments ADS1115 -- 16-bit ADC
- **Bus**: I2C
- **Address configuration**: ADDR pin tied to GND
  - ADDR = GND gives 7-bit I2C slave address **0x48**
  - (ADDR = VDD = 0x49, ADDR = SDA = 0x4A, ADDR = SCL = 0x4B; none used)
- **Function**: 4-channel 16-bit analog-to-digital conversion
- **Note**: Node should declare #address-cells = <1> and #size-cells = <0>
  to support optional per-channel sub-nodes in the device tree

### 3. NXP PCA9685 -- 16-Channel 12-bit PWM Controller
- **Bus**: I2C
- **Address configuration**: Address pins A0 through A5 all tied to GND
  - All address bits low gives 7-bit I2C slave address **0x40**
- **Function**: 16-channel 12-bit hardware PWM for servo and LED control

### 4. WIZnet W5500 -- Hardwired TCP/IP Ethernet Controller
- **Bus**: SPI
- **Chip select**: directly wired to CE0 (SPI0_CE0_N / GPIO8)
- **Clock**: maximum SPI clock frequency 33333333 Hz (33.3 MHz per W5500 datasheet)
- **Interrupt**: INTn output connected to GPIO25
  - Active-low, level-triggered (IRQ_TYPE_LEVEL_LOW = 8)
  - The interrupt-parent must reference the SoC GPIO controller
- **Function**: Hardware TCP/IP stack with 10/100 Ethernet PHY

## Device Tree Requirements
- Use /dts-v1/; and /plugin/; directives for overlay compilation with dtc -@
- Set status = "okay" (not "ok") on all enabled nodes per the Devicetree Specification
- Use standard upstream Linux kernel compatible strings for each device
- I2C child nodes require a reg property with the 7-bit slave address
- SPI child nodes require a reg property with the chip-select index
