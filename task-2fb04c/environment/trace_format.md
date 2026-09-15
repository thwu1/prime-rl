# ArduinoX86 Hardware Trace Capture Format (v1)

Binary format for storing hardware execution traces captured from an Intel 8088
CPU via the ArduinoX86 GPIO-based capture system. Each trace records full CPU
register state before and after executing a single instruction on real silicon.

## File Structure

### Header (8 bytes)

| Offset | Size | Type      | Description                       |
|--------|------|-----------|-----------------------------------|
| 0      | 4    | char[4]   | Magic identifier: `8T88`          |
| 4      | 2    | uint16 LE | Format version (currently `1`)    |
| 6      | 2    | uint16 LE | Number of trace records           |

### Records

Records are concatenated immediately after the header with no inter-record
padding. Each record is **81 bytes**.

#### Documented Record Fields

| Offset | Size | Type          | Description                                |
|--------|------|---------------|--------------------------------------------|
| 0      | 32   | char[32]      | Test identifier (null-padded ASCII string) |
| 32     | 1    | uint8         | Number of valid instruction bytes (1–8)    |
| 33     | 8    | uint8[8]      | Instruction opcode bytes (zero-padded)     |
| 41     | 16   | uint16 LE × 8 | Initial register file                      |
| 57     | 2    | uint16 LE     | Initial FLAGS register                     |
| 59     | 2    | uint16 LE     | Initial instruction pointer (IP)           |
| 61     | 16   | uint16 LE × 8 | Expected register file after execution     |
| 77     | 2    | uint16 LE     | Expected FLAGS after execution             |

Register file ordering: AX, CX, DX, BX, SP, BP, SI, DI

Trailing bytes in each record contain capture-session metadata whose layout is
specific to the ArduinoX86 firmware revision that produced the capture. Their
interpretation may vary between capture sessions.

## Notes

- All multi-byte integers are little-endian.
- Instruction bytes are stored in memory order (byte at CS:IP first).
- Register values are unsigned 16-bit.
- The FLAGS register follows the standard 8088 layout (bit 0 = CF, bit 2 = PF,
  bit 4 = AF, bit 6 = ZF, bit 7 = SF, bit 8 = TF, bit 9 = IF, bit 10 = DF,
  bit 11 = OF). Bit 1 is always set on the 8088.
- **Important**: The 8088 architecture leaves certain FLAGS bits undefined after
  specific instruction classes. Hardware behavior for undefined flag bits is
  nondeterministic — consecutive executions of the same instruction may produce
  different values for these bits. A valid conformance comparison **must**
  account for which FLAGS bits are architecturally meaningful for the particular
  instruction under test. Comparing all 16 FLAGS bits indiscriminately will
  produce spurious mismatches.
