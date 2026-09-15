# Thrust Calibration Binary Format (TCAL v2)

Binary file storing per-thruster calibration data from the thrust stand.

## File Layout

### Header (8 bytes)

| Offset | Size | Type      | Description                              |
|--------|------|-----------|------------------------------------------|
| 0x00   | 4    | char[4]   | Magic bytes: `TCAL` (0x54 0x43 0x41 0x4C)|
| 0x04   | 1    | uint8     | Format version (currently 2)             |
| 0x05   | 1    | uint8     | Number of thruster records               |
| 0x06   | 2    | uint16 LE | Flags (reserved, currently 0x0000)       |

### Per-Thruster Record (32 bytes each)

Records follow immediately after the header, packed sequentially.

| Offset | Size | Type      | Description                                    |
|--------|------|-----------|------------------------------------------------|
| 0x00   | 1    | uint8     | Thruster ID (1-indexed)                        |
| 0x01   | 3    | padding   | Reserved (0x00 0x00 0x00)                      |
| 0x04   | 4    | uint32 LE | Calibration date (Unix epoch seconds)          |
| 0x08   | 8    | float64 LE| Thrust coefficient (N per unit normalized cmd) |
| 0x10   | 4    | float32 LE| Positive deadband (normalized, 0.0-1.0)        |
| 0x14   | 4    | float32 LE| Negative deadband (normalized, 0.0-1.0)        |
| 0x18   | 4    | float32 LE| Maximum forward thrust (N)                     |
| 0x1C   | 4    | float32 LE| Maximum reverse thrust (N)                     |

### Total File Size

`8 + N * 32` bytes, where N = number of thrusters.

## Notes

- All multi-byte integers and floats are little-endian.
- Normalized command: `(pwm_us - 1500) / 400.0`, mapping PWM range
  [1100, 1900] to [-1.0, +1.0].
- Thrust coefficient relates normalized command to force:
  `force_N = thrust_coeff * normalized_command` (linear approximation).
- Deadband values specify the command magnitude below which the thruster
  produces negligible thrust.
