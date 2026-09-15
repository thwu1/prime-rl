#!/usr/bin/env python3
"""
Generate forensics scenario: corrupted x86-64 page tables with kernel ELF binary
and security hardening policy.

Creates a physical memory dump containing:
- Two decoy PML4 tables (stale address spaces)
- One real PML4 (the active CR3 at crash time)
- Four corrupted page table entries of different types
- A crash report with diagnostic symptoms
- A minimal kernel ELF binary with section layout and permissions
- A security policy document for W^X hardening

"""
import struct
import os
import sys


def make_entry(phys_addr, present=True, rw=False, us=False, nx=False, ps=False):
    """Create an x86-64 page table entry with specified flags."""
    entry = 0
    if present:
        entry |= 1
    if rw:
        entry |= (1 << 1)
    if us:
        entry |= (1 << 2)
    if ps:
        entry |= (1 << 7)
    entry |= (phys_addr & 0x000FFFFFFFFFF000)
    if nx:
        entry |= (1 << 63)
    return entry


def generate_elf(path):
    """Generate a minimal ELF64 binary representing the kernel, with section
    headers and program headers that encode expected virtual/physical layout
    and permissions. This ELF must be parsed with readelf/objdump to determine
    the expected kernel memory configuration."""

    # Section contents (minimal)
    text_content = bytes([0x90, 0x90, 0xC3, 0x90])  # nop nop ret nop
    data_content = bytes([0x42] * 8)
    rodata_content = b"ASTERINAS_KERNEL"
    debug_jit_content = bytes([0x00] * 8)

    # Section name string table
    # Index 0: \0, 1: .text, 7: .data, 13: .rodata, 21: .debug_jit, 32: .shstrtab
    shstrtab = b'\0.text\0.data\0.rodata\0.debug_jit\0.shstrtab\0'

    ELF_HDR_SZ = 64
    PHDR_SZ = 56
    SHDR_SZ = 64
    NUM_PHDR = 4
    NUM_SHDR = 6

    phdr_off = ELF_HDR_SZ
    content_off = phdr_off + NUM_PHDR * PHDR_SZ  # 64 + 224 = 288

    text_off = content_off
    data_off = text_off + len(text_content)
    rodata_off = data_off + len(data_content)
    djit_off = rodata_off + len(rodata_content)
    shstrtab_off = djit_off + len(debug_jit_content)

    shdr_off = shstrtab_off + len(shstrtab)
    shdr_off = (shdr_off + 7) & ~7  # 8-byte align

    # ELF header
    e_ident = b'\x7fELF' + bytes([2, 1, 1, 0]) + bytes(8)
    elf_hdr = struct.pack('<16sHHIQQQIHHHHHH',
        e_ident,
        2,                       # ET_EXEC
        62,                      # EM_X86_64
        1,                       # EV_CURRENT
        0xFFFFFF8000000000,      # e_entry (.text start)
        phdr_off,                # e_phoff
        shdr_off,                # e_shoff
        0,                       # e_flags
        ELF_HDR_SZ,
        PHDR_SZ,
        NUM_PHDR,
        SHDR_SZ,
        NUM_SHDR,
        5,                       # e_shstrndx
    )

    # Program headers  (PF_R=4, PF_W=2, PF_X=1)
    # Each segment: (file_offset, file_size, vaddr, paddr, flags)
    segs = [
        (text_off,   len(text_content),       0xFFFFFF8000000000, 0x300000, 5),  # R-X
        (data_off,   len(data_content),       0xFFFFFF8000001000, 0x301000, 6),  # RW-
        (rodata_off, len(rodata_content),     0xFFFFFF8000002000, 0x302000, 4),  # R--
        (djit_off,   len(debug_jit_content),  0xFFFFFF8000003000, 0x303000, 6),  # RW-
    ]
    phdrs = b''
    for foff, fsz, vaddr, paddr, flags in segs:
        phdrs += struct.pack('<IIQQQQQQ',
            1,        # PT_LOAD
            flags,
            foff,
            vaddr,
            paddr,
            fsz,
            0x1000,   # p_memsz (full page)
            0x1000,   # p_align
        )

    # Section headers  (SHF_WRITE=1, SHF_ALLOC=2, SHF_EXECINSTR=4)
    shdrs = bytes(SHDR_SZ)  # NULL entry
    secs = [
        (1,  1, 6, 0xFFFFFF8000000000, text_off,      len(text_content),       16),  # .text AX
        (7,  1, 3, 0xFFFFFF8000001000, data_off,      len(data_content),       16),  # .data WA
        (13, 1, 2, 0xFFFFFF8000002000, rodata_off,    len(rodata_content),     16),  # .rodata A
        (21, 1, 3, 0xFFFFFF8000003000, djit_off,      len(debug_jit_content),  16),  # .debug_jit WA
        (32, 3, 0, 0,                  shstrtab_off,  len(shstrtab),           1),   # .shstrtab
    ]
    for nm, stype, sflags, saddr, soff, ssz, salign in secs:
        shdrs += struct.pack('<IIQQQQIIQQ',
            nm, stype, sflags, saddr, soff, ssz, 0, 0, salign, 0)

    # Assemble the ELF binary
    blob = bytearray()
    blob += elf_hdr
    blob += phdrs
    blob += text_content
    blob += data_content
    blob += rodata_content
    blob += debug_jit_content
    blob += shstrtab
    while len(blob) < shdr_off:
        blob += b'\x00'
    blob += shdrs

    with open(path, 'wb') as f:
        f.write(blob)


def main():
    outdir = sys.argv[1] if len(sys.argv) > 1 else "/app/forensics"
    os.makedirs(outdir, exist_ok=True)

    NUM_PAGES = 20  # 81920 bytes total
    PAGE_SIZE = 4096
    mem_size = NUM_PAGES * PAGE_SIZE
    memory = bytearray(mem_size)

    def write_entry(table_phys, index, value):
        offset = table_phys + index * 8
        struct.pack_into('<Q', memory, offset, value)

    # =====================================================================
    # Physical memory layout (20 pages):
    # 0x00000: Decoy PML4 #1
    # 0x01000: Decoy PDPT #1
    # 0x02000: Decoy PD #1
    # 0x03000: Decoy PT #1
    # 0x04000: Decoy PML4 #2
    # 0x05000: REAL PML4 (CR3 = 0x5000)
    # 0x06000: PDPT_low
    # 0x07000: PD_low
    # 0x08000: PT_low
    # 0x09000: PDPT_user
    # 0x0A000: PD_user
    # 0x0B000: PT_user
    # 0x0C000: PDPT_kern (PML4[511])
    # 0x0D000: PD_kern
    # 0x0E000: PT_kern
    # 0x0F000: PDPT_mid (PML4[100])
    # 0x10000: PD_mid
    # 0x11000-0x13000: zero (available for hardening)
    # =====================================================================

    # === DECOY PML4 #1 at 0x0000 ===
    write_entry(0x0000, 0, make_entry(0x1000, present=True, rw=True, us=False))
    write_entry(0x1000, 0, make_entry(0x2000, present=True, rw=True, us=False))
    write_entry(0x2000, 0, make_entry(0x3000, present=True, rw=True, us=False))
    write_entry(0x3000, 0, make_entry(0x500000, present=True, rw=False, us=False, nx=False))

    # === DECOY PML4 #2 at 0x4000 ===
    write_entry(0x4000, 0, make_entry(0x20000, present=True, rw=True, us=False))
    write_entry(0x4000, 511, make_entry(0xC000, present=True, rw=True, us=False))

    # === REAL PML4 at 0x5000 (CR3 = 0x5000) ===
    write_entry(0x5000, 0,   make_entry(0x6000, present=True, rw=True, us=False))
    write_entry(0x5000, 1,   make_entry(0x9000, present=True, rw=True, us=True))
    write_entry(0x5000, 100, make_entry(0xF000, present=True, rw=True, us=True))
    write_entry(0x5000, 511, make_entry(0xC000, present=True, rw=True, us=False))

    # === Supervisor low-address region ===
    write_entry(0x6000, 0, make_entry(0x7000, present=True, rw=True, us=False))
    write_entry(0x7000, 0, make_entry(0x8000, present=True, rw=True, us=False))
    write_entry(0x8000, 0, make_entry(0x100000, present=True, rw=False, us=False, nx=False))  # VA 0x0 R-X
    write_entry(0x8000, 1, make_entry(0x101000, present=True, rw=True, us=False, nx=True))     # VA 0x1000 RW-
    write_entry(0x8000, 3, make_entry(0x103000, present=True, rw=True, us=False, nx=False))    # VA 0x3000 RWX (W^X!)

    # === User region (PML4[1]) ===
    write_entry(0x9000, 0, make_entry(0xA000, present=True, rw=True, us=True))
    write_entry(0x9000, 1, make_entry(0x40000000, present=True, rw=False, us=True, nx=True, ps=True))
    write_entry(0xA000, 0, make_entry(0xB000, present=True, rw=True, us=True))
    write_entry(0xA000, 1, make_entry(0x400000, present=True, rw=True, us=True, nx=True, ps=True))
    write_entry(0xB000, 5, make_entry(0x200000, present=True, rw=False, us=True, nx=False))

    # === Kernel space (PML4[511]) ===
    write_entry(0xC000, 0, make_entry(0xD000, present=True, rw=True, us=False))
    write_entry(0xD000, 0, make_entry(0xE000, present=True, rw=True, us=False))
    write_entry(0xE000, 0, make_entry(0x300000, present=True, rw=False, us=False, nx=False))  # .text R-X
    write_entry(0xE000, 1, make_entry(0x301000, present=True, rw=True, us=False, nx=True))     # .data RW-
    write_entry(0xE000, 2, make_entry(0x302000, present=True, rw=False, us=True, nx=True))     # .rodata R--
    write_entry(0xE000, 3, make_entry(0x303000, present=True, rw=True, us=False, nx=False))    # debug RWX (W^X!)

    # === Mid-range user (PML4[100]) ===
    write_entry(0xF000, 200, make_entry(0x10000, present=True, rw=True, us=True))
    write_entry(0x10000, 0, make_entry(0x1000000, present=True, rw=True, us=True, nx=False, ps=True))  # 2MB RWX (W^X!)

    # =====================================================================
    # APPLY CORRUPTIONS
    # =====================================================================

    # Corruption 1: PT_kern[0] NX bit injected (kernel .text non-executable)
    offset1 = 0xE000 + 0 * 8
    correct1 = make_entry(0x300000, present=True, rw=False, us=False, nx=False)
    corrupted1 = correct1 | (1 << 63)
    struct.pack_into('<Q', memory, offset1, corrupted1)

    # Corruption 2: PT_kern[1] Present bit cleared (kernel .data unmapped)
    offset2 = 0xE000 + 1 * 8
    correct2 = make_entry(0x301000, present=True, rw=True, us=False, nx=True)
    corrupted2 = correct2 & ~1
    struct.pack_into('<Q', memory, offset2, corrupted2)

    # Corruption 3: PT_user[5] PA bit 20 flipped (wrong physical page)
    offset3 = 0xB000 + 5 * 8
    correct3 = make_entry(0x200000, present=True, rw=False, us=True, nx=False)
    corrupted3 = correct3 ^ (1 << 20)
    struct.pack_into('<Q', memory, offset3, corrupted3)

    # Corruption 4: PT_user[7] Unauthorized mapping injected
    offset4 = 0xB000 + 7 * 8
    corrupted4 = make_entry(0x303000, present=True, rw=True, us=True, nx=False)
    struct.pack_into('<Q', memory, offset4, corrupted4)

    # =====================================================================
    # Write output files
    # =====================================================================

    # 1. memory.bin
    with open(os.path.join(outdir, "memory.bin"), "wb") as f:
        f.write(memory)

    # 2. kernel.elf
    generate_elf(os.path.join(outdir, "kernel.elf"))

    # 3. crash_report.log
    crash_report = """\
=== KERNEL PANIC - SYSTEM HALT ===
Captured at: 2024-03-15T14:23:47.892Z

--- EXCEPTION LOG (chronological) ---

[14:23:47.100] EXCEPTION: #PF (Page Fault)
  RIP: 0xFFFFFF8000000000
  Error Code: 0x00000011
  Faulting Address (CR2): 0xFFFFFF8000000000
  Analysis: Protection violation on supervisor instruction fetch.
  Note: The page is present in the page table but is marked
        non-executable (NX=1). This region should contain kernel .text
        and must be executable.

[14:23:47.200] EXCEPTION: #PF (Page Fault)
  RIP: 0xFFFFFF800000A120
  Error Code: 0x00000000
  Faulting Address (CR2): 0xFFFFFF8000001000
  Analysis: Not-present page fault during supervisor data read.
  Note: The page directory entry chain is valid down to the page table,
        but the page table entry itself has its present bit clear.

[14:23:47.350] INTEGRITY ALERT
  Monitor detected data mismatch at VA 0x0000008000005000.
  Expected content hash: SHA256:a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6
  Actual content hash:   SHA256:e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0
  Diagnosis: The physical backing page appears to have changed.
  The virtual-to-physical mapping for this address may be corrupt.

[14:23:47.500] SECURITY ALERT
  Integrity monitor detected unexpected user-accessible mapping.
  VA: 0x0000008000007000
  Physical target: 0x0000000000303000
  Effective permissions: RWX, User-accessible
  WARNING: Physical address 0x303000 belongs to the kernel address range.
  This mapping was NOT present in the last verified snapshot and
  represents a potential privilege escalation vector.

--- PARTIAL REGISTER STATE ---
(Captured by crash handler; CR3 was clobbered during handler setup)

RAX: 0x0000000000000000  RBX: 0xFFFFFF8000010000
RCX: 0x0000000000000001  RDX: 0x0000000000000000
RSI: 0x0000000000200000  RDI: 0xFFFFFF8000001000
RBP: 0xFFFFFF8000020FF0  RSP: 0xFFFFFF8000020F80
CR0: 0x0000000080050033  [PE=1, WP=1, PG=1]
CR2: 0xFFFFFF8000001000
CR3: [UNAVAILABLE - overwritten by crash handler]
CR4: 0x00000000000006A0
EFER: 0x0000000000000D01  [SCE=1, LME=1, LMA=1, NXE=1]

--- KERNEL BINARY ---
Expected kernel section layout and permissions are defined in the
kernel ELF binary at /app/forensics/kernel.elf. Use ELF analysis
tools (readelf, objdump) to extract section headers and program
headers for the authoritative kernel memory configuration.

--- BOOT-TIME VERIFIED MAPPINGS ---
The following virtual-to-physical translations were confirmed during
early boot and can be used as reference points to identify the active
address space in the dump:

  VA 0x0000000000000000 -> PA 0x0000000000100000 (4KB, R-X, supervisor)
  VA 0x0000008040000000 -> PA 0x0000000040000000 (1GB, R--, user)

--- PRE-CRASH USER-SPACE VERIFICATION ---
The integrity monitor's last snapshot of user-space mappings (T-10s
before crash). These were verified correct at snapshot time:

  VA 0x0000008000005000 -> PA 0x0000000000200000 (4KB, R-X, user)
  VA 0x0000008000007000 -> [not mapped]
"""
    with open(os.path.join(outdir, "crash_report.log"), "w") as f:
        f.write(crash_report)

    # 4. security_policy.txt
    policy = """\
x86-64 Virtual Memory Security Hardening Policy
================================================

Objective: Eliminate all W^X (Write XOR Execute) violations in the
repaired page tables while preserving correct functionality.

HARDENING RULES
---------------

1. KERNEL-SPACE PAGES COVERED BY KERNEL ELF SECTIONS:
   Use the kernel ELF's section flags and program header flags as
   the authoritative permission source.
   - If the ELF section has EXECINSTR/PF_X: page must be R-X
     (clear RW bit, clear NX bit)
   - If the ELF section has WRITE/PF_W but no EXECINSTR/PF_X:
     page must be RW- (keep RW bit, set NX bit)
   - If the ELF section has neither: page must be R--
     (clear RW bit, set NX bit)

2. NON-KERNEL PAGES NOT COVERED BY ANY ELF SECTION:
   If a page has both W and X effective permissions (W^X violation):
   - Set the NX bit to make it non-executable (prefer data safety)
   - Preserve all other permission bits unchanged

3. LARGE PAGES (2MB or 1GB) WITH W^X VIOLATIONS:
   - Demote to 4KB page table entries by allocating a new page table
     structure at the lowest-addressed unused (all-zero) physical
     page in the dump
   - In the new page table, each 4KB entry maps the corresponding
     sub-range of the original large page
   - Apply Rule 2 to each sub-page: set NX, preserve RW and US bits
   - Update the parent page directory entry to point to the new page
     table (clear the PS bit, set correct physical address and flags)

4. PRESERVATION:
   All page table entries that do NOT have W^X violations must remain
   unchanged in the hardened output.

SECURITY POSTURE METRICS
------------------------

Evaluate the following metrics for each state (corrupted, repaired,
hardened):

  wx_violations: Count of mapped pages with both effective W and X
                 permissions (i.e., writable AND executable).

  privilege_escalation_paths: Count of user-accessible pages that
                              provide WRITE access to physical
                              addresses used by kernel ELF sections
                              (as identified via program header
                              physical addresses).

  unmapped_critical_pages: Count of kernel ELF sections marked as
                           present whose corresponding virtual
                           addresses are NOT mapped (not present)
                           in the page tables.
"""
    with open(os.path.join(outdir, "security_policy.txt"), "w") as f:
        f.write(policy)


if __name__ == "__main__":
    main()
