# Data Format Specification

## programs.json

Top-level JSON object with fields:

### maps

Array of map definitions:

- `name` (string): Map name (e.g., `.rodata`, `conn_track_map`)
- `type` (string): BPF map type (e.g., `BPF_MAP_TYPE_HASH`, `BPF_MAP_TYPE_PROG_ARRAY`)
- `key_size` (int): Key size in bytes
- `value_size` (int): Value size in bytes
- `max_entries` (int): Maximum number of entries
- `index` (int): Map index used in relocations

### programs

Array of program definitions:

- `name` (string): Program name
- `bytecode` (string): Base64-encoded raw eBPF bytecode
- `relocations` (array): Map relocations for this program
- `is_entry` (bool): Whether this is the entry point program
- `tail_call_index` (int | null): Index in the `tail_call_map` prog array, or null for the entry program

### tail_call_map_index

Integer index of the prog array map used for tail calls.

### rodata_map_index

Integer index of the `.rodata` map containing global constants.

### rodata_layout

Layout of the `.rodata` section:

- `fields` (array): Field definitions with `name`, `offset`, `size`, `type`
- `total_size` (int): Total size of `.rodata` in bytes

---

## eBPF Instruction Encoding

Each instruction is 8 bytes, packed little-endian:

| Offset | Size | Field    | Description                                      |
|--------|------|----------|--------------------------------------------------|
| 0      | 1    | opcode   | Operation code                                   |
| 1      | 1    | regs     | dst_reg (low 4 bits), src_reg (high 4 bits)      |
| 2      | 2    | off      | Signed 16-bit offset                             |
| 4      | 4    | imm      | Signed 32-bit immediate                          |

To extract register fields from the `regs` byte:

```
dst_reg = regs & 0x0F
src_reg = (regs >> 4) & 0x0F
```

### Key Opcodes

**64-bit immediate load (lddw)** -- opcode `0x18`:

- Takes **two** instruction slots (16 bytes total)
- First slot: opcode=0x18, dst=target register, src=special meaning, imm=lower 32 bits
- Second slot: opcode=0x00, all other fields zero (upper 32 bits in imm if needed)
- When `src_reg=1`: the `imm` field contains a map index -- this loads the map's file descriptor (**map_fd** reference)
- When `src_reg=2`: the `imm` field contains a map index -- this loads a pointer to the map's value (**map_value** reference, used for `.rodata` access)

**Memory load (ldxw)** -- opcode `0x61`:

- Loads a 32-bit value from `[src_reg + off]` into `dst_reg`
- Used to read fields from `.rodata`: after loading the `.rodata` pointer via `lddw` with `src=2`, `ldxw dst, src, offset` reads a `u32` at the given byte offset

**Register move** -- opcode `0xbf`:

- `dst_reg = src_reg` (64-bit register-to-register move)

**Immediate move** -- opcode `0xb7`:

- `dst_reg = imm` (64-bit load immediate value into register)

**Conditional branch: jump if equal (jeq imm)** -- opcode `0x15`:

- If `dst_reg == imm`, jump forward by `off` instructions
- Jump target: `current_insn_index + 1 + off`
- Falls through to `current_insn_index + 1` if the condition is false

**Conditional branch: jump if not equal (jne imm)** -- opcode `0x55`:

- If `dst_reg != imm`, jump forward by `off` instructions

**Unconditional jump (ja)** -- opcode `0x05`:

- Jump forward by `off` instructions; target = `current_insn_index + 1 + off`

**Helper function call** -- opcode `0x85`:

- Calls BPF helper function number `imm`
- Helper 1: `bpf_map_lookup_elem` -- looks up a key in a map; returns pointer or NULL in `r0`
- Helper 12: `bpf_tail_call` -- performs a tail call using `r1`=ctx, `r2`=prog_array_map, `r3`=index
  - If successful, transfers control to the target program (does not return)
  - If the call fails (index out of bounds, program not loaded), **falls through** to the next instruction
- All calls clobber registers `r0` through `r5`

**Program exit** -- opcode `0x95`:

- Returns from the program with the value in `r0`

---

## Relocations

Each relocation entry specifies:

- `insn_idx` (int): Index of the `lddw` instruction (first slot) that references a map
- `map_index` (int): Which map is being referenced (matches the map's `index` field)
- `type` (string): Either `"map_fd"` (loads map file descriptor) or `"map_value"` (loads pointer to the map's data)

---

## Tail Call Mechanism

Programs are dispatched via the `tail_call_map` (a `BPF_MAP_TYPE_PROG_ARRAY`). The code pattern is:

1. Load the prog array map fd into `r2` via `lddw r2, src=1, imm=tail_call_map_index`
2. Set the tail call index in `r3` via `mov r3, INDEX`
3. Call helper 12 (`bpf_tail_call`)

Each non-entry program has a `tail_call_index` indicating its slot in the prog array. A tail call to index N transfers control to the program whose `tail_call_index` equals N.

---

## .rodata (Global Constants)

The `.rodata` map is a `BPF_MAP_TYPE_ARRAY` with a single entry containing all global constant values packed contiguously. Programs access these constants by:

1. Loading a pointer to the `.rodata` value via `lddw reg, src=2, imm=rodata_map_index`
2. Reading individual fields via `ldxw dst, reg, byte_offset`

The `rodata_layout` section of `programs.json` describes each field's name, byte offset, size, and type. All fields are `u32` (4 bytes, unsigned 32-bit, little-endian).

Configuration files in `/app/configs/` provide specific values for each field. A non-zero value means the feature is **enabled**; zero means **disabled**.
