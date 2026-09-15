"""
Verify PE reconstruction, structural analysis, and cross-tool code analysis.

"""
import json
import hashlib
import os
import re
import subprocess
import pytest
import pefile


def _hex_to_int(v):
    """Normalise a hex string or int to int for comparison."""
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        return int(v, 16)
    raise TypeError(f"cannot convert {type(v)} to int")


# ---------- Task 1: Reconstruction ----------

class TestReconstruction:
    def test_file_exists(self):
        assert os.path.isfile("/app/output/reconstructed.exe"), \
            "reconstructed.exe not found"

    def test_file_nonzero(self):
        assert os.path.getsize("/app/output/reconstructed.exe") > 0, \
            "reconstructed.exe is empty"

    def test_sha256_matches(self):
        with open("/app/.meta/expected_hash.txt") as f:
            expected = f.read().strip()
        with open("/app/output/reconstructed.exe", "rb") as f:
            actual = hashlib.sha256(f.read()).hexdigest()
        assert actual == expected, \
            f"SHA-256 mismatch:\n  expected: {expected}\n  actual:   {actual}"


# ---------- Task 2: Structural Analysis ----------

class TestPEReport:
    @pytest.fixture(autouse=True)
    def _load(self):
        with open("/app/output/pe_report.json") as f:
            self.report = json.load(f)
        self.pe = pefile.PE("/app/output/reconstructed.exe")

    def test_machine(self):
        assert _hex_to_int(self.report["machine"]) == self.pe.FILE_HEADER.Machine

    def test_number_of_sections(self):
        assert self.report["number_of_sections"] == self.pe.FILE_HEADER.NumberOfSections

    def test_entry_point(self):
        assert _hex_to_int(self.report["entry_point_rva"]) == \
            self.pe.OPTIONAL_HEADER.AddressOfEntryPoint

    def test_image_base(self):
        assert _hex_to_int(self.report["image_base"]) == \
            self.pe.OPTIONAL_HEADER.ImageBase

    def test_section_alignment(self):
        assert _hex_to_int(self.report["section_alignment"]) == \
            self.pe.OPTIONAL_HEADER.SectionAlignment

    def test_file_alignment(self):
        assert _hex_to_int(self.report["file_alignment"]) == \
            self.pe.OPTIONAL_HEADER.FileAlignment

    def test_size_of_image(self):
        assert _hex_to_int(self.report["size_of_image"]) == \
            self.pe.OPTIONAL_HEADER.SizeOfImage

    def test_size_of_headers(self):
        assert _hex_to_int(self.report["size_of_headers"]) == \
            self.pe.OPTIONAL_HEADER.SizeOfHeaders

    def test_section_count_matches(self):
        assert len(self.report["sections"]) == len(self.pe.sections)

    def test_section_names(self):
        for i, sec in enumerate(self.pe.sections):
            expected = sec.Name.decode("ascii").rstrip("\x00")
            assert self.report["sections"][i]["name"] == expected, \
                f"Section {i}: expected '{expected}'"

    def test_section_virtual_addresses(self):
        for i, sec in enumerate(self.pe.sections):
            got = _hex_to_int(self.report["sections"][i]["virtual_address"])
            assert got == sec.VirtualAddress, \
                f"Section {i} VA: expected 0x{sec.VirtualAddress:x}, got 0x{got:x}"

    def test_section_virtual_sizes(self):
        for i, sec in enumerate(self.pe.sections):
            got = _hex_to_int(self.report["sections"][i]["virtual_size"])
            assert got == sec.Misc_VirtualSize, \
                f"Section {i} VSize: expected 0x{sec.Misc_VirtualSize:x}, got 0x{got:x}"

    def test_section_raw_data_sizes(self):
        for i, sec in enumerate(self.pe.sections):
            got = _hex_to_int(self.report["sections"][i]["raw_data_size"])
            assert got == sec.SizeOfRawData, \
                f"Section {i} RawSize: expected 0x{sec.SizeOfRawData:x}, got 0x{got:x}"

    def test_import_dll_count(self):
        if hasattr(self.pe, "DIRECTORY_ENTRY_IMPORT"):
            assert len(self.report["imports"]) == len(self.pe.DIRECTORY_ENTRY_IMPORT)
        else:
            assert len(self.report.get("imports", [])) == 0

    def test_import_dll_names(self):
        if not hasattr(self.pe, "DIRECTORY_ENTRY_IMPORT"):
            return
        for i, entry in enumerate(self.pe.DIRECTORY_ENTRY_IMPORT):
            expected = entry.dll.decode("ascii")
            got = self.report["imports"][i]["dll"]
            assert got.lower() == expected.lower(), \
                f"Import {i}: expected '{expected}', got '{got}'"

    def test_import_function_names(self):
        if not hasattr(self.pe, "DIRECTORY_ENTRY_IMPORT"):
            return
        for i, entry in enumerate(self.pe.DIRECTORY_ENTRY_IMPORT):
            expected_funcs = []
            for imp in entry.imports:
                if imp.name:
                    expected_funcs.append(imp.name.decode("ascii"))
                else:
                    expected_funcs.append(f"ordinal_{imp.ordinal}")
            got_funcs = self.report["imports"][i]["functions"]
            assert len(got_funcs) == len(expected_funcs), \
                f"Import '{entry.dll.decode()}': expected {len(expected_funcs)} functions"
            for j, (g, e) in enumerate(zip(got_funcs, expected_funcs)):
                assert g == e, \
                    f"Import '{entry.dll.decode()}' func {j}: expected '{e}', got '{g}'"

    def test_relocation_entries_count(self):
        expected = 0
        if hasattr(self.pe, "DIRECTORY_ENTRY_BASERELOC"):
            for block in self.pe.DIRECTORY_ENTRY_BASERELOC:
                for entry in block.entries:
                    if entry.type != 0:
                        expected += 1
        assert self.report["relocation_entries"] == expected


# ---------- Task 3: Code Analysis ----------

class TestCodeAnalysis:
    @pytest.fixture(autouse=True)
    def _load(self):
        with open("/app/output/code_analysis.json") as f:
            self.analysis = json.load(f)
        self.pe = pefile.PE("/app/output/reconstructed.exe")

    def test_entry_point_bytes(self):
        ep_rva = self.pe.OPTIONAL_HEADER.AddressOfEntryPoint
        ep_offset = self.pe.get_offset_from_rva(ep_rva)
        with open("/app/output/reconstructed.exe", "rb") as f:
            f.seek(ep_offset)
            expected = f.read(32).hex()
        assert self.analysis["entry_point_raw_bytes"] == expected, \
            f"EP bytes mismatch:\n  expected: {expected}\n  actual:   {self.analysis['entry_point_raw_bytes']}"

    def test_call_instruction_count(self):
        result = subprocess.run(
            ["x86_64-w64-mingw32-objdump", "-d", "/app/output/reconstructed.exe"],
            capture_output=True, text=True
        )
        call_pattern = re.compile(r"\t(call|callq)\s")
        expected = sum(
            1 for line in result.stdout.split("\n")
            if call_pattern.search(line)
        )
        assert self.analysis["call_instruction_count"] == expected, \
            f"Call count mismatch: expected {expected}, got {self.analysis['call_instruction_count']}"

    def test_imported_function_list(self):
        expected = []
        if hasattr(self.pe, "DIRECTORY_ENTRY_IMPORT"):
            for entry in self.pe.DIRECTORY_ENTRY_IMPORT:
                dll = entry.dll.decode("ascii")
                for imp in entry.imports:
                    if imp.name:
                        expected.append(f"{dll}:{imp.name.decode('ascii')}")
                    else:
                        expected.append(f"{dll}:ordinal_{imp.ordinal}")
        expected.sort()
        assert self.analysis["imported_function_list"] == expected, \
            f"Import list mismatch"

    def test_total_executable_section_bytes(self):
        exe_flag = 0x20000000
        expected = sum(
            s.SizeOfRawData for s in self.pe.sections
            if s.Characteristics & exe_flag
        )
        assert self.analysis["total_executable_section_bytes"] == expected, \
            f"Exec bytes mismatch: expected {expected}"


class TestToolOutputs:
    def test_objdump_disasm_exists_and_valid(self):
        path = "/app/output/objdump_disasm.txt"
        assert os.path.isfile(path), "objdump_disasm.txt not found"
        with open(path) as f:
            content = f.read()
        assert len(content) > 100, "objdump disassembly unexpectedly short"
        assert "Disassembly of section" in content, \
            "objdump output missing expected section headers"

    def test_objdump_contains_instructions(self):
        with open("/app/output/objdump_disasm.txt") as f:
            content = f.read()
        instr_pattern = re.compile(r"^\s+[0-9a-f]+:\s+[0-9a-f ]+\t", re.MULTILINE)
        matches = instr_pattern.findall(content)
        assert len(matches) > 10, \
            "objdump output has too few disassembled instructions"

    def test_r2_analysis_exists_and_valid(self):
        path = "/app/output/r2_analysis.txt"
        assert os.path.isfile(path), "r2_analysis.txt not found"
        with open(path) as f:
            content = f.read()
        assert len(content) > 0, "r2 analysis output is empty"
        assert re.search(r"0x[0-9a-f]+", content), \
            "r2 output missing expected hex addresses"
