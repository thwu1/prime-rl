#!/usr/bin/env python3
"""
PE forensic reconstruction and analysis from virtual memory dump.

"""
import struct
import json
import os
import subprocess
import re


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def read_bytes(path):
    with open(path, "rb") as f:
        return bytearray(f.read())


def read_cstring(data, offset):
    end = offset
    while end < len(data) and data[end] != 0:
        end += 1
    return data[offset:end].decode("ascii", errors="replace")


def rva_to_offset(rva, sections):
    """Convert an RVA to a raw file offset using the section table.
    sections: list of (name, va, vsize, raw_size, raw_ptr, characteristics)
    """
    for _name, va, vsize, raw_size, raw_ptr, _chars in sections:
        limit = max(vsize, raw_size)
        if va <= rva < va + limit:
            return raw_ptr + (rva - va)
    return rva


# ---------------------------------------------------------------------------
# Task 1 – reconstruct on-disk PE from a virtual memory dump
# ---------------------------------------------------------------------------

def reconstruct_pe(dump_data, load_addr):
    dump = bytearray(dump_data)

    e_lfanew = struct.unpack_from("<I", dump, 0x3C)[0]
    coff = e_lfanew + 4
    num_sects = struct.unpack_from("<H", dump, coff + 2)[0]
    size_opt = struct.unpack_from("<H", dump, coff + 16)[0]

    opt = coff + 20
    magic = struct.unpack_from("<H", dump, opt)[0]
    pe32plus = magic == 0x20B

    if pe32plus:
        img_base = struct.unpack_from("<Q", dump, opt + 24)[0]
        file_align = struct.unpack_from("<I", dump, opt + 36)[0]
        size_hdrs = struct.unpack_from("<I", dump, opt + 60)[0]
        n_dd = struct.unpack_from("<I", dump, opt + 108)[0]
        dd_off = opt + 112
    else:
        img_base = struct.unpack_from("<I", dump, opt + 28)[0]
        file_align = struct.unpack_from("<I", dump, opt + 36)[0]
        size_hdrs = struct.unpack_from("<I", dump, opt + 60)[0]
        n_dd = struct.unpack_from("<I", dump, opt + 92)[0]
        dd_off = opt + 96

    delta = load_addr - img_base

    sec_base = opt + size_opt
    sections = []
    for i in range(num_sects):
        o = sec_base + i * 40
        vs = struct.unpack_from("<I", dump, o + 8)[0]
        va = struct.unpack_from("<I", dump, o + 12)[0]
        rs = struct.unpack_from("<I", dump, o + 16)[0]
        rp = struct.unpack_from("<I", dump, o + 20)[0]
        sections.append((va, vs, rs, rp))

    # Un-apply relocations
    if n_dd > 5 and delta != 0:
        rel_rva = struct.unpack_from("<I", dump, dd_off + 5 * 8)[0]
        rel_sz = struct.unpack_from("<I", dump, dd_off + 5 * 8 + 4)[0]
        if rel_rva > 0 and rel_sz > 0:
            pos = rel_rva
            end = rel_rva + rel_sz
            while pos < end:
                block_page = struct.unpack_from("<I", dump, pos)[0]
                block_size = struct.unpack_from("<I", dump, pos + 4)[0]
                if block_size == 0:
                    break
                n = (block_size - 8) // 2
                for i in range(n):
                    entry = struct.unpack_from("<H", dump, pos + 8 + i * 2)[0]
                    etype = entry >> 12
                    eoff = entry & 0xFFF
                    target = block_page + eoff
                    if etype == 10:  # IMAGE_REL_BASED_DIR64
                        if target + 8 <= len(dump):
                            val = struct.unpack_from("<Q", dump, target)[0]
                            struct.pack_into("<Q", dump, target, val - delta)
                    elif etype == 3:  # IMAGE_REL_BASED_HIGHLOW
                        if target + 4 <= len(dump):
                            val = struct.unpack_from("<I", dump, target)[0]
                            struct.pack_into(
                                "<I", dump, target, (val - delta) & 0xFFFFFFFF
                            )
                pos += block_size

    # Assemble on-disk file
    file_size = size_hdrs
    for va, vs, rs, rp in sections:
        end = rp + rs
        if end > file_size:
            file_size = end

    output = bytearray(file_size)
    output[:size_hdrs] = dump[:size_hdrs]

    for va, vs, rs, rp in sections:
        if rp > 0 and rs > 0:
            copy_len = min(rs, max(0, len(dump) - va))
            if copy_len > 0:
                output[rp:rp + copy_len] = dump[va:va + copy_len]

    return bytes(output)


# ---------------------------------------------------------------------------
# Task 2 – parse an on-disk PE and produce a structural report
# ---------------------------------------------------------------------------

def parse_pe(data):
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    coff = e_lfanew + 4
    machine = struct.unpack_from("<H", data, coff)[0]
    num_sects = struct.unpack_from("<H", data, coff + 2)[0]
    size_opt = struct.unpack_from("<H", data, coff + 16)[0]

    opt = coff + 20
    magic = struct.unpack_from("<H", data, opt)[0]
    pe32plus = magic == 0x20B

    ep_rva = struct.unpack_from("<I", data, opt + 16)[0]

    if pe32plus:
        img_base = struct.unpack_from("<Q", data, opt + 24)[0]
        sect_align = struct.unpack_from("<I", data, opt + 32)[0]
        file_align = struct.unpack_from("<I", data, opt + 36)[0]
        size_image = struct.unpack_from("<I", data, opt + 56)[0]
        size_hdrs = struct.unpack_from("<I", data, opt + 60)[0]
        n_dd = struct.unpack_from("<I", data, opt + 108)[0]
        dd_off = opt + 112
    else:
        img_base = struct.unpack_from("<I", data, opt + 28)[0]
        sect_align = struct.unpack_from("<I", data, opt + 32)[0]
        file_align = struct.unpack_from("<I", data, opt + 36)[0]
        size_image = struct.unpack_from("<I", data, opt + 56)[0]
        size_hdrs = struct.unpack_from("<I", data, opt + 60)[0]
        n_dd = struct.unpack_from("<I", data, opt + 92)[0]
        dd_off = opt + 96

    dd = []
    for i in range(min(n_dd, 16)):
        rva = struct.unpack_from("<I", data, dd_off + i * 8)[0]
        sz = struct.unpack_from("<I", data, dd_off + i * 8 + 4)[0]
        dd.append((rva, sz))

    sec_base = opt + size_opt
    sections = []
    for i in range(num_sects):
        o = sec_base + i * 40
        raw_name = data[o:o + 8]
        name = raw_name.split(b"\x00")[0].decode("ascii", errors="replace")
        vs = struct.unpack_from("<I", data, o + 8)[0]
        va = struct.unpack_from("<I", data, o + 12)[0]
        rs = struct.unpack_from("<I", data, o + 16)[0]
        rp = struct.unpack_from("<I", data, o + 20)[0]
        ch = struct.unpack_from("<I", data, o + 36)[0]
        sections.append((name, va, vs, rs, rp, ch))

    # Import directory (index 1)
    imports = []
    if len(dd) > 1 and dd[1][0] > 0:
        pos = rva_to_offset(dd[1][0], sections)
        while True:
            ilt_rva = struct.unpack_from("<I", data, pos)[0]
            name_rva = struct.unpack_from("<I", data, pos + 12)[0]
            iat_rva = struct.unpack_from("<I", data, pos + 16)[0]
            if name_rva == 0:
                break
            dll_name = read_cstring(data, rva_to_offset(name_rva, sections))
            thunk_rva = ilt_rva if ilt_rva != 0 else iat_rva
            thunk_off = rva_to_offset(thunk_rva, sections)
            funcs = []
            while True:
                if pe32plus:
                    td = struct.unpack_from("<Q", data, thunk_off)[0]
                    thunk_off += 8
                else:
                    td = struct.unpack_from("<I", data, thunk_off)[0]
                    thunk_off += 4
                if td == 0:
                    break
                ordinal_flag = 0x8000000000000000 if pe32plus else 0x80000000
                if td & ordinal_flag:
                    funcs.append(f"ordinal_{td & 0xFFFF}")
                else:
                    mask = 0x7FFFFFFFFFFFFFFF if pe32plus else 0x7FFFFFFF
                    hint_off = rva_to_offset(td & mask, sections)
                    funcs.append(read_cstring(data, hint_off + 2))
            imports.append({"dll": dll_name, "functions": funcs})
            pos += 20

    # Relocation directory (index 5)
    total_relocs = 0
    if len(dd) > 5 and dd[5][0] > 0:
        rel_off = rva_to_offset(dd[5][0], sections)
        end_off = rel_off + dd[5][1]
        pos = rel_off
        while pos < end_off:
            bsz = struct.unpack_from("<I", data, pos + 4)[0]
            if bsz == 0:
                break
            n = (bsz - 8) // 2
            for i in range(n):
                entry = struct.unpack_from("<H", data, pos + 8 + i * 2)[0]
                if (entry >> 12) != 0:
                    total_relocs += 1
            pos += bsz

    report = {
        "machine": f"0x{machine:x}",
        "number_of_sections": num_sects,
        "entry_point_rva": f"0x{ep_rva:x}",
        "image_base": f"0x{img_base:x}",
        "section_alignment": f"0x{sect_align:x}",
        "file_alignment": f"0x{file_align:x}",
        "size_of_image": f"0x{size_image:x}",
        "size_of_headers": f"0x{size_hdrs:x}",
        "sections": [
            {
                "name": name,
                "virtual_address": f"0x{va:x}",
                "virtual_size": f"0x{vs:x}",
                "raw_data_size": f"0x{rs:x}",
                "raw_data_pointer": f"0x{rp:x}",
                "characteristics": f"0x{ch:08x}",
            }
            for name, va, vs, rs, rp, ch in sections
        ],
        "imports": imports,
        "relocation_entries": total_relocs,
    }

    return report, sections


# ---------------------------------------------------------------------------
# Task 3 – cross-tool code analysis
# ---------------------------------------------------------------------------

def run_code_analysis(pe_data, report, sections):
    """Run objdump and radare2, then compute code analysis metrics."""

    # Generate objdump disassembly
    objdump_result = subprocess.run(
        ["x86_64-w64-mingw32-objdump", "-d", "/app/output/reconstructed.exe"],
        capture_output=True, text=True
    )
    with open("/app/output/objdump_disasm.txt", "w") as f:
        f.write(objdump_result.stdout)

    # Generate radare2 function analysis
    r2_result = subprocess.run(
        ["r2", "-q", "-c", "aaa; afl", "/app/output/reconstructed.exe"],
        capture_output=True, text=True, timeout=120
    )
    with open("/app/output/r2_analysis.txt", "w") as f:
        f.write(r2_result.stdout)

    # Count call instructions from objdump output
    call_pattern = re.compile(r"\t(call|callq)\s")
    call_count = sum(
        1 for line in objdump_result.stdout.split("\n")
        if call_pattern.search(line)
    )

    # Entry point raw bytes
    ep_rva = int(report["entry_point_rva"], 16)
    ep_offset = rva_to_offset(ep_rva, sections)
    ep_bytes = pe_data[ep_offset:ep_offset + 32].hex()

    # Imported function list (DLL:function, sorted)
    imported = []
    for imp_entry in report["imports"]:
        for func in imp_entry["functions"]:
            imported.append(f"{imp_entry['dll']}:{func}")
    imported.sort()

    # Total executable section bytes
    exe_flag = 0x20000000
    total_exec = sum(
        int(s["raw_data_size"], 16)
        for s in report["sections"]
        if int(s["characteristics"], 16) & exe_flag
    )

    return {
        "entry_point_raw_bytes": ep_bytes,
        "call_instruction_count": call_count,
        "imported_function_list": imported,
        "total_executable_section_bytes": total_exec,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    os.makedirs("/app/output", exist_ok=True)

    # --- Task 1: Reconstruct PE from memory dump ---
    dump = read_bytes("/app/samples/memory_dump.bin")
    with open("/app/samples/dump_meta.json") as f:
        meta = json.load(f)
    load_addr = int(meta["load_address"], 16)

    reconstructed = reconstruct_pe(dump, load_addr)
    with open("/app/output/reconstructed.exe", "wb") as f:
        f.write(reconstructed)
    print(f"reconstructed.exe written ({len(reconstructed)} bytes)")

    # --- Task 2: Structural analysis ---
    pe_data = read_bytes("/app/output/reconstructed.exe")
    report, sections = parse_pe(pe_data)
    with open("/app/output/pe_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print(
        f"pe_report.json written  "
        f"({report['number_of_sections']} sections, "
        f"{len(report['imports'])} imports, "
        f"{report['relocation_entries']} relocations)"
    )

    # --- Task 3: Code analysis with tools ---
    code_analysis = run_code_analysis(pe_data, report, sections)
    with open("/app/output/code_analysis.json", "w") as f:
        json.dump(code_analysis, f, indent=2)
    print(
        f"code_analysis.json written  "
        f"({code_analysis['call_instruction_count']} calls, "
        f"{len(code_analysis['imported_function_list'])} imports, "
        f"{code_analysis['total_executable_section_bytes']} exec bytes)"
    )


if __name__ == "__main__":
    main()
