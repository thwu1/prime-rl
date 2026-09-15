An x86_64 virtual machine crashed with a triple fault during early kernel boot. Crash artifacts are at `/app/`:

- `memory.bin` — Raw physical memory dump (binary)
- `registers.json` — CPU register state at crash time
- `boot_log.txt` — Serial console output before the crash

The physical memory contains the kernel's page table hierarchy. Analyze the dump to reconstruct the full virtual memory map, identify all page table anomalies, determine the crash root cause, and produce corrected output.

## Required Output

**`/app/report.json`**:
```json
{
  "cr3": "<hex>",
  "physical_memory_size": "<integer, total bytes>",
  "total_mapped_entries": "<count of reachable leaf page table entries where every intermediate entry in the walk from CR3 has its present bit set>",
  "memory_map": [
    {
      "virtual_address": "<hex>",
      "physical_address": "<hex>",
      "size": "<4096 | 2097152 | 1073741824>",
      "flags": "<hex>"
    }
  ],
  "anomalies": [
    {
      "virtual_address": "<hex>",
      "entry_physical_location": "<hex: byte offset in physical memory of the 8-byte entry>",
      "entry_current_value": "<hex>",
      "entry_corrected_value": "<hex>",
      "description": "<explanation>"
    }
  ],
  "crash_root_cause": "<explanation of why the system triple-faulted>"
}
```

**`/app/memory_fixed.bin`** — Copy of `memory.bin` with all anomalous page table entries corrected in place.

All hex values: `0x`-prefixed lowercase.