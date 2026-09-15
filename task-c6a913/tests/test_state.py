
import json
import os
import subprocess
import pytest

REPORT_PATH = "/app/output/report.json"


@pytest.fixture(scope="session", autouse=True)
def run_pipeline():
    """Run the evaluation pipeline once before all tests."""
    result = subprocess.run(
        ["python3", "/app/rgym_eval.py"],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, (
        f"Pipeline failed with exit code {result.returncode}:\n"
        f"stdout: {result.stdout[:2000]}\n"
        f"stderr: {result.stderr[:2000]}"
    )
    assert os.path.exists(REPORT_PATH), "Report file /app/output/report.json not generated"


@pytest.fixture(scope="session")
def report():
    with open(REPORT_PATH) as f:
        return json.load(f)


# ============================================================
# Bug 001: slab-out-of-bounds Read in parse_skb_options
# ============================================================
class TestBug001Report:
    def test_bug_type(self, report):
        assert report["bugs"]["bug_001"]["report"]["bug_type"] == "slab-out-of-bounds"

    def test_access_type(self, report):
        assert report["bugs"]["bug_001"]["report"]["access_type"] == "Read"

    def test_access_size(self, report):
        assert report["bugs"]["bug_001"]["report"]["access_size"] == 1

    def test_faulting_function(self, report):
        assert report["bugs"]["bug_001"]["report"]["faulting_function"] == "parse_skb_options"

    def test_slab_cache(self, report):
        assert report["bugs"]["bug_001"]["report"]["slab_cache"] == "kmalloc-64"

    def test_object_size(self, report):
        assert report["bugs"]["bug_001"]["report"]["object_size"] == 64

    def test_call_stack_contains_key_functions(self, report):
        stack = report["bugs"]["bug_001"]["report"]["call_stack"]
        assert "parse_skb_options" in stack
        assert "netfilter_rcv" in stack
        assert "kasan_report" in stack


class TestBug001Patches:
    def test_patch_a_pass(self, report):
        r = report["bugs"]["bug_001"]["patches"]["patch_a"]
        assert r["applied"] is True
        assert r["compiled"] is True
        assert r["result"] == "pass"
        assert r["valgrind_clean"] is True

    def test_patch_b_trigger(self, report):
        r = report["bugs"]["bug_001"]["patches"]["patch_b"]
        assert r["applied"] is True
        assert r["compiled"] is True
        assert r["result"] == "trigger"
        assert r["valgrind_clean"] is False

    def test_patch_c_build_fail(self, report):
        r = report["bugs"]["bug_001"]["patches"]["patch_c"]
        assert r["applied"] is True
        assert r["compiled"] is False
        assert r["result"] == "build_fail"
        assert r["valgrind_clean"] is None


# ============================================================
# Bug 002: slab-use-after-free Read in icache_evict_oldest
# ============================================================
class TestBug002Report:
    def test_bug_type(self, report):
        assert report["bugs"]["bug_002"]["report"]["bug_type"] == "slab-use-after-free"

    def test_access_type(self, report):
        assert report["bugs"]["bug_002"]["report"]["access_type"] == "Read"

    def test_access_size(self, report):
        assert report["bugs"]["bug_002"]["report"]["access_size"] == 8

    def test_faulting_function(self, report):
        assert report["bugs"]["bug_002"]["report"]["faulting_function"] == "icache_evict_oldest"

    def test_slab_cache(self, report):
        assert report["bugs"]["bug_002"]["report"]["slab_cache"] == "kmalloc-128"

    def test_object_size(self, report):
        assert report["bugs"]["bug_002"]["report"]["object_size"] == 128

    def test_call_stack_contains_key_functions(self, report):
        stack = report["bugs"]["bug_002"]["report"]["call_stack"]
        assert "icache_evict_oldest" in stack
        assert "ext4_iget" in stack


class TestBug002Patches:
    def test_patch_a_pass(self, report):
        r = report["bugs"]["bug_002"]["patches"]["patch_a"]
        assert r["applied"] is True
        assert r["compiled"] is True
        assert r["result"] == "pass"
        assert r["valgrind_clean"] is True

    def test_patch_b_pass(self, report):
        r = report["bugs"]["bug_002"]["patches"]["patch_b"]
        assert r["applied"] is True
        assert r["compiled"] is True
        assert r["result"] == "pass"
        assert r["valgrind_clean"] is True

    def test_patch_c_trigger(self, report):
        r = report["bugs"]["bug_002"]["patches"]["patch_c"]
        assert r["applied"] is True
        assert r["compiled"] is True
        assert r["result"] == "trigger"
        assert r["valgrind_clean"] is False


# ============================================================
# Bug 003: slab-out-of-bounds Write in ring_write
# ============================================================
class TestBug003Report:
    def test_bug_type(self, report):
        assert report["bugs"]["bug_003"]["report"]["bug_type"] == "slab-out-of-bounds"

    def test_access_type(self, report):
        assert report["bugs"]["bug_003"]["report"]["access_type"] == "Write"

    def test_access_size(self, report):
        assert report["bugs"]["bug_003"]["report"]["access_size"] == 4

    def test_faulting_function(self, report):
        assert report["bugs"]["bug_003"]["report"]["faulting_function"] == "ring_write"

    def test_slab_cache(self, report):
        assert report["bugs"]["bug_003"]["report"]["slab_cache"] == "kmalloc-16"

    def test_object_size(self, report):
        assert report["bugs"]["bug_003"]["report"]["object_size"] == 16

    def test_call_stack_contains_key_functions(self, report):
        stack = report["bugs"]["bug_003"]["report"]["call_stack"]
        assert "ring_write" in stack
        assert "vfs_write" in stack


class TestBug003Patches:
    def test_patch_a_pass(self, report):
        r = report["bugs"]["bug_003"]["patches"]["patch_a"]
        assert r["applied"] is True
        assert r["compiled"] is True
        assert r["result"] == "pass"
        assert r["valgrind_clean"] is True

    def test_patch_b_build_fail(self, report):
        r = report["bugs"]["bug_003"]["patches"]["patch_b"]
        assert r["applied"] is True
        assert r["compiled"] is False
        assert r["result"] == "build_fail"
        assert r["valgrind_clean"] is None

    def test_patch_c_trigger(self, report):
        r = report["bugs"]["bug_003"]["patches"]["patch_c"]
        assert r["applied"] is True
        assert r["compiled"] is True
        assert r["result"] == "trigger"
        assert r["valgrind_clean"] is False


# ============================================================
# Bug 004: slab-use-after-free Write in tq_expire_first
# ============================================================
class TestBug004Report:
    def test_bug_type(self, report):
        assert report["bugs"]["bug_004"]["report"]["bug_type"] == "slab-use-after-free"

    def test_access_type(self, report):
        assert report["bugs"]["bug_004"]["report"]["access_type"] == "Write"

    def test_access_size(self, report):
        assert report["bugs"]["bug_004"]["report"]["access_size"] == 4

    def test_faulting_function(self, report):
        assert report["bugs"]["bug_004"]["report"]["faulting_function"] == "tq_expire_first"

    def test_slab_cache(self, report):
        assert report["bugs"]["bug_004"]["report"]["slab_cache"] == "kmalloc-64"

    def test_object_size(self, report):
        assert report["bugs"]["bug_004"]["report"]["object_size"] == 64

    def test_call_stack_contains_key_functions(self, report):
        stack = report["bugs"]["bug_004"]["report"]["call_stack"]
        assert "tq_expire_first" in stack
        assert "run_timers" in stack


class TestBug004Patches:
    def test_patch_a_pass(self, report):
        r = report["bugs"]["bug_004"]["patches"]["patch_a"]
        assert r["applied"] is True
        assert r["compiled"] is True
        assert r["result"] == "pass"
        assert r["valgrind_clean"] is True

    def test_patch_b_pass(self, report):
        r = report["bugs"]["bug_004"]["patches"]["patch_b"]
        assert r["applied"] is True
        assert r["compiled"] is True
        assert r["result"] == "pass"
        assert r["valgrind_clean"] is True

    def test_patch_c_build_fail(self, report):
        r = report["bugs"]["bug_004"]["patches"]["patch_c"]
        assert r["applied"] is True
        assert r["compiled"] is False
        assert r["result"] == "build_fail"
        assert r["valgrind_clean"] is None


# ============================================================
# Summary statistics
# ============================================================
class TestSummary:
    def test_total_patches(self, report):
        assert report["summary"]["total_patches"] == 12

    def test_pass_count(self, report):
        assert report["summary"]["pass_count"] == 6

    def test_trigger_count(self, report):
        assert report["summary"]["trigger_count"] == 3

    def test_build_fail_count(self, report):
        assert report["summary"]["build_fail_count"] == 3

    def test_pass_rate(self, report):
        assert abs(report["summary"]["pass_rate"] - 0.5) < 0.01


# ============================================================
# Structural validation
# ============================================================
class TestStructure:
    def test_all_bugs_present(self, report):
        assert set(report["bugs"].keys()) == {"bug_001", "bug_002", "bug_003", "bug_004"}

    def test_all_patches_present(self, report):
        for bug_id in ["bug_001", "bug_002", "bug_003", "bug_004"]:
            patches = report["bugs"][bug_id]["patches"]
            assert set(patches.keys()) == {"patch_a", "patch_b", "patch_c"}, (
                f"Missing patches for {bug_id}: got {set(patches.keys())}"
            )

    def test_report_has_call_stack(self, report):
        for bug_id in report["bugs"]:
            stack = report["bugs"][bug_id]["report"]["call_stack"]
            assert isinstance(stack, list)
            assert len(stack) >= 3, f"{bug_id} call_stack too short: {stack}"

    def test_all_patches_have_valgrind_field(self, report):
        for bug_id in report["bugs"]:
            for patch_id, patch in report["bugs"][bug_id]["patches"].items():
                assert "valgrind_clean" in patch, (
                    f"{bug_id}/{patch_id} missing valgrind_clean field"
                )


# ============================================================
# Valgrind / ASan cross-validation consistency
# ============================================================
class TestValgrindConsistency:
    def test_pass_implies_valgrind_clean(self, report):
        for bug_id, bug in report["bugs"].items():
            for patch_id, patch in bug["patches"].items():
                if patch["result"] == "pass":
                    assert patch["valgrind_clean"] is True, (
                        f"{bug_id}/{patch_id}: result=pass but valgrind_clean={patch['valgrind_clean']}"
                    )

    def test_trigger_implies_valgrind_dirty(self, report):
        for bug_id, bug in report["bugs"].items():
            for patch_id, patch in bug["patches"].items():
                if patch["result"] == "trigger":
                    assert patch["valgrind_clean"] is False, (
                        f"{bug_id}/{patch_id}: result=trigger but valgrind_clean={patch['valgrind_clean']}"
                    )

    def test_build_fail_implies_valgrind_null(self, report):
        for bug_id, bug in report["bugs"].items():
            for patch_id, patch in bug["patches"].items():
                if patch["result"] == "build_fail":
                    assert patch["valgrind_clean"] is None, (
                        f"{bug_id}/{patch_id}: result=build_fail but valgrind_clean={patch['valgrind_clean']}"
                    )
