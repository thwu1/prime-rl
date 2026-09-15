#!/usr/bin/env python3
"""
RISC-V Sv39 Page Table Audit Tool — Reference Implementation

Reads RISC-V ELF binaries using riscv64-linux-gnu-readelf, walks the Sv39
page table hierarchy from a physical memory dump, and produces a JSON
audit report of mapping correctness.
"""

import json
import struct
import subprocess
import sys
import os


# ═══════════════════════════════════════════════════════════════════
# ELF segment extraction via readelf
# ═══════════════════════════════════════════════════════════════════

def parse_readelf_segments(elf_path):
    """Use riscv64-linux-gnu-readelf to extract PT_LOAD segments.

    Returns list of dicts: {vaddr: int, memsz: int, flags: str}
    flags is a lowercase string like 'rwx', 'rw', 'rx', 'r'.
    """
    # Try cross-readelf first, then generic readelf
    for cmd in ['riscv64-linux-gnu-readelf', 'readelf']:
        try:
            result = subprocess.run(
                [cmd, '-l', '-W', elf_path],
                capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                break
        except FileNotFoundError:
            continue
    else:
        raise RuntimeError(f"readelf not available to parse {elf_path}")

    segments = []
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if not stripped.startswith('LOAD'):
            continue

        parts = stripped.split()
        # Format: LOAD offset vaddr paddr filesz memsz [flags...] align
        # Flags may be split (e.g. "R E" → two tokens) or merged ("RWE")
        vaddr = int(parts[2], 16)
        memsz = int(parts[5], 16)

        # Flags are between memsz (index 5) and align (last element)
        flag_chars = ''.join(parts[6:-1])

        flags = ''
        if 'R' in flag_chars:
            flags += 'r'
        if 'W' in flag_chars:
            flags += 'w'
        if 'E' in flag_chars:
            flags += 'x'

        segments.append({'vaddr': vaddr, 'memsz': memsz, 'flags': flags})

    return segments


# ═══════════════════════════════════════════════════════════════════
# Sv39 Page Table Walk
# ═══════════════════════════════════════════════════════════════════

def read_pte(mem, paddr):
    """Read a 64-bit little-endian PTE from physical memory."""
    if paddr + 8 > len(mem):
        return None
    return struct.unpack_from('<Q', mem, paddr)[0]


def make_fault(access):
    """Generate a page-fault result for the given access type."""
    prefix = {'read': 'load', 'write': 'store', 'execute': 'fetch'}
    return {'status': 'fault', 'cause': f"{prefix[access]}_page_fault"}


def translate_va(mem, satp_ppn, svade, va, access, priv, mxr, sum_bit):
    """Perform one Sv39 address translation.

    Args:
        mem: Physical memory bytes
        satp_ppn: Root page table physical page number
        svade: If True, raise faults for unset A/D bits
        va: 64-bit virtual address
        access: 'read', 'write', or 'execute'
        priv: 'S' or 'U'
        mxr: Make eXecutable Readable
        sum_bit: Supervisor User Memory access
    """
    # ── Canonical check ──────────────────────────────────────────
    bit38 = (va >> 38) & 1
    upper = va >> 39
    if bit38 == 0 and upper != 0:
        return make_fault(access)
    if bit38 == 1 and upper != (1 << 25) - 1:
        return make_fault(access)

    vpn = [
        (va >> 12) & 0x1FF,  # VPN[0]
        (va >> 21) & 0x1FF,  # VPN[1]
        (va >> 30) & 0x1FF,  # VPN[2]
    ]

    a = satp_ppn * 4096

    for level in range(2, -1, -1):
        pte_addr = a + vpn[level] * 8
        pte = read_pte(mem, pte_addr)
        if pte is None:
            prefix = {'read': 'load', 'write': 'store', 'execute': 'fetch'}
            return {'status': 'fault', 'cause': f"{prefix[access]}_access_fault"}

        v = pte & 1
        r = (pte >> 1) & 1
        w = (pte >> 2) & 1
        x = (pte >> 3) & 1
        u = (pte >> 4) & 1
        a_bit = (pte >> 6) & 1
        d_bit = (pte >> 7) & 1
        ppn = pte >> 10

        # Validity and reserved encoding
        if v == 0 or (r == 0 and w == 1):
            return make_fault(access)

        # Pointer PTE (non-leaf)
        if r == 0 and w == 0 and x == 0:
            if level == 0:
                return make_fault(access)
            a = ppn * 4096
            continue

        # ── Leaf PTE ─────────────────────────────────────────────

        # Superpage alignment
        if level == 2 and (ppn & 0x3FFFF) != 0:
            return make_fault(access)
        if level == 1 and (ppn & 0x1FF) != 0:
            return make_fault(access)

        # Privilege / U-bit checks
        if priv == 'U':
            if u == 0:
                return make_fault(access)
        elif priv == 'S':
            if u == 1:
                if access == 'execute':
                    return make_fault(access)
                if not sum_bit:
                    return make_fault(access)

        # Access-type permission
        if access == 'read':
            if r == 0 and not (mxr and x == 1):
                return make_fault(access)
        elif access == 'write':
            if w == 0:
                return make_fault(access)
        elif access == 'execute':
            if x == 0:
                return make_fault(access)

        # Svade A/D bit checks
        if svade:
            if a_bit == 0:
                return make_fault(access)
            if access == 'write' and d_bit == 0:
                return make_fault(access)

        # ── Compute physical address ─────────────────────────────
        masks = {0: 0xFFF, 1: 0x1FFFFF, 2: 0x3FFFFFFF}
        pa = (ppn << 12) | (va & masks[level])
        sizes = {0: 4096, 1: 2097152, 2: 1073741824}
        return {'status': 'ok', 'pa': hex(pa), 'page_size': sizes[level]}

    return make_fault(access)


def audit_segment(mem, satp_ppn, svade, vaddr, flags, priv, mxr, sum_bit):
    """Audit a segment: check all required access types in order r, w, x.

    Returns the first fault encountered, or the ok result if all pass.
    """
    access_map = {'r': 'read', 'w': 'write', 'x': 'execute'}

    result = None
    for flag_char in flags:
        access = access_map[flag_char]
        result = translate_va(mem, satp_ppn, svade, vaddr, access,
                              priv, mxr, sum_bit)
        if result['status'] == 'fault':
            return result

    return result


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════

def main():
    with open('/app/physmem.bin', 'rb') as f:
        mem = f.read()
    with open('/app/satp.json') as f:
        satp = json.load(f)
    with open('/app/process_table.json') as f:
        procs = json.load(f)

    satp_ppn = satp['satp_ppn']
    svade = satp['svade']

    report = {
        'satp_ppn': satp_ppn,
        'svade': svade,
        'audits': [],
    }

    for proc in procs:
        elf_path = f"/app/binaries/{proc['binary']}"
        segments = parse_readelf_segments(elf_path)

        audit_entry = {
            'binary': proc['binary'],
            'priv': proc['priv'],
            'mxr': proc['mxr'],
            'sum': proc['sum'],
            'segments': [],
        }

        for seg in segments:
            result = audit_segment(
                mem, satp_ppn, svade,
                seg['vaddr'], seg['flags'],
                proc['priv'], proc['mxr'], proc['sum'])

            seg_result = {
                'vaddr': hex(seg['vaddr']),
                'memsz': seg['memsz'],
                'flags': seg['flags'],
            }
            seg_result.update(result)
            audit_entry['segments'].append(seg_result)

        report['audits'].append(audit_entry)

    json.dump(report, sys.stdout, indent=2)
    print()


if __name__ == '__main__':
    main()
