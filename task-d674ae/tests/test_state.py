
"""
Verification tests for the firmware security audit task.

Checks:
  1. Audit report exists, is valid JSON, and identifies the three
     vulnerability classes (compiler optimization, timing side-channel,
     missing stack hardening) with affected function names.
  2. Fixed firmware directory exists, compiles, and applies correct
     countermeasures: secure wipe (volatile / asm barrier), constant-
     time comparison (no memcmp in verify_pin), and stack protector.
"""

import json
import os
import re
import subprocess

FIRMWARE_DIR = "/app/firmware"
FIXED_DIR = "/app/firmware_fixed"
REPORT = "/app/audit_report.json"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _compile(src_dir: str) -> None:
    """Run `make clean all` in *src_dir* and assert success."""
    subprocess.run(["make", "-C", src_dir, "clean"],
                   capture_output=True, timeout=30)
    r = subprocess.run(["make", "-C", src_dir],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"Build failed in {src_dir}:\n{r.stderr}"


def _find_elf(src_dir: str) -> str:
    """Return path of first .elf in *src_dir* (builds if necessary)."""
    for f in os.listdir(src_dir):
        if f.endswith(".elf"):
            return os.path.join(src_dir, f)
    _compile(src_dir)
    for f in os.listdir(src_dir):
        if f.endswith(".elf"):
            return os.path.join(src_dir, f)
    raise FileNotFoundError(f"No .elf produced in {src_dir}")


def _disasm_function(elf_path: str, func_name: str) -> str:
    """Return the disassembly text of *func_name* from an ARM ELF."""
    r = subprocess.run(
        ["arm-none-eabi-objdump", "-d", elf_path],
        capture_output=True, text=True, timeout=30,
    )
    lines = r.stdout.splitlines()
    collecting = False
    result: list[str] = []
    for line in lines:
        if re.search(rf"<{re.escape(func_name)}>:", line):
            collecting = True
            result.append(line)
            continue
        if collecting:
            # Stop at the next function header or a blank line after content
            if line.strip() == "" and result:
                break
            if re.match(r"^[0-9a-f]+ <", line):
                break
            result.append(line)
    return "\n".join(result)


# ---------------------------------------------------------------------------
# Report tests
# ---------------------------------------------------------------------------

class TestAuditReport:
    """Verify the audit report identifies all vulnerability classes."""

    def test_report_exists_and_valid_json(self):
        assert os.path.exists(REPORT), "Missing /app/audit_report.json"
        with open(REPORT) as f:
            data = json.load(f)
        assert data is not None

    def test_report_identifies_compiler_optimization(self):
        with open(REPORT) as f:
            text = json.dumps(json.load(f)).lower()
        keywords = [
            "memset", "dead store", "dead-store", "optimized away",
            "optimised away", "compiler optimization", "compiler optimisation",
            "eliminated by", "elided", "removed by the compiler",
        ]
        assert any(k in text for k in keywords), (
            "Report must identify memset / dead-store optimization issue"
        )

    def test_report_identifies_timing_side_channel(self):
        with open(REPORT) as f:
            text = json.dumps(json.load(f)).lower()
        keywords = [
            "timing", "side channel", "side-channel",
            "memcmp", "constant-time", "constant time",
        ]
        assert any(k in text for k in keywords), (
            "Report must identify timing side-channel vulnerability"
        )

    def test_report_identifies_stack_hardening(self):
        with open(REPORT) as f:
            text = json.dumps(json.load(f)).lower()
        keywords = [
            "stack canary", "stack protector", "stack-protector",
            "fstack-protector", "buffer overflow protection",
            "stack smashing",
        ]
        assert any(k in text for k in keywords), (
            "Report must identify missing stack protection"
        )

    def test_report_names_affected_functions(self):
        with open(REPORT) as f:
            text = json.dumps(json.load(f)).lower()
        funcs = [
            "verify_pin",
            "process_unlock",
            "pair_device",
            "compute_challenge",
        ]
        found = sum(1 for fn in funcs if fn in text)
        assert found >= 3, (
            f"Report should name >= 3 of the 4 affected functions; found {found}"
        )


# ---------------------------------------------------------------------------
# Fixed-firmware tests
# ---------------------------------------------------------------------------

class TestFixedFirmware:
    """Verify the fixed firmware compiles and has correct countermeasures."""

    def test_fixed_directory_exists(self):
        assert os.path.isdir(FIXED_DIR), "Missing /app/firmware_fixed/"
        c_files = [f for f in os.listdir(FIXED_DIR) if f.endswith(".c")]
        assert len(c_files) >= 2, (
            "firmware_fixed/ must contain at least 2 .c source files"
        )

    def test_fixed_compiles(self):
        _compile(FIXED_DIR)

    def test_fixed_uses_secure_wipe(self):
        """Fixed source must use a volatile or barrier-based wipe technique."""
        all_src = ""
        for fn in os.listdir(FIXED_DIR):
            if fn.endswith(".c") or fn.endswith(".h"):
                with open(os.path.join(FIXED_DIR, fn)) as f:
                    all_src += f.read()
        wipe_indicators = [
            "volatile",
            "explicit_bzero",
            "__asm__",
            'asm volatile',
            'asm("',
            "asm(\"",
            "secure_wipe",
            "secure_zero",
            "secure_memzero",
            "platform_zeroize",
            "memzero_explicit",
            "OPENSSL_cleanse",
            "sodium_memzero",
            "memory_cleanse",
            "ct_poison",
        ]
        assert any(k in all_src for k in wipe_indicators), (
            "Fixed code must use a secure-wipe technique "
            "(volatile pointer, asm barrier, explicit_bzero, etc.)"
        )

    def test_fixed_verify_pin_no_memcmp_source(self):
        """verify_pin source must not use memcmp for security comparison."""
        for fn in os.listdir(FIXED_DIR):
            if not fn.endswith(".c"):
                continue
            with open(os.path.join(FIXED_DIR, fn)) as f:
                src = f.read()
            m = re.search(r"verify_pin\s*\([^)]*\)\s*\{", src)
            if not m:
                continue
            # Extract body
            start = m.end()
            depth = 1
            i = start
            while i < len(src) and depth > 0:
                if src[i] == "{":
                    depth += 1
                elif src[i] == "}":
                    depth -= 1
                i += 1
            body = src[start:i]
            assert "memcmp" not in body, (
                "Source: verify_pin still uses memcmp for comparison"
            )
            return  # found and checked
        # If verify_pin not found by name, skip (agent may have renamed)

    def test_fixed_verify_pin_no_memcmp_binary(self):
        """Disassembly of fixed verify_pin must not branch to memcmp."""
        elf = _find_elf(FIXED_DIR)
        disasm = _disasm_function(elf, "verify_pin")
        if not disasm:
            # Function might be renamed or inlined; skip binary check
            return
        assert "memcmp" not in disasm, (
            "Binary: fixed verify_pin still calls memcmp"
        )

    def test_fixed_makefile_stack_protector(self):
        mf = os.path.join(FIXED_DIR, "Makefile")
        assert os.path.exists(mf), "Missing Makefile in firmware_fixed/"
        with open(mf) as f:
            content = f.read()
        assert any(
            flag in content
            for flag in ["-fstack-protector-strong", "-fstack-protector-all"]
        ), "Fixed Makefile must enable -fstack-protector-strong or -all"
