#!/usr/bin/env python3
"""
RISC-V Sv39 page table forensics: diagnose and repair corrupted PTEs
from a qcow2 physical memory snapshot with device tree configuration.

"""

import json
import struct
import subprocess
import re


def parse_hex(s):
    if isinstance(s, int):
        return s
    return int(s, 16)


def read_pte(mem, offset):
    return struct.unpack_from('<Q', mem, offset)[0]


def write_pte_mem(mem, offset, value):
    struct.pack_into('<Q', mem, offset, value)


def get_ppn(pte):
    return (pte >> 10) & ((1 << 44) - 1)


def set_ppn(pte, ppn):
    ppn_mask = ((1 << 44) - 1) << 10
    return (pte & ~ppn_mask) | ((ppn & ((1 << 44) - 1)) << 10)


def extract_raw_from_qcow2(qcow2_path, raw_path):
    """Extract raw memory bytes from a qcow2 disk image using qemu-img."""
    subprocess.run(
        ["qemu-img", "convert", "-f", "qcow2", "-O", "raw",
         qcow2_path, raw_path],
        check=True
    )


def write_raw_to_qcow2(raw_path, qcow2_path):
    """Package raw memory bytes into a qcow2 disk image using qemu-img."""
    subprocess.run(
        ["qemu-img", "convert", "-f", "raw", "-O", "qcow2",
         raw_path, qcow2_path],
        check=True
    )


def decode_device_tree(dtb_path):
    """Decode a device tree blob using dtc and extract physical memory layout."""
    result = subprocess.run(
        ["dtc", "-I", "dtb", "-O", "dts", "-q", dtb_path],
        capture_output=True, text=True, check=True
    )
    dts = result.stdout

    # Find the memory node and extract the reg property.
    # With #address-cells=2, #size-cells=2, reg contains four 32-bit cells:
    #   <addr_hi addr_lo size_hi size_lo>
    mem_match = re.search(
        r'memory@[0-9a-fA-F]+\s*\{[^}]*reg\s*=\s*<([^>]+)>',
        dts, re.DOTALL
    )
    if not mem_match:
        raise RuntimeError("Could not find memory node in device tree")

    parts = mem_match.group(1).strip().split()
    addr_hi = int(parts[0], 0)
    addr_lo = int(parts[1], 0)
    size_hi = int(parts[2], 0)
    size_lo = int(parts[3], 0)

    base = (addr_hi << 32) | addr_lo
    size = (size_hi << 32) | size_lo
    return base, size


def diagnose_fault(mem, base, satp, mstatus, menvcfg, extensions, fault):
    va = parse_hex(fault["va"])
    access = fault["access"]
    priv = fault["privilege"]

    mode = (satp >> 60) & 0xF
    root_ppn = satp & ((1 << 44) - 1)

    if mode != 8:
        return None

    levels = 3
    vpn_width = 9

    vpns = []
    for i in range(levels):
        shift = 12 + i * vpn_width
        vpns.append((va >> shift) & ((1 << vpn_width) - 1))

    mxr = (mstatus >> 19) & 1
    sum_bit = (mstatus >> 18) & 1
    adue = (menvcfg >> 61) & 1

    svade = extensions.get("Svade", False)
    svadu = extensions.get("Svadu", False)
    svnapot = extensions.get("Svnapot", False)

    hw_ad_update = (svadu and adue == 1) or (not svadu and not svade)

    a_pa = root_ppn << 12

    for level in range(levels - 1, -1, -1):
        pte_pa = a_pa + vpns[level] * 8
        pte_offset = pte_pa - base

        if pte_offset < 0 or pte_offset + 8 > len(mem):
            return None

        pte = read_pte(mem, pte_offset)

        v = pte & 1
        r = (pte >> 1) & 1
        w = (pte >> 2) & 1
        x = (pte >> 3) & 1
        u = (pte >> 4) & 1
        a_bit = (pte >> 6) & 1
        d_bit = (pte >> 7) & 1
        ppn_val = get_ppn(pte)
        n_bit = (pte >> 63) & 1

        if v == 0:
            fixed = pte | 1
            return {"pte_phys_addr": hex(pte_pa), "current_pte": hex(pte),
                    "root_cause": "invalid_pte_v_bit_clear",
                    "corrected_pte": hex(fixed), "offset": pte_offset}

        if r == 0 and w == 1:
            fixed = pte | (1 << 1)
            return {"pte_phys_addr": hex(pte_pa), "current_pte": hex(pte),
                    "root_cause": "reserved_pte_encoding_w1_r0",
                    "corrected_pte": hex(fixed), "offset": pte_offset}

        is_leaf = (r == 1) or (x == 1)

        if not is_leaf:
            if level == 0:
                fixed = pte | (1 << 1) | (1 << 6)
                if access in ("store", "write"):
                    fixed |= (1 << 2) | (1 << 7)
                if access in ("fetch", "exec"):
                    fixed |= (1 << 3)
                return {"pte_phys_addr": hex(pte_pa), "current_pte": hex(pte),
                        "root_cause": "nonleaf_pte_at_level_0",
                        "corrected_pte": hex(fixed), "offset": pte_offset}
            a_pa = ppn_val << 12
            continue

        # Leaf PTE

        if level > 0:
            low_bits = level * vpn_width
            low_mask = (1 << low_bits) - 1
            if (ppn_val & low_mask) != 0:
                fixed_ppn = ppn_val & ~low_mask
                fixed = set_ppn(pte, fixed_ppn)
                return {"pte_phys_addr": hex(pte_pa), "current_pte": hex(pte),
                        "root_cause": "misaligned_superpage",
                        "corrected_pte": hex(fixed), "offset": pte_offset}

        if n_bit == 1:
            if not svnapot:
                fixed = pte & ~(1 << 63)
                return {"pte_phys_addr": hex(pte_pa), "current_pte": hex(pte),
                        "root_cause": "napot_not_supported",
                        "corrected_pte": hex(fixed), "offset": pte_offset}
            if level > 0:
                fixed = pte & ~(1 << 63)
                return {"pte_phys_addr": hex(pte_pa), "current_pte": hex(pte),
                        "root_cause": "napot_on_superpage",
                        "corrected_pte": hex(fixed), "offset": pte_offset}
            if (ppn_val & 0xF) != 0x8:
                fixed_ppn = (ppn_val & ~0xF) | 0x8
                fixed = set_ppn(pte, fixed_ppn)
                return {"pte_phys_addr": hex(pte_pa), "current_pte": hex(pte),
                        "root_cause": "invalid_napot_encoding_ppn30_not_1000",
                        "corrected_pte": hex(fixed), "offset": pte_offset}

        if access in ("load", "read"):
            if r == 0 and not (mxr and x == 1):
                fixed = pte | (1 << 1)
                if a_bit == 0 and not hw_ad_update:
                    fixed |= (1 << 6)
                return {"pte_phys_addr": hex(pte_pa), "current_pte": hex(pte),
                        "root_cause": "no_read_permission",
                        "corrected_pte": hex(fixed), "offset": pte_offset}
        elif access in ("store", "write"):
            if w == 0:
                fixed = pte | (1 << 2)
                if not hw_ad_update:
                    fixed |= (1 << 7)
                return {"pte_phys_addr": hex(pte_pa), "current_pte": hex(pte),
                        "root_cause": "no_write_permission",
                        "corrected_pte": hex(fixed), "offset": pte_offset}
        elif access in ("fetch", "exec"):
            if x == 0:
                fixed = pte | (1 << 3)
                return {"pte_phys_addr": hex(pte_pa), "current_pte": hex(pte),
                        "root_cause": "no_execute_permission",
                        "corrected_pte": hex(fixed), "offset": pte_offset}

        if priv == "U" and u == 0:
            fixed = pte | (1 << 4)
            return {"pte_phys_addr": hex(pte_pa), "current_pte": hex(pte),
                    "root_cause": "privilege_violation_umode_on_spage",
                    "corrected_pte": hex(fixed), "offset": pte_offset}
        elif priv == "S" and u == 1:
            if access in ("fetch", "exec"):
                fixed = pte & ~(1 << 4)
                return {"pte_phys_addr": hex(pte_pa), "current_pte": hex(pte),
                        "root_cause": "smode_cannot_exec_upage",
                        "corrected_pte": hex(fixed), "offset": pte_offset}
            if not sum_bit:
                fixed = pte & ~(1 << 4)
                return {"pte_phys_addr": hex(pte_pa), "current_pte": hex(pte),
                        "root_cause": "smode_access_upage_without_sum",
                        "corrected_pte": hex(fixed), "offset": pte_offset}

        if a_bit == 0 and not hw_ad_update:
            fixed = pte | (1 << 6)
            return {"pte_phys_addr": hex(pte_pa), "current_pte": hex(pte),
                    "root_cause": "accessed_bit_clear_svade_fault",
                    "corrected_pte": hex(fixed), "offset": pte_offset}

        if access in ("store", "write") and d_bit == 0 and not hw_ad_update:
            fixed = pte | (1 << 7)
            return {"pte_phys_addr": hex(pte_pa), "current_pte": hex(pte),
                    "root_cause": "dirty_bit_clear_svade_store_fault",
                    "corrected_pte": hex(fixed), "offset": pte_offset}

        return None

    return None


def main():
    # Step 1: Extract raw memory from qcow2 disk image
    print("Extracting raw memory from qcow2...")
    extract_raw_from_qcow2("/app/memory.qcow2", "/tmp/memory.raw")

    with open("/tmp/memory.raw", "rb") as f:
        mem = bytearray(f.read())

    # Step 2: Decode device tree to get physical memory layout
    print("Decoding device tree blob...")
    base, mem_size = decode_device_tree("/app/platform.dtb")
    print(f"  Physical memory: base={hex(base)}, size={hex(mem_size)}")

    # Step 3: Read system configuration
    with open("/app/system.json") as f:
        system = json.load(f)

    satp = parse_hex(system["satp"])
    mstatus = parse_hex(system["mstatus"])
    menvcfg = parse_hex(system["menvcfg"])
    extensions = system["extensions"]

    # Step 4: Read fault trace
    with open("/app/faults.json") as f:
        faults = json.load(f)

    # Step 5: Diagnose and fix each fault
    diagnosis = []

    for fault in faults:
        result = diagnose_fault(mem, base, satp, mstatus, menvcfg, extensions, fault)
        if result:
            entry = {
                "id": fault["id"],
                "pte_phys_addr": result["pte_phys_addr"],
                "current_pte": result["current_pte"],
                "root_cause": result["root_cause"],
                "corrected_pte": result["corrected_pte"],
            }
            diagnosis.append(entry)

            offset = result["offset"]
            fixed_value = parse_hex(result["corrected_pte"])
            write_pte_mem(mem, offset, fixed_value)
        else:
            print(f"WARNING: Could not diagnose fault id={fault['id']}")

    # Step 6: Write diagnosis report
    with open("/app/diagnosis.json", "w") as f:
        json.dump(diagnosis, f, indent=2)

    # Step 7: Write patched memory as qcow2
    print("Packaging fixed memory as qcow2...")
    fixed_raw = "/tmp/memory_fixed.raw"
    with open(fixed_raw, "wb") as f:
        f.write(mem)

    write_raw_to_qcow2(fixed_raw, "/app/memory_fixed.qcow2")

    print(f"Diagnosed and fixed {len(diagnosis)} faults.")


if __name__ == "__main__":
    main()
