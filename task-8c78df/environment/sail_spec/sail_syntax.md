# Sail Language Quick Reference

Guide to reading the Sail formal specification language, focused on constructs used in the RISC-V virtual memory translation files.

## Basic Syntax

- `function name(args) -> type = { body }` — Function definition
- `private function ...` — Module-private function
- `var x : type = value` — Mutable variable declaration
- `let x = value` — Immutable binding
- `if condition then { ... } else { ... }` — Conditional
- `return value` — Early return from function
- `match x { pat1 => ..., pat2 => ... }` — Pattern matching
- `assert(cond)` — Runtime assertion

## Types

- `bool` — Boolean (`true` / `false`)
- `int('n)` — Dependent integer type
- `bits('n)` — N-bit bitvector
- `physaddr` — Physical address (wrapper around bits)
- `xlenbits` — `bits(xlen)`, i.e. 32 or 64 bits depending on RV32/RV64
- `result('ok, 'err)` — Either `Ok(value)` or `Err(value)`
- `option('a)` — Either `Some(value)` or `None()`
- `struct { field1 : type1, ... }` — Named record type

## Operators

- `&` — Boolean AND (in boolean context)
- `|` — Boolean OR
- `not(x)` — Boolean NOT
- `==`, `!=` — Equality/inequality
- `@` — Bitvector concatenation (e.g., `ppn @ offset` joins bits)
- `x[hi .. lo]` — Bit slice extraction (inclusive, MSB first)
- `x[i]` — Single bit extraction
- `zeros()` — All-zero bitvector of inferred width
- `zero_extend(x)` — Zero-extend to wider width
- `sign_extend(x)` — Sign-extend to wider width
- `[x with field = val]` — Functional update of struct/bitfield

## Bitfield Declarations

```sail
bitfield Mstatus : bits(64) = {
  MXR  : 19,      // single bit at position 19
  SUM  : 18,
  MPRV : 17,
  MPP  : 12 .. 11, // 2-bit field at positions 12-11
}
```

Access: `mstatus[MXR]` returns a `bits(1)`, compare with `0b1` or `0b0`.

## Bitfield Types Used in Translation

### Satp64 (64-bit satp register)
```
Mode : 63 .. 60   // 4-bit mode field (8=Sv39, 9=Sv48, 10=Sv57)
Asid : 59 .. 44   // 16-bit ASID
PPN  : 43 .. 0    // 44-bit physical page number (root page table)
```

### Satp32 (32-bit satp register)
```
Mode : 31         // 1-bit mode (0=Bare, 1=Sv32)
Asid : 30 .. 22   // 9-bit ASID
PPN  : 21 .. 0    // 22-bit PPN
```

### Mstatus
```
MXR  : 19  // Make eXecutable Readable (allows load from X-only pages)
SUM  : 18  // permit Supervisor User Memory access
MPRV : 17  // Modify PRiVilege (use MPP for loads/stores)
MPP  : 12..11  // Machine Previous Privilege (00=U, 01=S, 11=M)
```

### MEnvcfg (Machine Environment Configuration)
```
PBMTE : 62  // Page-Based Memory Types Enable (Svpbmt)
ADUE  : 61  // A/D bit Update Enable (Svadu hardware updates)
```

## PTE (Page Table Entry) Format — 64-bit (Sv39/48/57)

```
Bit 63    : N (NAPOT, Svnapot extension)
Bits 62-61: PBMT (Page-Based Memory Type, Svpbmt extension)
Bits 60-54: Reserved (must be 0)
Bits 53-10: PPN (Physical Page Number, 44 bits)
Bits 9-8  : RSW (reserved for software)
Bit 7     : D (Dirty)
Bit 6     : A (Accessed)
Bit 5     : G (Global)
Bit 4     : U (User accessible)
Bit 3     : X (eXecute)
Bit 2     : W (Write)
Bit 1     : R (Read)
Bit 0     : V (Valid)
```

### PTE — 32-bit (Sv32)
```
Bits 31-10: PPN (22 bits)
Bits 9-0  : Same flags as above (D/A/G/U/X/W/R/V)
```

## Leaf vs Non-Leaf PTE

A PTE is a **leaf** (maps a page) if `R=1` or `X=1`.
A PTE is a **non-leaf** (points to next-level table) if `R=0` and `W=0` and `X=0`.
The encoding `W=1, R=0` is **reserved** and must be treated as invalid.

## Translation Modes

| Mode | Width | Levels | VPN bits/level | PTE size |
|------|-------|--------|----------------|----------|
| Sv32 | 32    | 2      | 10             | 4 bytes  |
| Sv39 | 39    | 3      | 9              | 8 bytes  |
| Sv48 | 48    | 4      | 9              | 8 bytes  |
| Sv57 | 57    | 5      | 9              | 8 bytes  |

## Key Functions

- `effectivePrivilege(access, mstatus, priv)` — Returns the privilege level to use for permission checking. For data accesses (not instruction fetch), if `MPRV=1`, uses `MPP` instead of actual privilege.
- `pt_walk(...)` — Recursive page table walk implementing Steps 2-8 of the Virtual Address Translation Process.
- `translationMode(priv)` — Determines translation mode from `satp` register. Machine mode always uses `Bare` (no translation).
- `check_PTE_permission(access, priv, mxr, do_sum, flags, ...)` — Checks R/W/X permissions considering privilege level, MXR, and SUM bits.
- `update_PTE_Bits(pte, access)` — Determines if A/D bits need updating.

## Permission Rules

1. **U-bit**: If `U=1`, page is accessible to User mode. Supervisor can access it only if `SUM=1` AND the access is NOT an instruction fetch.
2. **MXR**: If `mstatus.MXR=1`, loads from pages with `X=1` are permitted even if `R=0`.
3. **SUM**: If `mstatus.SUM=0`, Supervisor cannot access User pages (U=1).
4. **A/D bits**: If `A=0` (or `D=0` for stores), behavior depends on `menvcfg.ADUE`:
   - `ADUE=1` (Svadu): Hardware updates A/D bits automatically
   - `ADUE=0` (Svade/default): Page fault is raised

## Superpage Rules

At level `i > 0`, if a leaf PTE is found, it maps a superpage. The lower VPN bits from the virtual address replace the corresponding PPN bits. For alignment, PPN[level*vpn_bits-1 : 0] must be zero.

## NAPOT (Svnapot)

Only valid at level 0 with the N bit set. Only 64KiB NAPOT pages are supported. The PPN encoding must have `PPN[3:0] = 0b1000`. The physical address uses `VPN[0][3:0]` for the lower PPN bits, allowing 16 contiguous 4KiB pages to be described by a single PTE.

## Scenario JSON Format

```json
{
  "description": "...",
  "xlen": 64,
  "translation_mode": "Sv39",
  "privilege": "S",
  "access_type": "read",
  "virtual_address": "0x80202048",
  "satp": "0x8000000000080000",
  "mstatus": "0x0",
  "menvcfg": "0x0",
  "extensions": {"Svnapot": false, "Svpbmt": false},
  "memory": {
    "0x80000010": "0x0120000401000000"
  }
}
```

The `memory` field maps physical addresses (hex) to little-endian byte values (hex). Each entry represents a PTE at that physical address. For Sv39/48/57, entries are 8 bytes; for Sv32, entries are 4 bytes.
