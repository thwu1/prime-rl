# Industrial Monitoring HAT — Hardware Specification

## Platform
Raspberry Pi 4 Model B (BCM2711) with custom industrial monitoring HAT.

## Peripheral Connections

### 1. CAN Bus Controller — Microchip MCP2515
- **Bus**: SPI0, Chip Select 0 (CE0)
- **Crystal oscillator**: 16 MHz external oscillator
- **Interrupt**: MCP2515 INT pin → BCM GPIO 25, active-low, falling edge triggered
- **Maximum SPI clock speed**: 10 MHz
- **Clock source**: Requires a fixed-clock provider node referenced via `clocks` phandle

### 2. Analog-to-Digital Converter — Microchip MCP3008
- **Bus**: SPI0, Chip Select 1 (CE1)
- **Maximum SPI clock speed**: 1.35 MHz
- **No interrupt line**

### 3. GPIO Expander — Microchip MCP23017
- **Bus**: I2C1 (SDA1/SCL1 on GPIO2/GPIO3)
- **Address pins**: A2=GND, A1=GND, A0=GND → I2C address 0x20
- **Interrupt**: INTA pin → BCM GPIO 24, active-low, falling edge triggered
- **INTA and INTB mirrored**
- **Role**: Must function as both gpio-controller and interrupt-controller for downstream consumers
- **Note**: This is the I2C variant (MCP23017). The SPI variant is MCP23S17 — they use different kernel drivers.

### 4. Real-Time Clock — Maxim DS3231
- **Bus**: I2C1
- **I2C address**: 0x68 (fixed, not configurable)
- **Upstream Linux kernel binding**: vendor prefix `maxim`

### 5. Environmental Sensor — Bosch BME280
- **Bus**: I2C1
- **SDO pin**: Connected to GND → I2C address 0x76
- **Upstream Linux kernel binding**: `bosch,bme280`

### 6. Status LED
- **GPIO**: BCM GPIO 17
- **Polarity**: Active high — LED illuminates when GPIO is driven high
- **Default behavior**: Heartbeat blink pattern

### 7. Reset Button
- **GPIO**: BCM GPIO 22
- **Polarity**: Active low — button press pulls GPIO to ground
- **Input event**: KEY_POWER (linux input code 116)
- **Debounce interval**: 50 ms

### 8. 1-Wire Temperature Sensor Bus
- **GPIO**: BCM GPIO 4
- **External pull-up**: 4.7kΩ to 3.3V
- **Polarity**: Active high
- **Driver**: w1-gpio

## Variant Wiring Configuration

An alternative assembly variant exists for high-density rack installations where GPIO 25 and GPIO 24 are occupied by an adjacent expansion board:

- **Variant**: MCP2515 INT moves to BCM GPIO 12 (instead of GPIO 25)
- **Variant**: MCP23017 INTA moves to BCM GPIO 6 (instead of GPIO 24)

The combined overlay must accept runtime parameters to switch between standard and variant wiring without recompiling the overlay.

## Design Notes

- I2C0 is reserved for HAT ID EEPROM and CSI/DSI on the Raspberry Pi — it must never be used for user peripherals.
- I2C1 is the user-accessible I2C bus on the 40-pin header (SDA1=GPIO2, SCL1=GPIO3).
- SPI0 must be explicitly enabled and must declare proper address and size cell counts for child device addressing.
- Both SPI chip-select devices share the SPI0 bus and are distinguished solely by their chip select line.
- The MCP2515 CAN controller requires a fixed-clock provider node as its oscillator source, referenced via the `clocks` phandle property.
