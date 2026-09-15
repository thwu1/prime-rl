# I2C Bus Capture Binary Format (v1)

## File Structure

### Header (10 bytes)

| Offset | Size | Type    | Description                          |
|--------|------|---------|--------------------------------------|
| 0      | 4    | bytes   | Magic: `I2CB` (ASCII, 0x49 32 43 42) |
| 4      | 2    | uint16  | Version (little-endian), currently 1 |
| 6      | 4    | uint32  | Number of records (little-endian)    |

### Records (6 bytes each, immediately following header)

| Offset | Size | Type   | Description                              |
|--------|------|--------|------------------------------------------|
| 0      | 4    | uint32 | Timestamp in microseconds (little-endian) |
| 4      | 1    | uint8  | Event type (see table below)             |
| 5      | 1    | uint8  | Data byte (meaning depends on event type) |

Total file size = 10 + (num_records × 6) bytes.

## Event Types

| Code | Name         | Data byte meaning                                          |
|------|--------------|------------------------------------------------------------|
| 0x01 | `BUS_START`  | Unused (0x00). I2C START condition on the bus.             |
| 0x02 | `BUS_STOP`   | Unused (0x00). I2C STOP condition on the bus.              |
| 0x03 | `BYTE_WRITE` | The byte value written onto SDA by the master.             |
| 0x04 | `BYTE_READ`  | The byte value read from SDA (driven by the slave).        |
| 0x05 | `SLAVE_ACK`  | Unused (0x00). Acknowledge signal observed on the bus.     |
| 0x06 | `SLAVE_NACK` | Unused (0x00). Not-acknowledge signal observed on the bus. |

## I2C Protocol Context

The records represent a logic-analyzer-style capture of bus-level events. To reconstruct meaningful transactions, the following I2C protocol rules apply:

### Address Byte
The first `BYTE_WRITE` immediately following a `BUS_START` is the **address byte**:
- Bits [7:1] = 7-bit slave device address
- Bit [0] = R/W direction flag: `0` = master write, `1` = master read

### Acknowledgment Semantics
After each `BYTE_WRITE` or `BYTE_READ`, exactly one `SLAVE_ACK` or `SLAVE_NACK` follows:

- **Write direction** (`BYTE_WRITE` events after address ACK):
  - `SLAVE_ACK` = slave accepted the byte
  - `SLAVE_NACK` = slave rejected the byte (error condition)

- **Read direction** (`BYTE_READ` events):
  - `SLAVE_ACK` = master will read another byte (continue)
  - `SLAVE_NACK` = master signals end of read (normal termination, **not** an error)

- **After address byte**:
  - `SLAVE_ACK` = device is present and responding
  - `SLAVE_NACK` = no device at this address (device not present on bus)

### Repeated START
A `BUS_START` that occurs **without** a preceding `BUS_STOP` is a **repeated START** condition. This is commonly used in register-read sequences:

1. `BUS_START` → address+W → register address → repeated `BUS_START` → address+R → read data → `BUS_STOP`

The repeated START and subsequent events are part of the **same logical transaction** as the initial START.

### Transaction Boundaries
A transaction spans from the first `BUS_START` to the corresponding `BUS_STOP` (inclusive). Multiple phases within a transaction are separated by repeated START conditions.
