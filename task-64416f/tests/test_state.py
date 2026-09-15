"""
Tests for the three-address code IR optimizer and build pipeline.
Verifies semantic correctness, optimization effectiveness, specific patterns,
DOT CFG generation, and Makefile pipeline targets.
"""
import subprocess
import os
import pytest

PROGRAMS = ['prog1', 'prog2', 'prog3', 'prog4', 'prog5', 'prog6']

EXPECTED_OUTPUTS = {
    'prog1': ['130'],
    'prog2': ['31', '31'],
    'prog3': ['42', '50'],
    'prog4': ['200'],
    'prog5': ['25', '6'],
    'prog6': ['1120'],
}

# Minimum number of instructions that must be removed per program
MIN_REDUCTION = {
    'prog1': 3,
    'prog2': 2,
    'prog3': 3,
    'prog4': 0,
    'prog5': 0,
    'prog6': 3,
}


def count_instructions(ir_text):
    """Count meaningful instructions (excludes labels, comments, func/endfunc, nop, blanks)."""
    count = 0
    for line in ir_text.strip().split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('func ') or line == 'endfunc':
            continue
        if line.endswith(':'):
            continue
        if line == 'nop':
            continue
        count += 1
    return count


def run_interpreter(ir_file):
    """Run the interpreter on an IR file and return output lines."""
    result = subprocess.run(
        ['python3', '/app/ir_interpreter.py', ir_file],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"Interpreter failed on {ir_file}: {result.stderr}"
    return result.stdout.strip().split('\n') if result.stdout.strip() else []


def run_optimizer(ir_file):
    """Run the optimizer and return the optimized IR text."""
    result = subprocess.run(
        ['python3', '/app/optimize.py', ir_file],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, f"Optimizer failed on {ir_file}: {result.stderr}"
    return result.stdout


# ---------------------------------------------------------------------------
# Semantic correctness: optimized programs must produce identical output
# ---------------------------------------------------------------------------

class TestSemanticCorrectness:

    @pytest.mark.parametrize("prog", PROGRAMS)
    def test_original_output(self, prog):
        """Verify the interpreter produces expected output on the original program."""
        ir_file = f'/app/programs/{prog}.ir'
        output = run_interpreter(ir_file)
        assert output == EXPECTED_OUTPUTS[prog], (
            f"Original {prog} output mismatch: {output} != {EXPECTED_OUTPUTS[prog]}"
        )

    @pytest.mark.parametrize("prog", PROGRAMS)
    def test_optimized_output_matches(self, prog, tmp_path):
        """Optimized program must produce the same output as the original."""
        ir_file = f'/app/programs/{prog}.ir'

        orig_output = run_interpreter(ir_file)

        opt_ir = run_optimizer(ir_file)
        assert opt_ir.strip(), f"Optimizer produced empty output for {prog}"

        opt_file = tmp_path / f'{prog}_opt.ir'
        opt_file.write_text(opt_ir)

        opt_output = run_interpreter(str(opt_file))
        assert opt_output == orig_output, (
            f"Optimized {prog} output differs: {opt_output} != {orig_output}"
        )


# ---------------------------------------------------------------------------
# Optimization effectiveness: instruction count must decrease
# ---------------------------------------------------------------------------

class TestOptimizationEffectiveness:

    @pytest.mark.parametrize("prog", PROGRAMS)
    def test_instruction_reduction(self, prog, tmp_path):
        """Optimized program should have fewer instructions."""
        ir_file = f'/app/programs/{prog}.ir'

        with open(ir_file) as f:
            orig_ir = f.read()
        orig_count = count_instructions(orig_ir)

        opt_ir = run_optimizer(ir_file)
        opt_count = count_instructions(opt_ir)

        min_red = MIN_REDUCTION[prog]
        if min_red > 0:
            assert opt_count <= orig_count - min_red, (
                f"{prog}: expected at least {min_red} fewer instructions, "
                f"got {orig_count} -> {opt_count} (reduction: {orig_count - opt_count})"
            )


# ---------------------------------------------------------------------------
# Specific optimization patterns
# ---------------------------------------------------------------------------

class TestSpecificOptimizations:

    def test_dead_code_removed_prog1(self):
        """prog1: assignments to unused1/unused2/unused3 should be eliminated."""
        opt_ir = run_optimizer('/app/programs/prog1.ir')
        assert 'unused2' not in opt_ir, "Dead code not eliminated: unused2 still present"
        assert 'unused3' not in opt_ir, "Dead code not eliminated: unused3 still present"

    def test_cse_applied_prog2(self, tmp_path):
        """prog2: redundant arithmetic should be reduced."""
        opt_ir = run_optimizer('/app/programs/prog2.ir')
        opt_file = tmp_path / 'prog2_opt.ir'
        opt_file.write_text(opt_ir)

        opt_output = run_interpreter(str(opt_file))
        assert opt_output == ['31', '31']

        arith_ops = sum(
            1 for line in opt_ir.split('\n')
            if any(op in line for op in [' + ', ' * '])
            and '=' in line
            and not line.strip().startswith('#')
        )
        assert arith_ops < 4, (
            f"Expected fewer than 4 arithmetic ops after CSE, got {arith_ops}"
        )

    def test_unreachable_removed_prog3(self):
        """prog3: unreachable code after goto must be removed."""
        opt_ir = run_optimizer('/app/programs/prog3.ir')
        lines = [
            l.strip() for l in opt_ir.split('\n')
            if l.strip() and not l.strip().startswith('#')
        ]
        has_y_assign = any('y = 100' in l or 'y=100' in l for l in lines)
        assert not has_y_assign, "Unreachable code not eliminated: y = 100 still present"

    def test_loop_correctness_prog4(self, tmp_path):
        """prog4: loop must produce correct output after optimization."""
        opt_ir = run_optimizer('/app/programs/prog4.ir')
        opt_file = tmp_path / 'prog4_opt.ir'
        opt_file.write_text(opt_ir)

        opt_output = run_interpreter(str(opt_file))
        assert opt_output == ['200'], (
            f"Loop optimization broke semantics: {opt_output}"
        )

    def test_branch_correctness_prog5(self, tmp_path):
        """prog5: constant propagation through branches must not break output."""
        opt_ir = run_optimizer('/app/programs/prog5.ir')
        opt_file = tmp_path / 'prog5_opt.ir'
        opt_file.write_text(opt_ir)

        opt_output = run_interpreter(str(opt_file))
        assert opt_output == ['25', '6'], (
            f"Branch optimization produced wrong result: {opt_output}"
        )

    def test_combined_opts_prog6(self, tmp_path):
        """prog6: combined optimizations should achieve significant reduction."""
        ir_file = '/app/programs/prog6.ir'
        with open(ir_file) as f:
            orig_ir = f.read()

        opt_ir = run_optimizer(ir_file)
        opt_file = tmp_path / 'prog6_opt.ir'
        opt_file.write_text(opt_ir)

        opt_output = run_interpreter(str(opt_file))
        assert opt_output == ['1120'], (
            f"Combined optimization broke semantics: {opt_output}"
        )

        orig_count = count_instructions(orig_ir)
        opt_count = count_instructions(opt_ir)
        assert opt_count < orig_count - 2, (
            f"Expected significant optimization for prog6, "
            f"got {orig_count} -> {opt_count}"
        )


# ---------------------------------------------------------------------------
# CFG DOT generation: optimizer --dot must produce valid graphviz
# ---------------------------------------------------------------------------

class TestCFGGeneration:

    @pytest.mark.parametrize("prog", PROGRAMS)
    def test_dot_output_is_valid_graphviz(self, prog, tmp_path):
        """DOT CFG output must be parseable by graphviz dot command."""
        result = subprocess.run(
            ['python3', '/app/optimize.py', '--dot', f'/app/programs/{prog}.ir'],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"--dot failed for {prog}: {result.stderr}"
        dot_content = result.stdout
        assert dot_content.strip(), f"--dot produced empty output for {prog}"
        assert 'digraph' in dot_content, f"DOT output missing 'digraph' keyword for {prog}"

        # Validate by running through graphviz dot
        dot_file = tmp_path / f'{prog}.dot'
        dot_file.write_text(dot_content)
        svg_file = tmp_path / f'{prog}.svg'

        val = subprocess.run(
            ['dot', '-Tsvg', str(dot_file), '-o', str(svg_file)],
            capture_output=True, text=True, timeout=30,
        )
        assert val.returncode == 0, (
            f"graphviz dot failed to render {prog}.dot: {val.stderr}"
        )
        assert os.path.getsize(str(svg_file)) > 0, f"Rendered SVG is empty for {prog}"

    def test_cfg_has_edges_for_jump_program(self):
        """prog3 (with goto) must have control flow edges in CFG."""
        result = subprocess.run(
            ['python3', '/app/optimize.py', '--dot', '/app/programs/prog3.ir'],
            capture_output=True, text=True, timeout=30,
        )
        dot = result.stdout
        edges = [l for l in dot.split('\n') if '->' in l]
        assert len(edges) >= 1, "CFG for prog3 (has goto) must have edges"

    def test_cfg_loop_has_back_edges(self):
        """prog4 (with loop) must have back-edge and sufficient edges."""
        result = subprocess.run(
            ['python3', '/app/optimize.py', '--dot', '/app/programs/prog4.ir'],
            capture_output=True, text=True, timeout=30,
        )
        dot = result.stdout
        edges = [l for l in dot.split('\n') if '->' in l]
        assert len(edges) >= 4, (
            f"Loop CFG (prog4) should have at least 4 edges, found {len(edges)}"
        )

    def test_cfg_conditional_has_branch_edges(self):
        """prog5 (with conditional) must have branch edges."""
        result = subprocess.run(
            ['python3', '/app/optimize.py', '--dot', '/app/programs/prog5.ir'],
            capture_output=True, text=True, timeout=30,
        )
        dot = result.stdout
        edges = [l for l in dot.split('\n') if '->' in l]
        assert len(edges) >= 3, (
            f"Conditional CFG (prog5) should have at least 3 edges, found {len(edges)}"
        )

    def test_cfg_nodes_have_instruction_labels(self):
        """CFG nodes should include instruction content in their labels."""
        result = subprocess.run(
            ['python3', '/app/optimize.py', '--dot', '/app/programs/prog1.ir'],
            capture_output=True, text=True, timeout=30,
        )
        dot = result.stdout
        assert 'label=' in dot, "CFG nodes should have label attributes"
        assert 'print' in dot, "CFG node labels should include instruction content"

    def test_cfg_uses_box_nodes(self):
        """CFG nodes should use box shape."""
        result = subprocess.run(
            ['python3', '/app/optimize.py', '--dot', '/app/programs/prog1.ir'],
            capture_output=True, text=True, timeout=30,
        )
        dot = result.stdout
        assert 'box' in dot, "CFG nodes should use box shape"


# ---------------------------------------------------------------------------
# Makefile pipeline: make all must orchestrate the full pipeline
# ---------------------------------------------------------------------------

class TestMakefilePipeline:
    """Tests that the Makefile correctly orchestrates the build pipeline."""

    @classmethod
    def setup_class(cls):
        """Run make clean then make all once for all tests in this class."""
        subprocess.run(
            ['make', 'clean'],
            cwd='/app', capture_output=True, timeout=30,
        )
        cls.make_result = subprocess.run(
            ['make', 'all'],
            cwd='/app', capture_output=True, text=True, timeout=120,
        )

    def test_make_all_succeeds(self):
        """make all must complete with exit code 0."""
        assert self.make_result.returncode == 0, (
            f"make all failed:\nstdout: {self.make_result.stdout}\n"
            f"stderr: {self.make_result.stderr}"
        )

    def test_optimized_ir_files_created(self):
        """make optimize must produce output/*.ir for all programs."""
        for prog in PROGRAMS:
            path = f'/app/output/{prog}.ir'
            assert os.path.exists(path), f"Missing {path}"
            assert os.path.getsize(path) > 0, f"Empty output file {path}"

    def test_dot_cfg_files_created(self):
        """make cfg must produce cfg/*.dot for all programs."""
        for prog in PROGRAMS:
            path = f'/app/cfg/{prog}.dot'
            assert os.path.exists(path), f"Missing {path}"
            with open(path) as f:
                content = f.read()
            assert 'digraph' in content, f"{path} is not valid DOT"

    def test_svg_renders_created(self):
        """make cfg must produce cfg/*.svg for all programs."""
        for prog in PROGRAMS:
            path = f'/app/cfg/{prog}.svg'
            assert os.path.exists(path), f"Missing {path}"
            assert os.path.getsize(path) > 0, f"Empty SVG {path}"

    def test_report_created_with_all_programs(self):
        """make report must produce report.txt listing all programs."""
        path = '/app/output/report.txt'
        assert os.path.exists(path), f"Missing {path}"
        with open(path) as f:
            content = f.read()
        for prog in PROGRAMS:
            assert prog in content, f"Report missing entry for {prog}"

    def test_make_clean_removes_artifacts(self):
        """make clean must remove output/ and cfg/ directories."""
        subprocess.run(
            ['make', 'clean'],
            cwd='/app', capture_output=True, timeout=30,
        )
        assert not os.path.exists('/app/output'), "output/ not removed by make clean"
        assert not os.path.exists('/app/cfg'), "cfg/ not removed by make clean"
        # Restore for other tests that may run after
        subprocess.run(
            ['make', 'all'],
            cwd='/app', capture_output=True, timeout=120,
        )
