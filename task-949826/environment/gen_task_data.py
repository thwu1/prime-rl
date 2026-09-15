#!/usr/bin/env python3
"""Generate RISC-V Sv39 page table audit task data.

Creates:
  /app/physmem.bin          - Raw physical memory dump with Sv39 page tables
  /app/binaries/*.elf       - RISC-V ELF binaries with various LOAD segments
  /app/satp.json            - SATP register configuration
  /app/process_table.json   - Per-binary execution context (privilege, MXR, SUM)
  /app/sample_output.json   - Format reference showing expected output for kern.elf
"""
import struct
import json
import os

# ═══════════════════════════════════════════════════════════════════
# ELF64 RISC-V Binary Generator
# ═══════════════════════════════════════════════════════════════════

ELFMAG = b'\x7fELF'
ELFCLASS64 = 2
ELFDATA2LSB = 1
EV_CURRENT = 1
ET_EXEC = 2
EM_RISCV = 243
PT_LOAD = 1
PF_X = 0x1
PF_W = 0x2
PF_R = 0x4


def create_riscv_elf(filename, segments, entry=0):
    """Create a minimal valid ELF64 RISC-V executable.

    Args:
        filename: Output path
        segments: List of (vaddr, memsz, flags) tuples
        entry: Entry point virtual address
    """
    ehdr_size = 64
    phdr_size = 56
    phnum = len(segments)
    phoff = ehdr_size
    data_start = ehdr_size + phdr_size * phnum

    # ELF identification
    e_ident = ELFMAG + bytes([
        ELFCLASS64, ELFDATA2LSB, EV_CURRENT, 0, 0
    ]) + b'\x00' * 7

    # ELF header (after e_ident)
    ehdr = e_ident + struct.pack('<HHIQQQIHHHHHH',
        ET_EXEC,        # e_type
        EM_RISCV,       # e_machine
        EV_CURRENT,     # e_version
        entry,          # e_entry
        phoff,          # e_phoff
        0,              # e_shoff (no section headers)
        0x5,            # e_flags (RVC + double-float ABI)
        ehdr_size,      # e_ehsize
        phdr_size,      # e_phentsize
        phnum,          # e_phnum
        0,              # e_shentsize
        0,              # e_shnum
        0,              # e_shstrndx (SHN_UNDEF)
    )

    # Build program headers and segment data
    phdrs = b''
    seg_data = b''
    offset = data_start

    for vaddr, memsz, flags in segments:
        filesz = min(memsz, 256)
        phdrs += struct.pack('<IIQQQQQQ',
            PT_LOAD,    # p_type
            flags,      # p_flags
            offset,     # p_offset
            vaddr,      # p_vaddr
            vaddr,      # p_paddr
            filesz,     # p_filesz
            memsz,      # p_memsz
            0x1000,     # p_align (4KB)
        )
        # Fill with a deterministic pattern (RISC-V NOP = 0x00000013)
        seg_data += bytes([(0x13 + i * 7) % 256 for i in range(filesz)])
        offset += filesz

    elf_bytes = ehdr + phdrs + seg_data
    with open(filename, 'wb') as f:
        f.write(elf_bytes)
    os.chmod(filename, 0o644)


# ═══════════════════════════════════════════════════════════════════
# Sv39 Page Table Generator
# ═══════════════════════════════════════════════════════════════════

V = 1 << 0   # Valid
R = 1 << 1   # Read
W = 1 << 2   # Write
X = 1 << 3   # Execute
U = 1 << 4   # User
G = 1 << 5   # Global
A = 1 << 6   # Accessed
D = 1 << 7   # Dirty


def gen_physical_memory():
    """Generate a physical memory dump containing Sv39 page table hierarchy.

    Layout (7 pages = 28672 bytes):
      Page 0 (PA 0x0000): Root Level-2 page table
      Page 1 (PA 0x1000): Level-1 table A  (covers VA 0x00000000-0x3FFFFFFF)
      Page 2 (PA 0x2000): Level-1 table B  (covers VA 0x80000000-0xBFFFFFFF)
      Page 3 (PA 0x3000): Level-0 table A  (covers VA 0x00000000-0x001FFFFF)
      Page 4 (PA 0x4000): Level-0 table B  (covers VA 0x00A00000-0x00BFFFFF)
      Page 5 (PA 0x5000): Level-0 table C  (covers VA 0x80000000-0x801FFFFF)
      Page 6 (PA 0x6000): Noise / other memory content
    """
    mem = bytearray(7 * 4096)

    def write_pte(page, entry, ppn, flags):
        pte = (ppn << 10) | flags
        off = page * 4096 + entry * 8
        struct.pack_into('<Q', mem, off, pte)

    # ── Page 0: Root L2 table ────────────────────────────────────
    write_pte(0, 0, 0x1, V)                    # → L1 table A (page 1)
    write_pte(0, 1, 0x80000, V|R|W|X|A|D)      # 1GB gigapage PA=0x80000000
    write_pte(0, 2, 0x2, V)                    # → L1 table B (page 2)
    write_pte(0, 3, 0x80001, V|R|W|X|A|D)      # MISALIGNED 1GB gigapage
    write_pte(0, 4, 0x90000, V|W)              # Reserved encoding (W=1,R=0)

    # ── Page 1: L1 table A ───────────────────────────────────────
    write_pte(1, 0, 0x3, V)                    # → L0 table A (page 3)
    write_pte(1, 1, 0xA0000, V|R|X|A)          # 2MB megapage PA=0xA0000000, RX
    write_pte(1, 2, 0xB0000, V|R|W|A|D)        # 2MB megapage PA=0xB0000000, RW
    write_pte(1, 3, 0xC0001, V|R|W|A|D)        # MISALIGNED 2MB megapage
    write_pte(1, 4, 0xD0000, V|R|W|X|U|A|D)    # 2MB user megapage PA=0xD0000000
    write_pte(1, 5, 0x4, V)                    # → L0 table B (page 4)

    # ── Page 2: L1 table B ───────────────────────────────────────
    write_pte(2, 0, 0x5, V)                    # → L0 table C (page 5)
    write_pte(2, 1, 0xF0000, V|R|W|X|G|A|D)    # 2MB global megapage

    # ── Page 3: L0 table A ───────────────────────────────────────
    write_pte(3, 0, 0x10000, V|R|W|X|G|A|D)    # 4KB PA=0x10000000 S-mode RWX
    write_pte(3, 1, 0x10001, V|R|A)             # 4KB PA=0x10001000 S-mode R-only
    write_pte(3, 2, 0x10002, V|R|W|X|U|A|D)    # 4KB PA=0x10002000 U-mode RWX
    write_pte(3, 3, 0x10003, V|X|A)             # 4KB PA=0x10003000 X-only
    write_pte(3, 4, 0x10004, V|R|W|D)           # 4KB PA=0x10004000 RW, A=0
    write_pte(3, 5, 0x10005, V|R|W|A)           # 4KB PA=0x10005000 RW, D=0
    write_pte(3, 6, 0x10006, V)                 # Non-leaf at L0 (R=W=X=0)
    write_pte(3, 7, 0x10007, V|W)               # Reserved encoding (W=1,R=0)
    # Entry 8: all zeros → V=0, invalid PTE

    # ── Page 4: L0 table B ───────────────────────────────────────
    write_pte(4, 0, 0x20000, V|R|W|X|G|A|D)    # 4KB PA=0x20000000 S-mode RWX
    write_pte(4, 1, 0x20001, V|R|A)             # 4KB PA=0x20001000 S-mode R-only

    # ── Page 5: L0 table C ───────────────────────────────────────
    write_pte(5, 0, 0x30000, V|R|X|A)           # 4KB PA=0x30000000 RX
    write_pte(5, 1, 0x30001, V|R|W|U|A|D)       # 4KB PA=0x30001000 U-mode RW

    # ── Page 6: Noise (simulates other memory content) ───────────
    for i in range(512):
        struct.pack_into('<Q', mem, 6 * 4096 + i * 8, 0xDEADBEEF00000000 | i)

    return bytes(mem)


# ═══════════════════════════════════════════════════════════════════
# Generate all task files
# ═══════════════════════════════════════════════════════════════════

os.makedirs('/app/binaries', exist_ok=True)

# ── Physical memory dump ─────────────────────────────────────────
physmem = gen_physical_memory()
with open('/app/physmem.bin', 'wb') as f:
    f.write(physmem)

# ── SATP configuration ──────────────────────────────────────────
with open('/app/satp.json', 'w') as f:
    json.dump({"satp_ppn": 0, "svade": True}, f, indent=2)

# ── RISC-V ELF binaries ─────────────────────────────────────────
# kern.elf: supervisor kernel — tests basic 4KB mapping + permission fault
create_riscv_elf('/app/binaries/kern.elf', [
    (0x0000000000000000, 0x1000, PF_R | PF_W | PF_X),   # S-mode RWX page
    (0x0000000000001000, 0x1000, PF_R | PF_W),           # S-mode R-only (W fails)
], entry=0x0)

# driver.elf: device driver — tests 2MB megapages + misaligned superpage
create_riscv_elf('/app/binaries/driver.elf', [
    (0x0000000000200000, 0x1000, PF_R | PF_X),           # 2MB RX megapage
    (0x0000000000400000, 0x1000, PF_R | PF_W),           # 2MB RW megapage
    (0x0000000000600000, 0x1000, PF_R),                   # misaligned megapage
], entry=0x200000)

# app_alpha.elf: user process — tests U-mode access + user megapage
create_riscv_elf('/app/binaries/app_alpha.elf', [
    (0x0000000000002000, 0x1000, PF_R | PF_W | PF_X),   # U-mode 4KB page
    (0x0000000000800000, 0x1000, PF_R | PF_X),           # U-mode 2MB megapage
], entry=0x2000)

# monitor.elf: supervisor with MXR — tests X-only + Svade A/D faults
create_riscv_elf('/app/binaries/monitor.elf', [
    (0x0000000000003000, 0x1000, PF_R | PF_X),           # X-only page (MXR helps)
    (0x0000000000004000, 0x1000, PF_R | PF_W),           # Svade: A=0 fault
    (0x0000000000005000, 0x1000, PF_R | PF_W),           # Svade: D=0 fault
], entry=0x3000)

# diag.elf: supervisor with SUM — tests SUM, invalid PTEs, gigapage
create_riscv_elf('/app/binaries/diag.elf', [
    (0x0000000000002000, 0x1000, PF_R),                   # U-page via SUM
    (0x0000000000006000, 0x1000, PF_R),                   # non-leaf at L0
    (0x0000000000007000, 0x1000, PF_R),                   # reserved encoding
    (0x0000000000008000, 0x1000, PF_R),                   # invalid PTE (V=0)
    (0x0000000040000000, 0x1000, PF_R | PF_W | PF_X),   # 1GB gigapage
], entry=0x2000)

# ── Process table (execution context per binary) ─────────────────
process_table = [
    {"binary": "kern.elf",      "priv": "S", "mxr": False, "sum": False},
    {"binary": "driver.elf",    "priv": "S", "mxr": False, "sum": False},
    {"binary": "app_alpha.elf", "priv": "U", "mxr": False, "sum": False},
    {"binary": "monitor.elf",   "priv": "S", "mxr": True,  "sum": False},
    {"binary": "diag.elf",      "priv": "S", "mxr": False, "sum": True},
]
with open('/app/process_table.json', 'w') as f:
    json.dump(process_table, f, indent=2)

# ── Sample output (format reference for kern.elf only) ───────────
sample = {
    "_note": "Expected audit output for kern.elf only. Use as format reference.",
    "binary": "kern.elf",
    "priv": "S",
    "mxr": False,
    "sum": False,
    "segments": [
        {
            "vaddr": "0x0",
            "memsz": 4096,
            "flags": "rwx",
            "status": "ok",
            "pa": "0x10000000",
            "page_size": 4096,
        },
        {
            "vaddr": "0x1000",
            "memsz": 4096,
            "flags": "rw",
            "status": "fault",
            "cause": "store_page_fault",
        },
    ],
}
with open('/app/sample_output.json', 'w') as f:
    json.dump(sample, f, indent=2)

print(f"Generated task data:")
print(f"  physmem.bin: {len(physmem)} bytes ({len(physmem) // 4096} pages)")
print(f"  binaries: {sorted(os.listdir('/app/binaries/'))}")
print(f"  process_table.json: {len(process_table)} entries")
