
import subprocess
import json
import os
import pytest
import pefile

SAMPLES_DIR = "/app/samples"
BUILD_SRC = "/app/build_src"
EDITOR = "/app/pe_import_editor.py"


def run_editor(*args):
    result = subprocess.run(
        ["python3", EDITOR] + list(args),
        capture_output=True, text=True, timeout=30
    )
    return result


def run_analyze(pe_file):
    result = run_editor("analyze", pe_file)
    assert result.returncode == 0, f"Analyze failed for {pe_file}: {result.stderr}"
    return json.loads(result.stdout)


def pefile_imports(pe_path):
    """Get imports using pefile as ground-truth oracle."""
    pe = pefile.PE(pe_path)
    imports = {}
    if hasattr(pe, "DIRECTORY_ENTRY_IMPORT"):
        for entry in pe.DIRECTORY_ENTRY_IMPORT:
            dll = entry.dll.decode("ascii", errors="replace")
            funcs = []
            for imp in entry.imports:
                if imp.name:
                    funcs.append(imp.name.decode("ascii"))
                else:
                    funcs.append(f"ordinal:{imp.ordinal}")
            imports[dll] = funcs
    pe.close()
    return imports


def pefile_exports(pe_path):
    """Get export names using pefile as ground-truth oracle."""
    pe = pefile.PE(pe_path)
    names = []
    if hasattr(pe, "DIRECTORY_ENTRY_EXPORT"):
        for sym in pe.DIRECTORY_ENTRY_EXPORT.symbols:
            if sym.name:
                names.append(sym.name.decode("ascii"))
    pe.close()
    return names


def pefile_info(pe_path):
    """Get basic PE info using pefile as ground-truth oracle."""
    pe = pefile.PE(pe_path)
    info = {
        "format": "PE32" if pe.OPTIONAL_HEADER.Magic == 0x10B else "PE32+",
        "machine": {0x14C: "I386", 0x8664: "AMD64"}.get(
            pe.FILE_HEADER.Machine, hex(pe.FILE_HEADER.Machine)
        ),
        "num_sections": pe.FILE_HEADER.NumberOfSections,
        "entry_point_rva": pe.OPTIONAL_HEADER.AddressOfEntryPoint,
        "image_base": pe.OPTIONAL_HEADER.ImageBase,
    }
    pe.close()
    return info


def compare_imports(parsed, pe_path):
    """Compare parsed imports against pefile oracle."""
    expected = pefile_imports(pe_path)
    parsed_dlls = {k.upper() for k in parsed.get("imports", {})}
    expected_dlls = {k.upper() for k in expected}
    assert parsed_dlls == expected_dlls, (
        f"DLL mismatch: got {parsed_dlls}, expected {expected_dlls}"
    )
    for dll, expected_funcs in expected.items():
        parsed_dll = None
        for k in parsed["imports"]:
            if k.upper() == dll.upper():
                parsed_dll = k
                break
        assert parsed_dll is not None, f"Missing DLL: {dll}"
        parsed_funcs = set(parsed["imports"][parsed_dll])
        assert parsed_funcs == set(expected_funcs), (
            f"Function mismatch for {dll}: "
            f"got {sorted(parsed_funcs)}, expected {sorted(expected_funcs)}"
        )


class TestSampleCompilation:
    """Verify PE samples were compiled from provided source."""

    def test_build_sources_exist(self):
        for name in ["hello32.c", "multi64.c", "mathlib.c"]:
            assert os.path.isfile(os.path.join(BUILD_SRC, name)), (
                f"Build source {name} not found at {BUILD_SRC}"
            )

    def test_hello32_exists(self):
        path = os.path.join(SAMPLES_DIR, "hello32.exe")
        assert os.path.isfile(path), (
            "hello32.exe not found — compile from /app/build_src/hello32.c"
        )

    def test_multi64_exists(self):
        path = os.path.join(SAMPLES_DIR, "multi64.exe")
        assert os.path.isfile(path), (
            "multi64.exe not found — compile from /app/build_src/multi64.c"
        )

    def test_mathlib_exists(self):
        path = os.path.join(SAMPLES_DIR, "mathlib.dll")
        assert os.path.isfile(path), (
            "mathlib.dll not found — compile from /app/build_src/mathlib.c"
        )

    def test_hello32_is_pe32(self):
        pe = pefile.PE(os.path.join(SAMPLES_DIR, "hello32.exe"))
        assert pe.OPTIONAL_HEADER.Magic == 0x10B, "hello32.exe must be PE32 (32-bit)"
        assert pe.FILE_HEADER.Machine == 0x14C, "hello32.exe must target I386"
        pe.close()

    def test_multi64_is_pe64(self):
        pe = pefile.PE(os.path.join(SAMPLES_DIR, "multi64.exe"))
        assert pe.OPTIONAL_HEADER.Magic == 0x20B, "multi64.exe must be PE32+ (64-bit)"
        assert pe.FILE_HEADER.Machine == 0x8664, "multi64.exe must target AMD64"
        pe.close()

    def test_mathlib_is_dll_with_exports(self):
        pe = pefile.PE(os.path.join(SAMPLES_DIR, "mathlib.dll"))
        assert pe.OPTIONAL_HEADER.Magic == 0x10B, "mathlib.dll must be PE32"
        assert hasattr(pe, "DIRECTORY_ENTRY_EXPORT"), "mathlib.dll must have exports"
        export_names = {
            s.name.decode("ascii")
            for s in pe.DIRECTORY_ENTRY_EXPORT.symbols
            if s.name
        }
        assert "add_numbers" in export_names
        assert "multiply_numbers" in export_names
        assert "factorial" in export_names
        pe.close()


class TestSourceConstraints:
    """Verify the parser is implemented from scratch."""

    def test_editor_exists(self):
        assert os.path.isfile(EDITOR), f"Editor not found at {EDITOR}"

    def test_no_pe_libraries(self):
        with open(EDITOR) as f:
            src = f.read()
        for lib in ["pefile", "lief", "pepy", "peutils"]:
            assert f"import {lib}" not in src, f"Must not use {lib} library"
            assert f"from {lib}" not in src, f"Must not use {lib} library"

    def test_validate_uses_objdump(self):
        """The validate command must invoke objdump for cross-checking."""
        with open(EDITOR) as f:
            src = f.read()
        assert "objdump" in src, (
            "validate command must use objdump for cross-checking"
        )


class TestAnalyzePE32:
    """Test analysis of 32-bit PE executable."""

    @pytest.fixture
    def pe_path(self):
        return os.path.join(SAMPLES_DIR, "hello32.exe")

    def test_format(self, pe_path):
        parsed = run_analyze(pe_path)
        expected = pefile_info(pe_path)
        assert parsed["format"] == expected["format"]

    def test_machine(self, pe_path):
        parsed = run_analyze(pe_path)
        expected = pefile_info(pe_path)
        assert parsed["machine"] == expected["machine"]

    def test_num_sections(self, pe_path):
        parsed = run_analyze(pe_path)
        expected = pefile_info(pe_path)
        assert parsed["num_sections"] == expected["num_sections"]

    def test_entry_point(self, pe_path):
        parsed = run_analyze(pe_path)
        expected = pefile_info(pe_path)
        assert parsed["entry_point_rva"] == expected["entry_point_rva"]

    def test_image_base(self, pe_path):
        parsed = run_analyze(pe_path)
        expected = pefile_info(pe_path)
        assert parsed["image_base"] == expected["image_base"]

    def test_imports(self, pe_path):
        parsed = run_analyze(pe_path)
        compare_imports(parsed, pe_path)


class TestAnalyzePE64:
    """Test analysis of 64-bit PE executable."""

    @pytest.fixture
    def pe_path(self):
        return os.path.join(SAMPLES_DIR, "multi64.exe")

    def test_format(self, pe_path):
        parsed = run_analyze(pe_path)
        expected = pefile_info(pe_path)
        assert parsed["format"] == expected["format"]

    def test_machine(self, pe_path):
        parsed = run_analyze(pe_path)
        expected = pefile_info(pe_path)
        assert parsed["machine"] == expected["machine"]

    def test_num_sections(self, pe_path):
        parsed = run_analyze(pe_path)
        expected = pefile_info(pe_path)
        assert parsed["num_sections"] == expected["num_sections"]

    def test_entry_point(self, pe_path):
        parsed = run_analyze(pe_path)
        expected = pefile_info(pe_path)
        assert parsed["entry_point_rva"] == expected["entry_point_rva"]

    def test_image_base(self, pe_path):
        parsed = run_analyze(pe_path)
        expected = pefile_info(pe_path)
        assert parsed["image_base"] == expected["image_base"]

    def test_imports(self, pe_path):
        parsed = run_analyze(pe_path)
        compare_imports(parsed, pe_path)


class TestAnalyzeDLL:
    """Test analysis of DLL with export table."""

    @pytest.fixture
    def pe_path(self):
        return os.path.join(SAMPLES_DIR, "mathlib.dll")

    def test_format(self, pe_path):
        parsed = run_analyze(pe_path)
        assert parsed["format"] == "PE32"

    def test_has_exports(self, pe_path):
        parsed = run_analyze(pe_path)
        assert "exports" in parsed and parsed["exports"] is not None

    def test_export_names(self, pe_path):
        parsed = run_analyze(pe_path)
        expected_names = set(pefile_exports(pe_path))
        parsed_names = set()
        for f in parsed["exports"]["functions"]:
            if "name" in f and f["name"]:
                parsed_names.add(f["name"])
        assert parsed_names == expected_names, (
            f"Export mismatch: got {sorted(parsed_names)}, "
            f"expected {sorted(expected_names)}"
        )

    def test_export_dll_name(self, pe_path):
        parsed = run_analyze(pe_path)
        assert parsed["exports"]["dll_name"].lower() == "mathlib.dll"


class TestInjectImport:
    """Test import injection into PE files."""

    def test_inject_pe32(self):
        src = os.path.join(SAMPLES_DIR, "hello32.exe")
        dst = "/tmp/hello32_injected.exe"
        result = run_editor("inject", src, dst, "USER32.dll", "MessageBoxA")
        assert result.returncode == 0, f"Inject failed: {result.stderr}"

        injected = pefile_imports(dst)
        user32_funcs = None
        for dll, funcs in injected.items():
            if dll.upper() == "USER32.DLL":
                user32_funcs = funcs
                break
        assert user32_funcs is not None, (
            f"USER32.dll not found in injected imports. DLLs: {list(injected.keys())}"
        )
        assert "MessageBoxA" in user32_funcs

    def test_inject_pe64(self):
        src = os.path.join(SAMPLES_DIR, "multi64.exe")
        dst = "/tmp/multi64_injected.exe"
        result = run_editor("inject", src, dst, "ADVAPI32.dll", "RegOpenKeyExA")
        assert result.returncode == 0, f"Inject failed: {result.stderr}"

        injected = pefile_imports(dst)
        advapi_funcs = None
        for dll, funcs in injected.items():
            if dll.upper() == "ADVAPI32.DLL":
                advapi_funcs = funcs
                break
        assert advapi_funcs is not None, (
            f"ADVAPI32.dll not found. DLLs: {list(injected.keys())}"
        )
        assert "RegOpenKeyExA" in advapi_funcs

    def test_inject_preserves_original_imports(self):
        src = os.path.join(SAMPLES_DIR, "hello32.exe")
        dst = "/tmp/hello32_preserved.exe"
        original = pefile_imports(src)

        result = run_editor("inject", src, dst, "USER32.dll", "MessageBoxA")
        assert result.returncode == 0, f"Inject failed: {result.stderr}"

        modified = pefile_imports(dst)
        for dll, funcs in original.items():
            mod_dll = None
            for k in modified:
                if k.upper() == dll.upper():
                    mod_dll = k
                    break
            assert mod_dll is not None, f"Original DLL {dll} missing after injection"
            assert set(funcs).issubset(set(modified[mod_dll])), (
                f"Original functions from {dll} missing after injection"
            )

    def test_injected_pe_valid(self):
        src = os.path.join(SAMPLES_DIR, "hello32.exe")
        dst = "/tmp/hello32_valid.exe"
        result = run_editor("inject", src, dst, "USER32.dll", "MessageBoxA")
        assert result.returncode == 0

        try:
            pe = pefile.PE(dst)
            pe.close()
        except Exception as e:
            pytest.fail(f"Modified PE is not valid: {e}")

    def test_analyze_injected_pe(self):
        """The custom parser must also correctly analyze its own injected output."""
        src = os.path.join(SAMPLES_DIR, "hello32.exe")
        dst = "/tmp/hello32_roundtrip.exe"
        result = run_editor("inject", src, dst, "USER32.dll", "MessageBoxA")
        assert result.returncode == 0

        parsed = run_analyze(dst)
        assert parsed["format"] == "PE32"

        user32_found = False
        for dll in parsed.get("imports", {}):
            if dll.upper() == "USER32.DLL":
                assert "MessageBoxA" in parsed["imports"][dll]
                user32_found = True
        assert user32_found, "Injected import not visible to own parser"

    def test_inject_pe64_preserves_imports(self):
        src = os.path.join(SAMPLES_DIR, "multi64.exe")
        dst = "/tmp/multi64_preserved.exe"
        original = pefile_imports(src)

        result = run_editor("inject", src, dst, "ADVAPI32.dll", "RegOpenKeyExA")
        assert result.returncode == 0

        modified = pefile_imports(dst)
        for dll, funcs in original.items():
            mod_dll = None
            for k in modified:
                if k.upper() == dll.upper():
                    mod_dll = k
                    break
            assert mod_dll is not None, f"Original DLL {dll} missing after injection"
            assert set(funcs).issubset(set(modified[mod_dll]))


class TestValidateCommand:
    """Test the objdump cross-validation command."""

    def test_validate_hello32(self):
        result = run_editor("validate", os.path.join(SAMPLES_DIR, "hello32.exe"))
        assert result.returncode == 0, (
            f"Validate failed for hello32.exe: {result.stderr}\n{result.stdout}"
        )
        assert "VALID" in result.stdout

    def test_validate_multi64(self):
        result = run_editor("validate", os.path.join(SAMPLES_DIR, "multi64.exe"))
        assert result.returncode == 0, (
            f"Validate failed for multi64.exe: {result.stderr}\n{result.stdout}"
        )
        assert "VALID" in result.stdout

    def test_validate_mathlib_dll(self):
        result = run_editor("validate", os.path.join(SAMPLES_DIR, "mathlib.dll"))
        assert result.returncode == 0, (
            f"Validate failed for mathlib.dll: {result.stderr}\n{result.stdout}"
        )
        assert "VALID" in result.stdout

    def test_validate_injected_pe(self):
        """Validate must also work on modified/injected PE binaries."""
        src = os.path.join(SAMPLES_DIR, "hello32.exe")
        dst = "/tmp/hello32_validate.exe"
        result = run_editor("inject", src, dst, "USER32.dll", "MessageBoxA")
        assert result.returncode == 0

        result = run_editor("validate", dst)
        assert result.returncode == 0, (
            f"Validate failed on injected PE: {result.stderr}\n{result.stdout}"
        )
        assert "VALID" in result.stdout
