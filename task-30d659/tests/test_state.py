
import subprocess
import json
import re
import pytest


def run_optimizer(input_file, stats=False):
    """Run the RVV peephole optimizer on an input file."""
    cmd = ["python3", "/app/rvv_peephole.py", input_file]
    if stats:
        cmd.append("--stats")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, f"Optimizer failed with exit code {result.returncode}: {result.stderr}"
    return result.stdout


def extract_function(asm_text, func_name):
    """Extract assembly lines for a function, from its label to the next .globl."""
    lines = asm_text.split('\n')
    start = None
    for i, line in enumerate(lines):
        if re.match(rf'^\s*{re.escape(func_name)}\s*:', line.strip()):
            start = i
            break
    if start is None:
        pytest.fail(f"Function '{func_name}' not found in output")

    end = len(lines)
    for i in range(start + 1, len(lines)):
        if re.match(r'^\s*\.globl\b', lines[i]):
            end = i
            break

    return '\n'.join(lines[start:end])


def count_instruction(asm_text, mnemonic):
    """Count exact occurrences of a specific instruction mnemonic."""
    count = 0
    for line in asm_text.split('\n'):
        stripped = line.strip()
        ci = stripped.find('#')
        if ci >= 0:
            stripped = stripped[:ci].strip()
        m = re.match(r'^\.?\w+\s*:\s*(.*)', stripped)
        if m:
            stripped = m.group(1).strip()
        if not stripped:
            continue
        parts = stripped.split(None, 1)
        if parts and parts[0] == mnemonic:
            count += 1
    return count


def has_instruction(asm_text, mnemonic):
    return count_instruction(asm_text, mnemonic) > 0


# ---------------------------------------------------------------------------
# Test vsetvli elimination (input_basic.s)
# ---------------------------------------------------------------------------
class TestVsetvliElimination:
    """Verify redundant vsetvli instructions are removed correctly."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.output = run_optimizer("/app/input/input_basic.s")

    def test_vec_add_eliminates_redundant_vsetvli(self):
        func = extract_function(self.output, "vec_add_f32")
        assert count_instruction(func, "vsetvli") == 1, \
            "vec_add_f32 should have exactly 1 vsetvli (second is redundant)"

    def test_vec_saxpy_eliminates_redundant_vsetvli(self):
        func = extract_function(self.output, "vec_saxpy_f64")
        assert count_instruction(func, "vsetvli") == 1, \
            "vec_saxpy_f64 should have exactly 1 vsetvli (second is redundant)"

    def test_vec_convert_keeps_different_vsetvli(self):
        func = extract_function(self.output, "vec_convert")
        assert count_instruction(func, "vsetvli") == 2, \
            "vec_convert must keep both vsetvli (different SEW/LMUL configs)"

    def test_preserves_arithmetic_instructions(self):
        func = extract_function(self.output, "vec_add_f32")
        assert has_instruction(func, "vle32.v"), "vle32.v must be preserved"
        assert has_instruction(func, "vfadd.vv"), "vfadd.vv must be preserved"
        assert has_instruction(func, "vse32.v"), "vse32.v must be preserved"

    def test_preserves_branch_and_ret(self):
        func = extract_function(self.output, "vec_add_f32")
        assert has_instruction(func, "bnez"), "bnez must be preserved"
        assert has_instruction(func, "ret"), "ret must be preserved"


# ---------------------------------------------------------------------------
# Test vector-scalar fusion (input_fusion.s)
# ---------------------------------------------------------------------------
class TestVectorScalarFusion:
    """Verify broadcast-to-scalar fusion and negative cases."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.output = run_optimizer("/app/input/input_fusion.s")

    def test_fma_splat_fused_to_vf(self):
        func = extract_function(self.output, "fma_splat")
        assert not has_instruction(func, "vfmv.v.f"), \
            "vfmv.v.f should be removed after fusion"
        assert not has_instruction(func, "vfmadd.vv"), \
            "vfmadd.vv should be converted to vfmadd.vf"
        assert has_instruction(func, "vfmadd.vf"), \
            "Should have vfmadd.vf after fusion"

    def test_fma_splat_stored_not_fused(self):
        func = extract_function(self.output, "fma_splat_stored")
        assert has_instruction(func, "vfmv.v.f"), \
            "vfmv.v.f must be kept (broadcast value stored to memory)"
        assert has_instruction(func, "vfmadd.vv"), \
            "vfmadd.vv must NOT be fused (broadcast has non-fusable use)"
        assert not has_instruction(func, "vfmadd.vf"), \
            "Should NOT have vfmadd.vf when broadcast is stored"

    def test_int_add_scalar_fused_to_vx(self):
        func = extract_function(self.output, "int_add_scalar")
        assert not has_instruction(func, "vmv.v.x"), \
            "vmv.v.x should be removed after fusion"
        assert not has_instruction(func, "vadd.vv"), \
            "vadd.vv should be converted to vadd.vx"
        assert has_instruction(func, "vadd.vx"), \
            "Should have vadd.vx after fusion"

    def test_int_add_scalar_stored_not_fused(self):
        func = extract_function(self.output, "int_add_scalar_stored")
        assert has_instruction(func, "vmv.v.x"), \
            "vmv.v.x must be kept (broadcast value stored to memory)"
        assert has_instruction(func, "vadd.vv"), \
            "vadd.vv must NOT be fused (broadcast has non-fusable use)"

    def test_multi_fuse_all_uses_converted(self):
        func = extract_function(self.output, "multi_fuse")
        assert not has_instruction(func, "vmv.v.x"), \
            "vmv.v.x should be removed (all uses fusable)"
        assert count_instruction(func, "vadd.vx") == 2, \
            "Both vadd.vv should be converted to vadd.vx"
        assert count_instruction(func, "vadd.vv") == 0, \
            "No vadd.vv should remain"


# ---------------------------------------------------------------------------
# Test mixed optimizations (input_mixed.s)
# ---------------------------------------------------------------------------
class TestMixedOptimizations:
    """Verify combined vsetvli elimination and fusion, plus control flow cases."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.output = run_optimizer("/app/input/input_mixed.s")

    def test_mixed_opts_both_optimizations(self):
        func = extract_function(self.output, "mixed_opts")
        assert count_instruction(func, "vsetvli") == 1, \
            "Should eliminate the redundant vsetvli"
        assert has_instruction(func, "vfmul.vf"), \
            "Should fuse vfmul.vv to vfmul.vf"
        assert not has_instruction(func, "vfmul.vv"), \
            "vfmul.vv should be replaced"
        assert not has_instruction(func, "vfmv.v.f"), \
            "vfmv.v.f should be removed"

    def test_across_label_keeps_both_vsetvli(self):
        func = extract_function(self.output, "across_label")
        assert count_instruction(func, "vsetvli") == 2, \
            "Must keep both vsetvli (label between them is a branch target)"

    def test_chain_fusion_both_broadcasts(self):
        func = extract_function(self.output, "chain_fusion")
        assert not has_instruction(func, "vfmv.v.f"), \
            "Both vfmv.v.f should be removed"
        assert has_instruction(func, "vfmul.vf"), \
            "First fusion: vfmul.vv -> vfmul.vf"
        assert has_instruction(func, "vfmadd.vf"), \
            "Second fusion: vfmadd.vv -> vfmadd.vf"
        assert not has_instruction(func, "vfmul.vv"), \
            "No vfmul.vv should remain"
        assert not has_instruction(func, "vfmadd.vv"), \
            "No vfmadd.vv should remain"


# ---------------------------------------------------------------------------
# Test edge cases (input_edge.s)
# ---------------------------------------------------------------------------
class TestEdgeCases:
    """Verify edge case handling in input_edge.s."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.output = run_optimizer("/app/input/input_edge.s")

    def test_sub_fusable_converts_to_vx(self):
        func = extract_function(self.output, "vec_sub_fusable")
        assert not has_instruction(func, "vmv.v.x"), \
            "vmv.v.x should be removed (fusable use)"
        assert has_instruction(func, "vsub.vx"), \
            "vsub.vv should be converted to vsub.vx"
        assert not has_instruction(func, "vsub.vv"), \
            "vsub.vv should not remain"

    def test_sub_nonfusable_preserves_broadcast(self):
        func = extract_function(self.output, "vec_sub_nonfusable")
        assert has_instruction(func, "vmv.v.x"), \
            "vmv.v.x must be kept (non-fusable operand position in non-commutative op)"
        assert has_instruction(func, "vsub.vv"), \
            "vsub.vv must NOT be fused (broadcast in wrong position)"

    def test_vsetvli_diff_rd_not_eliminated(self):
        func = extract_function(self.output, "vsetvli_diff_rd")
        assert count_instruction(func, "vsetvli") == 2, \
            "Both vsetvli must be kept (different destination registers)"

    def test_broadcast_before_kill_partial_fusion(self):
        func = extract_function(self.output, "broadcast_before_kill")
        assert not has_instruction(func, "vmv.v.x"), \
            "vmv.v.x should be removed (only fusable use before kill)"
        assert count_instruction(func, "vadd.vx") == 1, \
            "First vadd should be fused to vadd.vx"
        assert count_instruction(func, "vadd.vv") == 1, \
            "Second vadd should remain as vadd.vv (uses reloaded vector)"
        assert has_instruction(func, "vle32.v"), \
            "Vector load that overwrites broadcast reg must be preserved"

    def test_sub_fusable_correct_scalar_reg(self):
        func = extract_function(self.output, "vec_sub_fusable")
        for line in func.split('\n'):
            stripped = line.strip()
            if stripped.startswith("vsub.vx"):
                assert "a4" in stripped, \
                    "Fused vsub.vx must reference original scalar register a4"
                break
        else:
            pytest.fail("No vsub.vx found in vec_sub_fusable")

    def test_broadcast_kill_correct_scalar_reg(self):
        func = extract_function(self.output, "broadcast_before_kill")
        for line in func.split('\n'):
            stripped = line.strip()
            if stripped.startswith("vadd.vx"):
                assert "a4" in stripped, \
                    "Fused vadd.vx must reference original scalar register a4"
                break
        else:
            pytest.fail("No vadd.vx found in broadcast_before_kill")


# ---------------------------------------------------------------------------
# Test --stats JSON output
# ---------------------------------------------------------------------------
class TestStatsOutput:
    """Verify --stats produces correct JSON statistics."""

    def test_basic_stats(self):
        output = run_optimizer("/app/input/input_basic.s", stats=True)
        stats = json.loads(output)
        assert stats["redundant_vsetvli_removed"] == 2, \
            "input_basic.s has 2 redundant vsetvli"
        assert stats["fusions_applied"] == 0
        assert stats["broadcast_instructions_removed"] == 0

    def test_fusion_stats(self):
        output = run_optimizer("/app/input/input_fusion.s", stats=True)
        stats = json.loads(output)
        assert stats["redundant_vsetvli_removed"] == 0
        assert stats["fusions_applied"] == 4, \
            "4 fusions: 1 in fma_splat, 1 in int_add_scalar, 2 in multi_fuse"
        assert stats["broadcast_instructions_removed"] == 3, \
            "3 broadcasts removed: fma_splat, int_add_scalar, multi_fuse"

    def test_mixed_stats(self):
        output = run_optimizer("/app/input/input_mixed.s", stats=True)
        stats = json.loads(output)
        assert stats["redundant_vsetvli_removed"] == 1, \
            "1 redundant vsetvli in mixed_opts"
        assert stats["fusions_applied"] == 3, \
            "3 fusions: 1 in mixed_opts, 2 in chain_fusion"
        assert stats["broadcast_instructions_removed"] == 3, \
            "3 broadcasts removed: 1 in mixed_opts, 2 in chain_fusion"

    def test_edge_stats(self):
        output = run_optimizer("/app/input/input_edge.s", stats=True)
        stats = json.loads(output)
        assert stats["redundant_vsetvli_removed"] == 0, \
            "No vsetvli should be eliminated (different rd case)"
        assert stats["fusions_applied"] == 2, \
            "2 fusions: vec_sub_fusable + broadcast_before_kill"
        assert stats["broadcast_instructions_removed"] == 2, \
            "2 broadcasts removed: vec_sub_fusable + broadcast_before_kill"

    def test_stats_is_valid_json(self):
        for fname in ["input_basic.s", "input_fusion.s", "input_mixed.s", "input_edge.s"]:
            output = run_optimizer(f"/app/input/{fname}", stats=True)
            stats = json.loads(output)
            assert isinstance(stats["redundant_vsetvli_removed"], int)
            assert isinstance(stats["fusions_applied"], int)
            assert isinstance(stats["broadcast_instructions_removed"], int)


# ---------------------------------------------------------------------------
# Test output validity
# ---------------------------------------------------------------------------
class TestOutputValidity:
    """Verify the output is structurally valid assembly."""

    def test_directives_preserved(self):
        for fname in ["input_basic.s", "input_fusion.s", "input_mixed.s", "input_edge.s"]:
            output = run_optimizer(f"/app/input/{fname}")
            assert ".text" in output, f".text directive missing in {fname} output"
            assert ".globl" in output, f".globl directive missing in {fname} output"

    def test_function_labels_preserved(self):
        output = run_optimizer("/app/input/input_basic.s")
        assert "vec_add_f32:" in output
        assert "vec_saxpy_f64:" in output
        assert "vec_convert:" in output

    def test_local_labels_preserved(self):
        output = run_optimizer("/app/input/input_mixed.s")
        assert ".Lskip:" in output, "Local label .Lskip must be preserved"

    def test_output_is_nonempty(self):
        for fname in ["input_basic.s", "input_fusion.s", "input_mixed.s", "input_edge.s"]:
            output = run_optimizer(f"/app/input/{fname}")
            assert len(output.strip()) > 100, f"Output for {fname} suspiciously short"

    def test_fused_instruction_has_correct_scalar_reg(self):
        """Verify the fused instruction references the original scalar register."""
        output = run_optimizer("/app/input/input_fusion.s")
        func = extract_function(output, "fma_splat")
        for line in func.split('\n'):
            stripped = line.strip()
            if stripped.startswith("vfmadd.vf"):
                assert "fa4" in stripped, \
                    "Fused vfmadd.vf must reference original scalar register fa4"
                break
        else:
            pytest.fail("No vfmadd.vf found in fma_splat")

    def test_fused_int_instruction_has_correct_scalar_reg(self):
        """Verify the fused vadd.vx references the original integer register."""
        output = run_optimizer("/app/input/input_fusion.s")
        func = extract_function(output, "int_add_scalar")
        for line in func.split('\n'):
            stripped = line.strip()
            if stripped.startswith("vadd.vx"):
                assert "a4" in stripped, \
                    "Fused vadd.vx must reference original scalar register a4"
                break
        else:
            pytest.fail("No vadd.vx found in int_add_scalar")

    def test_edge_function_labels_preserved(self):
        output = run_optimizer("/app/input/input_edge.s")
        assert "vec_sub_fusable:" in output
        assert "vec_sub_nonfusable:" in output
        assert "vsetvli_diff_rd:" in output
        assert "broadcast_before_kill:" in output


# ---------------------------------------------------------------------------
# Test assembly validation with riscv64-linux-gnu-as
# ---------------------------------------------------------------------------
class TestAssemblyValidation:
    """Verify optimized output assembles correctly with the RISC-V cross-assembler."""

    @pytest.mark.parametrize("input_file", [
        "/app/input/input_basic.s",
        "/app/input/input_fusion.s",
        "/app/input/input_mixed.s",
        "/app/input/input_edge.s",
    ])
    def test_output_assembles(self, input_file, tmp_path):
        output = run_optimizer(input_file)
        asm_file = tmp_path / "output.s"
        asm_file.write_text(output)
        result = subprocess.run(
            ["riscv64-linux-gnu-as", "-march=rv64gcv", "-o", "/dev/null", str(asm_file)],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, \
            f"Output for {input_file} failed to assemble:\n{result.stderr}"
