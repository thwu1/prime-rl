Build a command-line tool at `/app/ptw_audit` that audits whether a set of RISC-V ELF binaries are correctly mapped by the system's Sv39 page table configuration.

## Inputs

- `/app/physmem.bin` — Raw physical memory image containing Sv39 page table hierarchy. 64-bit little-endian PTEs, 512 entries per 4096-byte page.
- `/app/satp.json` — `{"satp_ppn": <int>, "svade": <bool>}`. `satp_ppn` is the physical page number of the root page table.
- `/app/process_table.json` — Array of execution contexts: `{"binary": "<name>", "priv": "S"|"U", "mxr": <bool>, "sum": <bool>}`.
- `/app/binaries/*.elf` — RISC-V ELF64 executables. Each has one or more PT_LOAD segments at specific virtual addresses with permission flags.

The system includes `riscv64-linux-gnu-readelf` (from `binutils-riscv64-linux-gnu`) and `xxd` for binary analysis.

## Task

For each entry in the process table, extract the corresponding ELF binary's LOAD segments (virtual address, memory size, permission flags) and walk the Sv39 page tables to determine whether each segment's base virtual address is correctly mapped with the required permissions under the given execution context.

For each segment, verify access types in order: read (if PF_R), write (if PF_W), execute (if PF_X). Report the first failing access type.

The audit must correctly handle: three-level page table walks, superpage translations with alignment validation, R/W/X permission checks accounting for privilege mode / U-bit / MXR / SUM, Svade hardware A/D bit faults, reserved PTE encodings (W && !R), non-leaf PTEs at the final level, and canonical virtual address validation.

## Output

Write JSON to stdout:

```json
{
  "satp_ppn": 0,
  "svade": true,
  "audits": [
    {
      "binary": "<name>",
      "priv": "S",
      "mxr": false,
      "sum": false,
      "segments": [
        {"vaddr": "<hex>", "memsz": 4096, "flags": "rwx", "status": "ok", "pa": "<hex>", "page_size": 4096},
        {"vaddr": "<hex>", "memsz": 4096, "flags": "rw", "status": "fault", "cause": "store_page_fault"}
      ]
    }
  ]
}
```

- `flags`: lowercase subset of `rwx` in that order (e.g. `rwx`, `rw`, `rx`, `r`).
- `page_size`: `4096`, `2097152`, or `1073741824`.
- Fault causes: `load_page_fault`, `store_page_fault`, `fetch_page_fault`.
- Hex values use `0x` prefix, lowercase.

A format reference for kern.elf is at `/app/sample_output.json`.