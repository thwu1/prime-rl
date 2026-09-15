#!/usr/bin/env python3
"""Generate x86-64 page table dump for the security audit task."""
import struct
import json
import os
import sys


def make_entry(phys_addr, present=True, rw=False, us=False, nx=False, ps=False):
    """Create a page table entry with specified flags."""
    entry = 0
    if present:
        entry |= 1            # bit 0: Present
    if rw:
        entry |= (1 << 1)     # bit 1: Read/Write
    if us:
        entry |= (1 << 2)     # bit 2: User/Supervisor
    if ps:
        entry |= (1 << 7)     # bit 7: Page Size
    entry |= (phys_addr & 0x000FFFFFFFFFF000)  # bits 12-51: physical address
    if nx:
        entry |= (1 << 63)    # bit 63: Execute Disable
    return entry


def main():
    outdir = sys.argv[1] if len(sys.argv) > 1 else "/app/ptdump"
    os.makedirs(outdir, exist_ok=True)

    NUM_PAGES = 12
    PAGE_SIZE = 4096
    mem_size = NUM_PAGES * PAGE_SIZE
    memory = bytearray(mem_size)

    def write_entry(table_phys, index, value):
        offset = table_phys + index * 8
        struct.pack_into('<Q', memory, offset, value)

    # Physical layout (12 pages):
    # 0x00000: PML4
    # 0x01000: PDPT_0  (PML4[0] -> supervisor low-address region)
    # 0x02000: PD_0    (PDPT_0[0])
    # 0x03000: PT_0    (PD_0[0])
    # 0x04000: PDPT_1  (PML4[1] -> user region)
    # 0x05000: PD_1    (PDPT_1[0])
    # 0x06000: PT_1    (PD_1[0])
    # 0x07000: PDPT_K  (PML4[511] -> kernel space)
    # 0x08000: PD_K    (PDPT_K[0])
    # 0x09000: PT_K    (PD_K[0])
    # 0x0A000: PDPT_2  (PML4[100] -> user mid-range)
    # 0x0B000: PD_2    (PDPT_2[200])

    PML4   = 0x00000
    PDPT_0 = 0x01000
    PD_0   = 0x02000
    PT_0   = 0x03000
    PDPT_1 = 0x04000
    PD_1   = 0x05000
    PT_1   = 0x06000
    PDPT_K = 0x07000
    PD_K   = 0x08000
    PT_K   = 0x09000
    PDPT_2 = 0x0A000
    PD_2   = 0x0B000

    # ====== PML4 ======
    write_entry(PML4, 0,   make_entry(PDPT_0, present=True, rw=True, us=False))
    write_entry(PML4, 1,   make_entry(PDPT_1, present=True, rw=True, us=True))
    write_entry(PML4, 100, make_entry(PDPT_2, present=True, rw=True, us=True))
    write_entry(PML4, 511, make_entry(PDPT_K, present=True, rw=True, us=False))

    # ====== PDPT_0 -> PD_0 ======
    write_entry(PDPT_0, 0, make_entry(PD_0, present=True, rw=True, us=False))

    # ====== PD_0 -> PT_0 ======
    write_entry(PD_0, 0, make_entry(PT_0, present=True, rw=True, us=False))

    # ====== PT_0 (supervisor low-address pages) ======
    # [0]: VA 0x0 -> PA 0x100000, R-X, supervisor (code)
    write_entry(PT_0, 0, make_entry(0x100000, present=True, rw=False, us=False, nx=False))
    # [1]: VA 0x1000 -> PA 0x101000, RW-, supervisor (data)
    write_entry(PT_0, 1, make_entry(0x101000, present=True, rw=True, us=False, nx=True))
    # [2]: not present (zero)
    # [3]: VA 0x3000 -> PA 0x103000, RWX, supervisor -- W+X ANOMALY
    write_entry(PT_0, 3, make_entry(0x103000, present=True, rw=True, us=False, nx=False))

    # ====== PDPT_1 (user region) ======
    # [0] -> PD_1
    write_entry(PDPT_1, 0, make_entry(PD_1, present=True, rw=True, us=True))
    # [1]: 1GB large page -> PA 0x40000000, R--, user
    write_entry(PDPT_1, 1, make_entry(0x40000000, present=True, rw=False, us=True, nx=True, ps=True))

    # ====== PD_1 ======
    # [0] -> PT_1
    write_entry(PD_1, 0, make_entry(PT_1, present=True, rw=True, us=True))
    # [1]: 2MB large page -> PA 0x400000, RW-, user
    write_entry(PD_1, 1, make_entry(0x400000, present=True, rw=True, us=True, nx=True, ps=True))

    # ====== PT_1 ======
    # [5]: VA 0x8000005000 -> PA 0x200000, R-X, user
    write_entry(PT_1, 5, make_entry(0x200000, present=True, rw=False, us=True, nx=False))

    # ====== PDPT_K -> PD_K (kernel space via PML4[511]) ======
    write_entry(PDPT_K, 0, make_entry(PD_K, present=True, rw=True, us=False))

    # ====== PD_K -> PT_K ======
    write_entry(PD_K, 0, make_entry(PT_K, present=True, rw=True, us=False))

    # ====== PT_K (kernel pages at VA 0xFFFFFF8000000000+) ======
    # [0]: R-X, supervisor (kernel code)
    write_entry(PT_K, 0, make_entry(0x300000, present=True, rw=False, us=False, nx=False))
    # [1]: RW-, supervisor (kernel data)
    write_entry(PT_K, 1, make_entry(0x301000, present=True, rw=True, us=False, nx=True))
    # [2]: R--, supervisor (PT has U/S=1 but higher levels have U/S=0 -> effective supervisor)
    write_entry(PT_K, 2, make_entry(0x302000, present=True, rw=False, us=True, nx=True))
    # [3]: RWX, supervisor -- KERNEL W+X ANOMALY
    write_entry(PT_K, 3, make_entry(0x303000, present=True, rw=True, us=False, nx=False))

    # ====== PDPT_2 -> PD_2 (mid-range user via PML4[100]) ======
    write_entry(PDPT_2, 200, make_entry(PD_2, present=True, rw=True, us=True))

    # ====== PD_2 ======
    # [0]: 2MB large page -> PA 0x1000000, RWX, user -- W+X ANOMALY
    write_entry(PD_2, 0, make_entry(0x1000000, present=True, rw=True, us=True, nx=False, ps=True))

    # Write memory.bin
    with open(os.path.join(outdir, "memory.bin"), "wb") as f:
        f.write(memory)

    # Write metadata.json
    metadata = {"cr3": 0, "memory_size": mem_size}
    with open(os.path.join(outdir, "metadata.json"), "w") as f:
        json.dump(metadata, f, indent=2)

    # Write queries.json
    queries = {"addresses": [
        "0x0000000000000000",
        "0x0000000000001000",
        "0x0000000000002000",
        "0x0000000000000abc",
        "0x0000008000005000",
        "0x0000008000200000",
        "0x0000008000200123",
        "0x0000008040000000",
        "0x0000008040abcdef",
        "0xffffff8000000000",
        "0xffffff8000003000",
        "0x0000000000003000",
        "0x0000323200000000",
        "0x0000010000000000",
        "0x0000008000006000"
    ]}
    with open(os.path.join(outdir, "queries.json"), "w") as f:
        json.dump(queries, f, indent=2)


if __name__ == "__main__":
    main()
