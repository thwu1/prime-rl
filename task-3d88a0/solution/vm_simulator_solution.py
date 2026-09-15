#!/usr/bin/env python3
"""
x86_64 Virtual Memory Subsystem Simulator — reference solution.

Implements:
  - PhysicalMemory: frame-level physical RAM simulation
  - VirtualMemoryManager: 4-level (PML4/PDPT/PD/PT) page table management
      with 4KB, 2MB, and 1GB page support
  - HeapAllocator: first-fit allocator with boundary-tag coalescing
"""

import struct

PAGE_SIZE = 4096
PAGE_SHIFT = 12
ENTRIES_PER_TABLE = 512

# ── Page table entry flags ──────────────────────────────────────────────────
PTE_PRESENT       = 1 << 0
PTE_WRITABLE      = 1 << 1
PTE_USER          = 1 << 2
PTE_WRITE_THROUGH = 1 << 3
PTE_CACHE_DISABLE = 1 << 4
PTE_ACCESSED      = 1 << 5
PTE_DIRTY         = 1 << 6
PTE_HUGE_PAGE     = 1 << 7
PTE_GLOBAL        = 1 << 8
PTE_NO_EXECUTE    = 1 << 63

# Masks for extracting physical addresses from page table entries
ADDR_MASK         = 0x000FFFFFFFFFF000   # bits 12-51
HUGE_2MB_ADDR     = 0x000FFFFFFFE00000   # bits 21-51
HUGE_1GB_ADDR     = 0x000FFFFFC0000000   # bits 30-51
FLAG_BITS_MASK    = 0xFFF                # bits 0-11


# ── Exceptions ──────────────────────────────────────────────────────────────
class PageFault(Exception):
    """Raised when a virtual address translation fails."""
    def __init__(self, virt_addr: int, reason: str):
        self.virt_addr = virt_addr
        self.reason = reason
        super().__init__(f"Page fault at {virt_addr:#018x}: {reason}")


# ── Helper functions ────────────────────────────────────────────────────────
def is_canonical(addr: int) -> bool:
    addr = addr & 0xFFFFFFFFFFFFFFFF
    bit47 = (addr >> 47) & 1
    upper = (addr >> 48) & 0xFFFF
    return upper == (0xFFFF if bit47 else 0x0000)


def decompose_virtual_address(virt_addr: int) -> tuple:
    virt_addr = virt_addr & 0xFFFFFFFFFFFFFFFF
    if not is_canonical(virt_addr):
        raise ValueError(f"Non-canonical address: {virt_addr:#018x}")
    offset   = virt_addr & 0xFFF
    pt_idx   = (virt_addr >> 12) & 0x1FF
    pd_idx   = (virt_addr >> 21) & 0x1FF
    pdpt_idx = (virt_addr >> 30) & 0x1FF
    pml4_idx = (virt_addr >> 39) & 0x1FF
    return (pml4_idx, pdpt_idx, pd_idx, pt_idx, offset)


# ── Physical Memory ────────────────────────────────────────────────────────
class PhysicalMemory:
    def __init__(self, size_bytes: int):
        if size_bytes % PAGE_SIZE != 0:
            raise ValueError("size must be a multiple of PAGE_SIZE")
        self._mem = bytearray(size_bytes)
        self._total = size_bytes // PAGE_SIZE
        self._free = list(range(self._total - 1, -1, -1))
        self._alloc = set()

    def allocate_frame(self) -> int:
        if not self._free:
            raise MemoryError("No free physical frames")
        idx = self._free.pop()
        self._alloc.add(idx)
        a = idx * PAGE_SIZE
        self._mem[a:a + PAGE_SIZE] = b'\x00' * PAGE_SIZE
        return a

    def free_frame(self, addr: int):
        if addr % PAGE_SIZE:
            raise ValueError(f"Not frame-aligned: {addr:#x}")
        idx = addr // PAGE_SIZE
        if idx not in self._alloc:
            raise ValueError(f"Frame at {addr:#x} not allocated")
        self._alloc.discard(idx)
        self._free.append(idx)

    def read(self, addr: int, size: int) -> bytes:
        return bytes(self._mem[addr:addr + size])

    def write(self, addr: int, data: bytes):
        self._mem[addr:addr + len(data)] = data

    def read_u64(self, addr: int) -> int:
        return struct.unpack('<Q', self._mem[addr:addr + 8])[0]

    def write_u64(self, addr: int, val: int):
        struct.pack_into('<Q', self._mem, addr, val & 0xFFFFFFFFFFFFFFFF)

    @property
    def allocated_frame_count(self) -> int:
        return len(self._alloc)

    @property
    def total_frame_count(self) -> int:
        return self._total


# ── Virtual Memory Manager ─────────────────────────────────────────────────
class VirtualMemoryManager:
    def __init__(self, phys_mem: PhysicalMemory):
        self._phys = phys_mem
        self._cr3 = phys_mem.allocate_frame()
        self._pf_count = 0

    @property
    def cr3(self) -> int:
        return self._cr3

    @property
    def page_fault_count(self) -> int:
        return self._pf_count

    def _rpte(self, tbl: int, idx: int) -> int:
        return self._phys.read_u64(tbl + idx * 8)

    def _wpte(self, tbl: int, idx: int, val: int):
        self._phys.write_u64(tbl + idx * 8, val)

    @staticmethod
    def _effective(entries: list) -> int:
        leaf = entries[-1]
        eff = leaf & FLAG_BITS_MASK
        if not all(e & PTE_WRITABLE for e in entries):
            eff &= ~PTE_WRITABLE
        if not all(e & PTE_USER for e in entries):
            eff &= ~PTE_USER
        if any(e & PTE_NO_EXECUTE for e in entries):
            eff |= PTE_NO_EXECUTE
        return eff

    def translate(self, virt_addr: int) -> tuple:
        virt_addr &= 0xFFFFFFFFFFFFFFFF
        if not is_canonical(virt_addr):
            self._pf_count += 1
            raise PageFault(virt_addr, "non-canonical address")

        pml4_i, pdpt_i, pd_i, pt_i, off = decompose_virtual_address(virt_addr)
        entries = []

        # L4 — PML4
        e = self._rpte(self._cr3, pml4_i)
        if not (e & PTE_PRESENT):
            self._pf_count += 1
            raise PageFault(virt_addr, "PML4 entry not present")
        e |= PTE_ACCESSED
        self._wpte(self._cr3, pml4_i, e)
        entries.append(e)
        nxt = e & ADDR_MASK

        # L3 — PDPT
        e = self._rpte(nxt, pdpt_i)
        if not (e & PTE_PRESENT):
            self._pf_count += 1
            raise PageFault(virt_addr, "PDPT entry not present")
        e |= PTE_ACCESSED
        self._wpte(nxt, pdpt_i, e)
        entries.append(e)
        if e & PTE_HUGE_PAGE:
            pa = (e & HUGE_1GB_ADDR) | (virt_addr & 0x3FFFFFFF)
            return (pa, self._effective(entries))
        nxt = e & ADDR_MASK

        # L2 — PD
        e = self._rpte(nxt, pd_i)
        if not (e & PTE_PRESENT):
            self._pf_count += 1
            raise PageFault(virt_addr, "PD entry not present")
        e |= PTE_ACCESSED
        self._wpte(nxt, pd_i, e)
        entries.append(e)
        if e & PTE_HUGE_PAGE:
            pa = (e & HUGE_2MB_ADDR) | (virt_addr & 0x1FFFFF)
            return (pa, self._effective(entries))
        nxt = e & ADDR_MASK

        # L1 — PT
        e = self._rpte(nxt, pt_i)
        if not (e & PTE_PRESENT):
            self._pf_count += 1
            raise PageFault(virt_addr, "PT entry not present")
        e |= PTE_ACCESSED
        self._wpte(nxt, pt_i, e)
        entries.append(e)

        pa = (e & ADDR_MASK) | off
        return (pa, self._effective(entries))

    def _ensure(self, parent: int, idx: int, flags: int) -> int:
        e = self._rpte(parent, idx)
        if e & PTE_PRESENT:
            changed = e
            if flags & PTE_WRITABLE:
                changed |= PTE_WRITABLE
            if flags & PTE_USER:
                changed |= PTE_USER
            if changed != e:
                self._wpte(parent, idx, changed)
            return e & ADDR_MASK
        tbl = self._phys.allocate_frame()
        iflags = PTE_PRESENT
        if flags & PTE_WRITABLE:
            iflags |= PTE_WRITABLE
        if flags & PTE_USER:
            iflags |= PTE_USER
        self._wpte(parent, idx, tbl | iflags)
        return tbl

    def map_page(self, virt: int, phys: int, flags: int):
        virt &= 0xFFFFFFFFFFFFFFFF
        if not is_canonical(virt):
            raise ValueError(f"Non-canonical: {virt:#018x}")
        if virt % PAGE_SIZE:
            raise ValueError("virt not page-aligned")
        if phys % PAGE_SIZE:
            raise ValueError("phys not page-aligned")
        pml4_i, pdpt_i, pd_i, pt_i, _ = decompose_virtual_address(virt)
        pdpt = self._ensure(self._cr3, pml4_i, flags)
        pd   = self._ensure(pdpt, pdpt_i, flags)
        pt   = self._ensure(pd, pd_i, flags)
        if self._rpte(pt, pt_i) & PTE_PRESENT:
            raise ValueError(f"Already mapped: {virt:#018x}")
        self._wpte(pt, pt_i, (phys & ADDR_MASK) | (flags & ~ADDR_MASK))

    def unmap_page(self, virt: int):
        virt &= 0xFFFFFFFFFFFFFFFF
        if not is_canonical(virt):
            raise ValueError(f"Non-canonical: {virt:#018x}")
        pml4_i, pdpt_i, pd_i, pt_i, _ = decompose_virtual_address(virt)
        e = self._rpte(self._cr3, pml4_i)
        if not (e & PTE_PRESENT):
            raise ValueError(f"Not mapped: {virt:#018x}")
        e2 = self._rpte(e & ADDR_MASK, pdpt_i)
        if not (e2 & PTE_PRESENT):
            raise ValueError(f"Not mapped: {virt:#018x}")
        if e2 & PTE_HUGE_PAGE:
            raise ValueError("Cannot unmap 4KB from huge page")
        e3 = self._rpte(e2 & ADDR_MASK, pd_i)
        if not (e3 & PTE_PRESENT):
            raise ValueError(f"Not mapped: {virt:#018x}")
        if e3 & PTE_HUGE_PAGE:
            raise ValueError("Cannot unmap 4KB from huge page")
        pt_phys = e3 & ADDR_MASK
        if not (self._rpte(pt_phys, pt_i) & PTE_PRESENT):
            raise ValueError(f"Not mapped: {virt:#018x}")
        self._wpte(pt_phys, pt_i, 0)

    def map_huge_page_2mb(self, virt: int, phys: int, flags: int):
        virt &= 0xFFFFFFFFFFFFFFFF
        MB2 = 2 * 1024 * 1024
        if not is_canonical(virt):
            raise ValueError(f"Non-canonical: {virt:#018x}")
        if virt % MB2:
            raise ValueError("virt not 2MB-aligned")
        if phys % MB2:
            raise ValueError("phys not 2MB-aligned")
        pml4_i, pdpt_i, pd_i, _, _ = decompose_virtual_address(virt)
        pdpt = self._ensure(self._cr3, pml4_i, flags)
        pd   = self._ensure(pdpt, pdpt_i, flags)
        if self._rpte(pd, pd_i) & PTE_PRESENT:
            raise ValueError(f"Already mapped: {virt:#018x}")
        self._wpte(pd, pd_i, (phys & HUGE_2MB_ADDR) | flags | PTE_HUGE_PAGE)

    def map_huge_page_1gb(self, virt: int, phys: int, flags: int):
        virt &= 0xFFFFFFFFFFFFFFFF
        GB1 = 1024 * 1024 * 1024
        if not is_canonical(virt):
            raise ValueError(f"Non-canonical: {virt:#018x}")
        if virt % GB1:
            raise ValueError("virt not 1GB-aligned")
        if phys % GB1:
            raise ValueError("phys not 1GB-aligned")
        pml4_i, pdpt_i, _, _, _ = decompose_virtual_address(virt)
        pdpt = self._ensure(self._cr3, pml4_i, flags)
        if self._rpte(pdpt, pdpt_i) & PTE_PRESENT:
            raise ValueError(f"Already mapped: {virt:#018x}")
        self._wpte(pdpt, pdpt_i, (phys & HUGE_1GB_ADDR) | flags | PTE_HUGE_PAGE)

    def read_virtual(self, virt: int, size: int) -> bytes:
        out = bytearray()
        rem = size
        cur = virt & 0xFFFFFFFFFFFFFFFF
        while rem > 0:
            pa, _ = self.translate(cur)
            chunk = min(rem, PAGE_SIZE - (cur & 0xFFF))
            out.extend(self._phys.read(pa, chunk))
            rem -= chunk
            cur = (cur + chunk) & 0xFFFFFFFFFFFFFFFF
        return bytes(out)

    def write_virtual(self, virt: int, data: bytes):
        rem = len(data)
        cur = virt & 0xFFFFFFFFFFFFFFFF
        off = 0
        while rem > 0:
            pa, fl = self.translate(cur)
            if not (fl & PTE_WRITABLE):
                raise PermissionError(f"Not writable: {cur:#018x}")
            self._set_dirty(cur)
            chunk = min(rem, PAGE_SIZE - (cur & 0xFFF))
            self._phys.write(pa, data[off:off + chunk])
            rem -= chunk
            cur = (cur + chunk) & 0xFFFFFFFFFFFFFFFF
            off += chunk

    def _set_dirty(self, virt: int):
        pml4_i, pdpt_i, pd_i, pt_i, _ = decompose_virtual_address(virt)
        e = self._rpte(self._cr3, pml4_i)
        nxt = e & ADDR_MASK
        e2 = self._rpte(nxt, pdpt_i)
        if e2 & PTE_HUGE_PAGE:
            self._wpte(nxt, pdpt_i, e2 | PTE_DIRTY)
            return
        nxt2 = e2 & ADDR_MASK
        e3 = self._rpte(nxt2, pd_i)
        if e3 & PTE_HUGE_PAGE:
            self._wpte(nxt2, pd_i, e3 | PTE_DIRTY)
            return
        nxt3 = e3 & ADDR_MASK
        e4 = self._rpte(nxt3, pt_i)
        self._wpte(nxt3, pt_i, e4 | PTE_DIRTY)


# ── Heap Allocator ─────────────────────────────────────────────────────────
class HeapAllocator:
    """
    First-fit allocator with boundary-tag coalescing.

    Block layout (all sizes in bytes):
      [size:u64 | flags:u64]  header  (16 bytes)
      [... payload ...]                (variable, >= 8 bytes)
      [size:u64]              footer  (8 bytes)

    total block size = header + payload + footer;  always a multiple of 16.
    flags bit 0: 1 = allocated, 0 = free.
    """
    HEADER  = 16
    FOOTER  = 8
    OVERHEAD = HEADER + FOOTER       # 24
    MIN_PAY  = 8
    MIN_BLK  = 32                    # round_up(24+8, 16) = 32

    def __init__(self, vmm: VirtualMemoryManager, heap_start: int,
                 initial_pages: int = 4):
        if heap_start % 16:
            raise ValueError("heap_start must be 16-byte aligned")
        self._vmm = vmm
        self._start = heap_start
        self._end = heap_start
        for _ in range(initial_pages):
            self._map_page()
        total = self._end - self._start
        self._whdr(self._start, total, False)
        self._wftr(self._start, total)

    def _map_page(self):
        f = self._vmm._phys.allocate_frame()
        self._vmm.map_page(self._end, f, PTE_PRESENT | PTE_WRITABLE)
        self._end += PAGE_SIZE

    @staticmethod
    def _rnd(n: int) -> int:
        return (n + 15) & ~15

    def _whdr(self, addr: int, size: int, alloc: bool):
        self._vmm.write_virtual(addr, struct.pack('<QQ', size, 1 if alloc else 0))

    def _rhdr(self, addr: int) -> tuple:
        d = self._vmm.read_virtual(addr, 16)
        sz, fl = struct.unpack('<QQ', d)
        return sz, bool(fl & 1)

    def _wftr(self, block: int, size: int):
        self._vmm.write_virtual(block + size - self.FOOTER, struct.pack('<Q', size))

    def _rftr_before(self, addr: int) -> int:
        d = self._vmm.read_virtual(addr - self.FOOTER, 8)
        return struct.unpack('<Q', d)[0]

    def malloc(self, size: int) -> int:
        if size <= 0:
            raise ValueError("size must be positive")
        pay = max(size, self.MIN_PAY)
        need = self._rnd(self.OVERHEAD + pay)

        a = self._start
        while a < self._end:
            sz, used = self._rhdr(a)
            if sz == 0:
                break
            if not used and sz >= need:
                return self._alloc_block(a, sz, need)
            a += sz

        self._grow(need)
        return self.malloc(size)

    def _alloc_block(self, addr: int, blksz: int, need: int) -> int:
        rem = blksz - need
        if rem >= self.MIN_BLK:
            self._whdr(addr, need, True)
            self._wftr(addr, need)
            ra = addr + need
            self._whdr(ra, rem, False)
            self._wftr(ra, rem)
        else:
            need = blksz
            self._whdr(addr, need, True)
            self._wftr(addr, need)
        return addr + self.HEADER

    def _grow(self, need: int):
        pages = (need + PAGE_SIZE - 1) // PAGE_SIZE
        old = self._end
        for _ in range(pages):
            self._map_page()
        ns = self._end - old

        if old > self._start:
            ps = self._rftr_before(old)
            pa = old - ps
            _, pu = self._rhdr(pa)
            if not pu:
                c = ps + ns
                self._whdr(pa, c, False)
                self._wftr(pa, c)
                return
        self._whdr(old, ns, False)
        self._wftr(old, ns)

    def free(self, addr: int):
        ba = addr - self.HEADER
        sz, used = self._rhdr(ba)
        if not used:
            raise ValueError(f"Double free at {addr:#x}")
        self._whdr(ba, sz, False)
        self._wftr(ba, sz)

        # forward coalesce
        na = ba + sz
        if na < self._end:
            nsz, nu = self._rhdr(na)
            if not nu:
                sz += nsz
                self._whdr(ba, sz, False)
                self._wftr(ba, sz)

        # backward coalesce
        if ba > self._start:
            ps = self._rftr_before(ba)
            pa = ba - ps
            _, pu = self._rhdr(pa)
            if not pu:
                c = ps + sz
                self._whdr(pa, c, False)
                self._wftr(pa, c)

    @property
    def free_block_count(self) -> int:
        n = 0
        a = self._start
        while a < self._end:
            sz, used = self._rhdr(a)
            if sz == 0:
                break
            if not used:
                n += 1
            a += sz
        return n

    @property
    def total_heap_size(self) -> int:
        return self._end - self._start
