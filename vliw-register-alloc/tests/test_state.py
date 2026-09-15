"""
Tests for the VLIW backend compiler and toolchain integration.

"""

import subprocess
import os
import sys

sys.path.insert(0, "/app")

PROGRAMS = ["smoke", "scheduling", "pressure", "mixed"]


# ─── Toolchain integration tests ──────────────────────────────────────


def test_vsim_binary_exists():
    """The C simulator must be compiled from vsim.c source."""
    assert os.path.isfile("/app/tools/vsim"), \
        "vsim binary not found at /app/tools/vsim — compile /app/tools/vsim.c with gcc"
    assert os.access("/app/tools/vsim", os.X_OK), \
        "vsim exists but is not executable"


def test_vbin_files_generated():
    """All .vbin interchange files must be generated via vexport."""
    for name in PROGRAMS:
        path = f"/app/output/{name}.vbin"
        assert os.path.isfile(path), \
            f"{path} not found — use /app/tools/vexport.py to generate"
        assert os.path.getsize(path) > 50, \
            f"{path} is suspiciously small"


def _parse_vsim_output(stdout):
    """Parse vsim stdout into (cycles, {addr: value})."""
    cycles = None
    memory = {}
    for line in stdout.strip().split("\n"):
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "CYCLES":
            cycles = int(parts[1])
        elif parts[0] == "MEM":
            memory[int(parts[1])] = int(parts[2])
        elif parts[0] == "STATUS":
            assert parts[1] == "OK", f"vsim status: {parts[1]}"
    assert cycles is not None, "vsim output missing CYCLES line"
    return cycles, memory


def _get_reference(name):
    """Get sequential reference output for a named program."""
    from programs import get_test_cases
    from vliw import simulate_sequential
    for n, prog, mr, tc in get_test_cases():
        if n == name:
            return simulate_sequential(prog), mr, tc, prog
    raise ValueError(f"Unknown program: {name}")


def _test_vsim_program(name):
    """Run the C simulator on a .vbin file and verify correctness."""
    expected_mem, max_regs, target_cycles, prog = _get_reference(name)
    result = subprocess.run(
        ["/app/tools/vsim", f"/app/output/{name}.vbin"],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, \
        f"vsim failed on {name} (exit {result.returncode}): {result.stderr}"

    cycles, memory = _parse_vsim_output(result.stdout)

    for i in range(prog.data_size):
        assert memory.get(i, 0) == expected_mem[i], (
            f"[{name}] vsim mem[{i}]: expected {expected_mem[i]}, "
            f"got {memory.get(i, 0)}"
        )
    assert cycles <= target_cycles, \
        f"[{name}] vsim cycles {cycles} exceeds target {target_cycles}"


def test_vsim_smoke():
    _test_vsim_program("smoke")


def test_vsim_scheduling():
    _test_vsim_program("scheduling")


def test_vsim_pressure():
    _test_vsim_program("pressure")


def test_vsim_mixed():
    _test_vsim_program("mixed")


def test_dot_files_valid():
    """DOT dependency graphs must be generated and syntactically valid."""
    for name in PROGRAMS:
        dot_path = f"/app/output/{name}.dot"
        assert os.path.isfile(dot_path), \
            f"{dot_path} not found — generate with /app/tools/vdot.py"
        with open(dot_path) as f:
            content = f.read()
        assert "digraph" in content, \
            f"{dot_path} missing 'digraph' keyword — invalid DOT format"
        assert content.count("{") >= 2, \
            f"{dot_path} appears incomplete — missing subgraph clusters"


def test_svg_files_exist():
    """SVG renderings must be produced from DOT files using graphviz."""
    for name in PROGRAMS:
        svg_path = f"/app/output/{name}.svg"
        assert os.path.isfile(svg_path), (
            f"{svg_path} not found — render with: "
            f"dot -Tsvg /app/output/{name}.dot -o /app/output/{name}.svg"
        )
        assert os.path.getsize(svg_path) > 200, \
            f"{svg_path} too small to be valid SVG"


# ─── Python-level compiler correctness tests ──────────────────────────


def _test_python_compiler(name):
    """Verify compile() output through the Python VLIW simulator."""
    from programs import get_test_cases
    from vliw import simulate_sequential, simulate_vliw, validate_compiled
    from backend import compile

    for n, prog, mr, tc in get_test_cases():
        if n == name:
            expected = simulate_sequential(prog)
            compiled = compile(prog, mr)

            errors = validate_compiled(compiled, mr)
            assert not errors, \
                f"[{name}] Validation errors:\n" + "\n".join(errors)

            actual, cycles = simulate_vliw(
                compiled, prog.init_mem, prog.data_size
            )
            assert actual == expected, (
                f"[{name}] Memory mismatch.\n"
                f"  Expected: {expected}\n"
                f"  Got:      {actual}"
            )
            assert cycles <= tc, \
                f"[{name}] Cycle count {cycles} exceeds target {tc}"
            return
    raise ValueError(name)


def test_python_smoke():
    _test_python_compiler("smoke")


def test_python_scheduling():
    _test_python_compiler("scheduling")


def test_python_pressure():
    _test_python_compiler("pressure")


def test_python_mixed():
    _test_python_compiler("mixed")
