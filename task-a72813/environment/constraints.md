# RISC-V Configuration Constraint Specification

This document defines the constraint rules that a valid RISC-V hardware configuration
must satisfy. These rules are derived from the Sail RISC-V formal model's
`validate_config.sail` module, which is the official RISC-V ISA specification
maintained by RISC-V International.

A configuration is **valid** if and only if it satisfies every rule below.

## Configuration Schema

A configuration is a JSON object with the following top-level sections:

### `base`
| Field   | Type | Description |
|---------|------|-------------|
| `xlen`  | int  | ISA register width: 32 or 64 |

### `extensions.<name>`
| Field       | Type   | Description |
|-------------|--------|-------------|
| `supported` | bool   | Whether the extension is supported on this hart |

The V (vector) extension has additional fields when `supported` is true:

| Field           | Type   | Description |
|-----------------|--------|-------------|
| `support_level` | string | One of: `"Disabled"`, `"Integer"`, `"Float_single"`, `"Float_double"`, `"Full"` |
| `vlen_exp`      | int    | log2 of vector register length in bits (VLEN = 2^vlen_exp) |
| `elen_exp`      | int    | log2 of maximum element width in bits (ELEN = 2^elen_exp) |

Support levels form an ordered hierarchy:
`Disabled < Integer < Float_single < Float_double < Full`

### `memory.pmp`
| Field            | Type | Description |
|------------------|------|-------------|
| `count`          | int  | Total number of PMP entries |
| `usable_count`   | int  | Number of usable (not read-only-zero) PMP entries |
| `grain`          | int  | PMP granularity parameter G |
| `NA4_supported`  | bool | Whether NA4 (Naturally Aligned 4-byte) matching mode is available |
| `NAPOT_supported`| bool | Whether NAPOT matching mode is available |
| `TOR_supported`  | bool | Whether TOR (Top of Range) matching mode is available |

### `memory.regions[]`
| Field             | Type   | Description |
|-------------------|--------|-------------|
| `base`            | string | Hex address string (e.g. `"0x80000000"`) |
| `size`            | string | Hex size string (e.g. `"0x10000000"`) |
| `mem_type`        | string | `"MainMemory"` or `"IOMemory"` |
| `cacheable`       | bool   | Region supports caching |
| `coherent`        | bool   | Region is coherent across harts |
| `executable`      | bool   | Region supports instruction fetch |
| `readable`        | bool   | Region supports reads |
| `writable`        | bool   | Region supports writes |
| `read_idempotent` | bool   | Reads are idempotent (no side effects) |
| `write_idempotent`| bool   | Writes are idempotent (no side effects) |
| `atomic_support`  | string | `"AMONone"`, `"AMOArithmetic"`, or `"AMOCASQ"` |
| `reservability`   | string | `"RsrvNone"` or `"RsrvEventual"` |

### `platform`
| Field                      | Type | Description |
|----------------------------|------|-------------|
| `cache_block_size_exp`     | int  | log2 of cache block size in bytes |
| `reservation_set_size_exp` | int  | log2 of reservation set size in bytes |

### `mmu.<mode>`
| Field       | Type | Description |
|-------------|------|-------------|
| `supported` | bool | Whether the virtual memory translation mode is available |

Modes: `Sv32` (RV32 only), `Sv39`, `Sv48`, `Sv57` (RV64 only).

---

## Constraint Rules

### Category 1: Privilege Constraints

**Rule P1 — S_REQUIRES_U:**
If the S (Supervisor) extension is supported, the U (User) extension must also
be supported. Supervisor mode requires user mode for privilege separation. The
RISC-V privilege architecture mandates that supervisor mode cannot exist without
a less-privileged user mode.

**Rule P2 — H_REQUIRES_S:**
If the H (Hypervisor) extension is supported, the S extension must be supported.
The hypervisor extension virtualizes supervisor mode.

**Rule P3 — H_REQUIRES_U:**
If the H extension is supported, the U extension must be supported.

### Category 2: MMU Constraints

**Rule M1 — SV32_ONLY_RV32:**
Sv32 virtual memory mode is only valid when `xlen = 32`. The Sv32 page table
format uses 32-bit PTEs and 2-level page tables, which are specific to RV32.

**Rule M2 — SV39_ONLY_RV64:**
Sv39 is only valid when `xlen = 64`. Similarly for Sv48 and Sv57.

**Rule M3 — SV48_REQUIRES_SV39:**
If Sv48 is supported, Sv39 must also be supported. The RISC-V specification
requires implementations to support all shorter virtual address modes. An
implementation supporting 48-bit virtual addresses must also support 39-bit.

**Rule M4 — SV57_REQUIRES_SV48:**
If Sv57 is supported, Sv48 must also be supported.

**Rule M5 — SV_REQUIRES_S:**
On RV32: if Sv32 is supported, S must be supported.
On RV64: if any of Sv39/Sv48/Sv57 is supported, S must be supported.
Address translation requires supervisor mode to manage page tables via the
`satp` CSR.

### Category 3: Extension Dependency Constraints

**Rule E1 — F_REQUIRES_ZICSR:**
The F (single-precision floating-point) extension requires the Zicsr extension.
Floating-point operations need CSR access for the `fcsr` control/status register.

**Rule E2 — D_REQUIRES_F:**
The D (double-precision floating-point) extension requires the F extension.
D extends F with 64-bit floating-point registers and operations.

**Rule E3 — F_ZFINX_EXCLUSIVE:**
The F and Zfinx extensions are mutually exclusive. F uses dedicated `f0`–`f31`
floating-point registers, while Zfinx reuses the integer `x0`–`x31` registers
for floating-point operations. Supporting both simultaneously is architecturally
incoherent.

**Rule E4 — ZDINX_REQUIRES_ZFINX:**
The Zdinx (double-precision in integer registers) extension requires the Zfinx
extension. Zdinx extends Zfinx with double-precision operations.

**Rule E5 — ZHINX_REQUIRES_ZFINX:**
The Zhinx (half-precision in integer registers) extension requires the Zfinx
extension.

**Rule E6 — ZFINX_REQUIRES_ZICSR:**
The Zfinx extension requires Zicsr. Even though Zfinx reuses integer registers,
it still needs CSR access for `fcsr`.

**Rule E7 — ZABHA_REQUIRES_ZAAMO:**
The Zabha (byte/halfword atomic) extension requires Zaamo or A. Zabha extends
AMO operations to sub-word sizes and depends on the base AMO infrastructure.

**Rule E8 — ZACAS_REQUIRES_ZAAMO:**
The Zacas (atomic compare-and-swap) extension requires Zaamo or A.

### Category 4: Vector Extension Constraints

These rules apply only when the V extension has `supported = true`.

**Rule V1 — V_REQUIRES_ZICSR:**
The V extension requires Zicsr for access to vector CSRs (`vtype`, `vl`,
`vlenb`, `vstart`, `vxsat`, `vxrm`, `vcsr`).

**Rule V2 — VEXT_FLOAT_REQUIRES_F:**
If V's `support_level` is `"Float_single"`, `"Float_double"`, or `"Full"`,
the F extension must be supported. Vector floating-point instructions depend on
the scalar floating-point rounding mode in `fcsr.frm`.

**Rule V3 — VEXT_DOUBLE_REQUIRES_D:**
If V's `support_level` is `"Float_double"` or `"Full"`, the D extension must be
supported. 64-bit vector floating-point elements require double-precision support.

**Rule V4 — ELEN_LE_VLEN:**
`elen_exp` must be ≤ `vlen_exp` (equivalently, ELEN ≤ VLEN). The maximum
element width cannot exceed the vector register width.

**Rule V5 — VLEN_RANGE:**
`vlen_exp` must be in the range [3, 16] (VLEN from 8 bits to 65536 bits).

**Rule V6 — ELEN_RANGE:**
`elen_exp` must be in the range [3, 16] (ELEN from 8 bits to 65536 bits).

**Rule V7 — VEXT_INTEGER_ELEN:**
If `support_level` ≥ `"Integer"` (i.e., anything other than `"Disabled"`),
`elen_exp` must be ≥ 5 (ELEN ≥ 32). The Zve32x base vector extension requires
32-bit element support.

**Rule V8 — VEXT_DOUBLE_ELEN:**
If `support_level` is `"Float_double"` or `"Full"`, `elen_exp` must be ≥ 6
(ELEN ≥ 64). 64-bit floating-point vector elements require ELEN of at least 64.

**Rule V9 — VEXT_FULL_VLEN:**
If `support_level` is `"Full"`, `vlen_exp` must be ≥ 7 (VLEN ≥ 128). The full
V extension mandates VLEN of at least 128 bits per the RVV specification.

### Category 5: PMP Constraints

**Rule PMP1 — PMP_COUNT_VALID:**
The PMP entry `count` must be one of: 0, 16, or 64. These are the only valid
PMP entry counts defined in the RISC-V Privileged Architecture specification.

**Rule PMP2 — PMP_USABLE_LE_COUNT:**
`usable_count` must be ≤ `count`. The number of usable PMP entries cannot
exceed the total number of entries; higher-numbered entries are read-only zero.

**Rule PMP3 — PMP_NA4_GRAIN:**
If `NA4_supported` is true, `grain` must be 0. The NA4 (Naturally Aligned
4-byte) address matching mode provides 4-byte granularity. When grain G > 0,
the PMP granularity is 2^(G+2) bytes, making the 4-byte NA4 mode impossible
to encode. Implementations with coarser PMP granularity must disable NA4.

### Category 6: Memory Region Constraints

**Rule MR1 — REGION_ALIGNMENT:**
Region `base` addresses and `size` values must be aligned to 4 KiB (0x1000)
page boundaries. The architecture requires PMA regions to be page-aligned so
that physical memory attributes do not change within a page.

**Rule MR2 — REGIONS_SORTED_NO_OVERLAP:**
Regions must be sorted in strictly ascending order by `base` address, and
no two regions may overlap. Formally: for each consecutive pair of regions
(i, i+1), `base[i] + size[i] ≤ base[i+1]`.

**Rule MR3 — MAIN_MEMORY_PMA:**
Every `MainMemory` region must have all of the following attributes set to true:
`readable`, `writable`, `read_idempotent`, `write_idempotent`. Main memory must
support full read/write access with idempotent operations. This is required by
the RISC-V Platform specification for memory regions where code and data reside.

### Category 7: Platform Constraints

**Rule PL1 — ZIC64B_CACHE_BLOCK:**
If the Zic64b extension is supported, `cache_block_size_exp` must be exactly 6
(64-byte cache blocks). The Zic64b extension is an assertion that the natural
cache block size is 64 bytes.

**Rule PL2 — RESERVATION_SIZE:**
If the A or Zalrsc extension is supported, `reservation_set_size_exp` must be
≥ `ceil(log2(xlen / 8))`. For RV64 this means ≥ 3 (at least 8 bytes), and for
RV32 this means ≥ 2 (at least 4 bytes). The reservation set for LR/SC must be
at least as large as the widest atomic access size for the base ISA.
