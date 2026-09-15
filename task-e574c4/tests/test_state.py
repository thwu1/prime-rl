
import subprocess
import os
import re
import pytest

PROGRAMS = [
    'const_fold.tac',
    'dead_stores.tac',
    'cse.tac',
    'loop_combined.tac',
    'nested_flow.tac',
]

MAX_INSTRUCTIONS = {
    'const_fold.tac': 10,
    'dead_stores.tac': 12,
    'cse.tac': 16,
    'loop_combined.tac': 18,
    'nested_flow.tac': 25,
}

INTERPRETER = '/opt/tac/interpreter.py'
VALIDATOR = '/opt/tac/tac_validate.py'
PROGDIR = '/opt/tac/programs'


def count_instructions(tac_code):
    """Count executable instructions (not labels, comments, FUNC, END, or blanks)."""
    count = 0
    for line in tac_code.strip().split('\n'):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith('#'):
            continue
        if stripped.startswith('FUNC '):
            continue
        if stripped == 'END':
            continue
        if re.match(r'^\w+\s*:\s*$', stripped):
            continue
        count += 1
    return count


def run_interpreter(tac_file):
    """Run the TAC interpreter and return (stdout, returncode)."""
    result = subprocess.run(
        ['python3', INTERPRETER, tac_file],
        capture_output=True, text=True, timeout=30
    )
    return result.stdout.strip(), result.returncode


def run_optimizer(tac_file, output_file):
    """Run the optimizer, save output to file, return the optimized TAC text."""
    result = subprocess.run(
        ['bash', '/app/optimize.sh', tac_file],
        capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, \
        f"Optimizer failed on {tac_file}: stderr={result.stderr}"
    with open(output_file, 'w') as f:
        f.write(result.stdout)
    return result.stdout


class TestOptimizerCorrectness:
    """Optimized programs must produce identical output to originals."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.tmp = tmp_path
        self.progdir = PROGDIR

    @pytest.mark.parametrize("prog", PROGRAMS)
    def test_semantic_equivalence(self, prog):
        src = os.path.join(self.progdir, prog)
        opt = os.path.join(str(self.tmp), f'opt_{prog}')
        orig_out, orig_rc = run_interpreter(src)
        assert orig_rc == 0, f"Original {prog} crashed (rc={orig_rc})"
        opt_code = run_optimizer(src, opt)
        assert opt_code.strip(), f"Optimizer produced empty output for {prog}"
        opt_out, opt_rc = run_interpreter(opt)
        assert opt_rc == 0, f"Interpreter crashed on optimized {prog}"
        assert orig_out == opt_out, (
            f"Output mismatch for {prog}:\n"
            f"  Original:  {orig_out!r}\n"
            f"  Optimized: {opt_out!r}"
        )

    @pytest.mark.parametrize("prog", PROGRAMS)
    def test_output_is_valid_tac(self, prog):
        src = os.path.join(self.progdir, prog)
        opt = os.path.join(str(self.tmp), f'opt_{prog}')
        opt_code = run_optimizer(src, opt)
        assert 'FUNC' in opt_code, f"Optimized {prog} missing FUNC"
        assert 'END' in opt_code, f"Optimized {prog} missing END"
        result = subprocess.run(
            ['python3', INTERPRETER, opt],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, \
            f"Interpreter crashed on optimized {prog}: {result.stderr}"

    @pytest.mark.parametrize("prog", PROGRAMS)
    def test_tac_validates(self, prog):
        """Optimized TAC must pass the tac_validate tool."""
        src = os.path.join(self.progdir, prog)
        opt = os.path.join(str(self.tmp), f'opt_{prog}')
        run_optimizer(src, opt)
        result = subprocess.run(
            ['python3', VALIDATOR, opt],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, \
            f"tac_validate failed on optimized {prog}: {result.stderr}"


class TestOptimizationEffectiveness:
    """Optimized programs must meet instruction-count targets."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.tmp = tmp_path
        self.progdir = PROGDIR

    @pytest.mark.parametrize("prog", PROGRAMS)
    def test_instruction_reduction(self, prog):
        src = os.path.join(self.progdir, prog)
        opt = os.path.join(str(self.tmp), f'opt_{prog}')
        with open(src) as f:
            orig_count = count_instructions(f.read())
        opt_code = run_optimizer(src, opt)
        opt_count = count_instructions(opt_code)
        limit = MAX_INSTRUCTIONS[prog]
        assert opt_count <= limit, (
            f"{prog}: {opt_count} instructions after optimization, "
            f"limit is {limit} (original: {orig_count})"
        )


class TestSpecificOptimizations:
    """Verify that particular optimization patterns are applied."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.tmp = tmp_path
        self.progdir = PROGDIR

    def test_const_fold_no_literal_arithmetic(self):
        """After folding, no var = <int> op <int> should remain."""
        src = os.path.join(self.progdir, 'const_fold.tac')
        opt = os.path.join(str(self.tmp), 'opt_const_fold.tac')
        opt_code = run_optimizer(src, opt)
        const_ops = 0
        for line in opt_code.split('\n'):
            line = line.strip()
            if line.startswith('#') or not line:
                continue
            if re.match(r'\w+\s*=\s*\-?\d+\s*[\+\-\*/%]\s*\-?\d+', line):
                const_ops += 1
        assert const_ops == 0, (
            f"Found {const_ops} operations on literal constants "
            f"that should have been folded"
        )

    def test_dead_stores_eliminated(self):
        """All dead<N> variables must be removed from dead_stores.tac."""
        src = os.path.join(self.progdir, 'dead_stores.tac')
        opt = os.path.join(str(self.tmp), 'opt_dead_stores.tac')
        opt_code = run_optimizer(src, opt)
        dead_vars = set(re.findall(r'\bdead\d+\b', opt_code))
        assert len(dead_vars) == 0, \
            f"Dead variables still present: {dead_vars}"

    def test_cse_a_plus_b(self):
        """In cse.tac, 'a + b' should be computed at most once."""
        src = os.path.join(self.progdir, 'cse.tac')
        opt = os.path.join(str(self.tmp), 'opt_cse.tac')
        opt_code = run_optimizer(src, opt)
        hits = len(re.findall(r'\w+\s*=\s*a\s*\+\s*b', opt_code))
        assert hits <= 1, \
            f"'a + b' computed {hits} times, expected at most 1 after CSE"

    def test_cse_a_times_b(self):
        """In cse.tac, 'a * b' should be computed at most once."""
        src = os.path.join(self.progdir, 'cse.tac')
        opt = os.path.join(str(self.tmp), 'opt_cse.tac')
        opt_code = run_optimizer(src, opt)
        hits = len(re.findall(r'\w+\s*=\s*a\s*\*\s*b', opt_code))
        assert hits <= 1, \
            f"'a * b' computed {hits} times, expected at most 1 after CSE"

    def test_loop_dead_code_removed(self):
        """Dead variables inside the loop in loop_combined.tac must go."""
        src = os.path.join(self.progdir, 'loop_combined.tac')
        opt = os.path.join(str(self.tmp), 'opt_loop_combined.tac')
        opt_code = run_optimizer(src, opt)
        dead_vars = set(re.findall(r'\bdead\d+\b', opt_code))
        assert len(dead_vars) == 0, \
            f"Dead variables in loop still present: {dead_vars}"

    def test_nested_dead_fib_removed(self):
        """Dead fibonacci helper vars in nested_flow.tac must be removed."""
        src = os.path.join(self.progdir, 'nested_flow.tac')
        opt = os.path.join(str(self.tmp), 'opt_nested_flow.tac')
        opt_code = run_optimizer(src, opt)
        dead_fib = set(re.findall(r'\bdead_fib\d+\b', opt_code))
        assert len(dead_fib) == 0, \
            f"Dead fibonacci variables still present: {dead_fib}"
        dead_final = set(re.findall(r'\bdead_final\w*\b', opt_code))
        assert len(dead_final) == 0, \
            f"Dead final variables still present: {dead_final}"


class TestCFGVisualization:
    """Optimizer must produce valid DOT CFG files renderable by graphviz."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.tmp = tmp_path
        self.progdir = PROGDIR

    @pytest.mark.parametrize("prog", PROGRAMS)
    def test_dot_file_exists(self, prog):
        """DOT file must be created at /app/cfg_output/<basename>.dot."""
        src = os.path.join(self.progdir, prog)
        opt = os.path.join(str(self.tmp), f'opt_{prog}')
        run_optimizer(src, opt)
        basename = prog.replace('.tac', '')
        dot_file = f'/app/cfg_output/{basename}.dot'
        assert os.path.exists(dot_file), \
            f"DOT CFG file not found at {dot_file}"

    @pytest.mark.parametrize("prog", PROGRAMS)
    def test_dot_valid_graphviz(self, prog):
        """DOT file must be renderable by dot -Tsvg."""
        src = os.path.join(self.progdir, prog)
        opt = os.path.join(str(self.tmp), f'opt_{prog}')
        run_optimizer(src, opt)
        basename = prog.replace('.tac', '')
        dot_file = f'/app/cfg_output/{basename}.dot'
        result = subprocess.run(
            ['dot', '-Tsvg', dot_file],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, \
            f"graphviz dot -Tsvg failed on {dot_file}: {result.stderr}"

    @pytest.mark.parametrize("prog", PROGRAMS)
    def test_dot_contains_block_labels(self, prog):
        """DOT file must have nodes for all basic block labels in optimized TAC."""
        src = os.path.join(self.progdir, prog)
        opt = os.path.join(str(self.tmp), f'opt_{prog}')
        opt_code = run_optimizer(src, opt)
        basename = prog.replace('.tac', '')
        dot_file = f'/app/cfg_output/{basename}.dot'
        with open(dot_file) as f:
            dot_content = f.read()
        labels = re.findall(r'^\s*(\w+)\s*:\s*$', opt_code, re.MULTILINE)
        for label in labels:
            assert label in dot_content, \
                f"Block label '{label}' not found in DOT file {dot_file}"

    @pytest.mark.parametrize("prog", PROGRAMS)
    def test_dot_has_edges_when_multiblock(self, prog):
        """DOT file must contain directed edges for multi-block programs."""
        src = os.path.join(self.progdir, prog)
        opt = os.path.join(str(self.tmp), f'opt_{prog}')
        opt_code = run_optimizer(src, opt)
        basename = prog.replace('.tac', '')
        dot_file = f'/app/cfg_output/{basename}.dot'
        with open(dot_file) as f:
            dot_content = f.read()
        has_cf = bool(re.search(r'\bGOTO\s+\w+', opt_code))
        if has_cf:
            assert '->' in dot_content, \
                f"No directed edges in DOT file {dot_file} despite GOTO/IF in output"


class TestLLVMCrossValidation:
    """Optimizer must produce LLVM IR that assembles and executes correctly."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.tmp = tmp_path
        self.progdir = PROGDIR

    @pytest.mark.parametrize("prog", PROGRAMS)
    def test_llvm_ir_file_exists(self, prog):
        """LLVM IR file must be created at /app/llvm_output/<basename>.ll."""
        src = os.path.join(self.progdir, prog)
        opt = os.path.join(str(self.tmp), f'opt_{prog}')
        run_optimizer(src, opt)
        basename = prog.replace('.tac', '')
        ll_file = f'/app/llvm_output/{basename}.ll'
        assert os.path.exists(ll_file), \
            f"LLVM IR file not found at {ll_file}"

    @pytest.mark.parametrize("prog", PROGRAMS)
    def test_llvm_ir_assembles(self, prog):
        """LLVM IR must assemble cleanly via llvm-as."""
        src = os.path.join(self.progdir, prog)
        opt = os.path.join(str(self.tmp), f'opt_{prog}')
        run_optimizer(src, opt)
        basename = prog.replace('.tac', '')
        ll_file = f'/app/llvm_output/{basename}.ll'
        bc_file = os.path.join(str(self.tmp), f'{basename}.bc')
        result = subprocess.run(
            ['llvm-as', '-o', bc_file, ll_file],
            capture_output=True, text=True, timeout=15
        )
        assert result.returncode == 0, \
            f"llvm-as failed on {ll_file}: {result.stderr}"

    @pytest.mark.parametrize("prog", PROGRAMS)
    def test_llvm_ir_executes_correctly(self, prog):
        """LLVM IR executed via lli must produce output identical to original TAC."""
        src = os.path.join(self.progdir, prog)
        orig_out, orig_rc = run_interpreter(src)
        assert orig_rc == 0, f"Original {prog} crashed"
        opt = os.path.join(str(self.tmp), f'opt_{prog}')
        run_optimizer(src, opt)
        basename = prog.replace('.tac', '')
        ll_file = f'/app/llvm_output/{basename}.ll'
        result = subprocess.run(
            ['lli', ll_file],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, \
            f"lli execution failed on {ll_file}: {result.stderr}"
        assert result.stdout.strip() == orig_out, (
            f"LLVM IR output mismatch for {prog}:\n"
            f"  Expected (TAC interpreter): {orig_out!r}\n"
            f"  Got (lli):                  {result.stdout.strip()!r}"
        )
