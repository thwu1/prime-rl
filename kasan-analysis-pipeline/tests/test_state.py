
"""Tests for the kernel APR benchmark evaluation pipeline."""

import json
import os
import pytest


@pytest.fixture(scope="module")
def report_data():
    """Load the evaluation output."""
    path = "/app/output/evaluation.json"
    assert os.path.exists(path), f"Output file not found at {path}"
    with open(path) as f:
        data = json.load(f)
    return data


# ============================================================
# Section 1: KASAN Crash Analysis Tests
# ============================================================

class TestReport001SlabOOBRead:
    """Test analysis of slab-out-of-bounds Read report."""

    def test_bug_type(self, report_data):
        r = report_data["crash_analysis"]["report_001"]
        assert r["bug_type"] == "slab-out-of-bounds"

    def test_access_type(self, report_data):
        r = report_data["crash_analysis"]["report_001"]
        assert r["access_type"] == "Read"

    def test_access_size(self, report_data):
        r = report_data["crash_analysis"]["report_001"]
        assert r["access_size"] == 2

    def test_faulting_function(self, report_data):
        r = report_data["crash_analysis"]["report_001"]
        assert r["faulting_function"] == "skb_network_protocol"

    def test_faulting_source(self, report_data):
        r = report_data["crash_analysis"]["report_001"]
        assert r["faulting_source_file"] == "net/core/dev.c"
        assert r["faulting_source_line"] == 3268

    def test_buggy_addr(self, report_data):
        r = report_data["crash_analysis"]["report_001"]
        assert r["buggy_addr"] == "ffff88803a4c8594"

    def test_task_info(self, report_data):
        r = report_data["crash_analysis"]["report_001"]
        assert r["task_name"] == "syz-executor.0"
        assert r["pid"] == 5765
        assert r["cpu"] == 0

    def test_tainted(self, report_data):
        r = report_data["crash_analysis"]["report_001"]
        assert r["tainted"] is False

    def test_slab_info(self, report_data):
        r = report_data["crash_analysis"]["report_001"]
        assert r["slab_cache"] == "kmalloc-64"
        assert r["slab_object_size"] == 64
        assert r["alloc_size"] == 20

    def test_crash_stack_depth(self, report_data):
        r = report_data["crash_analysis"]["report_001"]
        assert len(r["crash_stack"]) == 9

    def test_crash_stack_inline(self, report_data):
        """First frame should be inline __dump_stack."""
        r = report_data["crash_analysis"]["report_001"]
        first = r["crash_stack"][0]
        assert first["function"] == "__dump_stack"
        assert first["is_inline"] is True
        assert first["file"] == "lib/dump_stack.c"
        assert first["line"] == 94

    def test_crash_stack_faulting(self, report_data):
        """5th frame should be the faulting function."""
        r = report_data["crash_analysis"]["report_001"]
        frame = r["crash_stack"][4]
        assert frame["function"] == "skb_network_protocol"
        assert frame["is_inline"] is False

    def test_alloc_stack(self, report_data):
        r = report_data["crash_analysis"]["report_001"]
        assert r["alloc_stack"] is not None
        assert len(r["alloc_stack"]) == 6
        assert r["alloc_stack"][-1]["function"] == "__alloc_skb"

    def test_free_stack(self, report_data):
        r = report_data["crash_analysis"]["report_001"]
        assert r["free_stack"] is None

    def test_shadow_byte(self, report_data):
        r = report_data["crash_analysis"]["report_001"]
        assert r["shadow_byte_value"] == "04"
        assert r["shadow_byte_meaning"] == "Partially accessible: 4 of 8 bytes"


class TestReport002SlabUAFRead:
    """Test analysis of slab-use-after-free Read report."""

    def test_bug_type(self, report_data):
        r = report_data["crash_analysis"]["report_002"]
        assert r["bug_type"] == "slab-use-after-free"

    def test_access(self, report_data):
        r = report_data["crash_analysis"]["report_002"]
        assert r["access_type"] == "Read"
        assert r["access_size"] == 8

    def test_faulting_function(self, report_data):
        r = report_data["crash_analysis"]["report_002"]
        assert r["faulting_function"] == "ext4_find_extent"
        assert r["faulting_source_file"] == "fs/ext4/extents.c"
        assert r["faulting_source_line"] == 903

    def test_task_info(self, report_data):
        r = report_data["crash_analysis"]["report_002"]
        assert r["task_name"] == "kworker/u8:3"
        assert r["pid"] == 1456
        assert r["cpu"] == 2

    def test_slab_info(self, report_data):
        r = report_data["crash_analysis"]["report_002"]
        assert r["slab_cache"] == "ext4_extent_status"
        assert r["slab_object_size"] == 72
        assert r["alloc_size"] == 72

    def test_crash_stack(self, report_data):
        r = report_data["crash_analysis"]["report_002"]
        assert len(r["crash_stack"]) == 7

    def test_alloc_stack(self, report_data):
        r = report_data["crash_analysis"]["report_002"]
        assert r["alloc_stack"] is not None
        assert len(r["alloc_stack"]) == 5
        assert r["alloc_stack"][-1]["function"] == "ext4_ext_tree_init"

    def test_free_stack(self, report_data):
        r = report_data["crash_analysis"]["report_002"]
        assert r["free_stack"] is not None
        assert len(r["free_stack"]) == 6
        assert r["free_stack"][-1]["function"] == "ext4_ext_drop_refs"

    def test_shadow_byte(self, report_data):
        r = report_data["crash_analysis"]["report_002"]
        assert r["shadow_byte_value"] == "fd"
        assert r["shadow_byte_meaning"] == "Freed slab object"


class TestReport003NullPtrDeref:
    """Test analysis of null-ptr-deref Write report."""

    def test_bug_type(self, report_data):
        r = report_data["crash_analysis"]["report_003"]
        assert r["bug_type"] == "null-ptr-deref"

    def test_access(self, report_data):
        r = report_data["crash_analysis"]["report_003"]
        assert r["access_type"] == "Write"
        assert r["access_size"] == 4

    def test_faulting_function(self, report_data):
        r = report_data["crash_analysis"]["report_003"]
        assert r["faulting_function"] == "i2c_smbus_xfer"

    def test_buggy_addr(self, report_data):
        r = report_data["crash_analysis"]["report_003"]
        assert r["buggy_addr"] == "0000000000000028"

    def test_tainted(self, report_data):
        r = report_data["crash_analysis"]["report_003"]
        assert r["tainted"] is True

    def test_no_slab_info(self, report_data):
        r = report_data["crash_analysis"]["report_003"]
        assert r["slab_cache"] is None
        assert r["slab_object_size"] is None

    def test_crash_stack_with_inline(self, report_data):
        r = report_data["crash_analysis"]["report_003"]
        assert len(r["crash_stack"]) == 8
        inline_frames = [f for f in r["crash_stack"] if f["is_inline"]]
        assert len(inline_frames) == 1
        assert inline_frames[0]["function"] == "check_memory_region_inline"

    def test_no_alloc_free_stacks(self, report_data):
        r = report_data["crash_analysis"]["report_003"]
        assert r["alloc_stack"] is None
        assert r["free_stack"] is None

    def test_shadow_byte_absent(self, report_data):
        """Null-ptr-deref has no shadow memory section."""
        r = report_data["crash_analysis"]["report_003"]
        assert r["shadow_byte_value"] is None
        assert r["shadow_byte_meaning"] is None


class TestReport004UAFWrite:
    """Test analysis of use-after-free Write report with IRQ+TASK sections."""

    def test_bug_type(self, report_data):
        r = report_data["crash_analysis"]["report_004"]
        assert r["bug_type"] == "use-after-free"

    def test_access(self, report_data):
        r = report_data["crash_analysis"]["report_004"]
        assert r["access_type"] == "Write"
        assert r["access_size"] == 8

    def test_faulting_function(self, report_data):
        r = report_data["crash_analysis"]["report_004"]
        assert r["faulting_function"] == "blk_mq_free_request"
        assert r["faulting_source_file"] == "block/blk-mq.c"
        assert r["faulting_source_line"] == 685

    def test_crash_stack_across_sections(self, report_data):
        """Stack should include frames from both IRQ and TASK sections."""
        r = report_data["crash_analysis"]["report_004"]
        assert len(r["crash_stack"]) == 8
        funcs = [f["function"] for f in r["crash_stack"]]
        assert "scsi_end_request" in funcs
        assert "blk_complete_reqs" in funcs

    def test_free_stack_only(self, report_data):
        r = report_data["crash_analysis"]["report_004"]
        assert r["alloc_stack"] is None
        assert r["free_stack"] is not None
        assert len(r["free_stack"]) == 6

    def test_slab_info(self, report_data):
        r = report_data["crash_analysis"]["report_004"]
        assert r["slab_cache"] == "kmalloc-192"
        assert r["slab_object_size"] == 192
        assert r["alloc_size"] == 192

    def test_shadow_byte(self, report_data):
        r = report_data["crash_analysis"]["report_004"]
        assert r["shadow_byte_value"] == "fd"
        assert r["shadow_byte_meaning"] == "Freed slab object"


class TestReport005GlobalOOB:
    """Test analysis of global-out-of-bounds Read report."""

    def test_bug_type(self, report_data):
        r = report_data["crash_analysis"]["report_005"]
        assert r["bug_type"] == "global-out-of-bounds"

    def test_access(self, report_data):
        r = report_data["crash_analysis"]["report_005"]
        assert r["access_type"] == "Read"
        assert r["access_size"] == 4

    def test_faulting_function(self, report_data):
        r = report_data["crash_analysis"]["report_005"]
        assert r["faulting_function"] == "ip6gre_header"
        assert r["faulting_source_file"] == "net/ipv6/ip6_gre.c"
        assert r["faulting_source_line"] == 963

    def test_no_slab_info(self, report_data):
        r = report_data["crash_analysis"]["report_005"]
        assert r["slab_cache"] is None
        assert r["slab_object_size"] is None

    def test_global_variable(self, report_data):
        r = report_data["crash_analysis"]["report_005"]
        assert r["global_variable"] == "ip6gre_protocol"

    def test_crash_stack(self, report_data):
        r = report_data["crash_analysis"]["report_005"]
        assert len(r["crash_stack"]) == 6

    def test_no_alloc_free_stacks(self, report_data):
        r = report_data["crash_analysis"]["report_005"]
        assert r["alloc_stack"] is None
        assert r["free_stack"] is None

    def test_shadow_byte(self, report_data):
        r = report_data["crash_analysis"]["report_005"]
        assert r["shadow_byte_value"] == "04"
        assert r["shadow_byte_meaning"] == "Partially accessible: 4 of 8 bytes"


class TestAllReportsPresent:
    """Verify all reports are present."""

    def test_report_count(self, report_data):
        assert len(report_data["crash_analysis"]) == 5

    def test_report_ids(self, report_data):
        expected = {"report_001", "report_002", "report_003", "report_004", "report_005"}
        assert set(report_data["crash_analysis"].keys()) == expected


# ============================================================
# Section 2: Patch Verdict Classification Tests
# ============================================================

class TestPatchVerdicts:
    """Test multi-VM patch verification verdict classification."""

    def test_all_pass(self, report_data):
        v = report_data["patch_verdicts"]["case_001"]
        assert v["verdict"] == "pass"
        assert v["vm_count"] == 26
        assert v["pass_count"] == 26
        assert v["trigger_count"] == 0
        assert v["boot_fail_count"] == 0

    def test_all_trigger(self, report_data):
        v = report_data["patch_verdicts"]["case_002"]
        assert v["verdict"] == "trigger"
        assert v["vm_count"] == 26
        assert v["trigger_count"] == 26
        assert v["pass_count"] == 0

    def test_racey_mostly_trigger(self, report_data):
        """20 trigger + 6 pass = racey."""
        v = report_data["patch_verdicts"]["case_003"]
        assert v["verdict"] == "racey"
        assert v["trigger_count"] == 20
        assert v["pass_count"] == 6

    def test_racey_even_split(self, report_data):
        """13 pass + 13 trigger = racey."""
        v = report_data["patch_verdicts"]["case_004"]
        assert v["verdict"] == "racey"
        assert v["pass_count"] == 13
        assert v["trigger_count"] == 13

    def test_boot_fail_with_passes(self, report_data):
        """24 pass + 2 boot_fail = boot_fail (boot_fail takes priority)."""
        v = report_data["patch_verdicts"]["case_005"]
        assert v["verdict"] == "boot_fail"
        assert v["boot_fail_count"] == 2
        assert v["pass_count"] == 24

    def test_boot_fail_mixed(self, report_data):
        """18 trigger + 6 pass + 2 boot_fail = boot_fail."""
        v = report_data["patch_verdicts"]["case_006"]
        assert v["verdict"] == "boot_fail"
        assert v["boot_fail_count"] == 2

    def test_racey_single_trigger(self, report_data):
        """25 pass + 1 trigger = racey."""
        v = report_data["patch_verdicts"]["case_007"]
        assert v["verdict"] == "racey"
        assert v["pass_count"] == 25
        assert v["trigger_count"] == 1

    def test_racey_single_pass(self, report_data):
        """25 trigger + 1 pass = racey."""
        v = report_data["patch_verdicts"]["case_008"]
        assert v["verdict"] == "racey"
        assert v["trigger_count"] == 25
        assert v["pass_count"] == 1

    def test_verdict_count(self, report_data):
        assert len(report_data["patch_verdicts"]) == 8


# ============================================================
# Section 3: Experiment Metrics Tests
# ============================================================

class TestExperimentMetricsPerConfig:
    """Test per-configuration metrics."""

    def test_gpt4o_pass_rate(self, report_data):
        m = report_data["experiment_metrics"]["per_config"]["simple_agent_gpt4o"]
        assert m["pass_count"] == 3
        assert m["total_bugs"] == 8
        assert abs(m["pass_rate"] - 0.375) < 1e-6

    def test_feedback_pass_rate(self, report_data):
        m = report_data["experiment_metrics"]["per_config"]["simple_agent_feedback"]
        assert m["pass_count"] == 4
        assert abs(m["pass_rate"] - 0.5) < 1e-6

    def test_exploration_pass_rate(self, report_data):
        m = report_data["experiment_metrics"]["per_config"]["exploration_agent"]
        assert m["pass_count"] == 3
        assert abs(m["pass_rate"] - 0.375) < 1e-6

    def test_gpt4o_cost(self, report_data):
        m = report_data["experiment_metrics"]["per_config"]["simple_agent_gpt4o"]
        assert abs(m["avg_cost_per_bug"] - 0.05) < 1e-6

    def test_feedback_cost(self, report_data):
        m = report_data["experiment_metrics"]["per_config"]["simple_agent_feedback"]
        assert abs(m["avg_cost_per_bug"] - 0.17) < 1e-6

    def test_gpt4o_build_failures(self, report_data):
        m = report_data["experiment_metrics"]["per_config"]["simple_agent_gpt4o"]
        assert m["compilation_fail_count"] == 1
        assert m["bad_patch_count"] == 0

    def test_feedback_build_failures(self, report_data):
        m = report_data["experiment_metrics"]["per_config"]["simple_agent_feedback"]
        assert m["compilation_fail_count"] == 0
        assert m["bad_patch_count"] == 1

    def test_exploration_build_failures(self, report_data):
        m = report_data["experiment_metrics"]["per_config"]["exploration_agent"]
        assert m["compilation_fail_count"] == 1
        assert m["bad_patch_count"] == 1


class TestExperimentMetricsUniqueSolves:
    """Test unique solve identification across configs."""

    def test_gpt4o_unique(self, report_data):
        m = report_data["experiment_metrics"]["per_config"]["simple_agent_gpt4o"]
        assert sorted(m["unique_solves"]) == ["bug_007"]
        assert m["unique_solve_count"] == 1

    def test_feedback_unique(self, report_data):
        m = report_data["experiment_metrics"]["per_config"]["simple_agent_feedback"]
        assert sorted(m["unique_solves"]) == ["bug_002", "bug_004"]
        assert m["unique_solve_count"] == 2

    def test_exploration_unique(self, report_data):
        m = report_data["experiment_metrics"]["per_config"]["exploration_agent"]
        assert sorted(m["unique_solves"]) == ["bug_006"]
        assert m["unique_solve_count"] == 1


class TestExperimentMetricsCombined:
    """Test cross-configuration combined metrics."""

    def test_combined_pass_rate(self, report_data):
        m = report_data["experiment_metrics"]
        assert m["combined_pass_count"] == 7
        assert abs(m["combined_pass_rate"] - 0.875) < 1e-6

    def test_combined_solved_bugs(self, report_data):
        m = report_data["experiment_metrics"]
        expected = ["bug_001", "bug_002", "bug_003", "bug_004", "bug_005", "bug_006", "bug_007"]
        assert sorted(m["combined_solved_bugs"]) == expected

    def test_total_bugs(self, report_data):
        m = report_data["experiment_metrics"]
        assert m["total_bugs"] == 8
