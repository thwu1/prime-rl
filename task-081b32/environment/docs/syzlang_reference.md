# Syzlang Reference (Subset)

This document describes the subset of syzkaller's syzlang DSL used in the description files under `/app/descriptions/`.

## Include Directives

Description files can reference kernel C header files using `include` directives:

```
include <linux/ioctl.h>
include <linux/types.h>
include <linux/my_driver.h>
```

These directives serve two purposes:
1. They tell the `syz-extract` constant extraction tool which headers to include when compiling a C program to extract constant values.
2. They document which kernel headers define the structures and constants used in the descriptions.

The included header files are located relative to the kernel source tree's `include/uapi/` or `include/` directories.

## Resource Declarations

Resources model values passed between syscalls (e.g., file descriptors, handles).

```
resource NAME[BASE_TYPE]: special_val1, special_val2
```

- `BASE_TYPE` is either a primitive integer type (`int8`, `int16`, `int32`, `int64`, `intptr`) or another resource (modeling inheritance).
- Special values after `:` are used occasionally as resource values. If omitted, the default special value is 0.
- Each resource type must be **produced** (used as output) by at least one syscall and **consumed** (used as input) by at least one syscall.

Example:
```
resource fd[int32]: 0xffffffffffffffff
resource sock[fd]
```

## Syscall Declarations

```
syscallname(arg1name arg1type, arg2name arg2type, ...) [return_type] [(attributes)]
```

- Arguments have a name followed by a type expression.
- Return type is optional. When present, it is typically a resource type.
- Call attributes like `(disabled)`, `(automatic_helper)` appear in parentheses after the return type.
- Syscall variants use `$` separator: `ioctl$MY_IOCTL(...)`.

Example:
```
open(file ptr[in, filename], flags flags[open_flags], mode flags[open_mode]) fd
close(fd fd)
ioctl$MY_CMD(fd my_fd, cmd const[0x1234], arg ptr[in, my_struct])
```

## Struct Definitions

```
structname {
    field1name    field1type    [(direction)]
    field2name    field2type    [(direction)]
    ...
} [attributes]
```

- Fields have a name, a type expression, and an optional direction annotation.
- Direction annotations: `(in)`, `(out)`, `(inout)`, `(out_overlay)`.
- When no direction is specified on a field, its effective direction depends on the pointer wrapping it in the syscall argument.
- Struct attributes: `[packed]`, `[align[N]]`, `[size[N]]`.

## Flag Definitions

```
flagname = VALUE1, VALUE2, VALUE3
```

Flags are referenced in type expressions as `flags[flagname, underlying_type]`.

## Type Expressions

Type expressions describe data types with optional parameters in brackets:

| Type | Syntax | Description |
|------|--------|-------------|
| Integer | `int8`, `int16`, `int32`, `int64`, `intptr` | Basic integer types |
| Boolean | `bool8`, `bool16`, `bool32`, `bool64` | Boolean (0 or 1) |
| Constant | `const[VALUE, TYPE]` or `const[VALUE]` | Fixed value |
| Flags | `flags[FLAGNAME, TYPE]` or `flags[FLAGNAME]` | Set of named values |
| Pointer | `ptr[DIRECTION, INNER_TYPE]` | Pointer to data |
| Array | `array[ELEMENT_TYPE, SIZE]` or `array[ELEMENT_TYPE]` | Fixed or variable array |
| String | `string[VALUE]` or `string[VALUE, SIZE]` | String buffer |
| Length | `len[FIELD_NAME, TYPE]` | Length of another field |
| Byte size | `bytesize[FIELD_NAME, TYPE]` | Byte size of another field |
| Void | `void` | Zero-size type |
| Buffer | `buffer[DIRECTION]` | Raw byte buffer |

### Pointer directions

- `ptr[in, T]` — input pointer; data flows from userspace to kernel
- `ptr[out, T]` — output pointer; data flows from kernel to userspace
- `ptr[inout, T]` — bidirectional pointer

### Length references

`len[FIELD]` refers to a sibling field in the same struct or a syscall argument by name. The referenced field must exist as a sibling in the containing struct.

## Ioctl Command Values

In syzlang, ioctl commands are specified as `const[VALUE]` where VALUE is the 32-bit integer that the kernel ioctl handler expects. This value is computed from the C header using `_IO`, `_IOR`, `_IOW`, or `_IOWR` macros:

```c
#define MY_IOCTL _IOWR('M', 0x01, struct my_data)
```

The resulting 32-bit value encodes:
- **Direction** (bits 31-30): 0=none, 1=write, 2=read, 3=read+write
- **Size** (bits 29-16): `sizeof(struct)` of the data argument
- **Type** (bits 15-8): magic number identifying the driver
- **Number** (bits 7-0): command number within the driver

The `const[...]` value in syzlang must match the value computed from the kernel header. If the C struct definition changes (affecting its size), the `const[...]` value must be updated accordingly.

## Resource Semantics

### Producers

A syscall **produces** a resource if:
1. Its return type is the resource type.
2. It has a `ptr[out, STRUCT]` argument where STRUCT contains a field of the resource type (all fields in an output struct are outputs).
3. It has a `ptr[inout, STRUCT]` argument where STRUCT contains a field of the resource type with an explicit `(out)` direction annotation.

### Consumers

A syscall **consumes** a resource if:
1. It has a direct argument of the resource type (e.g., `fd my_resource`).
2. It has a `ptr[in, STRUCT]` argument where STRUCT contains a field of the resource type.
3. It has a `ptr[inout, STRUCT]` argument where STRUCT contains a field of the resource type without an `(out)` annotation.
4. Any of the above, but through one level of pointer indirection within struct fields (e.g., a struct field `ptr[in, array[RESOURCE]]`).

### Namespace

All `.txt` description files in the same directory share a single namespace. Declarations in one file are visible to all other files.
