#!/usr/bin/env python3
"""
RISC-V Sv39 Page Table Walk Engine — Reference Solution

Implements the full Sv39 virtual-to-physical address translation
per the RISC-V Privileged Specification (Volume II).
"""

import json
import struct
import sys


def read_pte(mem, paddr):
    """Read a 64-bit little-endian PTE from physical memory."""
    if paddr + 8 > len(mem):
        return None
    return struct.unpack_from('<Q', mem, paddr)[0]


def make_fault(access):
    """Generate a page-fault result for the given access type."""
    prefix = {"read": "load", "write": "store", "execute": "fetch"}
    return {"status": "fault", "cause": f"{prefix[access]}_page_fault"}


def translate(mem, satp_ppn, svade, query):
    """Perform one Sv39 address translation."""
    va = int(query['va'], 16)
    access = query['access']
    priv = query['priv']
    mxr = query.get('mxr', False)
    sum_bit = query.get('sum', False)

    # ── Step 0: Canonical check ──────────────────────────────
    # Sv39: bits[63:39] must all equal bit[38].
    bit38 = (va >> 38) & 1
    upper_bits = va >> 39
    if bit38 == 0 and upper_bits != 0:
        return make_fault(access)
    if bit38 == 1 and upper_bits != (1 << 25) - 1:
        return make_fault(access)

    # ── Extract VPN fields ───────────────────────────────────
    vpn = [
        (va >> 12) & 0x1FF,   # VPN[0]
        (va >> 21) & 0x1FF,   # VPN[1]
        (va >> 30) & 0x1FF,   # VPN[2]
    ]

    # ── Page table walk: level 2 → 1 → 0 ────────────────────
    a = satp_ppn * 4096  # base address of root page table

    for level in range(2, -1, -1):
        pte_addr = a + vpn[level] * 8
        pte = read_pte(mem, pte_addr)

        if pte is None:
            prefix = {"read": "load", "write": "store", "execute": "fetch"}
            return {"status": "fault", "cause": f"{prefix[access]}_access_fault"}

        # Decode PTE fields
        v = pte & 1
        r = (pte >> 1) & 1
        w = (pte >> 2) & 1
        x = (pte >> 3) & 1
        u = (pte >> 4) & 1
        a_bit = (pte >> 6) & 1
        d_bit = (pte >> 7) & 1
        ppn = pte >> 10

        # ── Check validity and reserved encoding ─────────────
        if v == 0 or (r == 0 and w == 1):
            return make_fault(access)

        # ── Pointer PTE (non-leaf): R=W=X=0 ─────────────────
        if r == 0 and w == 0 and x == 0:
            if level == 0:
                # Non-leaf at the final level is invalid
                return make_fault(access)
            a = ppn * 4096
            continue

        # ── Leaf PTE found ───────────────────────────────────

        # Superpage alignment: lower PPN fields must be zero
        if level == 2 and (ppn & 0x3FFFF) != 0:
            return make_fault(access)
        if level == 1 and (ppn & 0x1FF) != 0:
            return make_fault(access)

        # ── Permission checks ────────────────────────────────
        # Privilege / U-bit interaction
        if priv == 'U':
            if u == 0:
                return make_fault(access)
        elif priv == 'S':
            if u == 1:
                # S-mode CANNOT fetch from user pages, regardless of SUM
                if access == 'execute':
                    return make_fault(access)
                # S-mode loads/stores need SUM=1 for user pages
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

        # ── Svade: A/D bit check ─────────────────────────────
        if svade:
            if a_bit == 0:
                return make_fault(access)
            if access == 'write' and d_bit == 0:
                return make_fault(access)

        # ── Compute physical address ─────────────────────────
        # For superpages, lower VA bits replace lower PPN bits
        if level == 0:
            pa = (ppn << 12) | (va & 0xFFF)
        elif level == 1:
            pa = (ppn << 12) | (va & 0x1FFFFF)
        else:  # level == 2
            pa = (ppn << 12) | (va & 0x3FFFFFFF)

        page_sizes = {0: 4096, 1: 2097152, 2: 1073741824}
        return {"status": "ok", "pa": hex(pa), "page_size": page_sizes[level]}

    # Exhausted all levels without finding a leaf — should not happen
    return make_fault(access)


def main():
    with open('/app/pagetables.bin', 'rb') as f:
        mem = f.read()

    with open('/app/config.json', 'r') as f:
        config = json.load(f)

    satp_ppn = config['satp_ppn']
    svade = config['svade']

    query_file = sys.argv[1]
    with open(query_file, 'r') as f:
        queries = json.load(f)

    results = []
    for q in queries:
        results.append(translate(mem, satp_ppn, svade, q))

    json.dump(results, sys.stdout)


if __name__ == '__main__':
    main()
