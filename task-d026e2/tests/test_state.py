
"""Tests for generalization-aware kernel evaluation pipeline."""

import os
import sys
import math
import shutil
import pytest
import yaml

sys.path.insert(0, '/app')


# ============================================================
# Test Injection Module
# ============================================================

class TestReplaceTestShapes:
    """Tests for bracket-balanced TEST_SHAPES replacement."""

    def test_basic_replacement(self):
        from evaluator.injection import replace_test_shapes

        source = (
            'import torch\n'
            '\n'
            'TEST_SHAPES = [\n'
            '    (2, 16, 128, 256, True, False),\n'
            '    (4, 32, 256, 512, True, True),\n'
            ']\n'
            '\n'
            'def run_test(shape):\n'
            '    pass\n'
        )
        replacement = (
            'TEST_SHAPES = [\n'
            '    (1, 8, 64, 128, True, False),\n'
            ']\n'
        )
        result = replace_test_shapes(source, replacement)
        assert '(1, 8, 64, 128, True, False)' in result
        assert '(2, 16, 128, 256, True, False)' not in result
        assert 'def run_test(shape):' in result
        assert 'import torch' in result

    def test_does_not_match_similar_names(self):
        from evaluator.injection import replace_test_shapes

        source = (
            'TEST_SHAPES = [\n'
            '    (1, 2, 3),\n'
            ']\n'
            '\n'
            'TEST_SHAPES_EXTENDED = []\n'
        )
        replacement = (
            'TEST_SHAPES = [\n'
            '    (4, 5, 6),\n'
            ']\n'
        )
        result = replace_test_shapes(source, replacement)
        assert '(4, 5, 6)' in result
        assert '(1, 2, 3)' not in result
        assert 'TEST_SHAPES_EXTENDED = []' in result

    def test_nested_brackets(self):
        from evaluator.injection import replace_test_shapes

        source = (
            'TEST_SHAPES = [\n'
            '    (2, [16, 32], 128),\n'
            '    (4, [64], 256),\n'
            ']\n'
            '\n'
            'x = 1\n'
        )
        replacement = (
            'TEST_SHAPES = [\n'
            '    (1, [8], 64),\n'
            ']\n'
        )
        result = replace_test_shapes(source, replacement)
        assert '(1, [8], 64)' in result
        assert '(2, [16, 32], 128)' not in result
        assert 'x = 1' in result

    def test_with_comments_inside(self):
        from evaluator.injection import replace_test_shapes

        source = (
            'TEST_SHAPES = [\n'
            '    (2, 16, 128, 256, True, False),\n'
            '    (8, 64, 512, 1024, False, True),  # large config\n'
            ']\n'
        )
        replacement = (
            'TEST_SHAPES = [\n'
            '    (1, 1, 1, 1, True, True),\n'
            ']\n'
        )
        result = replace_test_shapes(source, replacement)
        assert '(1, 1, 1, 1, True, True)' in result
        assert 'large config' not in result

    def test_on_actual_task_01(self):
        """Test injection on the actual task_01 source file."""
        from evaluator.injection import replace_test_shapes

        with open('/app/data/workspaces/task_01/scripts/task_runner.py') as f:
            source = f.read()

        with open('/app/data/held_out_configs/task_01.yaml') as f:
            config = yaml.safe_load(f)

        replacement = config['injections'][0]['replacement_code']
        result = replace_test_shapes(source, replacement)

        # New shapes present
        assert '(1, 8, 64, 128, True, False)' in result
        assert '(2, 8, 32, 64, False, False)' in result
        # Old shapes gone
        assert '(2, 16, 128, 256, True, False)' not in result
        assert '(4, 32, 256, 512, True, True)' not in result
        # Surrounding code preserved
        assert 'TEST_SHAPES_EXTENDED = []' in result
        assert 'def compile_kernel():' in result
        assert 'NUM_WARMUP = 3' in result


class TestReplaceFunction:
    """Tests for indentation-based function replacement."""

    def test_basic_replacement(self):
        from evaluator.injection import replace_function

        source = (
            'import torch\n'
            '\n'
            'def get_inputs():\n'
            '    configs = [[32, 4]]\n'
            '    for c in configs:\n'
            '        yield c\n'
            '\n'
            'def get_init_inputs():\n'
            '    return []\n'
        )
        replacement = (
            'def get_inputs():\n'
            '    configs = [[1, 4]]\n'
            '    for c in configs:\n'
            '        yield c\n'
        )
        result = replace_function(source, 'get_inputs', replacement)
        assert '[[1, 4]]' in result
        assert '[[32, 4]]' not in result
        assert 'def get_init_inputs():' in result

    def test_with_blank_lines_in_body(self):
        from evaluator.injection import replace_function

        source = (
            'def get_inputs():\n'
            '    configs = [\n'
            '        [16, 256],\n'
            '    ]\n'
            '\n'
            '    for shape in configs:\n'
            '        yield shape\n'
            '\n'
            'def get_init_inputs():\n'
            '    return []\n'
        )
        replacement = (
            'def get_inputs():\n'
            '    configs = [[1, 128]]\n'
            '    for shape in configs:\n'
            '        yield shape\n'
        )
        result = replace_function(source, 'get_inputs', replacement)
        assert '[[1, 128]]' in result
        assert '[16, 256]' not in result
        assert 'def get_init_inputs():' in result

    def test_with_comments_in_body(self):
        from evaluator.injection import replace_function

        source = (
            'def get_inputs():\n'
            '    # Standard test configurations\n'
            '    configs = [[32, 4]]\n'
            '    for c in configs:\n'
            '        yield c\n'
            '\n'
            'def other():\n'
            '    pass\n'
        )
        replacement = (
            'def get_inputs():\n'
            '    configs = [[1, 4]]\n'
            '    for c in configs:\n'
            '        yield c\n'
        )
        result = replace_function(source, 'get_inputs', replacement)
        assert '[[1, 4]]' in result
        assert 'Standard test' not in result
        assert 'def other():' in result

    def test_on_actual_task_04(self):
        """Test injection on task_04 source file with blank line in body."""
        from evaluator.injection import replace_function

        with open('/app/data/workspaces/task_04/pytorch_code_module/py_8821_SiLU.py') as f:
            source = f.read()

        with open('/app/data/held_out_configs/task_04.yaml') as f:
            config = yaml.safe_load(f)

        replacement = config['injections'][0]['replacement_code']
        result = replace_function(source, 'get_inputs', replacement)

        # New shapes present
        assert '[1, 128]' in result
        assert '[256, 2048]' in result
        # Old shapes gone
        assert '[16, 256]' not in result
        assert '[32, 512]' not in result
        # Surrounding code preserved
        assert 'class SiLUModel' in result
        assert 'def get_init_inputs():' in result


class TestRawReplace:
    """Tests for exact substring replacement."""

    def test_basic_replacement(self):
        from evaluator.injection import raw_replace

        source = 'hello world foo bar'
        result = raw_replace(source, 'foo', 'baz')
        assert result == 'hello world baz bar'

    def test_multiline_replacement(self):
        from evaluator.injection import raw_replace

        source = (
            "@pytest.mark.parametrize('X', [1, 2])\n"
            "def test_foo(X):\n"
            "    pass\n"
        )
        old = "@pytest.mark.parametrize('X', [1, 2])\n"
        new = "@pytest.mark.parametrize('X', [3, 4])\n"
        result = raw_replace(source, old, new)
        assert '[3, 4]' in result
        assert '[1, 2]' not in result
        assert 'def test_foo(X):' in result

    def test_not_found_raises(self):
        from evaluator.injection import raw_replace

        with pytest.raises(ValueError):
            raw_replace('hello world', 'nonexistent', 'replacement')

    def test_on_actual_task_03(self):
        """Test both raw_replace injections on task_03."""
        from evaluator.injection import raw_replace

        with open('/app/data/workspaces/task_03/test_add_kernel.py') as f:
            source = f.read()

        with open('/app/data/held_out_configs/task_03.yaml') as f:
            config = yaml.safe_load(f)

        # Apply first injection (correctness decorator)
        inj1 = config['injections'][0]
        result = raw_replace(source, inj1['old_code'], inj1['replacement_code'])
        assert '65536, 512' in result
        # First decorator changed; second (BLOCK_SIZE_ARG) still has original
        assert "BLOCK_SIZE,dtype_str',\n                         [(65536, 512" in result

        # Apply second injection to the result of the first
        inj2 = config['injections'][1]
        result2 = raw_replace(result, inj2['old_code'], inj2['replacement_code'])
        # After both injections, no original sizes should remain
        assert '98432' not in result2
        assert '1048576' not in result2
        assert '65536' in result2


class TestApplyInjection:
    """Tests for injection dispatcher."""

    def test_dispatch_test_shapes(self):
        from evaluator.injection import apply_injection

        source = 'TEST_SHAPES = [\n    (1, 2),\n]\n'
        spec = {
            'find_marker': 'TEST_SHAPES',
            'replacement_code': 'TEST_SHAPES = [\n    (3, 4),\n]\n',
        }
        result = apply_injection(source, spec)
        assert '(3, 4)' in result
        assert '(1, 2)' not in result

    def test_dispatch_function(self):
        from evaluator.injection import apply_injection

        source = 'def get_inputs():\n    return [1]\n\ndef other():\n    pass\n'
        spec = {
            'find_marker': 'def get_inputs',
            'replacement_code': 'def get_inputs():\n    return [2]\n',
        }
        result = apply_injection(source, spec)
        assert 'return [2]' in result
        assert 'return [1]' not in result

    def test_dispatch_raw_replace(self):
        from evaluator.injection import apply_injection

        source = 'foo bar baz\n'
        spec = {
            'find_marker': 'raw_replace',
            'old_code': 'bar',
            'replacement_code': 'qux',
        }
        result = apply_injection(source, spec)
        assert 'qux' in result
        assert 'bar' not in result


# ============================================================
# Test Scoring Module
# ============================================================

class TestResolveSpeedupRatio:
    """Tests for speedup ratio resolution."""

    def test_explicit_positive(self):
        from evaluator.scoring import resolve_speedup_ratio
        assert resolve_speedup_ratio(2.5, 5.0, 2.0) == 2.5

    def test_fallback_to_time_ratio(self):
        from evaluator.scoring import resolve_speedup_ratio
        assert resolve_speedup_ratio(0.0, 5.0, 2.0) == 2.5

    def test_none_explicit(self):
        from evaluator.scoring import resolve_speedup_ratio
        assert resolve_speedup_ratio(None, 5.0, 2.0) == 2.5

    def test_negative_explicit(self):
        from evaluator.scoring import resolve_speedup_ratio
        assert resolve_speedup_ratio(-1.0, 5.0, 2.0) == 2.5

    def test_no_data(self):
        from evaluator.scoring import resolve_speedup_ratio
        assert resolve_speedup_ratio(0.0, 0.0, 0.0) == 0.0

    def test_zero_opt_time(self):
        from evaluator.scoring import resolve_speedup_ratio
        assert resolve_speedup_ratio(0.0, 5.0, 0.0) == 0.0

    def test_zero_base_time(self):
        from evaluator.scoring import resolve_speedup_ratio
        assert resolve_speedup_ratio(0.0, 0.0, 2.0) == 0.0


class TestScore:
    """Tests for gated scoring."""

    def test_compilation_failed(self):
        from evaluator.scoring import score
        assert score(False, False, 0.0, 0.0) == 0.0

    def test_compilation_only(self):
        from evaluator.scoring import score
        assert score(True, False, 0.0, 0.0) == 20.0

    def test_compilation_and_correctness(self):
        from evaluator.scoring import score
        assert score(True, True, 0.0, 0.0) == 120.0

    def test_full_pass_with_time_ratio(self):
        from evaluator.scoring import score
        # speedup = 5.0/2.0 = 2.5 -> 2.5*100 = 250
        assert score(True, True, 5.0, 2.0) == 370.0

    def test_full_pass_with_explicit_speedup(self):
        from evaluator.scoring import score
        assert score(True, True, 5.0, 2.0, speedup_ratio=3.0) == 420.0

    def test_correctness_failed_ignores_speedup(self):
        from evaluator.scoring import score
        assert score(True, False, 5.0, 2.0, speedup_ratio=3.0) == 20.0


# ============================================================
# Test Analysis Module
# ============================================================

class TestClassifyGeneralization:
    """Tests for generalization quadrant classification."""

    def test_both_pass(self):
        from evaluator.analysis import classify_generalization
        assert classify_generalization(True, True) == 'both_pass'

    def test_opt_regression(self):
        from evaluator.analysis import classify_generalization
        assert classify_generalization(True, False) == 'opt_regression'

    def test_both_fail(self):
        from evaluator.analysis import classify_generalization
        assert classify_generalization(False, False) == 'both_fail'

    def test_opt_improvement(self):
        from evaluator.analysis import classify_generalization
        assert classify_generalization(False, True) == 'opt_improvement'


class TestComputeSummary:
    """Tests for aggregate summary computation."""

    @pytest.fixture
    def sample_results(self):
        return [
            {
                'task_name': 'triton2triton/vllm/fused_moe',
                'generalization_status': 'both_pass',
                'orig_heldout_pass_correctness': True,
                'opt_pass_correctness': True,
                'heldout_speedup': 2.5,
                'original_run_speedup': 2.5,
                'heldout_score': 370.0,
                'original_run_score': 370.0,
            },
            {
                'task_name': 'hip2hip/gpumode/GELU',
                'generalization_status': 'opt_regression',
                'orig_heldout_pass_correctness': True,
                'opt_pass_correctness': False,
                'heldout_speedup': 0.0,
                'original_run_speedup': 3.0,
                'heldout_score': 20.0,
                'original_run_score': 420.0,
            },
            {
                'task_name': 'triton2triton/rocmbench/easy/add_kernel',
                'generalization_status': 'both_fail',
                'orig_heldout_pass_correctness': False,
                'opt_pass_correctness': False,
                'heldout_speedup': 0.0,
                'original_run_speedup': 2.0,
                'heldout_score': 20.0,
                'original_run_score': 320.0,
            },
            {
                'task_name': 'hip2hip/gpumode/SiLU',
                'generalization_status': 'opt_improvement',
                'orig_heldout_pass_correctness': False,
                'opt_pass_correctness': True,
                'heldout_speedup': 0.0,
                'original_run_speedup': 2.5,
                'heldout_score': 120.0,
                'original_run_score': 370.0,
            },
            {
                'task_name': 'triton2triton/vllm/flash_attn',
                'generalization_status': 'both_pass',
                'orig_heldout_pass_correctness': True,
                'opt_pass_correctness': True,
                'heldout_speedup': 3.0,
                'original_run_speedup': 2.5,
                'heldout_score': 420.0,
                'original_run_score': 370.0,
            },
        ]

    def test_total_tasks(self, sample_results):
        from evaluator.analysis import compute_summary
        summary = compute_summary(sample_results)
        assert summary['total_tasks'] == 5

    def test_quadrant_counts(self, sample_results):
        from evaluator.analysis import compute_summary
        summary = compute_summary(sample_results)
        qc = summary['quadrant_counts']
        assert qc['both_pass'] == 2
        assert qc['opt_regression'] == 1
        assert qc['both_fail'] == 1
        assert qc['opt_improvement'] == 1

    def test_conditional_correctness(self, sample_results):
        from evaluator.analysis import compute_summary
        summary = compute_summary(sample_results)
        cc = summary['conditional_correctness']
        assert cc['orig_correct_count'] == 3
        assert cc['opt_also_correct_count'] == 2
        assert cc['rate_pct'] == pytest.approx(66.7, abs=0.1)

    def test_heldout_speedup_stats(self, sample_results):
        from evaluator.analysis import compute_summary
        summary = compute_summary(sample_results)
        hs = summary['heldout_speedup_stats']
        assert hs['mean'] == pytest.approx(2.75, abs=0.01)
        assert hs['median'] == pytest.approx(2.75, abs=0.01)

    def test_original_run_speedup_stats(self, sample_results):
        from evaluator.analysis import compute_summary
        summary = compute_summary(sample_results)
        ors = summary['original_run_speedup_stats']
        assert ors['mean'] == pytest.approx(2.5, abs=0.01)
        assert ors['median'] == pytest.approx(2.5, abs=0.01)

    def test_generalization_gap(self, sample_results):
        from evaluator.analysis import compute_summary
        summary = compute_summary(sample_results)
        gap = summary['generalization_gap']
        assert gap['correctness_retention_pct'] == pytest.approx(66.7, abs=0.1)
        assert gap['speedup_mean_delta'] == pytest.approx(0.25, abs=0.01)

    def test_per_task_present(self, sample_results):
        from evaluator.analysis import compute_summary
        summary = compute_summary(sample_results)
        assert len(summary['per_task']) == 5


# ============================================================
# Test Pipeline (Integration)
# ============================================================

class TestPipeline:
    """Integration tests for the full pipeline."""

    @pytest.fixture(autouse=True)
    def setup_output(self):
        """Ensure clean output directory."""
        out_dir = '/app/output'
        if os.path.exists(out_dir):
            shutil.rmtree(out_dir)
        os.makedirs(out_dir, exist_ok=True)
        yield
        # No cleanup — leave output for inspection

    def test_pipeline_runs(self):
        from evaluator.pipeline import run_pipeline
        result = run_pipeline('/app/data', '/app/output')
        assert result is not None
        assert isinstance(result, dict)

    def test_output_file_exists(self):
        from evaluator.pipeline import run_pipeline
        run_pipeline('/app/data', '/app/output')
        assert os.path.exists('/app/output/heldout_summary.yaml')

    def test_output_yaml_valid(self):
        from evaluator.pipeline import run_pipeline
        run_pipeline('/app/data', '/app/output')
        with open('/app/output/heldout_summary.yaml') as f:
            summary = yaml.safe_load(f)
        assert summary is not None
        assert 'total_tasks' in summary
        assert 'quadrant_counts' in summary
        assert 'conditional_correctness' in summary

    def test_output_total_tasks(self):
        from evaluator.pipeline import run_pipeline
        summary = run_pipeline('/app/data', '/app/output')
        assert summary['total_tasks'] == 5

    def test_output_quadrant_counts(self):
        from evaluator.pipeline import run_pipeline
        summary = run_pipeline('/app/data', '/app/output')
        qc = summary['quadrant_counts']
        assert qc['both_pass'] == 2
        assert qc['opt_regression'] == 1
        assert qc['both_fail'] == 1
        assert qc['opt_improvement'] == 1

    def test_output_conditional_correctness(self):
        from evaluator.pipeline import run_pipeline
        summary = run_pipeline('/app/data', '/app/output')
        cc = summary['conditional_correctness']
        assert cc['orig_correct_count'] == 3
        assert cc['opt_also_correct_count'] == 2
        assert cc['rate_pct'] == pytest.approx(66.7, abs=0.1)

    def test_output_heldout_speedup(self):
        from evaluator.pipeline import run_pipeline
        summary = run_pipeline('/app/data', '/app/output')
        hs = summary['heldout_speedup_stats']
        assert hs['mean'] == pytest.approx(2.75, abs=0.01)

    def test_output_generalization_gap(self):
        from evaluator.pipeline import run_pipeline
        summary = run_pipeline('/app/data', '/app/output')
        gap = summary['generalization_gap']
        assert gap['speedup_mean_delta'] == pytest.approx(0.25, abs=0.01)

    def test_injected_files_created(self):
        """Verify that injected source files are written to output."""
        from evaluator.pipeline import run_pipeline
        run_pipeline('/app/data', '/app/output')
        # At least one injected workspace should exist
        injected_dir = '/app/output/injected'
        assert os.path.exists(injected_dir), "No injected/ directory in output"
        entries = os.listdir(injected_dir)
        assert len(entries) >= 5, f"Expected 5 injected workspaces, got {len(entries)}"

    def test_injected_task_01_content(self):
        """Verify task_01 injection was applied correctly."""
        from evaluator.pipeline import run_pipeline
        run_pipeline('/app/data', '/app/output')

        injected = '/app/output/injected/task_01/scripts/task_runner.py'
        assert os.path.exists(injected), f"Injected file not found: {injected}"
        with open(injected) as f:
            content = f.read()
        # New held-out shapes present
        assert '(1, 8, 64, 128, True, False)' in content
        # Old shapes gone
        assert '(2, 16, 128, 256, True, False)' not in content
        # Similar variable name preserved
        assert 'TEST_SHAPES_EXTENDED' in content

    def test_per_task_generalization_status(self):
        """Verify per-task generalization status in summary."""
        from evaluator.pipeline import run_pipeline
        summary = run_pipeline('/app/data', '/app/output')
        per_task = summary['per_task']

        expected_statuses = {
            'triton2triton/vllm/fused_moe': 'both_pass',
            'hip2hip/gpumode/GELU': 'opt_regression',
            'triton2triton/rocmbench/easy/add_kernel': 'both_fail',
            'hip2hip/gpumode/SiLU': 'opt_improvement',
            'triton2triton/vllm/flash_attn': 'both_pass',
        }

        for task in per_task:
            name = task['task_name']
            assert name in expected_statuses, f"Unexpected task: {name}"
            assert task['generalization_status'] == expected_statuses[name], \
                f"Task {name}: expected {expected_statuses[name]}, got {task['generalization_status']}"

    def test_per_task_scores(self):
        """Verify per-task heldout scores."""
        from evaluator.pipeline import run_pipeline
        summary = run_pipeline('/app/data', '/app/output')
        per_task = {t['task_name']: t for t in summary['per_task']}

        # task_01: both_pass, speedup=2.5 -> 20+100+250=370
        assert per_task['triton2triton/vllm/fused_moe']['heldout_score'] == pytest.approx(370.0, abs=0.1)

        # task_02: opt_regression -> compilation only = 20
        assert per_task['hip2hip/gpumode/GELU']['heldout_score'] == pytest.approx(20.0, abs=0.1)

        # task_03: both_fail -> compilation only = 20
        assert per_task['triton2triton/rocmbench/easy/add_kernel']['heldout_score'] == pytest.approx(20.0, abs=0.1)

        # task_04: opt_improvement, no baseline -> 120
        assert per_task['hip2hip/gpumode/SiLU']['heldout_score'] == pytest.approx(120.0, abs=0.1)

        # task_05: both_pass, speedup=3.0 -> 20+100+300=420
        assert per_task['triton2triton/vllm/flash_attn']['heldout_score'] == pytest.approx(420.0, abs=0.1)
