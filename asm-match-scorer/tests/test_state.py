
"""
Tests for the assembly function match scorer.
All test object files are assembled at test time from .s sources in /tests/test_asm/.
Dynamic tests generate fresh assembly to prevent hardcoded lookup tables.
"""

import subprocess
import json
import os
import tempfile
import shutil
import pytest

ASM_DIR = '/tests/test_asm'


@pytest.fixture(scope='session')
def obj_dir():
    """Assemble all test .s files into .o files in a temp directory."""
    tmpdir = tempfile.mkdtemp(prefix='test_objs_')
    for fname in sorted(os.listdir(ASM_DIR)):
        if fname.endswith('.s'):
            src = os.path.join(ASM_DIR, fname)
            dst = os.path.join(tmpdir, fname[:-2] + '.o')
            result = subprocess.run(
                ['as', '--64', '-o', dst, src],
                capture_output=True, text=True
            )
            assert result.returncode == 0, f"Failed to assemble {fname}: {result.stderr}"
    yield tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)


def run_scorer(target_path, candidate_path):
    """Run the scorer and return parsed JSON output."""
    result = subprocess.run(
        ['python3', '/app/scorer.py', target_path, candidate_path],
        capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, (
        f"scorer.py failed (exit {result.returncode}):\n"
        f"stdout: {result.stdout[:500]}\nstderr: {result.stderr[:500]}"
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        pytest.fail(f"scorer.py output is not valid JSON:\n{result.stdout[:500]}")


def assemble_from_string(asm_text, dest_dir, name):
    """Write assembly text to file and assemble it."""
    s_path = os.path.join(dest_dir, f'{name}.s')
    o_path = os.path.join(dest_dir, f'{name}.o')
    with open(s_path, 'w') as f:
        f.write(asm_text)
    result = subprocess.run(
        ['as', '--64', '-o', o_path, s_path],
        capture_output=True, text=True
    )
    assert result.returncode == 0, f"Failed to assemble {name}: {result.stderr}"
    return o_path


# ---------------------------------------------------------------------------
# Identical functions must score 0
# ---------------------------------------------------------------------------

class TestIdentical:
    def test_score_zero(self, obj_dir):
        """Identical assembly files must produce score 0."""
        t = os.path.join(obj_dir, 't1_target.o')
        c = os.path.join(obj_dir, 't1_candidate.o')
        out = run_scorer(t, c)
        assert out['score'] == 0, f"Identical pair scored {out['score']}, expected 0"

    def test_self_compare(self, obj_dir):
        """Comparing a file to itself must produce score 0."""
        t = os.path.join(obj_dir, 't1_target.o')
        out = run_scorer(t, t)
        assert out['score'] == 0, f"Self-compare scored {out['score']}, expected 0"


# ---------------------------------------------------------------------------
# Register-renamed functions must score 0 after optimal mapping
# ---------------------------------------------------------------------------

class TestRegisterRename:
    def test_simple_rename(self, obj_dir):
        """Simple ebx<->ecx swap must score 0."""
        t = os.path.join(obj_dir, 't2_target.o')
        c = os.path.join(obj_dir, 't2_candidate.o')
        out = run_scorer(t, c)
        assert out['score'] == 0, f"Simple rename scored {out['score']}, expected 0"

    def test_extended_registers(self, obj_dir):
        """Extended register r8<->r9 swap (mixing 64/32-bit forms) must score 0."""
        t = os.path.join(obj_dir, 't3_target.o')
        c = os.path.join(obj_dir, 't3_candidate.o')
        out = run_scorer(t, c)
        assert out['score'] == 0, f"Extended reg rename scored {out['score']}, expected 0"

    def test_cyclic_rename(self, obj_dir):
        """Cyclic 3-register permutation (ebx->ecx->edx->ebx) must score 0."""
        t = os.path.join(obj_dir, 't4_target.o')
        c = os.path.join(obj_dir, 't4_candidate.o')
        out = run_scorer(t, c)
        assert out['score'] == 0, f"Cyclic rename scored {out['score']}, expected 0"


# ---------------------------------------------------------------------------
# Different functions must score > 0
# ---------------------------------------------------------------------------

class TestDifferent:
    def test_mnemonic_diff(self, obj_dir):
        """Single mnemonic change (add vs sub) must score > 0."""
        t = os.path.join(obj_dir, 't5_target.o')
        c = os.path.join(obj_dir, 't5_candidate.o')
        out = run_scorer(t, c)
        assert out['score'] > 0, f"Mnemonic diff scored 0, expected > 0"

    def test_length_diff(self, obj_dir):
        """Different-length functions must score > 0."""
        t = os.path.join(obj_dir, 't6_target.o')
        c = os.path.join(obj_dir, 't6_candidate.o')
        out = run_scorer(t, c)
        assert out['score'] > 0, f"Length diff scored 0, expected > 0"

    def test_completely_different(self, obj_dir):
        """Completely different functions must score > 0."""
        t = os.path.join(obj_dir, 't7_target.o')
        c = os.path.join(obj_dir, 't7_candidate.o')
        out = run_scorer(t, c)
        assert out['score'] > 0, f"Completely different scored 0, expected > 0"


# ---------------------------------------------------------------------------
# Mathematical properties
# ---------------------------------------------------------------------------

class TestProperties:
    @pytest.mark.parametrize("pair", [
        ('t2_target', 't2_candidate'),
        ('t3_target', 't3_candidate'),
        ('t5_target', 't5_candidate'),
        ('t7_target', 't7_candidate'),
    ])
    def test_symmetry(self, obj_dir, pair):
        """Score must be symmetric: score(A,B) == score(B,A)."""
        t = os.path.join(obj_dir, f'{pair[0]}.o')
        c = os.path.join(obj_dir, f'{pair[1]}.o')
        s1 = run_scorer(t, c)['score']
        s2 = run_scorer(c, t)['score']
        assert s1 == s2, (
            f"Asymmetric scores for ({pair[0]}, {pair[1]}): {s1} vs {s2}"
        )

    def test_ranking_completely_different_worse_than_single_diff(self, obj_dir):
        """Completely different function must score strictly worse than single mnemonic change."""
        s_single = run_scorer(
            os.path.join(obj_dir, 't5_target.o'),
            os.path.join(obj_dir, 't5_candidate.o')
        )['score']
        s_total = run_scorer(
            os.path.join(obj_dir, 't7_target.o'),
            os.path.join(obj_dir, 't7_candidate.o')
        )['score']
        assert s_total > s_single, (
            f"Ranking violated: completely_different ({s_total}) should be > "
            f"single_mnemonic_diff ({s_single})"
        )

    def test_bijective_mapping(self, obj_dir):
        """Register mapping must be bijective (no duplicate values)."""
        t = os.path.join(obj_dir, 't2_target.o')
        c = os.path.join(obj_dir, 't2_candidate.o')
        out = run_scorer(t, c)
        mapping = out.get('register_mapping', {})
        values = list(mapping.values())
        assert len(values) == len(set(values)), (
            f"Non-bijective mapping: {mapping}"
        )


# ---------------------------------------------------------------------------
# Output format
# ---------------------------------------------------------------------------

class TestOutputFormat:
    def test_required_fields(self, obj_dir):
        """Output must contain score, num_target, num_candidate, register_mapping."""
        t = os.path.join(obj_dir, 't1_target.o')
        c = os.path.join(obj_dir, 't1_candidate.o')
        out = run_scorer(t, c)
        assert 'score' in out, "Missing 'score' field"
        assert 'num_target' in out, "Missing 'num_target' field"
        assert 'num_candidate' in out, "Missing 'num_candidate' field"
        assert 'register_mapping' in out, "Missing 'register_mapping' field"

    def test_field_types(self, obj_dir):
        """Fields must have correct types."""
        t = os.path.join(obj_dir, 't1_target.o')
        c = os.path.join(obj_dir, 't1_candidate.o')
        out = run_scorer(t, c)
        assert isinstance(out['score'], int), f"score type: {type(out['score'])}"
        assert out['score'] >= 0, f"score must be non-negative: {out['score']}"
        assert isinstance(out['num_target'], int), f"num_target type: {type(out['num_target'])}"
        assert isinstance(out['num_candidate'], int), f"num_candidate type: {type(out['num_candidate'])}"
        assert out['num_target'] > 0, "num_target must be positive"
        assert out['num_candidate'] > 0, "num_candidate must be positive"
        assert isinstance(out['register_mapping'], dict), (
            f"register_mapping type: {type(out['register_mapping'])}"
        )


# ---------------------------------------------------------------------------
# Dynamic tests — assembly generated at test time to prevent hardcoding
# ---------------------------------------------------------------------------

class TestDynamic:
    def test_dynamic_rename_r14_r15(self, obj_dir):
        """Register rename with r14/r15 (not used in any static test case)."""
        target_asm = (
            ".text\n.globl dyn_fn\ndyn_fn:\n"
            "    movl %edi, %r14d\n"
            "    movl %esi, %r15d\n"
            "    addl %r15d, %r14d\n"
            "    imull $13, %r14d, %r14d\n"
            "    movl %r14d, %eax\n"
            "    retq\n"
        )
        candidate_asm = (
            ".text\n.globl dyn_fn\ndyn_fn:\n"
            "    movl %edi, %r15d\n"
            "    movl %esi, %r14d\n"
            "    addl %r14d, %r15d\n"
            "    imull $13, %r15d, %r15d\n"
            "    movl %r15d, %eax\n"
            "    retq\n"
        )
        t = assemble_from_string(target_asm, obj_dir, 'dyn_r14r15_t')
        c = assemble_from_string(candidate_asm, obj_dir, 'dyn_r14r15_c')
        out = run_scorer(t, c)
        assert out['score'] == 0, (
            f"Dynamic r14/r15 rename should score 0, got {out['score']}"
        )

    def test_dynamic_different(self, obj_dir):
        """Novel different function pair generated at test time."""
        target_asm = (
            ".text\n.globl dyn_diff\ndyn_diff:\n"
            "    movl %edi, %eax\n"
            "    sarl $4, %eax\n"
            "    andl $0xf0, %eax\n"
            "    retq\n"
        )
        candidate_asm = (
            ".text\n.globl dyn_diff\ndyn_diff:\n"
            "    movl %edi, %eax\n"
            "    shll $4, %eax\n"
            "    orl $0x0f, %eax\n"
            "    retq\n"
        )
        t = assemble_from_string(target_asm, obj_dir, 'dyn_diff_t')
        c = assemble_from_string(candidate_asm, obj_dir, 'dyn_diff_c')
        out = run_scorer(t, c)
        assert out['score'] > 0, (
            f"Dynamic different pair should score > 0, got {out['score']}"
        )

    def test_dynamic_four_reg_cycle(self, obj_dir):
        """4-register cyclic permutation (r10->r11->r12->r13->r10)."""
        target_asm = (
            ".text\n.globl dyn_cycle\ndyn_cycle:\n"
            "    movl $1, %r10d\n"
            "    movl $2, %r11d\n"
            "    movl $3, %r12d\n"
            "    movl $4, %r13d\n"
            "    addl %r10d, %r11d\n"
            "    addl %r11d, %r12d\n"
            "    addl %r12d, %r13d\n"
            "    movl %r13d, %eax\n"
            "    retq\n"
        )
        candidate_asm = (
            ".text\n.globl dyn_cycle\ndyn_cycle:\n"
            "    movl $1, %r11d\n"
            "    movl $2, %r12d\n"
            "    movl $3, %r13d\n"
            "    movl $4, %r10d\n"
            "    addl %r11d, %r12d\n"
            "    addl %r12d, %r13d\n"
            "    addl %r13d, %r10d\n"
            "    movl %r10d, %eax\n"
            "    retq\n"
        )
        t = assemble_from_string(target_asm, obj_dir, 'dyn_cyc_t')
        c = assemble_from_string(candidate_asm, obj_dir, 'dyn_cyc_c')
        out = run_scorer(t, c)
        assert out['score'] == 0, (
            f"4-register cycle should score 0, got {out['score']}"
        )

    def test_dynamic_self_score(self, obj_dir):
        """A freshly assembled file compared to itself must score 0."""
        asm = (
            ".text\n.globl dyn_self\ndyn_self:\n"
            "    pushq %rbp\n"
            "    movq %rsp, %rbp\n"
            "    movl %edi, %r11d\n"
            "    addl %esi, %r11d\n"
            "    imull %edx, %r11d\n"
            "    movl %r11d, %eax\n"
            "    popq %rbp\n"
            "    retq\n"
        )
        t = assemble_from_string(asm, obj_dir, 'dyn_self')
        out = run_scorer(t, t)
        assert out['score'] == 0, (
            f"Dynamic self-compare should score 0, got {out['score']}"
        )
