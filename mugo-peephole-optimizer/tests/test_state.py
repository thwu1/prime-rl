
import subprocess
import os
import pytest

PROGRAMS = ['fib', 'fact', 'collatz', 'gcd']
MUGO = '/app/mugo'
WORKDIR = '/tmp/peephole_test'
MIN_REDUCTION_PCT = 10.0


def setup_module():
    assert os.path.exists(MUGO), "Mugo compiler not found at /app/mugo"
    os.makedirs(WORKDIR, exist_ok=True)


def compile_with_mugo(program_name):
    """Compile a .go program with mugo and return the assembly string."""
    src_path = f'/app/programs/{program_name}.go'
    with open(src_path, 'r') as f:
        source = f.read()
    result = subprocess.run(
        [MUGO], input=source, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, f"Mugo compilation failed for {program_name}: {result.stderr}"
    return result.stdout


def assemble_link_run(asm_content, name):
    """Assemble, link, and run assembly. Returns stdout."""
    asm_path = os.path.join(WORKDIR, f'{name}.asm')
    obj_path = os.path.join(WORKDIR, f'{name}.o')
    exe_path = os.path.join(WORKDIR, name)

    with open(asm_path, 'w') as f:
        f.write(asm_content)

    r = subprocess.run(
        ['nasm', '-felf64', '-o', obj_path, asm_path],
        capture_output=True, text=True
    )
    assert r.returncode == 0, f"NASM assembly failed for {name}: {r.stderr}"

    r = subprocess.run(
        ['ld', '-o', exe_path, obj_path],
        capture_output=True, text=True
    )
    assert r.returncode == 0, f"Linker failed for {name}: {r.stderr}"

    r = subprocess.run(
        [exe_path], capture_output=True, text=True, timeout=30
    )
    assert r.returncode == 0, f"Execution failed for {name}: return code {r.returncode}"
    return r.stdout


def find_optimizer():
    """Find the optimizer script."""
    for path in ['/app/optimizer.py', '/app/optimize.py',
                 '/app/optimizer.sh', '/app/optimize.sh']:
        if os.path.exists(path):
            return path
    return None


def run_optimizer(asm_content):
    """Run the student's optimizer on assembly content."""
    opt_path = find_optimizer()
    assert opt_path is not None, (
        "No optimizer found. Expected /app/optimizer.py or /app/optimize.py"
    )
    if opt_path.endswith('.py'):
        cmd = ['python3', opt_path]
    else:
        cmd = ['bash', opt_path]
    r = subprocess.run(
        cmd, input=asm_content, capture_output=True, text=True, timeout=60
    )
    assert r.returncode == 0, f"Optimizer failed: {r.stderr}"
    assert r.stdout.strip(), "Optimizer produced empty output"
    return r.stdout


def count_instructions(asm_content):
    """Count x86 instruction lines, excluding labels, directives, blanks."""
    count = 0
    for line in asm_content.split('\n'):
        s = line.strip()
        if not s:
            continue
        if s.startswith(';'):
            continue
        # Pure label line (no instruction after it)
        if s.endswith(':') and ' ' not in s:
            continue
        # Assembler directives at start of line
        if s.startswith(('section ', 'global ', 'align ')):
            continue
        # Data/BSS directives (may have label: prefix)
        if ' equ ' in s:
            continue
        if ' db ' in s or s.startswith('db '):
            continue
        if ' dq ' in s or s.startswith('dq '):
            continue
        if ' resq ' in s or s.startswith('resq '):
            continue
        if ' resb ' in s or s.startswith('resb '):
            continue
        count += 1
    return count


def get_expected(program_name):
    with open(f'/app/expected/{program_name}.txt', 'r') as f:
        return f.read()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_optimizer_exists():
    """An optimizer file must exist at /app/optimizer.py or similar."""
    assert find_optimizer() is not None, (
        "No optimizer found at /app/optimizer.py, /app/optimize.py, "
        "/app/optimizer.sh, or /app/optimize.sh"
    )


@pytest.mark.parametrize("program", PROGRAMS)
def test_original_correct(program):
    """Original (unoptimized) Mugo output assembles and runs correctly."""
    asm = compile_with_mugo(program)
    output = assemble_link_run(asm, f'{program}_orig')
    expected = get_expected(program)
    assert output == expected, (
        f"Original {program} output mismatch.\n"
        f"Expected:\n{expected}\nGot:\n{output}"
    )


@pytest.mark.parametrize("program", PROGRAMS)
def test_optimized_correct(program):
    """Optimized assembly produces output identical to expected."""
    asm = compile_with_mugo(program)
    expected = get_expected(program)
    opt_asm = run_optimizer(asm)
    output = assemble_link_run(opt_asm, f'{program}_opt')
    assert output == expected, (
        f"Optimized {program} output differs from expected.\n"
        f"Expected:\n{expected}\nGot:\n{output}"
    )


@pytest.mark.parametrize("program", PROGRAMS)
def test_instruction_count_reduced(program):
    """Optimizer must reduce instruction count for each program."""
    asm = compile_with_mugo(program)
    opt_asm = run_optimizer(asm)
    orig_count = count_instructions(asm)
    opt_count = count_instructions(opt_asm)
    assert opt_count < orig_count, (
        f"Optimizer did not reduce instructions for {program}: "
        f"{orig_count} -> {opt_count}"
    )


def test_overall_reduction_threshold():
    """Total instruction count reduction must be >= 10%."""
    total_orig = 0
    total_opt = 0
    for program in PROGRAMS:
        asm = compile_with_mugo(program)
        opt_asm = run_optimizer(asm)
        total_orig += count_instructions(asm)
        total_opt += count_instructions(opt_asm)
    reduction_pct = (total_orig - total_opt) / total_orig * 100
    assert reduction_pct >= MIN_REDUCTION_PCT, (
        f"Overall instruction reduction {reduction_pct:.1f}% is below "
        f"{MIN_REDUCTION_PCT}% threshold. "
        f"Original total: {total_orig}, Optimized total: {total_opt}"
    )
