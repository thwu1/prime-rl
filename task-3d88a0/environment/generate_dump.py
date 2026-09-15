#!/usr/bin/env python3
"""Generate the x86_64 page table forensics environment.

Creates a 4MB physical memory dump with a 4-level page table hierarchy
containing multiple planted anomalies, plus crash artifacts.
"""
import struct
import json

PHYS_SIZE = 4 * 1024 * 1024  # 4MB
PAGE_SIZE = 4096

# x86_64 page table entry flags
PRESENT    = 1 << 0
WRITABLE   = 1 << 1
USER       = 1 << 2
ACCESSED   = 1 << 5
DIRTY      = 1 << 6
HUGE_PAGE  = 1 << 7
NX         = 1 << 63

mem = bytearray(PHYS_SIZE)


def write_u64(offset, value):
    struct.pack_into('<Q', mem, offset, value & 0xFFFFFFFFFFFFFFFF)


def write_entry(table_phys, index, value):
    write_u64(table_phys + index * 8, value)


# ===== Page Table Layout =====
#
# Frame map:
#   0x000000 - reserved
#   0x001000 - PML4 (CR3)
#   0x002000 - PDPT for PML4[0] (user space)
#   0x003000 - PD for PDPT[0]
#   0x004000 - PT for PD[0] (first 2MB, 4KB pages)
#   0x005000 - PT for PD[3]
#   0x006000 - PDPT for PML4[256] (kernel space)
#   0x007000 - PD for kernel PDPT[0]
#   0x008000 - PT for kernel PD[0]
#   0x009000 - PT for PD[4] (unreachable due to anomaly)
#   0x010000+ - data frames

PML4 = 0x1000

# --- PML4 entries ---

# PML4[0]: user-space lower half -> PDPT at 0x2000
write_entry(PML4, 0, 0x2000 | PRESENT | WRITABLE | USER)

# PML4[256]: kernel upper half -> PDPT at 0x6000
# ANOMALY: NX bit set on PML4 entry, blocks code execution across entire kernel region
write_entry(PML4, 256, 0x6000 | PRESENT | WRITABLE | NX)

# --- User-space: PDPT at 0x2000 ---

# PDPT[0] -> PD at 0x3000
write_entry(0x2000, 0, 0x3000 | PRESENT | WRITABLE | USER)

# --- User-space: PD at 0x3000 ---

# PD[0] -> PT at 0x4000 (first 2MB as 4KB pages)
write_entry(0x3000, 0, 0x4000 | PRESENT | WRITABLE | USER)

# PD[1] -> 2MB huge page at phys 0x200000 (valid, correctly aligned)
write_entry(0x3000, 1, 0x200000 | PRESENT | WRITABLE | USER | HUGE_PAGE)

# PD[2] -> 2MB huge page at phys 0x201000
# ANOMALY: physical address not 2MB-aligned (0x201000 vs required 0x200000 boundary)
write_entry(0x3000, 2, 0x201000 | PRESENT | WRITABLE | USER | HUGE_PAGE)

# PD[3] -> PT at 0x5000
write_entry(0x3000, 3, 0x5000 | PRESENT | WRITABLE | USER)

# PD[4] -> PT at 0x9000
# ANOMALY: PRESENT bit cleared despite valid child page table
write_entry(0x3000, 4, 0x9000 | WRITABLE | USER)  # no PRESENT

# --- User-space: PT at 0x4000 (maps first 2MB as 4KB pages) ---

user_mappings = [
    (0,  0x010000),   # virt 0x0000
    (1,  0x011000),   # virt 0x1000
    (2,  0x012000),   # virt 0x2000
    (3,  0x013000),   # virt 0x3000
    (4,  0x004000),   # ANOMALY: self-referencing - maps to own PT frame
    (5,  0x014000),   # virt 0x5000
    (6,  0x015000),   # virt 0x6000
    (7,  0x016000),   # virt 0x7000
    (8,  0x017000),   # virt 0x8000
    (9,  0x018000),   # virt 0x9000
    (10, 0x500000),   # ANOMALY: physical address 0x500000 beyond 4MB RAM
]
for idx, phys in user_mappings:
    write_entry(0x4000, idx, phys | PRESENT | WRITABLE | USER)

# --- User-space: PT at 0x5000 (maps PD[3] region, virt 0x600000+) ---

write_entry(0x5000, 0, 0x019000 | PRESENT | WRITABLE | USER)  # virt 0x600000
write_entry(0x5000, 1, 0x01A000 | PRESENT | WRITABLE | USER)  # virt 0x601000

# --- User-space: PT at 0x9000 (maps PD[4] region, virt 0x800000+) ---
# These entries are valid but unreachable due to the PD[4] PRESENT anomaly

write_entry(0x9000, 0, 0x01B000 | PRESENT | WRITABLE | USER)  # would be virt 0x800000
write_entry(0x9000, 1, 0x01C000 | PRESENT | WRITABLE | USER)  # would be virt 0x801000

# --- Kernel-space: PDPT at 0x6000 ---

# PDPT[0] -> PD at 0x7000
write_entry(0x6000, 0, 0x7000 | PRESENT | WRITABLE)

# --- Kernel-space: PD at 0x7000 ---

# PD[0] -> PT at 0x8000
# ANOMALY: WRITABLE bit missing, makes all child pages effectively read-only
write_entry(0x7000, 0, 0x8000 | PRESENT)  # no WRITABLE

# --- Kernel-space: PT at 0x8000 (kernel code/data) ---

for i in range(4):
    write_entry(0x8000, i, (0x01D000 + i * 0x1000) | PRESENT | WRITABLE)

# --- Write identifiable data patterns in data frames ---

for frame_addr in [0x010000, 0x011000, 0x012000, 0x013000, 0x014000,
                   0x015000, 0x016000, 0x017000, 0x018000, 0x019000,
                   0x01A000, 0x01B000, 0x01C000, 0x01D000, 0x01E000,
                   0x01F000, 0x020000]:
    sig = struct.pack('<QQ', 0xCAFEBABEDEAD0000 | (frame_addr >> 12), frame_addr)
    mem[frame_addr + 16:frame_addr + 32] = sig

# ===== Write output files =====

with open('/app/memory.bin', 'wb') as f:
    f.write(mem)

registers = {
    "cr3": "0x1000",
    "rip": "0xffff800000000100",
    "rsp": "0xffff800000003ff0",
    "rflags": "0x10246",
    "cr0": "0x80010033",
    "cr4": "0x000006a0",
    "cs": "0x10",
    "ss": "0x18",
    "error_code": "0x0003",
    "fault_address": "0xffff800000002000"
}
with open('/app/registers.json', 'w') as f:
    json.dump(registers, f, indent=2)

serial = """\
[    0.000000] Booting kernel v0.1.0...
[    0.001234] Physical memory detected: 4194304 bytes (4 MB)
[    0.002345] Page tables initialized, CR3=0x1000
[    0.003456] Identity mapping first 2MB...
[    0.004567] Mapping kernel text section at 0xffff800000000000
[    0.005678] Mapping kernel stack at 0xffff800000003000
[    0.006789] Enabling NX bit support (EFER.NXE=1)
[    0.007890] Setting up user-space mappings...
[    0.008901] Initializing kernel BSS...
[    0.009012] PANIC: Page fault exception (#PF)
[    0.009013]   Faulting address: 0xffff800000002000
[    0.009014]   Error code: 0x0003
[    0.009015]   RIP: 0xffff800000000100
[    0.009016]   RSP: 0xffff800000003ff0
[    0.009017] Attempting to handle fault... failed
[    0.009018] Double fault!
[    0.009019] Double fault handler not available
[    0.009020] *** TRIPLE FAULT - SYSTEM HALTED ***
"""
with open('/app/boot_log.txt', 'w') as f:
    f.write(serial)

print("Environment generated successfully")
