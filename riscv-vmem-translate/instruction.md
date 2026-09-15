A RISC-V RV64 system running Sv39 virtual memory has crashed with multiple page faults. The crash artifacts are:

- `/app/memory.qcow2` — physical memory snapshot (qcow2 disk image)
- `/app/platform.dtb` — compiled device tree blob describing the hardware platform
- `/app/system.json` — processor CSR state and enabled ISA extensions at time of crash
- `/app/faults.json` — observed fault trace with virtual addresses, access types, and privilege levels

For each fault, identify the responsible page table entry, diagnose the violation under the system's current configuration, and determine the minimal correction that allows the faulting access to succeed without granting unnecessary additional privileges or capabilities.

Produce two output files:

`/app/diagnosis.json` — a JSON array with one object per fault:
- `id` (int): matching the fault ID from `faults.json`
- `pte_phys_addr` (hex string): physical address of the faulty PTE
- `current_pte` (hex string): the PTE value as found in memory
- `root_cause` (string): description of the specific violation
- `corrected_pte` (hex string): the minimally-corrected PTE value

`/app/memory_fixed.qcow2` — a qcow2 disk image containing the corrected physical memory with only the faulty PTEs modified and all other contents preserved exactly.