#!/usr/bin/env python3
"""
Reference solution: x86-64 page table walker and security auditor.

"""
import struct
import json
import os


def load_memory(path):
    with open(path, "rb") as f:
        return f.read()


def read_entry(memory, phys_addr):
    if phys_addr + 8 > len(memory):
        return None
    return struct.unpack_from('<Q', memory, phys_addr)[0]


def entry_present(e):
    return bool(e & 1)


def entry_rw(e):
    return bool(e & (1 << 1))


def entry_us(e):
    return bool(e & (1 << 2))


def entry_ps(e):
    return bool(e & (1 << 7))


def entry_nx(e):
    return bool(e & (1 << 63))


def phys_from_entry(e):
    return e & 0x000FFFFFFFFFF000


def phys_from_2mb(e):
    return e & 0x000FFFFFFFE00000


def phys_from_1gb(e):
    return e & 0x000FFFFFC0000000


def sign_extend_48(addr):
    if addr & (1 << 47):
        return addr | 0xFFFF000000000000
    return addr


def translate_va(memory, cr3, va):
    va48 = va & 0x0000FFFFFFFFFFFF
    pml4_idx = (va48 >> 39) & 0x1FF
    pdpt_idx = (va48 >> 30) & 0x1FF
    pd_idx = (va48 >> 21) & 0x1FF
    pt_idx = (va48 >> 12) & 0x1FF
    offset = va48 & 0xFFF

    rw_all = []
    us_all = []
    nx_all = []

    # PML4
    pml4e = read_entry(memory, cr3 + pml4_idx * 8)
    if pml4e is None or not entry_present(pml4e):
        return None
    rw_all.append(entry_rw(pml4e))
    us_all.append(entry_us(pml4e))
    nx_all.append(entry_nx(pml4e))

    # PDPT
    pdpt_base = phys_from_entry(pml4e)
    pdpte = read_entry(memory, pdpt_base + pdpt_idx * 8)
    if pdpte is None or not entry_present(pdpte):
        return None
    rw_all.append(entry_rw(pdpte))
    us_all.append(entry_us(pdpte))
    nx_all.append(entry_nx(pdpte))

    if entry_ps(pdpte):
        pa = phys_from_1gb(pdpte) + (va48 & 0x3FFFFFFF)
        return pa, 1 << 30, all(rw_all), not any(nx_all), all(us_all)

    # PD
    pd_base = phys_from_entry(pdpte)
    pde = read_entry(memory, pd_base + pd_idx * 8)
    if pde is None or not entry_present(pde):
        return None
    rw_all.append(entry_rw(pde))
    us_all.append(entry_us(pde))
    nx_all.append(entry_nx(pde))

    if entry_ps(pde):
        pa = phys_from_2mb(pde) + (va48 & 0x1FFFFF)
        return pa, 1 << 21, all(rw_all), not any(nx_all), all(us_all)

    # PT
    pt_base = phys_from_entry(pde)
    pte = read_entry(memory, pt_base + pt_idx * 8)
    if pte is None or not entry_present(pte):
        return None
    rw_all.append(entry_rw(pte))
    us_all.append(entry_us(pte))
    nx_all.append(entry_nx(pte))

    pa = phys_from_entry(pte) + offset
    return pa, 4096, all(rw_all), not any(nx_all), all(us_all)


def full_walk(memory, cr3):
    regions = []
    anomalies = []

    for pml4_i in range(512):
        pml4e = read_entry(memory, cr3 + pml4_i * 8)
        if pml4e is None or not entry_present(pml4e):
            continue
        l4_rw, l4_us, l4_nx = entry_rw(pml4e), entry_us(pml4e), entry_nx(pml4e)
        pdpt_base = phys_from_entry(pml4e)

        for pdpt_i in range(512):
            pdpte = read_entry(memory, pdpt_base + pdpt_i * 8)
            if pdpte is None or not entry_present(pdpte):
                continue
            l3_rw, l3_us, l3_nx = entry_rw(pdpte), entry_us(pdpte), entry_nx(pdpte)

            if entry_ps(pdpte):
                raw = (pml4_i << 39) | (pdpt_i << 30)
                va = sign_extend_48(raw)
                pa = phys_from_1gb(pdpte)
                sz = 1 << 30
                w = l4_rw and l3_rw
                x = not (l4_nx or l3_nx)
                u = l4_us and l3_us
                regions.append((va, va + sz, pa, sz, w, x, u))
                if w and x:
                    anomalies.append((va, pa, sz))
                continue

            pd_base = phys_from_entry(pdpte)
            for pd_i in range(512):
                pde = read_entry(memory, pd_base + pd_i * 8)
                if pde is None or not entry_present(pde):
                    continue
                l2_rw, l2_us, l2_nx = entry_rw(pde), entry_us(pde), entry_nx(pde)

                if entry_ps(pde):
                    raw = (pml4_i << 39) | (pdpt_i << 30) | (pd_i << 21)
                    va = sign_extend_48(raw)
                    pa = phys_from_2mb(pde)
                    sz = 1 << 21
                    w = l4_rw and l3_rw and l2_rw
                    x = not (l4_nx or l3_nx or l2_nx)
                    u = l4_us and l3_us and l2_us
                    regions.append((va, va + sz, pa, sz, w, x, u))
                    if w and x:
                        anomalies.append((va, pa, sz))
                    continue

                pt_base = phys_from_entry(pde)
                for pt_i in range(512):
                    pte = read_entry(memory, pt_base + pt_i * 8)
                    if pte is None or not entry_present(pte):
                        continue
                    l1_rw, l1_us, l1_nx = entry_rw(pte), entry_us(pte), entry_nx(pte)

                    raw = (pml4_i << 39) | (pdpt_i << 30) | (pd_i << 21) | (pt_i << 12)
                    va = sign_extend_48(raw)
                    pa = phys_from_entry(pte)
                    sz = 4096
                    w = l4_rw and l3_rw and l2_rw and l1_rw
                    x = not (l4_nx or l3_nx or l2_nx or l1_nx)
                    u = l4_us and l3_us and l2_us and l1_us
                    regions.append((va, va + sz, pa, sz, w, x, u))
                    if w and x:
                        anomalies.append((va, pa, sz))

    regions.sort(key=lambda r: r[0] % (2**64))
    anomalies.sort(key=lambda a: a[0] % (2**64))
    return regions, anomalies


def fmt(addr):
    if addr < 0:
        addr += 1 << 64
    return f"0x{addr:016x}"


def main():
    memory = load_memory("/app/ptdump/memory.bin")
    with open("/app/ptdump/metadata.json") as f:
        meta = json.load(f)
    with open("/app/ptdump/queries.json") as f:
        queries = json.load(f)

    cr3 = meta["cr3"]

    # Translations
    translations = []
    for addr_s in queries["addresses"]:
        va = int(addr_s, 16)
        result = translate_va(memory, cr3, va)
        entry = {"virtual_address": fmt(va)}
        if result is None:
            entry["present"] = False
        else:
            pa, page_size, writable, executable, user_accessible = result
            entry["present"] = True
            entry["physical_address"] = fmt(pa)
            entry["page_size"] = page_size
            entry["writable"] = writable
            entry["executable"] = executable
            entry["user_accessible"] = user_accessible
        translations.append(entry)

    # Full walk
    regions, anom_list = full_walk(memory, cr3)

    memmap = []
    for vs, ve, ps, sz, w, x, u in regions:
        memmap.append({
            "virtual_start": fmt(vs),
            "virtual_end": fmt(ve),
            "physical_start": fmt(ps),
            "page_size": sz,
            "writable": w,
            "executable": x,
            "user_accessible": u,
        })

    anomalies = []
    for va, pa, sz in anom_list:
        anomalies.append({
            "virtual_address": fmt(va),
            "physical_address": fmt(pa),
            "page_size": sz,
            "type": "writable_executable",
        })

    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/translations.json", "w") as f:
        json.dump(translations, f, indent=2)
    with open("/app/output/memmap.json", "w") as f:
        json.dump(memmap, f, indent=2)
    with open("/app/output/anomalies.json", "w") as f:
        json.dump(anomalies, f, indent=2)


if __name__ == "__main__":
    main()
