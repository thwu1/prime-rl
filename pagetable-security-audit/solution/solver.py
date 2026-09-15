#!/usr/bin/env python3
"""
Reference solution for x86-64 page table forensics & security hardening.

Discovers CR3 among decoys, diagnoses 4 corruption types via ELF analysis
and crash report cross-referencing, repairs the dump, audits W^X violations,
creates a hardened dump with W^X eliminated, and evaluates security posture.

"""
import struct
import json
import os
import re
import subprocess


# ============================================================
# Low-level PTE helpers
# ============================================================

def read_entry(mem, pa):
    if pa + 8 > len(mem):
        return None
    return struct.unpack_from('<Q', mem, pa)[0]

def entry_present(e): return bool(e & 1)
def entry_rw(e):      return bool(e & 2)
def entry_us(e):      return bool(e & 4)
def entry_ps(e):      return bool(e & 0x80)
def entry_nx(e):      return bool(e & (1 << 63))
def phys_4k(e):       return e & 0x000FFFFFFFFFF000
def phys_2m(e):       return e & 0x000FFFFFFFE00000
def phys_1g(e):       return e & 0x000FFFFFC0000000

def sign_ext(addr):
    return addr | 0xFFFF000000000000 if addr & (1 << 47) else addr

def fmt(addr):
    if addr < 0:
        addr += 1 << 64
    return f"0x{addr:016x}"


# ============================================================
# Page table walking
# ============================================================

def translate_va(mem, cr3, va):
    va48 = va & 0x0000FFFFFFFFFFFF
    idx = [(va48 >> s) & 0x1FF for s in (39, 30, 21, 12)]
    rw_a, us_a, nx_a = [], [], []

    pml4e = read_entry(mem, cr3 + idx[0] * 8)
    if pml4e is None or not entry_present(pml4e):
        return None
    rw_a.append(entry_rw(pml4e)); us_a.append(entry_us(pml4e)); nx_a.append(entry_nx(pml4e))

    pdpte = read_entry(mem, phys_4k(pml4e) + idx[1] * 8)
    if pdpte is None or not entry_present(pdpte):
        return None
    rw_a.append(entry_rw(pdpte)); us_a.append(entry_us(pdpte)); nx_a.append(entry_nx(pdpte))
    if entry_ps(pdpte):
        return phys_1g(pdpte) + (va48 & 0x3FFFFFFF), 1 << 30, all(rw_a), not any(nx_a), all(us_a)

    pde = read_entry(mem, phys_4k(pdpte) + idx[2] * 8)
    if pde is None or not entry_present(pde):
        return None
    rw_a.append(entry_rw(pde)); us_a.append(entry_us(pde)); nx_a.append(entry_nx(pde))
    if entry_ps(pde):
        return phys_2m(pde) + (va48 & 0x1FFFFF), 1 << 21, all(rw_a), not any(nx_a), all(us_a)

    pte = read_entry(mem, phys_4k(pde) + idx[3] * 8)
    if pte is None or not entry_present(pte):
        return None
    rw_a.append(entry_rw(pte)); us_a.append(entry_us(pte)); nx_a.append(entry_nx(pte))
    return phys_4k(pte) + (va48 & 0xFFF), 4096, all(rw_a), not any(nx_a), all(us_a)


def walk_to_pte(mem, cr3, va):
    va48 = va & 0x0000FFFFFFFFFFFF
    idx = [(va48 >> s) & 0x1FF for s in (39, 30, 21, 12)]

    pml4e = read_entry(mem, cr3 + idx[0] * 8)
    if pml4e is None or not entry_present(pml4e):
        return None
    pdpte = read_entry(mem, phys_4k(pml4e) + idx[1] * 8)
    if pdpte is None or not entry_present(pdpte) or entry_ps(pdpte):
        return None
    pde = read_entry(mem, phys_4k(pdpte) + idx[2] * 8)
    if pde is None or not entry_present(pde) or entry_ps(pde):
        return None
    pt_base = phys_4k(pde)
    off = pt_base + idx[3] * 8
    val = read_entry(mem, off)
    if val is None:
        return None
    return off, val


def full_walk(mem, cr3):
    regions = []
    for i4 in range(512):
        e4 = read_entry(mem, cr3 + i4 * 8)
        if e4 is None or not entry_present(e4):
            continue
        rw4, us4, nx4 = entry_rw(e4), entry_us(e4), entry_nx(e4)
        for i3 in range(512):
            e3 = read_entry(mem, phys_4k(e4) + i3 * 8)
            if e3 is None or not entry_present(e3):
                continue
            rw3, us3, nx3 = entry_rw(e3), entry_us(e3), entry_nx(e3)
            if entry_ps(e3):
                raw = (i4 << 39) | (i3 << 30)
                regions.append((sign_ext(raw), phys_1g(e3), 1 << 30,
                                rw4 and rw3, not (nx4 or nx3), us4 and us3))
                continue
            for i2 in range(512):
                e2 = read_entry(mem, phys_4k(e3) + i2 * 8)
                if e2 is None or not entry_present(e2):
                    continue
                rw2, us2, nx2 = entry_rw(e2), entry_us(e2), entry_nx(e2)
                if entry_ps(e2):
                    raw = (i4 << 39) | (i3 << 30) | (i2 << 21)
                    regions.append((sign_ext(raw), phys_2m(e2), 1 << 21,
                                    rw4 and rw3 and rw2,
                                    not (nx4 or nx3 or nx2),
                                    us4 and us3 and us2))
                    continue
                for i1 in range(512):
                    e1 = read_entry(mem, phys_4k(e2) + i1 * 8)
                    if e1 is None or not entry_present(e1):
                        continue
                    rw1, us1, nx1 = entry_rw(e1), entry_us(e1), entry_nx(e1)
                    raw = (i4 << 39) | (i3 << 30) | (i2 << 21) | (i1 << 12)
                    regions.append((sign_ext(raw), phys_4k(e1), 4096,
                                    rw4 and rw3 and rw2 and rw1,
                                    not (nx4 or nx3 or nx2 or nx1),
                                    us4 and us3 and us2 and us1))
    regions.sort(key=lambda r: r[0] % (2**64))
    return regions


# ============================================================
# ELF parsing (extract kernel section/program header info)
# ============================================================

def parse_kernel_elf(path):
    """Parse minimal ELF64 to extract section and program header info."""
    with open(path, 'rb') as f:
        data = f.read()

    # ELF header
    assert data[:4] == b'\x7fELF', "Not an ELF file"
    (e_phoff, e_shoff) = struct.unpack_from('<QQ', data, 32)
    (e_phentsize, e_phnum, e_shentsize, e_shnum, e_shstrndx) = \
        struct.unpack_from('<HHHHH', data, 54)

    # Read shstrtab
    shstr_off = e_shoff + e_shstrndx * e_shentsize
    (str_off, str_sz) = struct.unpack_from('<QQ', data, shstr_off + 24)
    strtab = data[str_off:str_off + str_sz]

    def get_str(idx):
        end = strtab.index(b'\0', idx)
        return strtab[idx:end].decode()

    # Parse sections
    sections = []
    for i in range(e_shnum):
        off = e_shoff + i * e_shentsize
        (sh_name, sh_type, sh_flags, sh_addr, sh_offset, sh_size) = \
            struct.unpack_from('<IIQQqq', data, off)
        if sh_type == 0:
            continue
        name = get_str(sh_name)
        sections.append({
            'name': name,
            'addr': sh_addr,
            'size': sh_size,
            'flags': sh_flags,
            'executable': bool(sh_flags & 4),   # SHF_EXECINSTR
            'writable': bool(sh_flags & 1),      # SHF_WRITE
            'alloc': bool(sh_flags & 2),         # SHF_ALLOC
        })

    # Parse program headers  (PF_R=4, PF_W=2, PF_X=1)
    segments = []
    for i in range(e_phnum):
        off = e_phoff + i * 56
        (p_type, p_flags, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz) = \
            struct.unpack_from('<IIQQQqq', data, off)
        if p_type != 1:  # PT_LOAD
            continue
        segments.append({
            'vaddr': p_vaddr,
            'paddr': p_paddr,
            'memsz': p_memsz,
            'executable': bool(p_flags & 1),
            'writable': bool(p_flags & 2),
        })

    return sections, segments


def parse_kernel_elf_with_readelf(path):
    """Fallback: use readelf to extract program header info."""
    segments = []
    try:
        out = subprocess.check_output(['readelf', '-l', path], text=True)
        for line in out.split('\n'):
            line = line.strip()
            if not line.startswith('LOAD'):
                continue
            parts = line.split()
            if len(parts) >= 6:
                offset = int(parts[1], 16)
                vaddr = int(parts[2], 16)
                paddr = int(parts[3], 16)
                filesz = int(parts[4], 16)
                memsz = int(parts[5], 16)
                flags_str = parts[6] if len(parts) > 6 else ''
                segments.append({
                    'vaddr': vaddr,
                    'paddr': paddr,
                    'memsz': memsz,
                    'executable': 'E' in flags_str,
                    'writable': 'W' in flags_str,
                })
    except Exception:
        pass
    return segments


# ============================================================
# CR3 discovery
# ============================================================

def find_cr3(mem):
    known = [
        (0x0000000000000000, 0x0000000000100000),
        (0x0000008040000000, 0x0000000040000000),
    ]
    for addr in range(0, len(mem), 4096):
        ok = True
        for va, pa in known:
            r = translate_va(mem, addr, va)
            if r is None or r[0] != pa:
                ok = False
                break
        if ok:
            return addr
    return None


# ============================================================
# Crash report parsing
# ============================================================

def parse_user_snapshot(text):
    snap = {}
    in_pre = False
    for line in text.split('\n'):
        if 'PRE-CRASH' in line:
            in_pre = True
            continue
        if in_pre and line.startswith('---'):
            break
        if in_pre:
            m = re.search(r'VA\s+(0x[0-9a-fA-F]+)\s*->\s*PA\s+(0x[0-9a-fA-F]+)', line)
            if m:
                snap[int(m.group(1), 16)] = int(m.group(2), 16)
            m2 = re.search(r'VA\s+(0x[0-9a-fA-F]+)\s*->\s*\[not mapped\]', line)
            if m2:
                snap[int(m2.group(1), 16)] = None
    return snap


# ============================================================
# Security posture metrics
# ============================================================

def count_wx(regions):
    return sum(1 for _, _, _, w, x, _ in regions if w and x)

def count_privesc(regions, kern_pa_ranges):
    """Count user pages with write access to kernel physical addresses."""
    count = 0
    for va, pa, sz, w, x, u in regions:
        if u and w:
            for kpa_start, kpa_end in kern_pa_ranges:
                if pa < kpa_end and pa + sz > kpa_start:
                    count += 1
                    break
    return count

def count_unmapped_critical(mem, cr3, segments):
    """Count kernel ELF segments that should be present but aren't mapped."""
    count = 0
    for seg in segments:
        va = seg['vaddr']
        r = translate_va(mem, cr3, va)
        if r is None:
            count += 1
    return count


# ============================================================
# Main
# ============================================================

def main():
    memory = bytearray(open("/app/forensics/memory.bin", "rb").read())
    crash_text = open("/app/forensics/crash_report.log").read()

    # Parse kernel ELF for expected layout
    segments = None
    elf_path = "/app/forensics/kernel.elf"
    if os.path.isfile(elf_path):
        try:
            sections, segments = parse_kernel_elf(elf_path)
        except Exception:
            segments = None

    if segments is None or len(segments) == 0:
        # Try readelf as second fallback
        if os.path.isfile(elf_path):
            segments = parse_kernel_elf_with_readelf(elf_path)

    if segments is None or len(segments) == 0:
        # Final fallback: derive kernel layout from crash report and memory
        # analysis. The crash report identifies kernel .text at VA 0xFFFFFF8000000000
        # and .data at VA 0xFFFFFF8000001000. We scan PT_kern for all kernel mappings.
        # From the page fault and ELF analysis we know the kernel maps 4 contiguous
        # pages starting at VA 0xFFFFFF8000000000.
        segments = [
            {'vaddr': 0xFFFFFF8000000000, 'paddr': 0x300000, 'memsz': 0x1000,
             'executable': True, 'writable': False},
            {'vaddr': 0xFFFFFF8000001000, 'paddr': 0x301000, 'memsz': 0x1000,
             'executable': False, 'writable': True},
            {'vaddr': 0xFFFFFF8000002000, 'paddr': 0x302000, 'memsz': 0x1000,
             'executable': False, 'writable': False},
            {'vaddr': 0xFFFFFF8000003000, 'paddr': 0x303000, 'memsz': 0x1000,
             'executable': False, 'writable': True},
        ]

    # Build kernel PA ranges from program headers
    kern_pa_ranges = [(s['paddr'], s['paddr'] + s['memsz']) for s in segments]

    # Build expected kernel mappings
    kern_expected = [
        {'va': seg['vaddr'], 'pa': seg['paddr'],
         'executable': seg['executable'], 'writable': seg['writable']}
        for seg in segments
    ]

    # ---- Step 1: Save corrupted state for posture analysis ----
    corrupted_mem = bytes(memory)  # snapshot before repairs

    # ---- Step 2: Discover CR3 ----
    cr3 = find_cr3(memory)
    assert cr3 is not None, "Failed to discover active PML4"

    # ---- Step 3: Corrupted state metrics ----
    corrupted_regions = full_walk(bytearray(corrupted_mem), cr3)
    corrupted_wx = count_wx(corrupted_regions)
    corrupted_privesc = count_privesc(corrupted_regions, kern_pa_ranges)
    corrupted_unmapped = count_unmapped_critical(bytearray(corrupted_mem), cr3, segments)

    # ---- Step 4: Identify corruptions using ELF + crash report ----
    corruptions = []
    user_snap = parse_user_snapshot(crash_text)

    # 4a: Check kernel entries against ELF-derived expectations
    for exp in kern_expected:
        va = exp['va']
        pte_info = walk_to_pte(memory, cr3, va)
        if pte_info is None:
            continue
        pte_off, pte_val = pte_info
        result = translate_va(memory, cr3, va)

        if result is None:
            # Should be present but isn't -> present_cleared
            correct = 1  # present
            if exp['writable']:
                correct |= 2
            correct |= (exp['pa'] & 0x000FFFFFFFFFF000)
            if not exp['executable']:
                correct |= (1 << 63)
            corruptions.append({
                'byte_offset': pte_off,
                'corrupted_value': fmt(pte_val),
                'corrected_value': fmt(correct),
                'virtual_address': fmt(va),
                'corruption_type': 'present_cleared',
            })
            struct.pack_into('<Q', memory, pte_off, correct)
        else:
            pa, ps, w, x, u = result
            if exp['executable'] and not x:
                # NX incorrectly set
                correct = pte_val & ~(1 << 63)
                corruptions.append({
                    'byte_offset': pte_off,
                    'corrupted_value': fmt(pte_val),
                    'corrected_value': fmt(correct),
                    'virtual_address': fmt(va),
                    'corruption_type': 'nx_injected',
                })
                struct.pack_into('<Q', memory, pte_off, correct)

    # 4b: Check user entries against pre-crash snapshot
    for va, expected_pa in user_snap.items():
        if expected_pa is not None:
            pte_info = walk_to_pte(memory, cr3, va)
            if pte_info is None:
                continue
            pte_off, pte_val = pte_info
            actual_pa = phys_4k(pte_val)
            if actual_pa != expected_pa:
                correct = (pte_val & ~0x000FFFFFFFFFF000) | (expected_pa & 0x000FFFFFFFFFF000)
                corruptions.append({
                    'byte_offset': pte_off,
                    'corrupted_value': fmt(pte_val),
                    'corrected_value': fmt(correct),
                    'virtual_address': fmt(va),
                    'corruption_type': 'address_bitflip',
                })
                struct.pack_into('<Q', memory, pte_off, correct)
        else:
            pte_info = walk_to_pte(memory, cr3, va)
            if pte_info is None:
                continue
            pte_off, pte_val = pte_info
            if entry_present(pte_val):
                corruptions.append({
                    'byte_offset': pte_off,
                    'corrupted_value': fmt(pte_val),
                    'corrected_value': fmt(0),
                    'virtual_address': fmt(va),
                    'corruption_type': 'unauthorized_mapping',
                })
                struct.pack_into('<Q', memory, pte_off, 0)

    corruptions.sort(key=lambda c: c['byte_offset'])

    # ---- Step 5: W^X audit on repaired state ----
    repaired_regions = full_walk(memory, cr3)
    audit = []
    for va, pa, sz, w, x, u in repaired_regions:
        if w and x:
            audit.append({
                'virtual_address': fmt(va),
                'physical_address': fmt(pa),
                'page_size': sz,
                'writable': True,
                'executable': True,
                'user_accessible': u,
            })

    repaired_wx = count_wx(repaired_regions)
    repaired_privesc = count_privesc(repaired_regions, kern_pa_ranges)
    repaired_unmapped = count_unmapped_critical(memory, cr3, segments)

    # ---- Step 6: Create hardened dump ----
    hardened = bytearray(memory)
    remediation = []

    # Find all W^X violations and apply hardening policy
    for va, pa, sz, w, x, u in repaired_regions:
        if not (w and x):
            continue

        if sz <= 4096:
            # 4KB page: set NX bit
            pte_info = walk_to_pte(hardened, cr3, va)
            if pte_info:
                pte_off, pte_val = pte_info
                new_val = pte_val | (1 << 63)  # set NX
                struct.pack_into('<Q', hardened, pte_off, new_val)
                remediation.append({
                    'virtual_address': fmt(va),
                    'original_permissions': 'RWX',
                    'hardened_permissions': 'RW-',
                    'method': 'nx_set',
                })
        else:
            # Large page: demote to 4KB PT
            va48 = va & 0x0000FFFFFFFFFFFF
            pml4_idx = (va48 >> 39) & 0x1FF
            pdpt_idx = (va48 >> 30) & 0x1FF
            pd_idx = (va48 >> 21) & 0x1FF

            pml4e = read_entry(hardened, cr3 + pml4_idx * 8)
            pdpte = read_entry(hardened, phys_4k(pml4e) + pdpt_idx * 8)

            if sz == (1 << 21):
                # 2MB page -> demote via PD entry
                pd_base = phys_4k(pdpte)
                pd_off = pd_base + pd_idx * 8
                old_pde = read_entry(hardened, pd_off)
                large_pa = phys_2m(old_pde)
                is_rw = entry_rw(old_pde)
                is_us = entry_us(old_pde)

                # Find lowest unused (all-zero) physical page
                new_pt_pa = None
                for pg in range(0, len(hardened), 4096):
                    if hardened[pg:pg+4096] == bytes(4096):
                        new_pt_pa = pg
                        break
                assert new_pt_pa is not None

                # Populate new PT with 512 4KB entries, all RW- NX
                for i in range(512):
                    sub_pa = large_pa + i * 4096
                    flags = 1  # present
                    if is_rw:
                        flags |= 2
                    if is_us:
                        flags |= 4
                    entry = (sub_pa & 0x000FFFFFFFFFF000) | flags | (1 << 63)  # NX
                    struct.pack_into('<Q', hardened, new_pt_pa + i * 8, entry)

                # Update PD entry to point to new PT (no PS bit)
                new_pde = (new_pt_pa & 0x000FFFFFFFFFF000) | 1  # present
                if is_rw:
                    new_pde |= 2
                if is_us:
                    new_pde |= 4
                struct.pack_into('<Q', hardened, pd_off, new_pde)

                remediation.append({
                    'virtual_address': fmt(va),
                    'original_permissions': 'RWX',
                    'hardened_permissions': 'RW-',
                    'method': 'large_page_demotion',
                })

    remediation.sort(key=lambda r: int(r['virtual_address'], 16) % (2**64))

    # ---- Step 7: Hardened state metrics ----
    hardened_regions = full_walk(hardened, cr3)
    hardened_wx = count_wx(hardened_regions)
    hardened_privesc = count_privesc(hardened_regions, kern_pa_ranges)
    hardened_unmapped = count_unmapped_critical(hardened, cr3, segments)

    # ---- Step 8: Write outputs ----
    os.makedirs("/app/output", exist_ok=True)

    with open("/app/output/cr3.json", "w") as f:
        json.dump({"cr3": cr3}, f, indent=2)

    with open("/app/output/corruptions.json", "w") as f:
        json.dump(corruptions, f, indent=2)

    with open("/app/output/repaired.bin", "wb") as f:
        f.write(memory)

    with open("/app/output/audit.json", "w") as f:
        json.dump(audit, f, indent=2)

    with open("/app/output/hardened.bin", "wb") as f:
        f.write(hardened)

    posture = {
        "corrupted": {
            "wx_violations": corrupted_wx,
            "privilege_escalation_paths": corrupted_privesc,
            "unmapped_critical_pages": corrupted_unmapped,
        },
        "repaired": {
            "wx_violations": repaired_wx,
            "privilege_escalation_paths": repaired_privesc,
            "unmapped_critical_pages": repaired_unmapped,
        },
        "hardened": {
            "wx_violations": hardened_wx,
            "privilege_escalation_paths": hardened_privesc,
            "unmapped_critical_pages": hardened_unmapped,
        },
        "remediation": remediation,
    }
    with open("/app/output/posture.json", "w") as f:
        json.dump(posture, f, indent=2)


if __name__ == "__main__":
    main()
