#!/usr/bin/env python3
"""
RISC-V Sv39/Sv48/Sv57 Virtual Address Translation Engine.

Reads memory.json (page table entries) and queries.json, performs
page table walks, and writes results.json.

"""

import json
import sys

PAGESIZE = 4096
PTESIZE = 8

MODE_LEVELS = {
    "Sv39": 3,
    "Sv48": 4,
    "Sv57": 5,
}

MODE_VA_BITS = {
    "Sv39": 39,
    "Sv48": 48,
    "Sv57": 57,
}


def parse_hex(s):
    """Parse a hex string (with or without 0x prefix) to int."""
    if isinstance(s, int):
        return s
    return int(s, 16)


def load_memory(path):
    """Load memory map: maps integer physical addresses to integer PTE values."""
    with open(path) as f:
        raw = json.load(f)
    mem = {}
    for addr_s, val_s in raw.items():
        mem[parse_hex(addr_s)] = parse_hex(val_s)
    return mem


def load_queries(path):
    with open(path) as f:
        return json.load(f)


def fault_type(access):
    if access in ("read", "load"):
        return "load_page_fault"
    elif access in ("write", "store"):
        return "store_page_fault"
    elif access in ("exec", "fetch"):
        return "fetch_page_fault"
    return "page_fault"


def make_fault(access):
    return {"status": "fault", "fault_type": fault_type(access)}


def translate(memory, query):
    mode = query["mode"]
    satp_ppn = parse_hex(query["satp_ppn"])
    va = parse_hex(query["va"])
    access = query["access"]
    priv = query["privilege"]
    mxr = query.get("mstatus_mxr", False)
    sum_bit = query.get("mstatus_sum", False)
    adue = query.get("adue", False)
    svnapot = query.get("svnapot", False)

    if mode not in MODE_LEVELS:
        return make_fault(access)

    levels = MODE_LEVELS[mode]
    va_bits = MODE_VA_BITS[mode]
    vpn_bits = 9  # always 9 for Sv39/48/57

    # Extract VPN fields: vpns[0]=VPN[0], vpns[1]=VPN[1], etc.
    vpns = []
    for i in range(levels):
        shift = 12 + i * vpn_bits
        vpn_i = (va >> shift) & ((1 << vpn_bits) - 1)
        vpns.append(vpn_i)

    # Page table walk
    a = satp_ppn * PAGESIZE
    i = levels - 1

    while True:
        # Step 2: compute PTE address and read PTE
        pte_addr = a + vpns[i] * PTESIZE
        pte = memory.get(pte_addr, 0)

        # Parse PTE fields
        v = pte & 1
        r = (pte >> 1) & 1
        w = (pte >> 2) & 1
        x = (pte >> 3) & 1
        u = (pte >> 4) & 1
        a_bit = (pte >> 6) & 1
        d_bit = (pte >> 7) & 1
        ppn = (pte >> 10) & ((1 << 44) - 1)
        n_bit = (pte >> 63) & 1

        # Check reserved bits [60:54]
        reserved = (pte >> 54) & 0x7F
        if reserved != 0:
            return make_fault(access)

        # Step 3: validity check
        if v == 0:
            return make_fault(access)
        if r == 0 and w == 1:
            return make_fault(access)

        # Step 4: leaf or non-leaf?
        is_leaf = (r == 1) or (x == 1)

        if not is_leaf:
            # Non-leaf PTE
            if i == 0:
                # Non-leaf at level 0 is invalid
                return make_fault(access)
            if n_bit == 1:
                # N bit on non-leaf is reserved
                return make_fault(access)
            a = ppn * PAGESIZE
            i -= 1
            continue

        # Step 5: Leaf PTE found at level i

        # Step 5a: NAPOT check
        if n_bit == 1:
            if i > 0:
                # NAPOT reserved for superpages
                return make_fault(access)
            if not svnapot:
                # Svnapot not enabled, N=1 is reserved
                return make_fault(access)
            # Check valid NAPOT encoding: PPN[3:0] must be 0b1000
            if (ppn & 0xF) != 0x8:
                return make_fault(access)

        # Step 5b: superpage alignment
        if i > 0:
            low_bits_count = i * vpn_bits
            low_mask = (1 << low_bits_count) - 1
            if (ppn & low_mask) != 0:
                return make_fault(access)

        # Step 6: permission check
        if access in ("read", "load"):
            if r == 0 and not (mxr and x == 1):
                return make_fault(access)
        elif access in ("write", "store"):
            if w == 0:
                return make_fault(access)
        elif access in ("exec", "fetch"):
            if x == 0:
                return make_fault(access)

        # U-bit privilege check
        if priv == "U":
            if u == 0:
                return make_fault(access)
        elif priv == "S":
            if u == 1:
                if access in ("exec", "fetch"):
                    # S-mode cannot execute U-pages regardless of SUM
                    return make_fault(access)
                if not sum_bit:
                    return make_fault(access)

        # Step 7: A/D bit check
        if a_bit == 0:
            if not adue:
                return make_fault(access)
            # Svadu mode: would update A bit, no fault

        if access in ("write", "store") and d_bit == 0:
            if not adue:
                return make_fault(access)
            # Svadu mode: would update D bit, no fault

        # Step 8: compute physical address
        if n_bit == 1 and svnapot:
            # NAPOT 64KB page
            base_ppn = ppn & ~0xF
            pa = (base_ppn << 12) | (va & 0xFFFF)
            page_size = 16 * PAGESIZE  # 64KB
        elif i == 0:
            # Regular 4KB page
            pa = (ppn << 12) | (va & 0xFFF)
            page_size = PAGESIZE
        else:
            # Superpage at level i
            offset_bits = 12 + i * vpn_bits
            offset_mask = (1 << offset_bits) - 1
            pa = ((ppn >> (i * vpn_bits)) << offset_bits) | (va & offset_mask)
            page_size = 1 << offset_bits

        return {
            "status": "ok",
            "pa": hex(pa),
            "page_size": page_size,
        }

    # Should not reach here
    return make_fault(access)


def main():
    memory = load_memory("/data/memory.json")
    queries = load_queries("/data/queries.json")

    results = []
    for query in queries:
        result = translate(memory, query)
        result["id"] = query["id"]
        results.append(result)

    results.sort(key=lambda r: r["id"])

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"Translated {len(results)} queries. Results written to /app/results.json")


if __name__ == "__main__":
    main()
