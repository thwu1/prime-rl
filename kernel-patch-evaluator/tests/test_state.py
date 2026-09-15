
import json
import os
import pytest

RESULTS_PATH = "/app/output/results.json"


@pytest.fixture(scope="module")
def results():
    assert os.path.exists(RESULTS_PATH), f"Results file not found: {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


# ---- Case 001: KASAN use-after-free in fs/myfs/inode.c ----

class TestCase001:
    def test_crash_type(self, results):
        info = results["case_001"]["crash_info"]
        assert info["type"] == "use-after-free"

    def test_crash_access_type(self, results):
        info = results["case_001"]["crash_info"]
        assert info["access_type"] == "Read"

    def test_crash_file(self, results):
        info = results["case_001"]["crash_info"]
        assert info["file"] == "fs/myfs/inode.c"

    def test_crash_function(self, results):
        info = results["case_001"]["crash_info"]
        assert info["function"] == "inode_unlink_data"

    def test_crash_line(self, results):
        info = results["case_001"]["crash_info"]
        assert info["line"] == 107

    def test_agent_modified_files(self, results):
        files = sorted(results["case_001"]["agent_patch"]["modified_files"])
        assert files == ["fs/myfs/inode.c"]

    def test_agent_modified_functions(self, results):
        funcs = sorted(results["case_001"]["agent_patch"]["modified_functions"])
        assert funcs == ["fs/myfs/inode.c:inode_unlink_data"]

    def test_developer_modified_files(self, results):
        files = sorted(results["case_001"]["developer_patch"]["modified_files"])
        assert files == ["fs/myfs/inode.c"]

    def test_developer_modified_functions(self, results):
        funcs = sorted(results["case_001"]["developer_patch"]["modified_functions"])
        assert funcs == ["fs/myfs/inode.c:inode_unlink_data"]

    def test_file_iou(self, results):
        assert results["case_001"]["metrics"]["file_iou"] == pytest.approx(1.0, abs=0.01)

    def test_function_iou(self, results):
        assert results["case_001"]["metrics"]["function_iou"] == pytest.approx(1.0, abs=0.01)

    def test_localization_hit(self, results):
        assert results["case_001"]["metrics"]["localization_hit"] is True

    def test_patch_equivalent(self, results):
        assert results["case_001"]["metrics"]["patch_equivalent"] is False


# ---- Case 002: KASAN slab-out-of-bounds in net/core/skbuff.c ----

class TestCase002:
    def test_crash_type(self, results):
        info = results["case_002"]["crash_info"]
        assert info["type"] == "slab-out-of-bounds"

    def test_crash_access_type(self, results):
        info = results["case_002"]["crash_info"]
        assert info["access_type"] == "Write"

    def test_crash_file(self, results):
        info = results["case_002"]["crash_info"]
        assert info["file"] == "net/core/skbuff.c"

    def test_crash_function(self, results):
        info = results["case_002"]["crash_info"]
        assert info["function"] == "skb_put_data"

    def test_crash_line(self, results):
        info = results["case_002"]["crash_info"]
        assert info["line"] == 63

    def test_agent_modified_files(self, results):
        files = sorted(results["case_002"]["agent_patch"]["modified_files"])
        assert files == ["net/core/skbuff.c"]

    def test_agent_modified_functions(self, results):
        funcs = sorted(results["case_002"]["agent_patch"]["modified_functions"])
        assert funcs == ["net/core/skbuff.c:skb_put_data"]

    def test_developer_modified_files(self, results):
        files = sorted(results["case_002"]["developer_patch"]["modified_files"])
        assert files == ["net/core/skbuff.c"]

    def test_developer_modified_functions(self, results):
        funcs = sorted(results["case_002"]["developer_patch"]["modified_functions"])
        assert funcs == ["net/core/skbuff.c:skb_alloc_validate", "net/core/skbuff.c:skb_put_data"]

    def test_file_iou(self, results):
        assert results["case_002"]["metrics"]["file_iou"] == pytest.approx(1.0, abs=0.01)

    def test_function_iou(self, results):
        assert results["case_002"]["metrics"]["function_iou"] == pytest.approx(0.5, abs=0.01)

    def test_localization_hit(self, results):
        assert results["case_002"]["metrics"]["localization_hit"] is True

    def test_patch_equivalent(self, results):
        assert results["case_002"]["metrics"]["patch_equivalent"] is False


# ---- Case 003: null-ptr-deref in block/blk-mq.c (variable renaming equivalence) ----

class TestCase003:
    def test_crash_type(self, results):
        info = results["case_003"]["crash_info"]
        assert info["type"] == "null-ptr-deref"

    def test_crash_access_type(self, results):
        info = results["case_003"]["crash_info"]
        assert info["access_type"] == "Read"

    def test_crash_file(self, results):
        info = results["case_003"]["crash_info"]
        assert info["file"] == "block/blk-mq.c"

    def test_crash_function(self, results):
        info = results["case_003"]["crash_info"]
        assert info["function"] == "blk_mq_get_tag"

    def test_crash_line(self, results):
        info = results["case_003"]["crash_info"]
        assert info["line"] == 48

    def test_agent_modified_files(self, results):
        files = sorted(results["case_003"]["agent_patch"]["modified_files"])
        assert files == ["block/blk-mq.c"]

    def test_agent_modified_functions(self, results):
        funcs = sorted(results["case_003"]["agent_patch"]["modified_functions"])
        assert funcs == ["block/blk-mq.c:blk_mq_get_tag"]

    def test_developer_modified_files(self, results):
        files = sorted(results["case_003"]["developer_patch"]["modified_files"])
        assert files == ["block/blk-mq.c"]

    def test_developer_modified_functions(self, results):
        funcs = sorted(results["case_003"]["developer_patch"]["modified_functions"])
        assert funcs == ["block/blk-mq.c:blk_mq_get_tag"]

    def test_file_iou(self, results):
        assert results["case_003"]["metrics"]["file_iou"] == pytest.approx(1.0, abs=0.01)

    def test_function_iou(self, results):
        assert results["case_003"]["metrics"]["function_iou"] == pytest.approx(1.0, abs=0.01)

    def test_localization_hit(self, results):
        assert results["case_003"]["metrics"]["localization_hit"] is True

    def test_patch_equivalent(self, results):
        # Agent renames tags->ts and tag->nr but same logical fix
        assert results["case_003"]["metrics"]["patch_equivalent"] is True


# ---- Case 004: WARNING in drivers/gpu/drm (multi-file, partial fix) ----

class TestCase004:
    def test_crash_type(self, results):
        info = results["case_004"]["crash_info"]
        assert info["type"] == "warning"

    def test_crash_access_type(self, results):
        info = results["case_004"]["crash_info"]
        assert info["access_type"] is None

    def test_crash_file(self, results):
        info = results["case_004"]["crash_info"]
        assert info["file"] == "drivers/gpu/drm/drm_mode.c"

    def test_crash_function(self, results):
        info = results["case_004"]["crash_info"]
        assert info["function"] == "drm_mode_setcrtc"

    def test_crash_line(self, results):
        info = results["case_004"]["crash_info"]
        assert info["line"] == 55

    def test_agent_modified_files(self, results):
        files = sorted(results["case_004"]["agent_patch"]["modified_files"])
        assert files == ["drivers/gpu/drm/drm_mode.c"]

    def test_agent_modified_functions(self, results):
        funcs = sorted(results["case_004"]["agent_patch"]["modified_functions"])
        assert funcs == ["drivers/gpu/drm/drm_mode.c:drm_mode_setcrtc"]

    def test_developer_modified_files(self, results):
        files = sorted(results["case_004"]["developer_patch"]["modified_files"])
        assert files == ["drivers/gpu/drm/drm_crtc.c", "drivers/gpu/drm/drm_mode.c"]

    def test_developer_modified_functions(self, results):
        funcs = sorted(results["case_004"]["developer_patch"]["modified_functions"])
        assert funcs == [
            "drivers/gpu/drm/drm_crtc.c:drm_crtc_init",
            "drivers/gpu/drm/drm_mode.c:drm_mode_setcrtc",
        ]

    def test_file_iou(self, results):
        assert results["case_004"]["metrics"]["file_iou"] == pytest.approx(0.5, abs=0.01)

    def test_function_iou(self, results):
        assert results["case_004"]["metrics"]["function_iou"] == pytest.approx(0.5, abs=0.01)

    def test_localization_hit(self, results):
        assert results["case_004"]["metrics"]["localization_hit"] is True

    def test_patch_equivalent(self, results):
        assert results["case_004"]["metrics"]["patch_equivalent"] is False


# ---- Case 005: null-ptr-deref in mm/slab_common.c (misleading hunk header, identical patches) ----

class TestCase005:
    def test_crash_type(self, results):
        info = results["case_005"]["crash_info"]
        assert info["type"] == "null-ptr-deref"

    def test_crash_access_type(self, results):
        info = results["case_005"]["crash_info"]
        assert info["access_type"] == "Write"

    def test_crash_file(self, results):
        info = results["case_005"]["crash_info"]
        assert info["file"] == "mm/slab_common.c"

    def test_crash_function(self, results):
        info = results["case_005"]["crash_info"]
        assert info["function"] == "kmem_cache_destroy"

    def test_crash_line(self, results):
        info = results["case_005"]["crash_info"]
        assert info["line"] == 118

    def test_agent_modified_files(self, results):
        files = sorted(results["case_005"]["agent_patch"]["modified_files"])
        assert files == ["mm/slab_common.c"]

    def test_agent_modified_functions(self, results):
        # Must correctly identify kmem_cache_destroy despite hunk header saying kmem_cache_create
        funcs = sorted(results["case_005"]["agent_patch"]["modified_functions"])
        assert funcs == ["mm/slab_common.c:kmem_cache_destroy"]

    def test_developer_modified_functions(self, results):
        funcs = sorted(results["case_005"]["developer_patch"]["modified_functions"])
        assert funcs == ["mm/slab_common.c:kmem_cache_destroy"]

    def test_file_iou(self, results):
        assert results["case_005"]["metrics"]["file_iou"] == pytest.approx(1.0, abs=0.01)

    def test_function_iou(self, results):
        assert results["case_005"]["metrics"]["function_iou"] == pytest.approx(1.0, abs=0.01)

    def test_localization_hit(self, results):
        assert results["case_005"]["metrics"]["localization_hit"] is True

    def test_patch_equivalent(self, results):
        # Identical patches should be equivalent
        assert results["case_005"]["metrics"]["patch_equivalent"] is True


# ---- Case 006: Dynamic test case (generated at test time) ----

class TestCase006:
    def test_case_present(self, results):
        assert "case_006" in results, "Dynamic case_006 missing from results"

    def test_crash_type(self, results):
        info = results["case_006"]["crash_info"]
        assert info["type"] == "use-after-free"

    def test_crash_access_type(self, results):
        info = results["case_006"]["crash_info"]
        assert info["access_type"] == "Read"

    def test_crash_file(self, results):
        info = results["case_006"]["crash_info"]
        assert info["file"] == "lib/test_helpers.c"

    def test_crash_function(self, results):
        info = results["case_006"]["crash_info"]
        assert info["function"] == "cleanup_context"

    def test_crash_line(self, results):
        info = results["case_006"]["crash_info"]
        assert info["line"] == 38

    def test_agent_modified_functions(self, results):
        # Hunk header says init_context, but actual change is in cleanup_context
        funcs = sorted(results["case_006"]["agent_patch"]["modified_functions"])
        assert funcs == ["lib/test_helpers.c:cleanup_context"]

    def test_developer_modified_functions(self, results):
        funcs = sorted(results["case_006"]["developer_patch"]["modified_functions"])
        assert funcs == ["lib/test_helpers.c:cleanup_context"]

    def test_file_iou(self, results):
        assert results["case_006"]["metrics"]["file_iou"] == pytest.approx(1.0, abs=0.01)

    def test_function_iou(self, results):
        assert results["case_006"]["metrics"]["function_iou"] == pytest.approx(1.0, abs=0.01)

    def test_localization_hit(self, results):
        assert results["case_006"]["metrics"]["localization_hit"] is True

    def test_patch_equivalent(self, results):
        # Identical patches (different index hash only)
        assert results["case_006"]["metrics"]["patch_equivalent"] is True


# ---- Case 007: null-ptr-deref in kernel/sched/fair.c (guard clause equivalence) ----

class TestCase007:
    def test_crash_type(self, results):
        info = results["case_007"]["crash_info"]
        assert info["type"] == "null-ptr-deref"

    def test_crash_access_type(self, results):
        info = results["case_007"]["crash_info"]
        assert info["access_type"] == "Read"

    def test_crash_file(self, results):
        info = results["case_007"]["crash_info"]
        assert info["file"] == "kernel/sched/fair.c"

    def test_crash_function(self, results):
        info = results["case_007"]["crash_info"]
        assert info["function"] == "update_load_avg"

    def test_crash_line(self, results):
        info = results["case_007"]["crash_info"]
        assert info["line"] == 27

    def test_agent_modified_files(self, results):
        files = sorted(results["case_007"]["agent_patch"]["modified_files"])
        assert files == ["kernel/sched/fair.c"]

    def test_agent_modified_functions(self, results):
        funcs = sorted(results["case_007"]["agent_patch"]["modified_functions"])
        assert funcs == ["kernel/sched/fair.c:update_load_avg"]

    def test_developer_modified_files(self, results):
        files = sorted(results["case_007"]["developer_patch"]["modified_files"])
        assert files == ["kernel/sched/fair.c"]

    def test_developer_modified_functions(self, results):
        funcs = sorted(results["case_007"]["developer_patch"]["modified_functions"])
        assert funcs == ["kernel/sched/fair.c:update_load_avg"]

    def test_file_iou(self, results):
        assert results["case_007"]["metrics"]["file_iou"] == pytest.approx(1.0, abs=0.01)

    def test_function_iou(self, results):
        assert results["case_007"]["metrics"]["function_iou"] == pytest.approx(1.0, abs=0.01)

    def test_localization_hit(self, results):
        assert results["case_007"]["metrics"]["localization_hit"] is True

    def test_patch_equivalent(self, results):
        # Guard clause restructuring: early return vs wrapped block
        assert results["case_007"]["metrics"]["patch_equivalent"] is True


# ---- Structural tests ----

class TestStructure:
    def test_all_cases_present(self, results):
        for case_id in ["case_001", "case_002", "case_003", "case_004", "case_005", "case_006", "case_007"]:
            assert case_id in results, f"Missing case: {case_id}"

    def test_output_file_exists(self):
        assert os.path.exists(RESULTS_PATH)

    def test_valid_json(self):
        with open(RESULTS_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_metrics_keys(self, results):
        for case_id in results:
            metrics = results[case_id]["metrics"]
            assert "file_iou" in metrics
            assert "function_iou" in metrics
            assert "localization_hit" in metrics
            assert "patch_equivalent" in metrics

    def test_iou_range(self, results):
        for case_id in results:
            metrics = results[case_id]["metrics"]
            assert 0.0 <= metrics["file_iou"] <= 1.0
            assert 0.0 <= metrics["function_iou"] <= 1.0
