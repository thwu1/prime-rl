The Sail RISC-V formal specification files at `/app/sail_spec/` define the official RISC-V virtual address translation algorithm. The relevant files are:

- `vmem.sail` — Page table walk (PTW) algorithm, permission checking, superpage handling, NAPOT page support, PBMT field interpretation, and A/D bit update logic
- `sys_regs.sail` — CSR bitfield definitions for `satp` (Satp32/Satp64), `mstatus` (MXR, SUM, MPRV, MPP), and `menvcfg` (PBMTE, ADUE)
- `sys_control.sail` — `effectivePrivilege()` function implementing MPRV-based privilege modification
- `sail_syntax.md` — Guide to reading Sail language constructs

A set of address translation scenarios is provided at `/app/scenarios/`. Each scenario is a JSON file describing a RISC-V hart's CSR state, physical memory contents (containing page table entries as raw hex bytes), and a virtual address access request.

Implement `/app/translate.py` that, when run as `python3 /app/translate.py`, processes every JSON file in `/app/scenarios/` and writes per-scenario results to `/app/results/<scenario_name>.json`.

Each result JSON must contain:

```json
{
  "outcome": "success" | "fault",
  "physical_address": "0x...",
  "fault_type": "load_page_fault" | "store_page_fault" | "fetch_page_fault",
  "page_level": 0,
  "pte_flags": {"d": true, "a": true, "g": false, "u": false, "x": false, "w": true, "r": true},
  "pbmt_mode": "pma" | "nc" | "io",
  "a_d_update_needed": false
}
```

On success: `physical_address`, `page_level` (0=4KiB, 1=2MiB/4MiB, 2=1GiB), `pte_flags`, `pbmt_mode`, and `a_d_update_needed` must be present. On fault: `fault_type` must be present. The fault type depends on the access type: `load_page_fault` for reads, `store_page_fault` for writes, `fetch_page_fault` for execute.

The translation engine must faithfully implement:

- **Multi-mode translation**: Sv32 (2-level, 32-bit PTEs), Sv39 (3-level), Sv48 (4-level), with correct VPN field extraction and PTE sizing
- **Superpage validation**: Alignment requirements on PPN fields at each level; misaligned superpages fault
- **Permission checking**: R/W/X bits per access type; U-bit interaction with privilege level; `mstatus.MXR` making execute-only pages readable; `mstatus.SUM` allowing supervisor access to user pages (except execute)
- **MPRV privilege modification**: `mstatus.MPRV` + `mstatus.MPP` changing effective privilege for data accesses only (not instruction fetch)
- **A/D bit semantics**: When A=0 or D=0 (for stores), behavior depends on `menvcfg.ADUE` — hardware update (success with `a_d_update_needed=true`) vs. software management (page fault)
- **Svnapot**: NAPOT 64KiB pages via N-bit in PTE, with specific PPN encoding (`PPN[3:0]=0b1000`), only at level 0
- **Svpbmt**: Page-based memory types from PTE bits [62:61], gated by `menvcfg.PBMTE`
- **Reserved PTE encodings**: W=1 R=0 is invalid; non-leaf at level 0 is invalid; N=1 at level > 0 is invalid

The translation function must also be importable: `from translate import translate_scenario` accepting a scenario dict and returning the result dict.