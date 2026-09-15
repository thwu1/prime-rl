"""
Verification tests for the register allocator and assembly emitter.
"""
import sys, os, subprocess, pytest
sys.path.insert(0, "/opt/regalloc")
sys.path.insert(0, "/app")

from ir import (
    Instr, Callq, Jump, JumpIf,
    Immediate, Register, Variable, Deref,
    instr_reads, instr_writes,
    CALLEE_SAVED,
)
from emulate import emulate
from programs import get_test_programs
from register_allocator import (
    allocate_registers, analyze_liveness, build_cfg,
    build_interference_graph, AllocResult,
)

_PROGRAMS = get_test_programs()
_IDS = [p[0] for p in _PROGRAMS]


# ─── helpers ──────────────────────────────────────────────────────────────────

def _has_variables(program):
    for instrs in program.blocks.values():
        for ins in instrs:
            if isinstance(ins, Instr):
                for a in ins.args:
                    if isinstance(a, Variable):
                        return True
    return False


def _variable_mapping(orig, alloc):
    """Compare two instruction-parallel programs, return {Variable: location}."""
    mapping = {}
    for label in orig.blocks:
        for oi, ai in zip(orig.blocks[label], alloc.blocks[label]):
            if isinstance(oi, Instr) and isinstance(ai, Instr):
                for oarg, aarg in zip(oi.args, ai.args):
                    if isinstance(oarg, Variable):
                        if oarg in mapping:
                            assert mapping[oarg] == aarg, (
                                f"Inconsistent mapping for {oarg}: "
                                f"{mapping[oarg]} vs {aarg}"
                            )
                        else:
                            mapping[oarg] = aarg
    return mapping


# ─── correctness ──────────────────────────────────────────────────────────────

class TestCorrectness:
    @pytest.mark.parametrize("name,program,expected,inputs", _PROGRAMS, ids=_IDS)
    def test_output(self, name, program, expected, inputs):
        res = allocate_registers(program)
        assert isinstance(res, AllocResult)
        out = emulate(res.program, inputs=inputs, stack_size=res.stack_size)
        assert out == expected, f"{name}: expected {expected}, got {out}"

    @pytest.mark.parametrize("name,program,expected,inputs", _PROGRAMS, ids=_IDS)
    def test_no_remaining_variables(self, name, program, expected, inputs):
        res = allocate_registers(program)
        assert not _has_variables(res.program), (
            f"{name}: allocated program still contains Variable operands"
        )

    @pytest.mark.parametrize("name,program,expected,inputs", _PROGRAMS, ids=_IDS)
    def test_consistent_mapping(self, name, program, expected, inputs):
        """Each Variable must map to the same location everywhere it appears."""
        res = allocate_registers(program)
        _variable_mapping(program, res.program)  # asserts internally


# ─── allocation quality ──────────────────────────────────────────────────────

class TestQuality:
    def _get_result(self, prog_name):
        prog = next(p[1] for p in _PROGRAMS if p[0] == prog_name)
        return allocate_registers(prog)

    def test_simple_arith_no_spills(self):
        res = self._get_result("simple_arith")
        assert res.stack_size == 0, (
            f"6-variable program should not spill; stack_size={res.stack_size}"
        )

    def test_branch_no_spills(self):
        res = self._get_result("with_branch")
        assert res.stack_size == 0

    def test_while_loop_no_spills(self):
        res = self._get_result("while_loop")
        assert res.stack_size == 0

    def test_high_pressure_spills(self):
        res = self._get_result("high_pressure")
        slots = res.stack_size // 8
        assert slots >= 2, f"Need >= 2 spill slots for 13-var program, got {slots}"
        assert slots <= 5, f"Too many spills ({slots}); optimal is 2-3"

    def test_callee_saved_used_for_call_live(self):
        res = self._get_result("calls_and_live")
        assert len(res.used_callee_saved) >= 1, (
            "Variable live across call must use a callee-saved register"
        )


# ─── liveness analysis (fixed-point for loops) ───────────────────────────────

class TestLiveness:
    def _live_after(self, prog_name):
        prog = next(p[1] for p in _PROGRAMS if p[0] == prog_name)
        s, p = build_cfg(prog)
        return analyze_liveness(prog, s, p), prog

    def test_while_sum_live_at_loop_test(self):
        la, prog = self._live_after("while_loop")
        first = la["loop_test"][0]
        assert Variable("sum") in first, (
            "'sum' must be live-after first instr of loop_test "
            "(requires fixed-point propagation through back-edge)"
        )

    def test_fib_vars_live_at_loop_test(self):
        la, prog = self._live_after("fibonacci_loop")
        first = la["loop_test"][0]
        assert Variable("a") in first, "'a' must be live at loop_test"
        assert Variable("b") in first, "'b' must be live at loop_test"

    def test_nested_loops_inner(self):
        la, prog = self._live_after("nested_loops")
        first = la["inner_test"][0]
        assert Variable("i") in first, "'i' must be live at inner_test"
        assert Variable("total") in first, "'total' must be live at inner_test"


# ─── interference validity ────────────────────────────────────────────────────

class TestInterferenceValidity:
    @pytest.mark.parametrize("name,program,expected,inputs", _PROGRAMS, ids=_IDS)
    def test_no_collision(self, name, program, expected, inputs):
        """No two interfering variables may share a location."""
        res = allocate_registers(program)
        mapping = _variable_mapping(program, res.program)
        s, p = build_cfg(program)
        la = analyze_liveness(program, s, p)
        ig = build_interference_graph(program, la)

        for edge in ig.edges():
            u, v = tuple(edge)
            if isinstance(u, Variable) and isinstance(v, Variable):
                if u in mapping and v in mapping:
                    assert repr(mapping[u]) != repr(mapping[v]), (
                        f"{name}: interfering {u} and {v} share {mapping[u]}"
                    )


# ─── native compilation via gcc ──────────────────────────────────────────────

class TestNativeCompilation:
    @pytest.mark.parametrize("name,program,expected,inputs", _PROGRAMS, ids=_IDS)
    def test_gcc_compile_and_run(self, name, program, expected, inputs, tmp_path):
        """Emit assembly, compile with gcc, and verify binary output."""
        from emit_asm import emit_program
        res = allocate_registers(program)
        asm_src = emit_program(res.program, res.stack_size, res.used_callee_saved)
        assert isinstance(asm_src, str) and len(asm_src) > 0, "emit_program returned empty"

        asm_file = tmp_path / f"{name}.s"
        bin_file = tmp_path / name
        asm_file.write_text(asm_src)

        # Compile with gcc
        result = subprocess.run(
            ["gcc", "-o", str(bin_file), str(asm_file),
             "/opt/regalloc/runtime.c", "-no-pie"],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, (
            f"gcc failed for {name}:\n{result.stderr}"
        )

        # Run the binary
        input_data = ("\n".join(str(i) for i in inputs) + "\n") if inputs else ""
        result = subprocess.run(
            [str(bin_file)],
            input=input_data, capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, (
            f"Binary {name} exited with code {result.returncode}:\n{result.stderr}"
        )

        output_lines = [int(x) for x in result.stdout.strip().split("\n") if x.strip()]
        assert output_lines == expected, (
            f"{name}: native binary output {output_lines} != expected {expected}"
        )

    def test_assembly_syntax_valid(self, tmp_path):
        """Assembly must at minimum parse without errors."""
        from emit_asm import emit_program
        name, program, expected, inputs = _PROGRAMS[0]
        res = allocate_registers(program)
        asm_src = emit_program(res.program, res.stack_size, res.used_callee_saved)

        asm_file = tmp_path / "syntax_check.s"
        obj_file = tmp_path / "syntax_check.o"
        asm_file.write_text(asm_src)

        result = subprocess.run(
            ["gcc", "-c", "-o", str(obj_file), str(asm_file)],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, (
            f"Assembly syntax error:\n{result.stderr}"
        )
