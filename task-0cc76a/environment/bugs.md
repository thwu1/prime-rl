# IMGP Library Bug Registry

This document describes four known security vulnerabilities in the IMGP
image parser library (`src/parser.c`). Each bug must be instrumented with
MAGMA canary instrumentation following the conventions in `magma/magma.h`.

---

## IMG001: Integer Overflow in Buffer Allocation

- **Type**: CWE-190 (Integer Overflow or Wraparound)
- **Location**: `parse_header()` in `src/parser.c`
- **Description**: The pixel buffer allocation size is computed by multiplying
  width, height, and channels using 32-bit unsigned arithmetic. When the
  mathematical product of these three values exceeds the range of `uint32_t`
  (4,294,967,295), the result silently wraps around, producing a buffer size
  far smaller than required. Subsequent operations that write pixel data into
  this undersized buffer cause a heap-based buffer overflow.
- **Impact**: Heap buffer overflow, potential arbitrary code execution.

---

## IMG002: Off-by-One Error in Palette Index Validation

- **Type**: CWE-193 (Off-by-One Error)
- **Location**: `apply_palette()` in `src/parser.c`
- **Description**: The palette index bounds check uses an incorrect relational
  operator, allowing an index value equal to the palette entry count to pass
  validation. Valid palette indices range from 0 to (palette_count - 1);
  an index equal to palette_count causes a one-element out-of-bounds read
  from the heap-allocated palette array.
- **Impact**: Out-of-bounds heap read, information disclosure.

---

## IMG003: Signed/Unsigned Type Confusion in Offset Validation

- **Type**: CWE-195 (Signed to Unsigned Conversion Error)
- **Location**: `apply_offsets()` in `src/parser.c`
- **Description**: The pixel offset validation compares a signed 32-bit offset
  value (`int32_t`) against an unsigned 16-bit pixel count (`uint16_t`). Under
  the C integer promotion rules, when operands have different signedness and
  different width, the narrower unsigned operand is promoted to the wider
  signed type. This causes the comparison to be performed in signed arithmetic:
  negative offset values compare as less than the pixel count and incorrectly
  pass the bounds check, allowing writes to memory locations before the pixel
  buffer.
- **Impact**: Out-of-bounds write, memory corruption.

---

## IMG004: Missing Length Validation in Offset Chunk Parsing

- **Type**: CWE-120 (Buffer Copy without Checking Size of Input)
- **Location**: `parse_offsets()` in `src/parser.c`
- **Description**: When parsing the OFFSETS chunk, the number of offset entries
  (`count`) is read from the chunk data header, but there is no validation that
  the chunk actually contains sufficient bytes to hold all declared entries.
  Each entry is 4 bytes, so the required data size is `2 + count * 4` bytes
  (including the 2-byte count field). When the chunk is shorter than this,
  the parsing loop reads past the chunk data boundary into adjacent memory.
  Note: this bug involves a compound condition (both the presence of entries
  and the insufficiency of the data).
- **Impact**: Out-of-bounds heap read, potential information disclosure.
