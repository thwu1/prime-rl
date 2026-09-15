"""
Tests for the VLIW instruction scheduler pipeline.

Validates scheduler correctness, bundle structure, register allocation,
scheduling quality, and the Make/Graphviz/jq integration pipeline.
"""


import json
import os
import subprocess
import sys
import pytest

sys.path.insert(0, "/app")

from isa import get_reads_writes, get_unit
from simulator import run_vliw
from scheduler import schedule


def load_program(name):
    with open(f"/app/programs/{name}.json") as f:
        return json.load(f)


def _get_all_registers(bundles):
    """Collect all register numbers used in the VLIW bundles."""
    regs = set()
    for bundle in bundles:
        for instr in bundle:
            reads, writes = get_reads_writes(instr)
            regs.update(reads)
            regs.update(writes)
    return regs


def _validate_bundle_structure(bundles):
    """Ensure each bundle has at most one instruction per functional unit
    and no write-write register conflicts."""
    for i, bundle in enumerate(bundles):
        units = []
        for instr in bundle:
            u = get_unit(instr)
            assert u not in units, (
                f"Bundle {i} has multiple '{u}' instructions: {bundle}"
            )
            units.append(u)

        all_writes = set()
        for instr in bundle:
            _, writes = get_reads_writes(instr)
            overlap = writes & all_writes
            assert not overlap, (
                f"Bundle {i} has write-write conflict on register(s) {overlap}"
            )
            all_writes.update(writes)


# ── Scheduler correctness tests ───────────────────────────────────────────

@pytest.mark.parametrize("prog_name", ["prog1", "prog2", "prog3"])
def test_correctness(prog_name):
    """Scheduled program must produce the same memory output as sequential."""
    prog = load_program(prog_name)
    instrs = prog["instructions"]
    memory_init = {int(k): v for k, v in prog["memory_init"].items()}
    expected_memory = {int(k): v for k, v in prog["expected_memory"].items()}

    bundles = schedule(instrs, max_registers=256)
    assert isinstance(bundles, list), "schedule() must return a list of bundles"
    assert len(bundles) > 0, "schedule() returned empty bundle list"

    vliw_memory, _ = run_vliw(bundles, memory_init)

    for addr, expected_val in expected_memory.items():
        actual_val = vliw_memory.get(addr, 0)
        assert actual_val == expected_val, (
            f"{prog_name}: memory[{addr}] = {actual_val:#x}, "
            f"expected {expected_val:#x}"
        )


@pytest.mark.parametrize("prog_name", ["prog1", "prog2", "prog3"])
def test_valid_bundles(prog_name):
    """Each bundle must have at most one instruction per functional unit
    and no write-write register conflicts."""
    prog = load_program(prog_name)
    bundles = schedule(prog["instructions"], max_registers=256)
    _validate_bundle_structure(bundles)


@pytest.mark.parametrize("prog_name", ["prog1", "prog2", "prog3"])
def test_register_count(prog_name):
    """All registers in the output must be in [0, 255]."""
    prog = load_program(prog_name)
    bundles = schedule(prog["instructions"], max_registers=256)
    all_regs = _get_all_registers(bundles)
    if all_regs:
        max_reg = max(all_regs)
        assert max_reg < 256, (
            f"{prog_name}: max register {max_reg} >= 256; "
            f"register allocation required"
        )


@pytest.mark.parametrize("prog_name", ["prog1", "prog2", "prog3"])
def test_cycle_improvement(prog_name):
    """Scheduled program must use fewer cycles than the sequential count."""
    prog = load_program(prog_name)
    instrs = prog["instructions"]
    memory_init = {int(k): v for k, v in prog["memory_init"].items()}

    bundles = schedule(instrs, max_registers=256)
    _, vliw_cycles = run_vliw(bundles, memory_init)

    sequential_cycles = len(instrs)
    assert vliw_cycles < sequential_cycles, (
        f"{prog_name}: VLIW cycles ({vliw_cycles}) must be less than "
        f"sequential ({sequential_cycles})"
    )


@pytest.mark.parametrize("prog_name", ["prog1", "prog2", "prog3"])
def test_instruction_count(prog_name):
    """Total instructions across all bundles must equal the original count."""
    prog = load_program(prog_name)
    instrs = prog["instructions"]

    bundles = schedule(instrs, max_registers=256)
    total_scheduled = sum(len(b) for b in bundles)
    assert total_scheduled == len(instrs), (
        f"{prog_name}: scheduled {total_scheduled} instructions but "
        f"original has {len(instrs)}"
    )


# ── Pipeline integration tests (Make + Graphviz + jq) ─────────────────────

class TestPipeline:
    """Tests for the Make/Graphviz/jq pipeline integration."""

    @classmethod
    def setup_class(cls):
        """Run make clean && make all once before pipeline tests."""
        subprocess.run(
            ["make", "-C", "/app", "clean"],
            capture_output=True, timeout=30
        )
        result = subprocess.run(
            ["make", "-C", "/app", "all"],
            capture_output=True, timeout=120
        )
        cls._make_rc = result.returncode
        cls._make_output = (
            result.stdout.decode(errors="replace") +
            result.stderr.decode(errors="replace")
        )

    def test_makefile_exists(self):
        """Makefile must exist at /app/Makefile."""
        assert os.path.isfile("/app/Makefile"), "Missing /app/Makefile"

    def test_make_all_succeeds(self):
        """make -C /app all must complete with exit code 0."""
        assert self._make_rc == 0, (
            f"make all failed (exit {self._make_rc}):\n{self._make_output}"
        )

    @pytest.mark.parametrize("prog_name", ["prog1", "prog2", "prog3"])
    def test_bundle_json_output(self, prog_name):
        """Scheduled bundles must be written to /app/output/ as JSON."""
        path = f"/app/output/{prog_name}_bundles.json"
        assert os.path.isfile(path), f"Missing {path}"
        with open(path) as f:
            bundles = json.load(f)
        assert isinstance(bundles, list) and len(bundles) > 0, (
            f"{path} must contain a non-empty JSON array of bundles"
        )

    @pytest.mark.parametrize("prog_name", ["prog1", "prog2", "prog3"])
    def test_svg_graph_output(self, prog_name):
        """Dependency graph SVGs must be rendered by dot at /app/output/."""
        path = f"/app/output/{prog_name}_deps.svg"
        assert os.path.isfile(path), f"Missing {path}"
        content = open(path).read()
        assert "<svg" in content.lower(), f"{path} is not valid SVG"

    def test_report_json_schema(self):
        """report.json must contain per-program statistics with correct keys."""
        path = "/app/output/report.json"
        assert os.path.isfile(path), f"Missing {path}"
        with open(path) as f:
            report = json.load(f)
        required_keys = {
            "sequential_cycles", "vliw_cycles", "speedup",
            "num_bundles", "total_instructions", "max_register"
        }
        for prog_name in ["prog1", "prog2", "prog3"]:
            assert prog_name in report, f"Missing {prog_name} in report"
            entry = report[prog_name]
            missing = required_keys - set(entry.keys())
            assert not missing, (
                f"Missing keys in {prog_name}: {missing}"
            )
            assert isinstance(entry["speedup"], (int, float))
            assert entry["speedup"] > 1.0, (
                f"{prog_name} speedup {entry['speedup']} not > 1.0"
            )
            assert entry["vliw_cycles"] < entry["sequential_cycles"], (
                f"{prog_name} vliw_cycles not less than sequential_cycles"
            )

    def test_jq_report_query(self):
        """report.json must be queryable with jq."""
        result = subprocess.run(
            ["jq", ".prog3.speedup", "/app/output/report.json"],
            capture_output=True, timeout=10
        )
        assert result.returncode == 0, (
            f"jq query failed: {result.stderr.decode(errors='replace')}"
        )
        speedup = float(result.stdout.decode().strip())
        assert speedup > 1.0, f"prog3 speedup via jq is {speedup}, not > 1.0"
