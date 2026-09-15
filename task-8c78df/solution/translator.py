#!/usr/bin/env python3
"""
RISC-V Virtual Address Translation Engine

Implements the RISC-V page table walk algorithm for Sv32, Sv39, Sv48, and Sv57
translation modes, based on the Sail RISC-V formal specification.
"""

import json
import os
import struct
import sys


PAGESIZE = 4096
PAGESIZE_BITS = 12

# Translation mode parameters: (levels, vpn_bits_per_level, pte_size_bytes)
MODE_PARAMS = {
    "Sv32": (2, 10, 4),
    "Sv39": (3, 9, 8),
    "Sv48": (4, 9, 8),
    "Sv57": (5, 9, 8),
}

# satp.Mode field values for 64-bit
SATP64_MODES = {8: "Sv39", 9: "Sv48", 10: "Sv57"}


def _parse_hex(val):
    """Parse a hex string or int into an integer."""
    if isinstance(val, int):
        return val
    return int(val, 16)


def _read_pte(memory, addr, pte_size):
    """Read a PTE from the memory map at the given physical address."""
    addr_hex = hex(addr)
    if addr_hex not in memory:
        return None
    raw = bytes.fromhex(memory[addr_hex].replace("0x", ""))
    if pte_size == 8:
        return struct.unpack('<Q', raw)[0]
    else:
        return struct.unpack('<I', raw)[0]


def _decode_pte(pte, pte_size):
    """Decode a PTE into its component fields."""
    v = bool(pte & 1)
    r = bool(pte & 2)
    w = bool(pte & 4)
    x = bool(pte & 8)
    u = bool(pte & 16)
    g = bool(pte & 32)
    a = bool(pte & 64)
    d = bool(pte & 128)
    if pte_size == 8:
        ppn = (pte >> 10) & ((1 << 44) - 1)
        pbmt = (pte >> 61) & 3
        n = bool(pte >> 63)
    else:
        ppn = (pte >> 10) & ((1 << 22) - 1)
        pbmt = 0
        n = False
    return {
        "v": v, "r": r, "w": w, "x": x, "u": u, "g": g,
        "a": a, "d": d, "ppn": ppn, "pbmt": pbmt, "n": n,
    }


def _fault_type(access_type):
    """Return the appropriate fault type string for the access type."""
    if access_type == "read":
        return "load_page_fault"
    elif access_type == "write":
        return "store_page_fault"
    else:
        return "fetch_page_fault"


def _fault(access_type):
    return {"outcome": "fault", "fault_type": _fault_type(access_type)}


def _effective_privilege(access_type, privilege, mstatus_val):
    """Compute effective privilege considering MPRV.

    MPRV only affects data accesses (loads/stores), NOT instruction fetch.
    When MPRV=1, data accesses use the privilege encoded in MPP.
    """
    if access_type != "execute" and privilege == "M":
        mprv = bool(mstatus_val & (1 << 17))
        if mprv:
            mpp = (mstatus_val >> 11) & 3
            return {0: "U", 1: "S", 3: "M"}.get(mpp, "M")
    return privilege


def translate_scenario(scenario):
    """Translate a virtual address according to the scenario configuration.

    Args:
        scenario: dict with keys xlen, translation_mode, privilege, access_type,
                  virtual_address, satp, mstatus, menvcfg, extensions, memory

    Returns:
        dict with outcome, and either physical_address + metadata or fault_type
    """
    xlen = scenario["xlen"]
    mode_name = scenario["translation_mode"]
    privilege = scenario["privilege"]
    access_type = scenario["access_type"]
    va = _parse_hex(scenario["virtual_address"])
    satp = _parse_hex(scenario["satp"])
    mstatus_val = _parse_hex(scenario["mstatus"])
    menvcfg_val = _parse_hex(scenario["menvcfg"])
    extensions = scenario.get("extensions", {})
    memory = scenario["memory"]

    # Compute effective privilege (MPRV handling)
    eff_priv = _effective_privilege(access_type, privilege, mstatus_val)

    # M-mode uses Bare translation (no address translation)
    if eff_priv == "M":
        return {
            "outcome": "success",
            "physical_address": hex(va),
            "page_level": 0,
            "pte_flags": {},
            "pbmt_mode": "pma",
            "a_d_update_needed": False,
        }

    # Extract satp fields
    if mode_name == "Sv32":
        ppn_base = satp & ((1 << 22) - 1)
    else:
        ppn_base = satp & ((1 << 44) - 1)

    levels, vpn_bits, pte_size = MODE_PARAMS[mode_name]

    # Extract CSR control bits
    mxr = bool(mstatus_val & (1 << 19))
    do_sum = bool(mstatus_val & (1 << 18))
    adue = bool(menvcfg_val & (1 << 61))
    pbmte = bool(menvcfg_val & (1 << 62))
    svnapot = extensions.get("Svnapot", False)
    svpbmt = extensions.get("Svpbmt", False)

    # Extract VPN fields from virtual address
    vpns = []
    for i in range(levels):
        vpn_i = (va >> (PAGESIZE_BITS + i * vpn_bits)) & ((1 << vpn_bits) - 1)
        vpns.append(vpn_i)

    page_offset = va & ((1 << PAGESIZE_BITS) - 1)

    # Check VA canonical form (sign extension) for 64-bit modes
    if xlen == 64 and mode_name != "Sv32":
        sv_width = PAGESIZE_BITS + levels * vpn_bits
        sign_bit = (va >> (sv_width - 1)) & 1
        upper_bits = va >> sv_width
        if sign_bit == 0:
            if upper_bits != 0:
                return _fault(access_type)
        else:
            expected = (1 << (64 - sv_width)) - 1
            if upper_bits != expected:
                return _fault(access_type)

    # Page table walk (Steps 2-8 of VATP)
    current_ppn = ppn_base

    for level in range(levels - 1, -1, -1):
        # Compute PTE address
        pte_addr = current_ppn * PAGESIZE + vpns[level] * pte_size

        # Read PTE (Step 2)
        pte_raw = _read_pte(memory, pte_addr, pte_size)
        if pte_raw is None:
            return _fault(access_type)

        pte = _decode_pte(pte_raw, pte_size)

        # Step 3: Check validity
        if not pte["v"]:
            return _fault(access_type)
        if pte["w"] and not pte["r"]:
            # Reserved encoding W=1, R=0
            return _fault(access_type)

        is_leaf = pte["r"] or pte["x"]

        if not is_leaf:
            # Non-leaf PTE (Step 4)
            if level == 0:
                # Pointer at leaf level is invalid
                return _fault(access_type)
            current_ppn = pte["ppn"]
            continue

        # Leaf PTE found (Step 5)

        # Superpage alignment check
        if level > 0:
            # NAPOT is reserved for levels > 0
            if pte["n"]:
                return _fault(access_type)
            low_bits = vpn_bits * level
            low_mask = (1 << low_bits) - 1
            if pte["ppn"] & low_mask != 0:
                return _fault(access_type)

        # Permission check (Steps 6-7)
        # U-bit check
        if eff_priv == "U" and not pte["u"]:
            return _fault(access_type)
        if eff_priv == "S":
            if pte["u"] and not do_sum:
                return _fault(access_type)
            if pte["u"] and access_type == "execute":
                # Supervisor cannot execute from user pages, even with SUM
                return _fault(access_type)

        # R/W/X check
        if access_type == "read":
            if not pte["r"] and not (pte["x"] and mxr):
                return _fault(access_type)
        elif access_type == "write":
            if not pte["w"]:
                return _fault(access_type)
        elif access_type == "execute":
            if not pte["x"]:
                return _fault(access_type)

        # A/D bit check (Step 8)
        need_a_update = not pte["a"]
        need_d_update = (access_type == "write") and not pte["d"]

        if need_a_update or need_d_update:
            if adue:
                a_d_update_needed = True
            else:
                # Software A/D management: raise page fault
                return _fault(access_type)
        else:
            a_d_update_needed = False

        # Compute physical address (Step 10)
        ppn = pte["ppn"]
        if level > 0:
            # Superpage: upper PPN from PTE, lower VPN from VA
            low_bits = vpn_bits * level
            upper_ppn = ppn >> low_bits
            lower_vpn = 0
            for i in range(level):
                lower_vpn |= vpns[i] << (vpn_bits * i)
            final_ppn = (upper_ppn << low_bits) | lower_vpn
        elif svnapot and pte["n"]:
            # NAPOT 64KiB page
            napot_bits = 4
            if (ppn & 0xF) != 0b1000:
                return _fault(access_type)
            upper = ppn >> napot_bits
            lower = vpns[0] & ((1 << napot_bits) - 1)
            final_ppn = (upper << napot_bits) | lower
        else:
            if pte["n"] and not svnapot:
                # N bit set but Svnapot not enabled -> invalid
                return _fault(access_type)
            final_ppn = ppn

        pa = final_ppn * PAGESIZE + page_offset

        # PBMT interpretation
        if pbmte and svpbmt:
            pbmt_modes = {0: "pma", 1: "nc", 2: "io"}
            pbmt_mode = pbmt_modes.get(pte["pbmt"], "reserved")
        else:
            pbmt_mode = "pma"

        return {
            "outcome": "success",
            "physical_address": hex(pa),
            "page_level": level,
            "pte_flags": {
                "d": pte["d"], "a": pte["a"], "g": pte["g"],
                "u": pte["u"], "x": pte["x"], "w": pte["w"], "r": pte["r"],
            },
            "pbmt_mode": pbmt_mode,
            "a_d_update_needed": a_d_update_needed,
        }

    # Should not reach here — all paths return above
    return _fault(access_type)


def main():
    scenarios_dir = "/app/scenarios"
    results_dir = "/app/results"
    os.makedirs(results_dir, exist_ok=True)

    for fname in sorted(os.listdir(scenarios_dir)):
        if not fname.endswith(".json"):
            continue
        scenario_name = fname[:-5]
        with open(os.path.join(scenarios_dir, fname)) as f:
            scenario = json.load(f)

        result = translate_scenario(scenario)

        with open(os.path.join(results_dir, fname), "w") as f:
            json.dump(result, f, indent=2)

        status = result["outcome"].upper()
        print(f"{scenario_name}: {status}")
        if result["outcome"] == "success":
            print(f"  PA={result['physical_address']}, level={result['page_level']}")
        else:
            print(f"  fault={result['fault_type']}")


if __name__ == "__main__":
    main()
