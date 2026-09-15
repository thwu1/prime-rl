# Syzkaller Const Extraction

## Overview

Syzkaller's description compilation pipeline has two stages:

1. **Constant extraction** (`syz-extract`): Extracts numeric values of symbolic constants referenced in syzlang description files from kernel C headers.
2. **Code generation** (`syz-sysgen`): Compiles syzlang descriptions together with extracted constants into Go code used by the fuzzer.

This document describes the constant extraction process.

## How It Works

Syzlang description files contain `include` directives that reference kernel header files:

```
include <linux/ioctl.h>
include <linux/types.h>
include <linux/hwaccel.h>
```

These directives tell `syz-extract` which C headers to include when extracting constant values. The tool:

1. Scans the syzlang files for all symbolic constant references (in `const[...]` type expressions and flag value definitions).
2. Generates a small C program that `#include`s the referenced headers and uses `printf` to print each constant's numeric value.
3. Compiles the generated C program with `gcc` using the appropriate include paths.
4. Runs the compiled program to obtain the actual constant values.
5. Writes the results to `.const` files.

## Ioctl Command Encoding

Linux ioctl command numbers encode four fields in a 32-bit integer following the `_IOC` convention:

```
Bits 31-30:  direction  (2 bits)
Bits 29-16:  data size  (14 bits)
Bits 15-8:   type/magic (8 bits)
Bits 7-0:    number     (8 bits)
```

Direction values:
- `0` = `_IOC_NONE` — no data transfer (`_IO` macro)
- `1` = `_IOC_WRITE` — userspace writes to kernel (`_IOW` macro)
- `2` = `_IOC_READ` — userspace reads from kernel (`_IOR` macro)
- `3` = `_IOC_READ|_IOC_WRITE` — bidirectional (`_IOWR` macro)

The `size` field encodes `sizeof(struct)` of the data structure passed through the ioctl argument pointer. The `type` field is a magic number identifying the driver (e.g., `'H'` = 0x48).

Kernel headers define ioctl commands using macros like:
```c
#define MY_IOCTL _IOWR(MAGIC, 0x01, struct my_data)
```

In syzlang descriptions, the corresponding syscall uses the numeric value:
```
ioctl$MY_IOCTL(fd my_fd, cmd const[0xc0104d01], arg ptr[inout, my_data])
```

The `const[...]` value in the syzlang description should match the value computed by the C preprocessor from the kernel header's `_IO*` macro. Mismatches indicate errors in the syzlang description.

## Cross-Validation

After extracting constants from C headers, the extracted values should be compared against the `const[...]` values in syzlang descriptions. Each ioctl command's 32-bit value can be decomposed into direction, size, type, and number fields to pinpoint which component is wrong when a mismatch is found.

Common mismatch types:
- **Direction mismatch**: syzlang uses wrong direction bits (e.g., IOWR instead of IOW)
- **Size mismatch**: syzlang encodes wrong struct size (e.g., the C struct changed but the syzlang `const[...]` was not updated)
- **Number mismatch**: wrong ioctl command number

The C header files for this driver interface are located at `/app/include/linux/`.
