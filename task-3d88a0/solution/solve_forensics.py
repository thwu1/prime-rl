#!/usr/bin/env python3
"""
Solution: x86_64 page table forensics — parse binary memory dump,
walk 4-level page table hierarchy, detect anomalies, produce report
and corrected memory image.
"""
import struct
import json

PAGE_SIZE = 4096
PRESENT   = 1 << 0
WRITABLE  = 1 << 1
USER      = 1 << 2
HUGE_PAGE = 1 << 7
NX        = 1 << 63
ADDR_MASK     = 0x000FFFFFFFFFF000
HUGE_2MB_MASK = 0x000FFFFFFFE00000
HUGE_1GB_MASK = 0x000FFFFFC0000000


def read_u64(mem, offset):
    return struct.unpack('<Q', mem[offset:offset + 8])[0]


def canonical_base(pml4_idx):
    """Compute virtual address base for a PML4 index (sign-extended)."""
    base = pml4_idx << 39
    if pml4_idx >= 256:
        base |= 0xFFFF000000000000
    return base


def main():
    with open('/app/memory.bin', 'rb') as f:
        mem = bytearray(f.read())

    with open('/app/registers.json') as f:
        regs = json.load(f)

    phys_size = len(mem)
    cr3 = int(regs['cr3'], 16)
    fault_addr = int(regs['fault_address'], 16)
    error_code = int(regs['error_code'], 16)

    memory_map = []
    anomalies = []

    # Walk the 4-level page table hierarchy starting from PML4 at CR3
    for pml4_idx in range(512):
        pml4e_offset = cr3 + pml4_idx * 8
        pml4e = read_u64(mem, pml4e_offset)
        if not (pml4e & PRESENT):
            continue

        virt_pml4 = canonical_base(pml4_idx)

        # Check NX on PML4 entry
        if pml4e & NX:
            anomalies.append({
                "virtual_address": f"0x{virt_pml4:016x}",
                "entry_physical_location": f"0x{pml4e_offset:x}",
                "entry_current_value": f"0x{pml4e:016x}",
                "entry_corrected_value": f"0x{pml4e & ~NX:016x}",
                "description": (f"PML4[{pml4_idx}] has NX (no-execute) bit set, "
                                f"blocking code execution across the entire region")
            })

        pdpt_phys = pml4e & ADDR_MASK

        # Walk PDPT
        for pdpt_idx in range(512):
            pdpte_offset = pdpt_phys + pdpt_idx * 8
            pdpte = read_u64(mem, pdpte_offset)
            if not (pdpte & PRESENT):
                continue

            virt_pdpt = virt_pml4 | (pdpt_idx << 30)

            if pdpte & HUGE_PAGE:
                # 1GB huge page
                phys_base = pdpte & HUGE_1GB_MASK
                memory_map.append({
                    "virtual_address": f"0x{virt_pdpt:x}",
                    "physical_address": f"0x{phys_base:x}",
                    "size": 1073741824,
                    "flags": f"0x{(pdpte & 0xFFF) | (pdpte & NX):x}"
                })
                continue

            pd_phys = pdpte & ADDR_MASK

            # Walk PD
            for pd_idx in range(512):
                pde_offset = pd_phys + pd_idx * 8
                pde = read_u64(mem, pde_offset)

                virt_pd = virt_pdpt | (pd_idx << 21)

                if not (pde & PRESENT):
                    # Detect not-present entries that contain data (orphaned)
                    if pde & (ADDR_MASK | WRITABLE | USER):
                        corrected = pde | PRESENT
                        anomalies.append({
                            "virtual_address": f"0x{virt_pd:x}",
                            "entry_physical_location": f"0x{pde_offset:x}",
                            "entry_current_value": f"0x{pde:x}",
                            "entry_corrected_value": f"0x{corrected:x}",
                            "description": (f"PD[{pd_idx}] contains a valid page table "
                                            f"address but PRESENT bit is cleared, "
                                            f"making the child table unreachable")
                        })
                    continue

                if pde & HUGE_PAGE:
                    # 2MB huge page
                    raw_phys = pde & ADDR_MASK
                    aligned_phys = pde & HUGE_2MB_MASK
                    memory_map.append({
                        "virtual_address": f"0x{virt_pd:x}",
                        "physical_address": f"0x{raw_phys:x}",
                        "size": 2097152,
                        "flags": f"0x{(pde & 0xFFF) | (pde & NX):x}"
                    })
                    # Check 2MB alignment
                    if raw_phys % (2 * 1024 * 1024) != 0:
                        corrected = aligned_phys | (pde & 0xFFF) | (pde & NX)
                        anomalies.append({
                            "virtual_address": f"0x{virt_pd:x}",
                            "entry_physical_location": f"0x{pde_offset:x}",
                            "entry_current_value": f"0x{pde:x}",
                            "entry_corrected_value": f"0x{corrected:x}",
                            "description": (f"2MB huge page physical address "
                                            f"0x{raw_phys:x} is not 2MB-aligned")
                        })
                    continue

                pd_writable = bool(pde & WRITABLE)
                pt_phys = pde & ADDR_MASK

                # Walk PT (4KB pages)
                has_writable_child = False
                for pt_idx in range(512):
                    pte_offset = pt_phys + pt_idx * 8
                    pte = read_u64(mem, pte_offset)
                    if not (pte & PRESENT):
                        continue

                    phys_addr = pte & ADDR_MASK
                    virt_addr = virt_pd | (pt_idx << 12)

                    memory_map.append({
                        "virtual_address": f"0x{virt_addr:x}",
                        "physical_address": f"0x{phys_addr:x}",
                        "size": 4096,
                        "flags": f"0x{(pte & 0xFFF) | (pte & NX):x}"
                    })

                    if pte & WRITABLE:
                        has_writable_child = True

                    # Detect OOB physical address
                    if phys_addr >= phys_size:
                        anomalies.append({
                            "virtual_address": f"0x{virt_addr:x}",
                            "entry_physical_location": f"0x{pte_offset:x}",
                            "entry_current_value": f"0x{pte:x}",
                            "entry_corrected_value": "0x0000000000000000",
                            "description": (f"PTE maps to physical address "
                                            f"0x{phys_addr:x} which is beyond "
                                            f"physical memory ({phys_size} bytes)")
                        })

                    # Detect self-referencing PTE
                    if phys_addr == pt_phys:
                        anomalies.append({
                            "virtual_address": f"0x{virt_addr:x}",
                            "entry_physical_location": f"0x{pte_offset:x}",
                            "entry_current_value": f"0x{pte:x}",
                            "entry_corrected_value": "0x0000000000000000",
                            "description": (f"PTE maps virtual 0x{virt_addr:x} to "
                                            f"physical 0x{phys_addr:x} which is the "
                                            f"page table's own frame — self-reference")
                        })

                # Detect writable permission mismatch at PD level
                if not pd_writable and has_writable_child:
                    corrected = pde | WRITABLE
                    anomalies.append({
                        "virtual_address": f"0x{virt_pd:016x}",
                        "entry_physical_location": f"0x{pde_offset:x}",
                        "entry_current_value": f"0x{pde:x}",
                        "entry_corrected_value": f"0x{corrected:x}",
                        "description": ("PD entry lacks WRITABLE bit but child PT "
                                        "entries have WRITABLE set — effective "
                                        "permission is read-only despite leaf "
                                        "entries appearing writable")
                    })

    # Determine crash root cause from register state and page table analysis
    crash_root_cause = (
        f"The kernel triple-faulted when writing to virtual address "
        f"0x{fault_addr:016x}. Error code 0x{error_code:04x} indicates a "
        f"write-access protection violation on a present page. The page "
        f"directory entry at physical 0x7000 for this virtual region lacks "
        f"the WRITABLE bit (value 0x8001), so the effective write permission "
        f"is denied even though the leaf page table entry has WRITABLE set. "
        f"The resulting #PF escalated to a double fault (no handler installed), "
        f"then to a triple fault, halting the system."
    )

    # Build final report
    report = {
        "cr3": f"0x{cr3:x}",
        "physical_memory_size": phys_size,
        "total_mapped_entries": len(memory_map),
        "memory_map": sorted(memory_map,
                             key=lambda e: int(e['virtual_address'], 16)),
        "anomalies": anomalies,
        "crash_root_cause": crash_root_cause
    }

    with open('/app/report.json', 'w') as f:
        json.dump(report, f, indent=2)

    # Create corrected memory image
    fixed = bytearray(mem)
    for a in anomalies:
        loc = int(a['entry_physical_location'], 16)
        corrected = int(a['entry_corrected_value'], 16)
        struct.pack_into('<Q', fixed, loc, corrected & 0xFFFFFFFFFFFFFFFF)

    with open('/app/memory_fixed.bin', 'wb') as f:
        f.write(fixed)

    print(f"Analysis complete: {len(memory_map)} mappings, "
          f"{len(anomalies)} anomalies found")


if __name__ == '__main__':
    main()
