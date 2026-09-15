#!/usr/bin/env python3
"""
PE Import Editor - Analyze and modify Windows PE binary import tables.
Implemented from scratch with no third-party PE parsing libraries.

"""

import struct
import json
import sys
import subprocess
import re

# PE constants
IMAGE_DOS_SIGNATURE = 0x5A4D
IMAGE_NT_SIGNATURE = 0x00004550
IMAGE_FILE_MACHINE_I386 = 0x14C
IMAGE_FILE_MACHINE_AMD64 = 0x8664
IMAGE_OPTIONAL_HDR32_MAGIC = 0x10B
IMAGE_OPTIONAL_HDR64_MAGIC = 0x20B
IMAGE_DIRECTORY_ENTRY_EXPORT = 0
IMAGE_DIRECTORY_ENTRY_IMPORT = 1
IMAGE_SCN_CNT_INITIALIZED_DATA = 0x00000040
IMAGE_SCN_MEM_READ = 0x40000000
IMAGE_SCN_MEM_WRITE = 0x80000000


def align_up(value, alignment):
    if alignment == 0:
        return value
    return (value + alignment - 1) & ~(alignment - 1)


class PEFile:
    def __init__(self, filepath):
        with open(filepath, "rb") as f:
            self.data = bytearray(f.read())
        self.sections = []
        self._parse()

    def _parse(self):
        # DOS Header
        dos_magic = struct.unpack_from("<H", self.data, 0)[0]
        if dos_magic != IMAGE_DOS_SIGNATURE:
            raise ValueError("Invalid DOS signature (expected MZ)")
        self.e_lfanew = struct.unpack_from("<I", self.data, 0x3C)[0]

        # PE Signature
        pe_sig = struct.unpack_from("<I", self.data, self.e_lfanew)[0]
        if pe_sig != IMAGE_NT_SIGNATURE:
            raise ValueError("Invalid PE signature")

        # COFF Header (20 bytes after PE signature)
        coff_off = self.e_lfanew + 4
        (
            self.machine,
            self.num_sections,
            self.timestamp,
            self.symbol_table_ptr,
            self.num_symbols,
            self.opt_header_size,
            self.characteristics,
        ) = struct.unpack_from("<HHIIIHH", self.data, coff_off)

        # Optional Header
        self.opt_off = coff_off + 20
        self.magic = struct.unpack_from("<H", self.data, self.opt_off)[0]

        if self.magic == IMAGE_OPTIONAL_HDR32_MAGIC:
            self.is_pe32plus = False
            self.format_str = "PE32"
            self.entry_point = struct.unpack_from("<I", self.data, self.opt_off + 16)[0]
            self.image_base = struct.unpack_from("<I", self.data, self.opt_off + 28)[0]
            self.section_alignment = struct.unpack_from(
                "<I", self.data, self.opt_off + 32
            )[0]
            self.file_alignment = struct.unpack_from(
                "<I", self.data, self.opt_off + 36
            )[0]
            self.size_of_image = struct.unpack_from(
                "<I", self.data, self.opt_off + 56
            )[0]
            self.size_of_headers = struct.unpack_from(
                "<I", self.data, self.opt_off + 60
            )[0]
            self.num_data_dirs = struct.unpack_from(
                "<I", self.data, self.opt_off + 92
            )[0]
            self.data_dir_off = self.opt_off + 96

        elif self.magic == IMAGE_OPTIONAL_HDR64_MAGIC:
            self.is_pe32plus = True
            self.format_str = "PE32+"
            self.entry_point = struct.unpack_from("<I", self.data, self.opt_off + 16)[0]
            self.image_base = struct.unpack_from("<Q", self.data, self.opt_off + 24)[0]
            self.section_alignment = struct.unpack_from(
                "<I", self.data, self.opt_off + 32
            )[0]
            self.file_alignment = struct.unpack_from(
                "<I", self.data, self.opt_off + 36
            )[0]
            self.size_of_image = struct.unpack_from(
                "<I", self.data, self.opt_off + 56
            )[0]
            self.size_of_headers = struct.unpack_from(
                "<I", self.data, self.opt_off + 60
            )[0]
            self.num_data_dirs = struct.unpack_from(
                "<I", self.data, self.opt_off + 108
            )[0]
            self.data_dir_off = self.opt_off + 112
        else:
            raise ValueError(f"Unknown optional header magic: 0x{self.magic:04X}")

        # Section Headers
        self.sections_off = self.opt_off + self.opt_header_size
        self.sections = []
        for i in range(self.num_sections):
            sec_off = self.sections_off + i * 40
            raw_name = self.data[sec_off : sec_off + 8]
            name = raw_name.rstrip(b"\x00").decode("ascii", errors="replace")
            (
                virtual_size,
                virtual_address,
                raw_size,
                raw_offset,
                reloc_ptr,
                linenum_ptr,
                num_relocs,
                num_linenums,
                chars,
            ) = struct.unpack_from("<IIIIIIHHI", self.data, sec_off + 8)
            self.sections.append(
                {
                    "name": name,
                    "virtual_size": virtual_size,
                    "virtual_address": virtual_address,
                    "raw_size": raw_size,
                    "raw_offset": raw_offset,
                    "characteristics": chars,
                }
            )

    def rva_to_offset(self, rva):
        """Convert an RVA to a file offset using section mappings."""
        for sec in self.sections:
            va = sec["virtual_address"]
            vs = sec["virtual_size"]
            rs = sec["raw_size"]
            limit = max(vs, rs) if vs > 0 else rs
            if va <= rva < va + limit:
                file_off = rva - va
                if file_off < rs:
                    return sec["raw_offset"] + file_off
                return None
        if rva < self.size_of_headers:
            return rva
        return None

    def read_string_at(self, offset):
        """Read a null-terminated ASCII string at the given file offset."""
        end = self.data.index(b"\x00", offset)
        return self.data[offset:end].decode("ascii", errors="replace")

    def get_data_directory(self, index):
        """Return (rva, size) for the given data directory index."""
        if index >= self.num_data_dirs:
            return 0, 0
        off = self.data_dir_off + index * 8
        return struct.unpack_from("<II", self.data, off)

    def get_imports(self):
        """Parse the Import Directory Table and return {dll: [functions]}."""
        import_rva, import_size = self.get_data_directory(IMAGE_DIRECTORY_ENTRY_IMPORT)
        if import_rva == 0:
            return {}

        import_off = self.rva_to_offset(import_rva)
        if import_off is None:
            return {}

        imports = {}
        off = import_off
        entry_size = 8 if self.is_pe32plus else 4
        ordinal_flag = 0x8000000000000000 if self.is_pe32plus else 0x80000000

        while True:
            ilt_rva, timestamp, forwarder_chain, name_rva, iat_rva = (
                struct.unpack_from("<IIIII", self.data, off)
            )
            if name_rva == 0:
                break

            name_off = self.rva_to_offset(name_rva)
            if name_off is None:
                off += 20
                continue
            dll_name = self.read_string_at(name_off)

            # Use ILT if available, otherwise fall back to IAT
            thunk_rva = ilt_rva if ilt_rva != 0 else iat_rva
            thunk_off = self.rva_to_offset(thunk_rva)
            if thunk_off is None:
                off += 20
                continue

            functions = []
            t_off = thunk_off
            while True:
                if self.is_pe32plus:
                    entry = struct.unpack_from("<Q", self.data, t_off)[0]
                else:
                    entry = struct.unpack_from("<I", self.data, t_off)[0]

                if entry == 0:
                    break

                if entry & ordinal_flag:
                    ordinal = entry & 0xFFFF
                    functions.append(f"ordinal:{ordinal}")
                else:
                    hint_rva = entry & (
                        0x7FFFFFFFFFFFFFFF if self.is_pe32plus else 0x7FFFFFFF
                    )
                    hint_off = self.rva_to_offset(hint_rva)
                    if hint_off is not None:
                        func_name = self.read_string_at(hint_off + 2)
                        functions.append(func_name)

                t_off += entry_size

            imports[dll_name] = functions
            off += 20

        return imports

    def get_exports(self):
        """Parse the Export Directory Table."""
        export_rva, export_size = self.get_data_directory(IMAGE_DIRECTORY_ENTRY_EXPORT)
        if export_rva == 0:
            return None

        export_off = self.rva_to_offset(export_rva)
        if export_off is None:
            return None

        (
            _characteristics,
            _timestamp,
            _major_ver,
            _minor_ver,
            name_rva,
            ordinal_base,
            num_functions,
            num_names,
            addr_funcs_rva,
            addr_names_rva,
            addr_ords_rva,
        ) = struct.unpack_from("<IIHHIIIIIII", self.data, export_off)

        dll_name_off = self.rva_to_offset(name_rva)
        dll_name = self.read_string_at(dll_name_off) if dll_name_off else ""

        # Read function RVAs
        func_addrs = []
        fa_off = self.rva_to_offset(addr_funcs_rva)
        if fa_off is not None:
            for i in range(num_functions):
                rva = struct.unpack_from("<I", self.data, fa_off + i * 4)[0]
                func_addrs.append(rva)

        # Build ordinal-index -> name mapping
        name_map = {}
        if addr_names_rva and addr_ords_rva:
            names_off = self.rva_to_offset(addr_names_rva)
            ords_off = self.rva_to_offset(addr_ords_rva)
            if names_off is not None and ords_off is not None:
                for i in range(num_names):
                    n_rva = struct.unpack_from("<I", self.data, names_off + i * 4)[0]
                    ordinal_idx = struct.unpack_from("<H", self.data, ords_off + i * 2)[
                        0
                    ]
                    n_off = self.rva_to_offset(n_rva)
                    if n_off is not None:
                        name_map[ordinal_idx] = self.read_string_at(n_off)

        functions = []
        for i in range(num_functions):
            if i >= len(func_addrs) or func_addrs[i] == 0:
                continue
            func = {"ordinal": ordinal_base + i, "rva": func_addrs[i]}
            if i in name_map:
                func["name"] = name_map[i]
            # Detect forwarded exports (RVA points inside export directory)
            if export_rva <= func_addrs[i] < export_rva + export_size:
                fwd_off = self.rva_to_offset(func_addrs[i])
                if fwd_off is not None:
                    func["forwarded_to"] = self.read_string_at(fwd_off)
            functions.append(func)

        return {
            "dll_name": dll_name,
            "ordinal_base": ordinal_base,
            "functions": functions,
        }

    def analyze(self):
        """Return a dict with complete PE analysis."""
        machine_names = {
            IMAGE_FILE_MACHINE_I386: "I386",
            IMAGE_FILE_MACHINE_AMD64: "AMD64",
        }
        result = {
            "format": self.format_str,
            "machine": machine_names.get(self.machine, f"0x{self.machine:04X}"),
            "num_sections": self.num_sections,
            "entry_point_rva": self.entry_point,
            "image_base": self.image_base,
            "sections": [
                {
                    "name": s["name"],
                    "virtual_address": s["virtual_address"],
                    "virtual_size": s["virtual_size"],
                    "raw_size": s["raw_size"],
                    "raw_offset": s["raw_offset"],
                }
                for s in self.sections
            ],
            "imports": self.get_imports(),
        }

        exports = self.get_exports()
        if exports:
            result["exports"] = {
                "dll_name": exports["dll_name"],
                "functions": [
                    {
                        "name": f.get("name", ""),
                        "ordinal": f["ordinal"],
                        "rva": f["rva"],
                    }
                    for f in exports["functions"]
                ],
            }

        return result

    def inject_import(self, output_path, dll_name, func_name):
        """Add a new import entry and write the modified PE to output_path.

        Rebuilds the entire import table in a new .idata section so that
        all import data (descriptors, ILTs, IATs, name strings, hint/name
        records) is self-contained within one section.  This is essential
        because GNU binutils objdump reads all import data relative to the
        section that contains the Import Directory RVA — if existing
        descriptors' Name/ILT RVAs point to a different section, objdump
        cannot resolve them.
        """
        data = bytearray(self.data)
        entry_size = 8 if self.is_pe32plus else 4
        ordinal_flag = (
            0x8000000000000000 if self.is_pe32plus else 0x80000000
        )

        # Read all existing imports via our parser
        existing_imports = self.get_imports()

        # Merge the new import (case-insensitive DLL match)
        merged = False
        for k in existing_imports:
            if k.upper() == dll_name.upper():
                if func_name not in existing_imports[k]:
                    existing_imports[k].append(func_name)
                merged = True
                break
        if not merged:
            existing_imports[dll_name] = [func_name]

        # --- Compute new section placement ---
        max_va_end = max(
            s["virtual_address"] + max(s["virtual_size"], s["raw_size"])
            for s in self.sections
        )
        new_va = align_up(max_va_end, self.section_alignment)

        max_raw_end = max(
            s["raw_offset"] + s["raw_size"]
            for s in self.sections
            if s["raw_offset"] > 0
        )
        new_raw_off = align_up(max_raw_end, self.file_alignment)

        # === Build self-contained .idata section content ===
        num_dlls = len(existing_imports)
        idt_total = (num_dlls + 1) * 20  # descriptors + null terminator

        # Phase 1: reserve IDT space (filled in phase 3)
        content = bytearray(idt_total)

        # Phase 2: per-DLL data — strings, hint/names, ILT, IAT
        per_dll = []  # [(dll_name_secoff, ilt_secoff, iat_secoff)]

        for dll, funcs in existing_imports.items():
            # DLL name string
            dn_off = len(content)
            content.extend(dll.encode("ascii") + b"\x00")
            # 2-byte alignment for subsequent hint/name records
            if len(content) % 2:
                content.append(0)

            # Hint/Name records
            func_meta = []  # [("ordinal", val) | ("name", secoff)]
            for fn in funcs:
                if fn.startswith("ordinal:"):
                    func_meta.append(("ordinal", int(fn.split(":")[1])))
                else:
                    hn_off = len(content)
                    content.extend(struct.pack("<H", 0))  # hint = 0
                    content.extend(fn.encode("ascii") + b"\x00")
                    if len(content) % 2:
                        content.append(0)
                    func_meta.append(("name", hn_off))

            # ILT (Import Lookup Table)
            ilt_off = len(content)
            for ftype, fval in func_meta:
                if ftype == "ordinal":
                    val = ordinal_flag | fval
                else:
                    val = new_va + fval  # RVA of hint/name in new section
                if self.is_pe32plus:
                    content.extend(struct.pack("<Q", val))
                else:
                    content.extend(struct.pack("<I", val))
            content.extend(b"\x00" * entry_size)  # null terminator

            # IAT (identical to ILT in on-disk PE files)
            iat_off = len(content)
            for ftype, fval in func_meta:
                if ftype == "ordinal":
                    val = ordinal_flag | fval
                else:
                    val = new_va + fval
                if self.is_pe32plus:
                    content.extend(struct.pack("<Q", val))
                else:
                    content.extend(struct.pack("<I", val))
            content.extend(b"\x00" * entry_size)  # null terminator

            per_dll.append((dn_off, ilt_off, iat_off))

        # Phase 3: fill in IDT entries
        for i, (dn_off, ilt_off, iat_off) in enumerate(per_dll):
            struct.pack_into(
                "<IIIII",
                content,
                i * 20,
                new_va + ilt_off,   # OriginalFirstThunk (ILT)
                0,                   # TimeDateStamp
                0,                   # ForwarderChain
                new_va + dn_off,     # Name
                new_va + iat_off,    # FirstThunk (IAT)
            )
        # Null-terminator IDT entry is already zeroed

        # Pad to file alignment
        raw_size = align_up(len(content), self.file_alignment)
        content.extend(b"\x00" * (raw_size - len(content)))
        virtual_size = raw_size

        # --- Header updates ---

        # Verify space for new section header
        sec_header_off = self.sections_off + self.num_sections * 40
        if sec_header_off + 40 > self.size_of_headers:
            raise ValueError(
                "No space for additional section header in PE headers area"
            )

        # Rename any existing .idata section to avoid ambiguity
        for i in range(self.num_sections):
            soff = self.sections_off + i * 40
            sname = data[soff : soff + 8].rstrip(b"\x00")
            if sname == b".idata":
                data[soff : soff + 8] = b".oidata\x00"
                break

        # Write new .idata section header
        sec_header = struct.pack(
            "<8sIIIIIIHHI",
            b".idata\x00\x00",
            virtual_size,
            new_va,
            raw_size,
            new_raw_off,
            0,  # PointerToRelocations
            0,  # PointerToLinenumbers
            0,  # NumberOfRelocations
            0,  # NumberOfLinenumbers
            IMAGE_SCN_CNT_INITIALIZED_DATA | IMAGE_SCN_MEM_READ | IMAGE_SCN_MEM_WRITE,
        )
        data[sec_header_off : sec_header_off + 40] = sec_header

        # Update COFF header: NumberOfSections
        coff_off = self.e_lfanew + 4
        struct.pack_into("<H", data, coff_off + 2, self.num_sections + 1)

        # Update Import data directory to point to new IDT
        dd_off = self.data_dir_off + IMAGE_DIRECTORY_ENTRY_IMPORT * 8
        struct.pack_into("<II", data, dd_off, new_va, idt_total)

        # Update SizeOfImage
        new_soi = align_up(new_va + virtual_size, self.section_alignment)
        struct.pack_into("<I", data, self.opt_off + 56, new_soi)

        # Ensure file is large enough and write section content
        total_size = new_raw_off + raw_size
        if len(data) < total_size:
            data.extend(b"\x00" * (total_size - len(data)))
        data[new_raw_off : new_raw_off + raw_size] = content

        with open(output_path, "wb") as f:
            f.write(data)


def validate_pe(pe_file):
    """Cross-check analyze output against objdump -p.

    Uses a robust comparison strategy: extract DLL names from objdump via
    the unambiguous 'DLL Name:' lines, then verify each named import and
    export function appears in the objdump output using word-boundary search.
    This avoids fragile line-format parsing that breaks across objdump versions.
    """
    pe = PEFile(pe_file)
    analysis = pe.analyze()

    # Find a working PE-capable objdump
    objdump_output = ""
    for cmd in [
        "i686-w64-mingw32-objdump",
        "x86_64-w64-mingw32-objdump",
        "objdump",
    ]:
        try:
            proc = subprocess.run(
                [cmd, "-p", pe_file],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if proc.returncode == 0 and "file format" in proc.stdout:
                objdump_output = proc.stdout
                break
        except FileNotFoundError:
            continue

    if not objdump_output:
        print("MISMATCH: no PE-capable objdump found in PATH", file=sys.stderr)
        sys.exit(1)

    mismatches = []

    # --- Compare imported DLL names (case-insensitive) ---
    objdump_dll_set = set()
    for m in re.finditer(r"DLL Name:\s*(\S+)", objdump_output):
        objdump_dll_set.add(m.group(1).upper())

    analyzer_dll_set = {k.upper() for k in analysis.get("imports", {})}

    if objdump_dll_set != analyzer_dll_set:
        mismatches.append(
            f"Imported DLLs differ: "
            f"analyzer={sorted(analyzer_dll_set)} "
            f"objdump={sorted(objdump_dll_set)}"
        )

    # --- Verify each named import function appears in objdump output ---
    for dll, funcs in analysis.get("imports", {}).items():
        for func in funcs:
            if func.startswith("ordinal:"):
                continue
            pattern = r'\b' + re.escape(func) + r'\b'
            if not re.search(pattern, objdump_output):
                mismatches.append(
                    f"Import {func} from {dll} not found in objdump output"
                )

    # --- Verify each named export function appears in objdump output ---
    if analysis.get("exports"):
        for f in analysis["exports"]["functions"]:
            name = f.get("name", "")
            if not name:
                continue
            pattern = r'\b' + re.escape(name) + r'\b'
            if not re.search(pattern, objdump_output):
                mismatches.append(
                    f"Export {name} not found in objdump output"
                )

    if mismatches:
        print("MISMATCH: " + "; ".join(mismatches))
        sys.exit(1)
    else:
        print("VALID")
        sys.exit(0)


def main():
    if len(sys.argv) < 2:
        print(
            "Usage:\n"
            "  pe_import_editor.py analyze <pe_file>\n"
            "  pe_import_editor.py inject <input> <output> <dll> <function>\n"
            "  pe_import_editor.py validate <pe_file>",
            file=sys.stderr,
        )
        sys.exit(1)

    command = sys.argv[1]

    if command == "analyze":
        if len(sys.argv) != 3:
            print("Usage: pe_import_editor.py analyze <pe_file>", file=sys.stderr)
            sys.exit(1)
        pe = PEFile(sys.argv[2])
        print(json.dumps(pe.analyze(), indent=2))

    elif command == "inject":
        if len(sys.argv) != 6:
            print(
                "Usage: pe_import_editor.py inject <input> <output> <dll> <function>",
                file=sys.stderr,
            )
            sys.exit(1)
        pe = PEFile(sys.argv[2])
        pe.inject_import(sys.argv[3], sys.argv[4], sys.argv[5])
        print(
            f"Injected import {sys.argv[5]} from {sys.argv[4]} into {sys.argv[3]}",
            file=sys.stderr,
        )

    elif command == "validate":
        if len(sys.argv) != 3:
            print("Usage: pe_import_editor.py validate <pe_file>", file=sys.stderr)
            sys.exit(1)
        validate_pe(sys.argv[2])

    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
