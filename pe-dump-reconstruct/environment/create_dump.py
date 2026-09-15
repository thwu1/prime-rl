#!/usr/bin/env python3
"""
Simulate PE loading: map sections to virtual addresses and apply base relocations.
Produces a raw memory dump as if the PE were loaded at a specified address.
"""
import struct
import sys
import json


def create_dump(pe_path, dump_path, meta_path, load_addr):
    with open(pe_path, 'rb') as f:
        pe_data = bytearray(f.read())

    # DOS header
    e_lfanew = struct.unpack_from('<I', pe_data, 0x3C)[0]

    # COFF header
    coff_off = e_lfanew + 4
    num_sections = struct.unpack_from('<H', pe_data, coff_off + 2)[0]
    size_opt_hdr = struct.unpack_from('<H', pe_data, coff_off + 16)[0]

    # Optional header
    opt_off = coff_off + 20
    magic = struct.unpack_from('<H', pe_data, opt_off)[0]
    pe32plus = (magic == 0x20B)

    if pe32plus:
        image_base = struct.unpack_from('<Q', pe_data, opt_off + 24)[0]
        size_of_image = struct.unpack_from('<I', pe_data, opt_off + 56)[0]
        size_of_headers = struct.unpack_from('<I', pe_data, opt_off + 60)[0]
        n_rva_sizes = struct.unpack_from('<I', pe_data, opt_off + 108)[0]
        dd_off = opt_off + 112
    else:
        image_base = struct.unpack_from('<I', pe_data, opt_off + 28)[0]
        size_of_image = struct.unpack_from('<I', pe_data, opt_off + 56)[0]
        size_of_headers = struct.unpack_from('<I', pe_data, opt_off + 60)[0]
        n_rva_sizes = struct.unpack_from('<I', pe_data, opt_off + 92)[0]
        dd_off = opt_off + 96

    # Section headers
    sec_off = opt_off + size_opt_hdr
    sections = []
    for i in range(num_sections):
        o = sec_off + i * 40
        name = pe_data[o:o + 8]
        vsize = struct.unpack_from('<I', pe_data, o + 8)[0]
        va = struct.unpack_from('<I', pe_data, o + 12)[0]
        raw_size = struct.unpack_from('<I', pe_data, o + 16)[0]
        raw_ptr = struct.unpack_from('<I', pe_data, o + 20)[0]
        sections.append((name, vsize, va, raw_size, raw_ptr))

    # Relocation directory (index 5)
    reloc_rva = 0
    reloc_size = 0
    if n_rva_sizes > 5:
        reloc_rva = struct.unpack_from('<I', pe_data, dd_off + 5 * 8)[0]
        reloc_size = struct.unpack_from('<I', pe_data, dd_off + 5 * 8 + 4)[0]

    # --- Build virtual memory image ---
    dump = bytearray(size_of_image)

    # Copy headers
    hdr_copy = min(size_of_headers, len(pe_data), size_of_image)
    dump[:hdr_copy] = pe_data[:hdr_copy]

    # Map sections
    for name, vsize, va, raw_size, raw_ptr in sections:
        if raw_ptr > 0 and raw_size > 0:
            copy_len = min(raw_size, size_of_image - va, len(pe_data) - raw_ptr)
            if copy_len > 0:
                dump[va:va + copy_len] = pe_data[raw_ptr:raw_ptr + copy_len]

    # Apply base relocations
    delta = load_addr - image_base
    if reloc_rva > 0 and reloc_size > 0 and delta != 0:
        pos = reloc_rva
        end = reloc_rva + reloc_size
        while pos < end:
            block_page = struct.unpack_from('<I', dump, pos)[0]
            block_size = struct.unpack_from('<I', dump, pos + 4)[0]
            if block_size == 0:
                break
            n_entries = (block_size - 8) // 2
            for i in range(n_entries):
                entry = struct.unpack_from('<H', dump, pos + 8 + i * 2)[0]
                etype = entry >> 12
                eoff = entry & 0xFFF
                target = block_page + eoff
                if etype == 10:  # IMAGE_REL_BASED_DIR64
                    if target + 8 <= size_of_image:
                        val = struct.unpack_from('<Q', dump, target)[0]
                        struct.pack_into('<Q', dump, target, val + delta)
                elif etype == 3:  # IMAGE_REL_BASED_HIGHLOW
                    if target + 4 <= size_of_image:
                        val = struct.unpack_from('<I', dump, target)[0]
                        struct.pack_into('<I', dump, target, (val + delta) & 0xFFFFFFFF)
                # type 0 = padding, skip
            pos += block_size

    # Write dump
    with open(dump_path, 'wb') as f:
        f.write(dump)

    # Write metadata
    meta = {
        "load_address": "0x{:016X}".format(load_addr),
        "description": "Virtual memory dump of original.exe. Sections mapped at their VirtualAddress offsets; base relocations applied for the load address."
    }
    with open(meta_path, 'w') as f:
        json.dump(meta, f, indent=2)

    print("Created memory dump:")
    print("  PE:           {}".format(pe_path))
    print("  Image base:   0x{:016X}".format(image_base))
    print("  Load address: 0x{:016X}".format(load_addr))
    print("  Delta:        0x{:016X}".format(delta & 0xFFFFFFFFFFFFFFFF))
    print("  SizeOfImage:  0x{:X} ({} bytes)".format(size_of_image, size_of_image))
    print("  Sections:     {}".format(num_sections))
    print("  Reloc RVA:    0x{:X}  Size: {}".format(reloc_rva, reloc_size))


if __name__ == '__main__':
    if len(sys.argv) != 5:
        print("Usage: {} <pe_path> <dump_path> <meta_path> <load_address_hex>".format(sys.argv[0]))
        sys.exit(1)
    create_dump(sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4], 16))
