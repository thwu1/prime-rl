"""
Tests for the assembly optimizer.
Verifies correctness (semantic preservation) and optimization levels
(static instruction count targets) for all programs.

"""
import json
import os
import subprocess
import tempfile


PROGRAMS = ['prog1', 'prog2', 'prog3', 'prog4', 'prog5']

TEST_CASES = {
    'prog1': [
        ('6', '390\n'),
        ('100', '6030\n'),
        ('0', '30\n'),
        ('1', '90\n'),
    ],
    'prog2': [
        ('5', '36\n'),
        ('10', '121\n'),
        ('0', '1\n'),
        ('1', '4\n'),
        ('-3', '4\n'),
    ],
    'prog3': [
        ('5', '90\n'),
        ('10', '330\n'),
        ('0', '0\nzero\n'),
        ('1', '6\n'),
    ],
    'prog4': [
        ('5', '81\n'),
        ('10', '306\n'),
        ('-3', '55\n'),
        ('0', '14\n'),
        ('-1', '15\n'),
    ],
    'prog5': [
        ('5', '330\n'),
        ('10', '1310\n'),
        ('0', '0\n'),
        ('1', '14\n'),
    ],
}


def load_targets():
    with open('/app/targets.json') as f:
        return json.load(f)


def count_static_instructions(asm_file):
    """Count non-empty, non-comment, non-LABEL lines."""
    count = 0
    with open(asm_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('LABEL'):
                continue
            count += 1
    return count


def run_vm(asm_file, stdin_data):
    """Run program through the Go VM binary and return stdout."""
    result = subprocess.run(
        ['/app/vm', asm_file],
        input=stdin_data,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"VM error: {result.stderr}")
    return result.stdout


def run_optimizer(input_asm, output_asm):
    """Run the optimizer on a program."""
    result = subprocess.run(
        ['python3', '/app/optimizer.py', input_asm, output_asm],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Optimizer error: {result.stderr}")


class TestOptimizerExists:
    def test_optimizer_file_exists(self):
        assert os.path.isfile('/app/optimizer.py'), \
            "optimizer.py must exist at /app/optimizer.py"

    def test_optimizer_is_executable(self):
        """Verify optimizer runs without crashing on a simple program."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.asm', delete=False) as f:
            f.write('PUSH_INT 42\nPRINTLN\nHALT\n')
            infile = f.name
        outfile = infile + '.opt'
        try:
            run_optimizer(infile, outfile)
            assert os.path.isfile(outfile), "Optimizer did not produce output file"
        finally:
            os.unlink(infile)
            if os.path.exists(outfile):
                os.unlink(outfile)


class TestCorrectnessProg1:
    """Test prog1 preserves semantics after optimization."""
    def test_all_inputs(self):
        orig = '/app/programs/prog1.asm'
        opt = '/tmp/test_prog1_opt.asm'
        run_optimizer(orig, opt)
        for input_data, expected in TEST_CASES['prog1']:
            output = run_vm(opt, input_data + '\n')
            assert output == expected, \
                f"prog1 with input '{input_data}': expected '{expected.strip()}', got '{output.strip()}'"


class TestCorrectnessProg2:
    """Test prog2 preserves semantics after optimization."""
    def test_all_inputs(self):
        orig = '/app/programs/prog2.asm'
        opt = '/tmp/test_prog2_opt.asm'
        run_optimizer(orig, opt)
        for input_data, expected in TEST_CASES['prog2']:
            output = run_vm(opt, input_data + '\n')
            assert output == expected, \
                f"prog2 with input '{input_data}': expected '{expected.strip()}', got '{output.strip()}'"


class TestCorrectnessProg3:
    """Test prog3 preserves semantics after optimization."""
    def test_all_inputs(self):
        orig = '/app/programs/prog3.asm'
        opt = '/tmp/test_prog3_opt.asm'
        run_optimizer(orig, opt)
        for input_data, expected in TEST_CASES['prog3']:
            output = run_vm(opt, input_data + '\n')
            assert output == expected, \
                f"prog3 with input '{input_data}': expected '{expected.strip()}', got '{output.strip()}'"


class TestCorrectnessProg4:
    """Test prog4 preserves semantics after optimization."""
    def test_all_inputs(self):
        orig = '/app/programs/prog4.asm'
        opt = '/tmp/test_prog4_opt.asm'
        run_optimizer(orig, opt)
        for input_data, expected in TEST_CASES['prog4']:
            output = run_vm(opt, input_data + '\n')
            assert output == expected, \
                f"prog4 with input '{input_data}': expected '{expected.strip()}', got '{output.strip()}'"


class TestCorrectnessProg5:
    """Test prog5 preserves semantics after optimization."""
    def test_all_inputs(self):
        orig = '/app/programs/prog5.asm'
        opt = '/tmp/test_prog5_opt.asm'
        run_optimizer(orig, opt)
        for input_data, expected in TEST_CASES['prog5']:
            output = run_vm(opt, input_data + '\n')
            assert output == expected, \
                f"prog5 with input '{input_data}': expected '{expected.strip()}', got '{output.strip()}'"


class TestOptimizationTargets:
    """Test that optimized programs meet instruction count targets."""

    def _check_target(self, prog_name):
        targets = load_targets()
        target = targets[prog_name]['target']
        original_count = targets[prog_name]['original']

        orig = f'/app/programs/{prog_name}.asm'
        opt = f'/tmp/test_{prog_name}_target.asm'
        run_optimizer(orig, opt)

        opt_count = count_static_instructions(opt)
        assert opt_count <= target, \
            f"{prog_name}: optimized has {opt_count} instructions " \
            f"(original: {original_count}, target: <={target})"
        assert opt_count < original_count, \
            f"{prog_name}: optimized ({opt_count}) must be fewer than original ({original_count})"

    def test_prog1_target(self):
        self._check_target('prog1')

    def test_prog2_target(self):
        self._check_target('prog2')

    def test_prog3_target(self):
        self._check_target('prog3')

    def test_prog4_target(self):
        self._check_target('prog4')

    def test_prog5_target(self):
        self._check_target('prog5')


class TestOptimizedProgramValidity:
    """Test that optimized programs are valid assembly (no VM errors)."""

    def test_all_optimized_programs_run(self):
        """Verify all optimized programs can be executed by the VM."""
        for prog in PROGRAMS:
            orig = f'/app/programs/{prog}.asm'
            opt = f'/tmp/test_{prog}_valid.asm'
            run_optimizer(orig, opt)
            result = subprocess.run(
                ['/app/vm', opt],
                input='1\n',
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert result.returncode == 0, \
                f"{prog}: optimized program failed: {result.stderr}"
