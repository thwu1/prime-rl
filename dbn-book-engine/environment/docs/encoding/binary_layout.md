# Binary Layout

DBN record structs use the `#[repr(C)]` attribute with little-endian byte order
on all supported platforms.

## repr(C) Semantics

The `#[repr(C)]` attribute ensures fields are laid out in declaration order
following C ABI alignment rules:

- Each field is aligned to its natural alignment boundary (equal to its size
  for primitive types)
- Padding bytes are inserted between fields when necessary to satisfy alignment
- The struct's overall alignment equals the largest field alignment

## Record Length

The `length` field at the start of every record header gives the total record
size measured in 32-bit words (4-byte units). This can be used to verify correct
parsing and to skip unknown record types.
