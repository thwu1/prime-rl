
"""
Verification tests for MiniStack-16 toolchain recovery.

Tests cover:
1. Correctness: all 4 programs produce expected output after bug fixes
2. Assembler: negative immediates and jump offsets work correctly
3. Disassembler: exists, produces valid assembly, resolves labels, round-trips
4. Semantics report: resolves ISA ambiguities with evidence
5. Optimizer: exists, reduces size, preserves semantics
6. Selftest: comprehensive ISA test program exists and passes
"""

import subprocess
import os
import re
import json
import pytest


PROGRAMS = ["hello", "fibonacci", "signed_ops", "gcd"]

REQUIRED_SELFTEST_MNEMONICS = [
    "add", "sub", "mul", "div", "mod",
    "and", "or", "xor", "not", "neg",
    "shl", "shr", "eq", "lt", "gt",
    "over", "dup", "load", "store",
]


def _run_bin(bin_path, timeout=10):
    """Execute a .bin program and return (stdout, returncode, stderr)."""
    result = subprocess.run(
        ["/app/emulator", bin_path],
        capture_output=True, text=True, timeout=timeout,
    )
    return result.stdout, result.returncode, result.stderr


def _expected(program_name):
    """Read the expected output for a program."""
    path = f"/app/expected/{program_name}.txt"
    with open(path, "r") as f:
        return f.read()


def _assemble(asm_path, bin_path):
    """Assemble an .asm file to .bin. Returns (success, stderr)."""
    result = subprocess.run(
        ["python3", "/app/assembler.py", asm_path, bin_path],
        capture_output=True, text=True, timeout=10,
    )
    return result.returncode == 0, result.stderr


def _disassemble(bin_path, asm_path):
    """Disassemble a .bin file to .asm. Returns (success, stderr)."""
    result = subprocess.run(
        ["python3", "/app/disassembler.py", bin_path, asm_path],
        capture_output=True, text=True, timeout=10,
    )
    return result.returncode == 0, result.stderr


def _optimize(in_bin, out_bin):
    """Run optimizer on a binary. Returns (success, stderr)."""
    result = subprocess.run(
        ["python3", "/app/optimizer.py", in_bin, out_bin],
        capture_output=True, text=True, timeout=10,
    )
    return result.returncode == 0, result.stderr


# ---- Program correctness tests ----

@pytest.mark.parametrize("name", PROGRAMS)
def test_program_output(name):
    """Each program produces correct output after bug fixes."""
    bin_path = f"/app/programs/{name}.bin"
    assert os.path.exists(bin_path), f"Binary not found: {bin_path}"
    stdout, rc, stderr = _run_bin(bin_path)
    expected = _expected(name)
    assert stdout == expected, (
        f"Output mismatch for {name}:\n"
        f"  Expected: {expected!r}\n  Got: {stdout!r}\n  Stderr: {stderr}"
    )


# ---- Assembler correctness tests ----

def test_assembler_negative_push():
    """Assembler correctly encodes negative immediate values."""
    asm_path = "/tmp/neg_test.asm"
    bin_path = "/tmp/neg_test.bin"
    with open(asm_path, "w") as f:
        f.write("push -1\nputi\npush 10\nputc\nhalt\n")
    ok, err = _assemble(asm_path, bin_path)
    assert ok, f"Assembly failed: {err}"
    stdout, rc, stderr = _run_bin(bin_path)
    assert stdout == "-1\n", (
        f"PUSH -1 should produce -1, got {stdout!r}. "
        f"Assembler may be truncating negative values. Stderr: {stderr}"
    )


def test_assembler_jump_offset():
    """Assembler correctly computes jump offsets relative to next instruction."""
    asm_path = "/tmp/jmp_test.asm"
    bin_path = "/tmp/jmp_test.bin"
    with open(asm_path, "w") as f:
        f.write("jmp skip\npush 99\nputi\nskip:\npush 42\nputi\npush 10\nputc\nhalt\n")
    ok, err = _assemble(asm_path, bin_path)
    assert ok, f"Assembly failed: {err}"
    stdout, rc, stderr = _run_bin(bin_path)
    assert stdout == "42\n", (
        f"JMP skip should skip PUSH 99/PUTI and print 42, got {stdout!r}. "
        f"Assembler may be computing wrong jump offsets. Stderr: {stderr}"
    )


# ---- Disassembler tests ----

def test_disassembler_exists():
    """disassembler.py must exist at /app/disassembler.py."""
    assert os.path.exists("/app/disassembler.py"), (
        "Disassembler not found at /app/disassembler.py"
    )


def test_disassembler_produces_assembly():
    """Disassembler produces valid assembly for hello.bin."""
    ok, err = _disassemble("/app/programs/hello.bin", "/tmp/dis_hello.asm")
    assert ok, f"Disassembly of hello.bin failed: {err}"
    assert os.path.exists("/tmp/dis_hello.asm")
    with open("/tmp/dis_hello.asm") as f:
        asm = f.read().lower()
    assert "push" in asm, "Disassembly missing PUSH"
    assert "putc" in asm, "Disassembly missing PUTC"
    assert "halt" in asm, "Disassembly missing HALT"


def test_disassembler_resolves_labels():
    """Disassembler resolves jump targets to labels for programs with branches."""
    ok, err = _disassemble("/app/programs/gcd.bin", "/tmp/dis_gcd.asm")
    assert ok, f"Disassembly of gcd.bin failed: {err}"
    with open("/tmp/dis_gcd.asm") as f:
        asm = f.read()
    assert re.search(r'^\w+:', asm, re.MULTILINE), (
        "Disassembly of gcd.bin has no labels — jump targets must be resolved"
    )


# ---- Round-trip tests ----

@pytest.mark.parametrize("name", PROGRAMS)
def test_roundtrip(name):
    """Disassemble -> reassemble -> run produces same output."""
    bin_path = f"/app/programs/{name}.bin"
    rt_asm = f"/tmp/rt_{name}.asm"
    rt_bin = f"/tmp/rt_{name}.bin"

    ok, err = _disassemble(bin_path, rt_asm)
    assert ok, f"Disassemble {name} failed: {err}"

    ok, err = _assemble(rt_asm, rt_bin)
    assert ok, f"Reassemble {name} failed: {err}"

    stdout, rc, stderr = _run_bin(rt_bin)
    expected = _expected(name)
    assert stdout == expected, (
        f"Round-trip output mismatch for {name}:\n"
        f"  Expected: {expected!r}\n  Got: {stdout!r}\n  Stderr: {stderr}"
    )


# ---- Semantics report tests ----

def test_semantics_report():
    """semantics_report.json resolves all ISA ambiguities with evidence."""
    path = "/app/semantics_report.json"
    assert os.path.exists(path), "semantics_report.json not found at /app/"

    with open(path) as f:
        report = json.load(f)

    assert "ambiguities" in report, "Report missing 'ambiguities' key"
    assert isinstance(report["ambiguities"], list), "'ambiguities' must be a list"
    assert len(report["ambiguities"]) >= 3, (
        f"Must resolve at least 3 ambiguities (SHR, LT/GT, MOD), found {len(report['ambiguities'])}"
    )

    # Each entry must have required fields
    for entry in report["ambiguities"]:
        assert "instruction" in entry, f"Entry missing 'instruction': {entry}"
        assert "resolution" in entry, f"Entry missing 'resolution': {entry}"
        assert "evidence" in entry, f"Entry missing 'evidence': {entry}"
        assert len(str(entry["evidence"])) >= 15, (
            f"Evidence too short for {entry['instruction']}: {entry['evidence']}"
        )

    # Check required ambiguities are covered
    instructions = {e["instruction"].upper().replace("/", "_") for e in report["ambiguities"]}
    # Flatten to check individual instructions
    all_instrs = set()
    for e in report["ambiguities"]:
        for part in re.split(r'[/,\s]+', e["instruction"].upper()):
            part = part.strip()
            if part:
                all_instrs.add(part)

    assert "SHR" in all_instrs, "Must resolve SHR shift-type ambiguity"
    assert "MOD" in all_instrs, "Must resolve MOD sign-convention ambiguity"
    assert "LT" in all_instrs or "GT" in all_instrs, (
        "Must resolve comparison signedness ambiguity (LT or GT)"
    )

    # Verify resolutions are correct
    for entry in report["ambiguities"]:
        instr = entry["instruction"].upper()
        res = entry["resolution"].lower()
        if "SHR" in instr:
            assert any(w in res for w in ["arithmetic", "sign"]), (
                f"SHR must be resolved as arithmetic shift, got: {res}"
            )
        if "LT" in instr or "GT" in instr:
            assert "signed" in res or "sign" in res, (
                f"LT/GT must be resolved as signed comparison, got: {res}"
            )
        if "MOD" in instr:
            assert any(w in res for w in ["signed", "sign", "truncat", "c-style"]), (
                f"MOD must be resolved as signed/truncated remainder, got: {res}"
            )


# ---- Optimizer tests ----

def test_optimizer_exists():
    """optimizer.py must exist at /app/optimizer.py."""
    assert os.path.exists("/app/optimizer.py"), (
        "Optimizer not found at /app/optimizer.py"
    )


def test_optimizer_reduces_size():
    """Optimizer reduces binary size on a program with optimization opportunities."""
    # Create a test program with known constant-folding and dead-code opportunities
    asm_src = (
        "push 10\npush 20\nadd\nputi\npush 10\nputc\n"
        "push 42\npush 0\nadd\nputi\npush 10\nputc\n"
        "push 99\npop\npush 7\nputi\npush 10\nputc\n"
        "halt\n"
    )
    with open("/tmp/opt_src.asm", "w") as f:
        f.write(asm_src)
    ok, err = _assemble("/tmp/opt_src.asm", "/tmp/opt_src.bin")
    assert ok, f"Assembly of optimizer test program failed: {err}"
    orig_size = os.path.getsize("/tmp/opt_src.bin")

    ok, err = _optimize("/tmp/opt_src.bin", "/tmp/opt_out.bin")
    assert ok, f"Optimizer failed: {err}"

    opt_size = os.path.getsize("/tmp/opt_out.bin")
    assert opt_size < orig_size, (
        f"Optimizer must reduce size: original={orig_size}, optimized={opt_size}"
    )

    # Verify semantics preserved
    orig_out, _, _ = _run_bin("/tmp/opt_src.bin")
    opt_out, _, _ = _run_bin("/tmp/opt_out.bin")
    assert orig_out == opt_out, (
        f"Optimizer changed semantics:\n"
        f"  Original: {orig_out!r}\n  Optimized: {opt_out!r}"
    )


@pytest.mark.parametrize("name", PROGRAMS)
def test_optimizer_preserves_semantics(name):
    """Optimizing existing programs preserves their output."""
    bin_path = f"/app/programs/{name}.bin"
    opt_path = f"/tmp/opt_{name}.bin"

    ok, err = _optimize(bin_path, opt_path)
    assert ok, f"Optimizer failed on {name}: {err}"

    expected = _expected(name)
    opt_out, rc, stderr = _run_bin(opt_path)
    assert opt_out == expected, (
        f"Optimized {name} output mismatch:\n"
        f"  Expected: {expected!r}\n  Got: {opt_out!r}\n  Stderr: {stderr}"
    )


# ---- Selftest tests ----

def test_selftest_exists():
    """selftest.asm must exist at /app/programs/selftest.asm."""
    assert os.path.exists("/app/programs/selftest.asm"), (
        "Selftest source not found at /app/programs/selftest.asm"
    )


def test_selftest_mnemonics():
    """selftest.asm must use all required instruction mnemonics."""
    with open("/app/programs/selftest.asm") as f:
        source = f.read().lower()
    source_no_comments = re.sub(r'[;#].*', '', source)
    missing = []
    for mnemonic in REQUIRED_SELFTEST_MNEMONICS:
        if not re.search(r'\b' + re.escape(mnemonic) + r'\b', source_no_comments):
            missing.append(mnemonic)
    assert not missing, (
        f"selftest.asm is missing instruction mnemonics: {', '.join(missing)}"
    )


def test_selftest_output():
    """selftest.asm assembles and produces expected output."""
    asm_path = "/app/programs/selftest.asm"
    bin_path = "/app/programs/selftest.bin"

    if not os.path.exists(bin_path):
        ok, err = _assemble(asm_path, bin_path)
        assert ok, f"Selftest assembly failed: {err}"

    stdout, rc, stderr = _run_bin(bin_path)
    assert rc == 0, f"Selftest crashed: {stderr}"
    expected = _expected("selftest")
    assert stdout == expected, (
        f"Selftest output mismatch:\n"
        f"  Expected: {expected!r}\n  Got: {stdout!r}"
    )
