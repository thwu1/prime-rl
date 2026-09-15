
import subprocess
import json
import os
import re
import pytest


EXPECTED_VERDICTS = {
    # Visible programs (in /app/objects/)
    "simple_pass": {"verdict": "accept"},
    "null_deref": {"verdict": "reject", "reason": "null_ptr_deref"},
    "null_check_ok": {"verdict": "accept"},
    "uninit_reg": {"verdict": "reject", "reason": "uninit_reg"},
    "loop_detected": {"verdict": "reject", "reason": "loop"},
    "unreachable": {"verdict": "reject", "reason": "unreachable"},
    "pkt_bounds_ok": {"verdict": "accept"},
    "pkt_no_bounds": {"verdict": "reject", "reason": "pkt_bounds"},
    # Hidden extra programs (in /tmp/extra_objects/)
    "no_exit": {"verdict": "reject", "reason": "no_exit"},
    "null_wrong_branch": {"verdict": "reject", "reason": "null_ptr_deref"},
    "uninit_in_branch": {"verdict": "reject", "reason": "uninit_reg"},
    "combined_valid": {"verdict": "accept"},
}

EXPECTED_INSN_COUNTS = {
    "simple_pass": 2,
    "null_deref": 8,
    "null_check_ok": 11,
    "uninit_reg": 2,
    "loop_detected": 6,
    "unreachable": 4,
    "pkt_bounds_ok": 10,
    "pkt_no_bounds": 5,
    "no_exit": 4,
    "null_wrong_branch": 11,
    "uninit_in_branch": 5,
    "combined_valid": 20,
}

PROGRAMS_WITH_CALLS = {"null_deref", "null_check_ok", "null_wrong_branch", "combined_valid"}

PROGRAM_DIRS = ["/app/objects", "/tmp/extra_objects"]


def find_program(name):
    """Find a BPF ELF object file by name."""
    for d in PROGRAM_DIRS:
        path = os.path.join(d, f"{name}.o")
        if os.path.exists(path):
            return path
    raise FileNotFoundError(f"Program {name}.o not found in {PROGRAM_DIRS}")


def run_verifier(program_path):
    """Run the verifier and return parsed JSON result."""
    result = subprocess.run(
        ["python3", "/app/verifier.py", program_path],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"Verifier exited with code {result.returncode} on {program_path}.\n"
        f"stderr: {result.stderr}\nstdout: {result.stdout}"
    )
    stdout = result.stdout.strip()
    lines = stdout.split("\n")
    for line in reversed(lines):
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)
    raise ValueError(
        f"No JSON output from verifier on {program_path}. stdout: {stdout}"
    )


def get_reference_disasm(program_path):
    """Run llvm-objdump-18 to get ground-truth disassembly mnemonics."""
    result = subprocess.run(
        ["llvm-objdump-18", "-d", "--no-show-raw-insn", program_path],
        capture_output=True, text=True, timeout=10,
    )
    lines = []
    for line in result.stdout.split("\n"):
        stripped = line.strip()
        m = re.match(r'^[0-9a-f]+:\s+(.+)$', stripped)
        if m:
            lines.append(m.group(1).strip())
    return lines


class TestVerifierExists:
    def test_verifier_script_exists(self):
        assert os.path.exists("/app/verifier.py"), \
            "Verifier script not found at /app/verifier.py"


class TestVerifierAcceptPrograms:
    """Test programs that should be accepted."""

    @pytest.mark.parametrize("prog_name", [
        "simple_pass",
        "null_check_ok",
        "pkt_bounds_ok",
        "combined_valid",
    ])
    def test_accept(self, prog_name):
        path = find_program(prog_name)
        result = run_verifier(path)
        assert result["verdict"] == "accept", \
            f"Program {prog_name} should be accepted but got: {result}"


class TestVerifierRejectPrograms:
    """Test programs that should be rejected with specific reasons."""

    @pytest.mark.parametrize("prog_name,expected_reason", [
        ("null_deref", "null_ptr_deref"),
        ("null_wrong_branch", "null_ptr_deref"),
        ("uninit_reg", "uninit_reg"),
        ("uninit_in_branch", "uninit_reg"),
        ("loop_detected", "loop"),
        ("unreachable", "unreachable"),
        ("pkt_no_bounds", "pkt_bounds"),
        ("no_exit", "no_exit"),
    ])
    def test_reject(self, prog_name, expected_reason):
        path = find_program(prog_name)
        result = run_verifier(path)
        assert result["verdict"] == "reject", \
            f"Program {prog_name} should be rejected but got: {result}"
        assert result.get("reason") == expected_reason, (
            f"Program {prog_name} should be rejected with reason "
            f"'{expected_reason}' but got '{result.get('reason')}'"
        )


class TestDisassemblyOutput:
    """Test that the verifier produces correct disassembly via llvm-objdump-18."""

    @pytest.mark.parametrize("prog_name", list(EXPECTED_INSN_COUNTS.keys()))
    def test_disasm_count(self, prog_name):
        path = find_program(prog_name)
        result = run_verifier(path)
        disasm = result.get("disasm", [])
        expected = EXPECTED_INSN_COUNTS[prog_name]
        assert isinstance(disasm, list), \
            f"disasm field must be a list, got {type(disasm).__name__}"
        assert len(disasm) == expected, \
            f"Expected {expected} instructions for {prog_name}, got {len(disasm)}"

    @pytest.mark.parametrize("prog_name", list(EXPECTED_INSN_COUNTS.keys()))
    def test_disasm_has_exit(self, prog_name):
        path = find_program(prog_name)
        result = run_verifier(path)
        disasm = result.get("disasm", [])
        assert any("exit" in line.lower() for line in disasm), \
            f"Disassembly for {prog_name} should contain 'exit'"

    @pytest.mark.parametrize("prog_name", list(PROGRAMS_WITH_CALLS))
    def test_disasm_has_call(self, prog_name):
        path = find_program(prog_name)
        result = run_verifier(path)
        disasm = result.get("disasm", [])
        assert any("call" in line.lower() for line in disasm), \
            f"Disassembly for {prog_name} should contain 'call'"

    @pytest.mark.parametrize("prog_name", list(EXPECTED_INSN_COUNTS.keys()))
    def test_disasm_matches_objdump(self, prog_name):
        """Verify disasm matches llvm-objdump-18 output."""
        path = find_program(prog_name)
        result = run_verifier(path)
        actual = result.get("disasm", [])
        expected = get_reference_disasm(path)
        assert len(actual) == len(expected), (
            f"Instruction count mismatch for {prog_name}: "
            f"verifier={len(actual)}, llvm-objdump={len(expected)}"
        )
        for i, (a, e) in enumerate(zip(actual, expected)):
            assert a.strip() == e.strip(), (
                f"Disasm mismatch for {prog_name} at instruction {i}: "
                f"verifier={a!r}, llvm-objdump={e!r}"
            )


class TestVerifierCompleteness:
    """Verify all expected programs are tested."""

    def test_all_programs_have_files(self):
        for name in EXPECTED_VERDICTS:
            path = find_program(name)
            assert os.path.exists(path), f"Program file missing for {name}"

    def test_all_programs_produce_valid_json(self):
        for name in EXPECTED_VERDICTS:
            path = find_program(name)
            result = run_verifier(path)
            assert "verdict" in result, \
                f"Result for {name} missing 'verdict': {result}"
            assert result["verdict"] in ("accept", "reject"), \
                f"Invalid verdict for {name}: {result['verdict']}"
            if result["verdict"] == "reject":
                assert "reason" in result, \
                    f"Rejected program {name} missing 'reason': {result}"


class TestELFValidity:
    """Verify the ELF object files are valid and can be read by standard tools."""

    @pytest.mark.parametrize("prog_name", list(EXPECTED_INSN_COUNTS.keys()))
    def test_readelf_works(self, prog_name):
        path = find_program(prog_name)
        result = subprocess.run(
            ["readelf", "-S", "-W", path],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, \
            f"readelf failed on {prog_name}: {result.stderr}"
        assert ".text" in result.stdout, \
            f"readelf output for {prog_name} missing .text section"

    @pytest.mark.parametrize("prog_name", list(EXPECTED_INSN_COUNTS.keys()))
    def test_objdump_works(self, prog_name):
        path = find_program(prog_name)
        result = subprocess.run(
            ["llvm-objdump-18", "-d", path],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, \
            f"llvm-objdump-18 failed on {prog_name}: {result.stderr}"
        assert "elf64-bpf" in result.stdout.lower() or "bpf" in result.stdout.lower(), \
            f"llvm-objdump-18 did not recognize {prog_name} as BPF"
