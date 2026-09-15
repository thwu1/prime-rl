# Syzlang Syntax Reference

Syzlang is the syscall description language used by syzkaller, a coverage-guided
kernel fuzzer. Descriptions define syscall interfaces so the fuzzer can generate
valid programs (sequences of syscalls with concrete arguments).

## Syscall Descriptions

```
syscallname "(" [arg ["," arg]*] ")" [type] ["(" attribute* ")"]
arg = argname type
```

Example:
```
open(file ptr[in, filename], flags flags[open_flags], mode flags[open_mode]) fd
read(fd fd, buf buffer[out], count len[buf])
close(fd fd)
```

Syscall variants use `$` suffix: `ioctl$MY_CMD(fd fd, cmd const[MY_CMD], arg ptr[in, my_struct])`

## Resources

Resources model values passed between syscalls (e.g., file descriptors).
A resource must be **produced** (output) by at least one syscall and
**consumed** (input) by at least one syscall.

```
resource identifier "[" underlying_type "]" [ ":" special_values ]
```

`underlying_type` is `int8`, `int16`, `int32`, `int64`, `intptr`, or another resource.
Special values are used occasionally as resource values.

```
resource fd[int32]: 0xffffffffffffffff, AT_FDCWD
resource sock[fd]
resource sock_unix[sock]

socket(...) sock          # produces sock
accept(fd sock, ...) sock # consumes and produces sock
close(fd fd)              # consumes fd (and all subtypes)
```

**Important**: The underlying type must match the C type used in the kernel.
For example, if a handle is `typedef __u32 handle_t`, use `int32`.
If a cookie is `typedef __u64 cookie_t`, use `int64`.

## Types

### Integers
`int8`, `int16`, `int32`, `int64`, `intptr`. Append `be` for big-endian.
Range: `int32[0:100]`. Aligned range: `int32[0:4096, 512]`.

### const
`const[value, type]` - constant value of specified type.
Use for fields that must be zero (padding): `padding const[0, int32]`.

### flags
`flags[flagname, type]` - references a flag set.
Flag sets: `flagname = CONST1, CONST2, CONST3`

### ptr / ptr64
`ptr[direction, type]` - pointer to object.
Directions: `in` (input), `out` (output), `inout` (both).
Optional: `ptr[in, type, opt]` - pointer may be NULL.

**Important**: If a struct contains both input and output fields, the pointer
direction must be `inout`, not just `in`.

### len / bytesize / bitsize
`len[argname, type]` - length of another field (element count for arrays).
`bytesize[argname, type]` - always in bytes.
Path expressions: `len[parent:field, type]`, `len[struct:field:subfield, type]`.

### string
`string[value]` or `string[flagname]` - zero-terminated string.

### array
`array[type]` - variable-length array.
`array[type, N]` - fixed-length array of N elements.

### buffer
`buffer[direction]` - shorthand for `ptr[direction, array[int8]]`.

### vma
`vma` - pointer to a set of pages.

## Structs

```
structname "{" "\n"
    (fieldname type ("(" fieldattribute* ")")? "\n")+
"}" ("[" attribute* "]")?
```

Field attributes: `(in)`, `(out)`, `(inout)`, `(out_overlay)`.

Struct attributes:
- `[packed]` - no padding, alignment 1 (like `__attribute__((packed))`)
- `[align[N]]` - alignment N with padding
- `[size[N]]` - padded to size N

**Field order must match the C struct layout.**

Example:
```
my_struct {
    field0  const[0x42, int16]
    field1  int32
    field2  ptr[in, array[int8]]
    field3  fd              (out)
} [packed]
```

## Unions

Unions model C anonymous unions or discriminated alternatives.

```
unionname "[" "\n"
    (fieldname type "\n")+
"]" ("[" attribute* "]")?
```

Attributes: `[varlen]`, `[size[N]]`.

Without attributes, the union is padded to the size of the largest member
(matching C union semantics). Use `[varlen]` for variable-length unions.

Example:
```
my_payload [
    opt_a   struct_a
    opt_b   struct_b
    opt_c   struct_c
]
```

When a C struct contains an anonymous union, model it as a named syzlang
union and reference it as a field in the parent struct:
```
# C:  struct event { int type; union { struct a; struct b; }; };
# syzlang:
event_payload [
    a   event_type_a
    b   event_type_b
]

event {
    type    int32
    payload event_payload
}
```

## Type Aliases

```
type identifier underlying_type
```
Example: `type signalno int32[0:65]`

The underlying type must match the C type. For `__u32`, use `int32`.

## Include Directives

Description files must include the relevant kernel UAPI headers:
```
include <uapi/linux/my_device.h>
```

This is required so that `syz-extract` can extract constant values.

## Summary of Rules

- Use `const[0, type]` for padding fields that the kernel requires to be zero.
- Resource types must match C types: `__u32` -> `int32`, `__u64` -> `int64`.
- Struct field order must match the C struct definition exactly.
- Use the correct flag constants for each context (don't mix flag namespaces).
- Every resource must have at least one producer and one consumer.
- When a struct has output fields, use `ptr[inout, ...]` in the syscall.
- Struct `__attribute__((packed))` requires `[packed]` in syzlang.
- The include must reference the UAPI header for the specific device.
