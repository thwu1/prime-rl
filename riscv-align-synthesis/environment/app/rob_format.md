# ROB (Relocatable Object Bundle) Binary Format v1

All multi-byte integers are **little-endian**.

## File Header (16 bytes)

| Offset | Size | Type   | Field          | Description                              |
|--------|------|--------|----------------|------------------------------------------|
| 0      | 4    | bytes  | magic          | `0x524F4201` (ASCII `ROB\x01`)           |
| 4      | 2    | uint16 | version        | Format version (must be `1`)             |
| 6      | 2    | uint16 | arch           | ELF e_machine: `243`=RISC-V, `258`=LoongArch |
| 8      | 4    | uint32 | section_count  | Number of section entries                |
| 12     | 4    | uint32 | reloc_count    | Total number of relocation entries       |

## Section Table (20 bytes per entry, immediately follows header)

| Offset | Size | Type   | Field      | Description                       |
|--------|------|--------|------------|-----------------------------------|
| 0      | 1    | uint8  | name_len   | Length of section name in bytes   |
| 1      | 15   | bytes  | name       | Section name (ASCII, null-padded) |
| 16     | 2    | uint16 | size       | Section content size in bytes     |
| 18     | 2    | uint16 | addralign  | Required address alignment        |

## Relocation Table (12 bytes per entry, follows section table)

| Offset | Size | Type   | Field       | Description                                    |
|--------|------|--------|-------------|------------------------------------------------|
| 0      | 2    | uint16 | section_idx | Index into the section table (0-based)         |
| 2      | 2    | uint16 | r_offset    | Offset within the section                      |
| 4      | 2    | uint16 | r_type      | Relocation type (36=R_RISCV_ALIGN, 102=R_LARCH_ALIGN) |
| 6      | 2    | uint16 | r_format    | `0` = RELA (has explicit addend), `1` = REL (no addend) |
| 8      | 4    | int32  | r_addend    | Addend value (meaningful only when r_format=0) |

## Layout

```
[Header: 16 bytes]
[Section 0: 20 bytes]
[Section 1: 20 bytes]
...
[Section N-1: 20 bytes]
[Reloc 0: 12 bytes]
[Reloc 1: 12 bytes]
...
[Reloc M-1: 12 bytes]
```

Total file size: `16 + 20 * section_count + 12 * reloc_count` bytes.

## Notes

- Relocations reference sections by `section_idx` (0-based index into the section table).
- A section may have zero or more relocations. Iterate the full relocation table and group by `section_idx`.
- When `r_format = 1` (REL), the `r_addend` field is present in the binary but its value is meaningless and should be treated as unavailable.
