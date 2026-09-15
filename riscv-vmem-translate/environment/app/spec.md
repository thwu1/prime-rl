# RISC-V Virtual Memory Address Translation Specification

This document specifies the RISC-V Sv39, Sv48, and Sv57 virtual memory
address translation mechanisms as defined by the RISC-V Privileged
Architecture Specification. An implementation of this specification must
correctly translate virtual addresses to physical addresses or raise the
appropriate page faults.

## 1. Page Table Entry (PTE) Format

Each PTE is 8 bytes (64 bits) with the following layout:

```
Bit(s)    Field
──────    ─────
63        N       (NAPOT, Svnapot extension)
62:61     PBMT    (Page-Based Memory Types, Svpbmt extension; ignored here)
60:54     Reserved (must be zero)
53:10     PPN     (Physical Page Number, 44 bits)
9:8       RSW     (Reserved for Software, ignored)
7         D       (Dirty)
6         A       (Accessed)
5         G       (Global)
4         U       (User)
3         X       (Execute)
2         W       (Write)
1         R       (Read)
0         V       (Valid)
```

### PPN Sub-fields

The 44-bit PPN is further divided:

```
PPN[2] = PTE[53:28]   (26 bits)
PPN[1] = PTE[27:19]   (9 bits)
PPN[0] = PTE[18:10]   (9 bits)
```

### PTE Validity

A PTE is **invalid** if any of:
- V = 0
- R = 0 and W = 1 (reserved encoding)
- Any reserved bits (60:54) are non-zero
- N = 1 and Svnapot is not enabled (bit 63 is reserved when Svnapot is off)

### Leaf vs. Non-Leaf

A **valid** PTE is a **leaf** if R = 1 or X = 1.
A valid PTE with R = 0, W = 0, X = 0 is a **non-leaf** (pointer to next-level page table).

## 2. Virtual Address Formats

### Sv39 (39-bit virtual address)

```
Bits      Field       Width
──────    ─────       ─────
38:30     VPN[2]      9 bits
29:21     VPN[1]      9 bits
20:12     VPN[0]      9 bits
11:0      offset      12 bits
```

Sign extension: bits [63:39] must all equal bit 38.

Walk levels: 3 (start at level 2, descend to level 0).

Page sizes: 4 KiB (level 0), 2 MiB (level 1), 1 GiB (level 2).

### Sv48 (48-bit virtual address)

```
Bits      Field       Width
──────    ─────       ─────
47:39     VPN[3]      9 bits
38:30     VPN[2]      9 bits
29:21     VPN[1]      9 bits
20:12     VPN[0]      9 bits
11:0      offset      12 bits
```

Sign extension: bits [63:48] must all equal bit 47.

Walk levels: 4 (start at level 3, descend to level 0).

Page sizes: 4 KiB (level 0), 2 MiB (level 1), 1 GiB (level 2), 512 GiB (level 3).

### Sv57 (57-bit virtual address)

```
Bits      Field       Width
──────    ─────       ─────
56:48     VPN[4]      9 bits
47:39     VPN[3]      9 bits
38:30     VPN[2]      9 bits
29:21     VPN[1]      9 bits
20:12     VPN[0]      9 bits
11:0      offset      12 bits
```

Sign extension: bits [63:57] must all equal bit 56.

Walk levels: 5 (start at level 4, descend to level 0).

## 3. Page Table Walk Algorithm

Given: translation mode (Sv39/Sv48/Sv57), satp.PPN (root page table PPN),
virtual address, access type, privilege level, and control bits.

Let `LEVELS` = 3 for Sv39, 4 for Sv48, 5 for Sv57.
Let `PTESIZE` = 8 bytes.
Let `PAGESIZE` = 4096 bytes.

**Step 1.** Let `a` = satp.PPN × PAGESIZE. Let `i` = LEVELS − 1.

**Step 2.** Let `pte_addr` = `a` + VPN[i] × PTESIZE. Read the PTE at `pte_addr`.
If the address is not in the memory map, treat the PTE as zero (V=0).

**Step 3.** If the PTE is invalid (see §1), raise a page fault.

**Step 4.** If the PTE is a non-leaf:
- If `i` = 0, this is a pointer at the last level — raise a page fault.
- Otherwise, let `a` = PTE.PPN × PAGESIZE, decrement `i`, go to Step 2.

**Step 5.** The PTE is a leaf. This is a superpage if `i` > 0.

**Step 5a. NAPOT check (level 0 only, Svnapot):**
If `i` > 0 and PTE.N = 1, raise a page fault (NAPOT is reserved for superpages).
If `i` = 0 and PTE.N = 1:
- If Svnapot is not enabled, raise a page fault.
- Only 64 KiB NAPOT pages are defined. Verify PPN[3:0] = 0b1000.
  If not, raise a page fault (reserved NAPOT encoding).

**Step 5b. Superpage alignment:**
If `i` > 0, the low `i × 9` bits of PPN must all be zero.
If any are non-zero, the superpage is misaligned — raise a page fault.

**Step 6. Permission check** (see §4).

**Step 7. A/D bit check** (see §5).

**Step 8. Compute physical address:**

For a regular page (i = 0, N = 0):
```
PA = PPN << 12 | VA[11:0]
```

For a superpage at level i (i > 0):
```
offset_bits = 12 + i × 9
PA = PPN[43 : i×9] << offset_bits | VA[offset_bits−1 : 0]
```
That is, the upper bits of PPN provide the high physical address, and the
lower VPN fields plus page offset from the VA provide the low physical address.

For a NAPOT 64 KiB page (i = 0, N = 1):
```
base_ppn = PPN & ~0xF    (clear low 4 bits)
PA = base_ppn << 12 | VA[15:0]
```
The NAPOT range covers 16 contiguous 4 KiB pages (64 KiB total). The low 16 bits
of the virtual address select within this range.

## 4. Permission Checking

After finding a leaf PTE, check permissions based on access type and privilege.

### Read access
- If PTE.R = 1, read is permitted.
- If PTE.R = 0 and MXR = 1 and PTE.X = 1, read is permitted (MXR makes
  execute-only pages readable).
- Otherwise, raise a **load page fault**.

### Write access
- If PTE.W = 1, write is permitted.
- Otherwise, raise a **store page fault**.

### Execute (instruction fetch) access
- If PTE.X = 1, execute is permitted.
- Otherwise, raise a **fetch page fault**.

### U-bit and privilege interaction

- **U-mode** accessing a page with U = 0: page fault.
- **S-mode** accessing a page with U = 1:
  - For **load/store**: permitted only if mstatus.SUM = 1.
  - For **instruction fetch**: always a page fault (SUM does not affect fetches).
- **S-mode** accessing a page with U = 0: permitted.
- **U-mode** accessing a page with U = 1: permitted.

## 5. Accessed and Dirty Bit Handling

After permission checks pass, check A and D bits.

### Svade mode (adue = false)
In this mode, A/D bits are managed by software. The hardware raises a
page fault if the bits are not pre-set:
- If PTE.A = 0 for any access: raise a page fault.
- If PTE.D = 0 for a write access: raise a page fault.
- PTE.D = 0 is acceptable for read/execute access (no fault).

### Svadu mode (adue = true)
In this mode, the hardware automatically updates A/D bits. No fault is
raised for missing A/D bits; the translation succeeds as if the bits
were already set.

## 6. Fault Types

The fault type depends on the access type that triggered the translation:

| Access Type | Fault Type |
|-------------|-----------|
| read / load | `load_page_fault` |
| write / store | `store_page_fault` |
| exec / fetch | `fetch_page_fault` |

All translation failures (invalid PTE, misaligned superpage, permission
violation, A/D bit fault) raise the fault type corresponding to the
original access type.

## 7. Input / Output Format

### Input: `/data/memory.json`

A JSON object mapping hex physical addresses to hex PTE values:
```json
{
  "0x80000000": "0x0000000020000401",
  ...
}
```
Addresses not present in the map should be treated as containing zero
(PTE with V=0).

### Input: `/data/queries.json`

A JSON array of translation queries:
```json
[
  {
    "id": 1,
    "mode": "Sv39",
    "satp_ppn": "0x80000",
    "va": "0x0000000000000abc",
    "access": "read",
    "privilege": "S",
    "mstatus_mxr": false,
    "mstatus_sum": false,
    "adue": false,
    "svnapot": false
  },
  ...
]
```

Fields:
- `mode`: "Sv39", "Sv48", or "Sv57"
- `satp_ppn`: Root page table physical page number (hex string)
- `va`: 64-bit virtual address (hex string)
- `access`: "read", "write", or "exec"
- `privilege`: "S" (Supervisor) or "U" (User)
- `mstatus_mxr`: MXR bit (boolean)
- `mstatus_sum`: SUM bit (boolean)
- `adue`: A/D Update Enable — false = Svade mode, true = Svadu mode
- `svnapot`: Whether Svnapot extension is enabled (boolean)

### Output: `/app/results.json`

A JSON array with one result per query, ordered by id:
```json
[
  {
    "id": 1,
    "status": "ok",
    "pa": "0x80010abc",
    "page_size": 4096
  },
  {
    "id": 2,
    "status": "fault",
    "fault_type": "store_page_fault"
  }
]
```

For successful translations: include `pa` (hex string) and `page_size` (integer bytes).
For faults: include `fault_type` (string).
