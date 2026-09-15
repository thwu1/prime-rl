#!/usr/bin/env python3
"""Generate RISC-V Sv39 page table binary for the PTW task."""
import struct

# 6 pages of 4096 bytes each = 24576 bytes total
mem = bytearray(6 * 4096)

# PTE flag bits
V = 1 << 0   # Valid
R = 1 << 1   # Read
W = 1 << 2   # Write
X = 1 << 3   # Execute
U = 1 << 4   # User
G = 1 << 5   # Global
A = 1 << 6   # Accessed
D = 1 << 7   # Dirty

def write_pte(page_idx, entry_idx, ppn, flags):
    pte = (ppn << 10) | flags
    offset = page_idx * 4096 + entry_idx * 8
    struct.pack_into('<Q', mem, offset, pte)

# ============================================================
# Page 0 (offset 0x0000): Root page table (Level 2)
# ============================================================
# Entry 0: Pointer to Level-1 table A (page 1)
write_pte(0, 0, 0x1, V)
# Entry 1: 1GB gigapage at PA 0x80000000, supervisor R+W+X
write_pte(0, 1, 0x80000, V|R|W|X|A|D)
# Entry 2: Pointer to Level-1 table B (page 2)
write_pte(0, 2, 0x2, V)
# Entry 3: MISALIGNED 1GB gigapage (PPN[0] != 0)
write_pte(0, 3, 0x80001, V|R|W|X|A|D)
# Entry 4: Reserved encoding (W=1, R=0)
write_pte(0, 4, 0x90000, V|W)

# ============================================================
# Page 1 (offset 0x1000): Level-1 table A
# ============================================================
# Entry 0: Pointer to Level-0 table A (page 3)
write_pte(1, 0, 0x3, V)
# Entry 1: 2MB megapage at PA 0xA0000000, R+X (no W, no D)
write_pte(1, 1, 0xA0000, V|R|X|A)
# Entry 2: 2MB megapage at PA 0xB0000000, R+W (no X)
write_pte(1, 2, 0xB0000, V|R|W|A|D)
# Entry 3: MISALIGNED 2MB megapage (PPN[0] != 0)
write_pte(1, 3, 0xC0001, V|R|W|A|D)
# Entry 4: 2MB user megapage at PA 0xD0000000, R+W+X
write_pte(1, 4, 0xD0000, V|R|W|X|U|A|D)
# Entry 5: Pointer to Level-0 table B (page 4)
write_pte(1, 5, 0x4, V)

# ============================================================
# Page 2 (offset 0x2000): Level-1 table B
# ============================================================
# Entry 0: Pointer to Level-0 table C (page 5)
write_pte(2, 0, 0x5, V)
# Entry 1: 2MB global megapage at PA 0xF0000000, R+W+X
write_pte(2, 1, 0xF0000, V|R|W|X|G|A|D)

# ============================================================
# Page 3 (offset 0x3000): Level-0 table A
# ============================================================
# Entry 0: 4KB at PA 0x10000000, supervisor global R+W+X
write_pte(3, 0, 0x10000, V|R|W|X|G|A|D)
# Entry 1: 4KB at PA 0x10001000, supervisor read-only
write_pte(3, 1, 0x10001, V|R|A)
# Entry 2: 4KB at PA 0x10002000, user R+W+X
write_pte(3, 2, 0x10002, V|R|W|X|U|A|D)
# Entry 3: 4KB at PA 0x10003000, execute-only (X=1, R=0)
write_pte(3, 3, 0x10003, V|X|A)
# Entry 4: 4KB at PA 0x10004000, R+W but A bit NOT set
write_pte(3, 4, 0x10004, V|R|W|D)
# Entry 5: 4KB at PA 0x10005000, R+W+A but D bit NOT set
write_pte(3, 5, 0x10005, V|R|W|A)
# Entry 6: Non-leaf PTE at level 0 (V=1, R=W=X=0) — invalid
write_pte(3, 6, 0x10006, V)
# Entry 7: Reserved encoding at leaf (W=1, R=0)
write_pte(3, 7, 0x10007, V|W)

# ============================================================
# Page 4 (offset 0x4000): Level-0 table B
# ============================================================
# Entry 0: 4KB at PA 0x20000000, supervisor global R+W+X
write_pte(4, 0, 0x20000, V|R|W|X|G|A|D)
# Entry 1: 4KB at PA 0x20001000, supervisor read-only
write_pte(4, 1, 0x20001, V|R|A)

# ============================================================
# Page 5 (offset 0x5000): Level-0 table C
# ============================================================
# Entry 0: 4KB at PA 0x30000000, R+X
write_pte(5, 0, 0x30000, V|R|X|A)
# Entry 1: 4KB at PA 0x30001000, user R+W
write_pte(5, 1, 0x30001, V|R|W|U|A|D)

with open('/app/pagetables.bin', 'wb') as f:
    f.write(mem)

print("Generated /app/pagetables.bin ({} bytes)".format(len(mem)))
