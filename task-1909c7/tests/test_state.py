
"""Tests for the kernel SLUB cache collision analyzer output."""

import json
import os
import pytest


ANALYSIS_PATH = "/app/output/analysis.json"


@pytest.fixture(scope="module")
def analysis():
    """Load the analysis output."""
    assert os.path.exists(ANALYSIS_PATH), f"Output file {ANALYSIS_PATH} does not exist"
    with open(ANALYSIS_PATH) as f:
        data = json.load(f)
    return data


@pytest.fixture(scope="module")
def cache_analysis(analysis):
    return analysis["cache_analysis"]


@pytest.fixture(scope="module")
def vuln_analysis(analysis):
    return analysis["vulnerability_analysis"]


def get_vuln_by_id(vuln_analysis, vuln_id):
    """Find a vulnerability analysis entry by its ID."""
    for v in vuln_analysis:
        if v["vuln_id"] == vuln_id:
            return v
    return None


def get_target_structures(vuln_entry):
    """Extract the set of target structure names from a vulnerability entry."""
    return {t["structure"] for t in vuln_entry["reachable_targets"]}


def get_target_by_name(vuln_entry, struct_name):
    """Get a specific target entry by structure name."""
    for t in vuln_entry["reachable_targets"]:
        if t["structure"] == struct_name:
            return t
    return None


def get_field_entries(target_entry, field_name):
    """Get all controllable_fields entries for a given field name."""
    return [f for f in target_entry["controllable_fields"] if f["field_name"] == field_name]


# ============================================================
# Test 1: Output structure and validity
# ============================================================
class TestOutputStructure:
    def test_output_exists(self):
        assert os.path.exists(ANALYSIS_PATH), "analysis.json must exist"

    def test_valid_json(self, analysis):
        assert isinstance(analysis, dict)

    def test_has_cache_analysis(self, analysis):
        assert "cache_analysis" in analysis

    def test_has_vulnerability_analysis(self, analysis):
        assert "vulnerability_analysis" in analysis

    def test_three_vulnerabilities_analyzed(self, vuln_analysis):
        assert len(vuln_analysis) == 3

    def test_vuln_ids_present(self, vuln_analysis):
        ids = {v["vuln_id"] for v in vuln_analysis}
        assert ids == {"vuln_1", "vuln_2", "vuln_3"}


# ============================================================
# Test 2: Cache merging correctness
# ============================================================
class TestCacheMerging:
    def test_drill_cache_merges_into_kmalloc_192(self, cache_analysis):
        merged = cache_analysis["merged_caches"]
        assert "drill_cache" in merged
        assert merged["drill_cache"] == "kmalloc-192"

    def test_cred_jar_is_standalone(self, cache_analysis):
        standalone = cache_analysis["standalone_caches"]
        assert "cred_jar" in standalone

    def test_cred_jar_not_merged(self, cache_analysis):
        merged = cache_analysis["merged_caches"]
        assert "cred_jar" not in merged

    def test_sighand_cache_is_standalone(self, cache_analysis):
        standalone = cache_analysis["standalone_caches"]
        assert "sighand_cache" in standalone

    def test_sighand_cache_not_merged(self, cache_analysis):
        merged = cache_analysis["merged_caches"]
        assert "sighand_cache" not in merged

    def test_exactly_one_merged_cache(self, cache_analysis):
        merged = cache_analysis["merged_caches"]
        assert len(merged) == 1

    def test_exactly_two_standalone_caches(self, cache_analysis):
        standalone = cache_analysis["standalone_caches"]
        assert len(standalone) == 2


# ============================================================
# Test 3: Vulnerability 1 - UAF-write in kmalloc-64
# ============================================================
class TestVuln1Targets:
    def test_effective_cache(self, vuln_analysis):
        v1 = get_vuln_by_id(vuln_analysis, "vuln_1")
        assert v1["effective_cache"] == "kmalloc-64"

    def test_msg_msg_is_target(self, vuln_analysis):
        v1 = get_vuln_by_id(vuln_analysis, "vuln_1")
        targets = get_target_structures(v1)
        assert "msg_msg" in targets

    def test_pipe_buffer_is_target(self, vuln_analysis):
        v1 = get_vuln_by_id(vuln_analysis, "vuln_1")
        targets = get_target_structures(v1)
        assert "pipe_buffer" in targets

    def test_cred_not_target(self, vuln_analysis):
        v1 = get_vuln_by_id(vuln_analysis, "vuln_1")
        targets = get_target_structures(v1)
        assert "cred" not in targets

    def test_seq_operations_not_target(self, vuln_analysis):
        v1 = get_vuln_by_id(vuln_analysis, "vuln_1")
        targets = get_target_structures(v1)
        assert "seq_operations" not in targets

    def test_drill_item_not_target(self, vuln_analysis):
        v1 = get_vuln_by_id(vuln_analysis, "vuln_1")
        targets = get_target_structures(v1)
        assert "drill_item" not in targets

    def test_tty_struct_not_target(self, vuln_analysis):
        v1 = get_vuln_by_id(vuln_analysis, "vuln_1")
        targets = get_target_structures(v1)
        assert "tty_struct" not in targets

    def test_exactly_two_targets(self, vuln_analysis):
        v1 = get_vuln_by_id(vuln_analysis, "vuln_1")
        targets = get_target_structures(v1)
        assert len(targets) == 2

    def test_collision_type_same_cache(self, vuln_analysis):
        v1 = get_vuln_by_id(vuln_analysis, "vuln_1")
        for t in v1["reachable_targets"]:
            assert t["collision_type"] == "same_cache"


# ============================================================
# Test 4: Vulnerability 1 - Field overlap analysis
# ============================================================
class TestVuln1Fields:
    def test_msg_msg_m_ts_controllable(self, vuln_analysis):
        v1 = get_vuln_by_id(vuln_analysis, "vuln_1")
        msg = get_target_by_name(v1, "msg_msg")
        fields = get_field_entries(msg, "m_ts")
        assert len(fields) >= 1
        f = fields[0]
        assert f["field_offset"] == 24
        assert f["field_size"] == 8
        assert f["capability"] == "info_leak"

    def test_msg_msg_next_segment_controllable(self, vuln_analysis):
        v1 = get_vuln_by_id(vuln_analysis, "vuln_1")
        msg = get_target_by_name(v1, "msg_msg")
        fields = get_field_entries(msg, "next_segment")
        assert len(fields) >= 1
        f = fields[0]
        assert f["field_offset"] == 32
        assert f["capability"] == "arbitrary_read"

    def test_pipe_buffer_page_controllable(self, vuln_analysis):
        v1 = get_vuln_by_id(vuln_analysis, "vuln_1")
        pb = get_target_by_name(v1, "pipe_buffer")
        fields = get_field_entries(pb, "page")
        assert len(fields) >= 1
        assert fields[0]["capability"] == "arbitrary_rw"
        assert fields[0]["exploit_method"] == "page_ptr"

    def test_pipe_buffer_ops_controllable(self, vuln_analysis):
        v1 = get_vuln_by_id(vuln_analysis, "vuln_1")
        pb = get_target_by_name(v1, "pipe_buffer")
        fields = get_field_entries(pb, "ops")
        assert len(fields) >= 1
        assert fields[0]["capability"] == "code_exec"
        assert fields[0]["exploit_method"] == "func_ptr"

    def test_pipe_buffer_flags_controllable(self, vuln_analysis):
        v1 = get_vuln_by_id(vuln_analysis, "vuln_1")
        pb = get_target_by_name(v1, "pipe_buffer")
        fields = get_field_entries(pb, "flags")
        assert len(fields) >= 1
        assert fields[0]["capability"] == "privilege_escalation"
        assert fields[0]["exploit_method"] == "flag_field"

    def test_controllable_region_full_object(self, vuln_analysis):
        v1 = get_vuln_by_id(vuln_analysis, "vuln_1")
        msg = get_target_by_name(v1, "msg_msg")
        assert msg["controllable_region"]["offset_in_target"] == 0
        assert msg["controllable_region"]["size"] == 64


# ============================================================
# Test 5: Vulnerability 2 - UAF-write in drill_cache
# ============================================================
class TestVuln2Targets:
    def test_effective_cache_kmalloc_192(self, vuln_analysis):
        v2 = get_vuln_by_id(vuln_analysis, "vuln_2")
        assert v2["effective_cache"] == "kmalloc-192"

    def test_drill_item_is_target(self, vuln_analysis):
        v2 = get_vuln_by_id(vuln_analysis, "vuln_2")
        targets = get_target_structures(v2)
        assert "drill_item" in targets

    def test_file_event_info_is_target(self, vuln_analysis):
        v2 = get_vuln_by_id(vuln_analysis, "vuln_2")
        targets = get_target_structures(v2)
        assert "file_event_info" in targets

    def test_cred_not_reachable(self, vuln_analysis):
        v2 = get_vuln_by_id(vuln_analysis, "vuln_2")
        targets = get_target_structures(v2)
        assert "cred" not in targets

    def test_msg_msg_not_reachable(self, vuln_analysis):
        v2 = get_vuln_by_id(vuln_analysis, "vuln_2")
        targets = get_target_structures(v2)
        assert "msg_msg" not in targets

    def test_exactly_two_targets(self, vuln_analysis):
        v2 = get_vuln_by_id(vuln_analysis, "vuln_2")
        targets = get_target_structures(v2)
        assert len(targets) == 2


class TestVuln2Fields:
    def test_drill_item_callback_controllable(self, vuln_analysis):
        v2 = get_vuln_by_id(vuln_analysis, "vuln_2")
        di = get_target_by_name(v2, "drill_item")
        fields = get_field_entries(di, "callback")
        assert len(fields) >= 1
        assert fields[0]["capability"] == "code_exec"
        assert fields[0]["field_offset"] == 0
        assert fields[0]["field_size"] == 8

    def test_file_event_info_handler_controllable(self, vuln_analysis):
        v2 = get_vuln_by_id(vuln_analysis, "vuln_2")
        fei = get_target_by_name(v2, "file_event_info")
        fields = get_field_entries(fei, "handler")
        assert len(fields) >= 1
        assert fields[0]["capability"] == "code_exec"

    def test_controllable_region_8_bytes(self, vuln_analysis):
        v2 = get_vuln_by_id(vuln_analysis, "vuln_2")
        di = get_target_by_name(v2, "drill_item")
        assert di["controllable_region"]["offset_in_target"] == 0
        assert di["controllable_region"]["size"] == 8

    def test_drill_item_next_not_controllable(self, vuln_analysis):
        """next field at offset 144 should NOT be controllable with only 8 bytes."""
        v2 = get_vuln_by_id(vuln_analysis, "vuln_2")
        di = get_target_by_name(v2, "drill_item")
        fields = get_field_entries(di, "next")
        assert len(fields) == 0

    def test_drill_item_owner_cred_not_controllable(self, vuln_analysis):
        """owner_cred at offset 160 should NOT be controllable with only 8 bytes."""
        v2 = get_vuln_by_id(vuln_analysis, "vuln_2")
        di = get_target_by_name(v2, "drill_item")
        fields = get_field_entries(di, "owner_cred")
        assert len(fields) == 0

    def test_file_event_info_target_path_not_controllable(self, vuln_analysis):
        """target_path at offset 16 should NOT be controllable with only 8 bytes at offset 0."""
        v2 = get_vuln_by_id(vuln_analysis, "vuln_2")
        fei = get_target_by_name(v2, "file_event_info")
        fields = get_field_entries(fei, "target_path")
        assert len(fields) == 0


# ============================================================
# Test 6: Vulnerability 3 - OOB-write past kmalloc-96
# ============================================================
class TestVuln3Targets:
    def test_effective_cache_kmalloc_96(self, vuln_analysis):
        v3 = get_vuln_by_id(vuln_analysis, "vuln_3")
        assert v3["effective_cache"] == "kmalloc-96"

    def test_subprocess_info_is_target(self, vuln_analysis):
        v3 = get_vuln_by_id(vuln_analysis, "vuln_3")
        targets = get_target_structures(v3)
        assert "subprocess_info" in targets

    def test_timer_list_wrapper_is_target(self, vuln_analysis):
        v3 = get_vuln_by_id(vuln_analysis, "vuln_3")
        targets = get_target_structures(v3)
        assert "timer_list_wrapper" in targets

    def test_msg_msg_not_target(self, vuln_analysis):
        v3 = get_vuln_by_id(vuln_analysis, "vuln_3")
        targets = get_target_structures(v3)
        assert "msg_msg" not in targets

    def test_exactly_two_targets(self, vuln_analysis):
        v3 = get_vuln_by_id(vuln_analysis, "vuln_3")
        targets = get_target_structures(v3)
        assert len(targets) == 2

    def test_collision_type_adjacent(self, vuln_analysis):
        v3 = get_vuln_by_id(vuln_analysis, "vuln_3")
        for t in v3["reachable_targets"]:
            assert t["collision_type"] == "adjacent_object"


class TestVuln3Fields:
    def test_overflow_region_16_bytes(self, vuln_analysis):
        """OOB: 88+24=112, object=96, overflow = 112-96 = 16 bytes into next object."""
        v3 = get_vuln_by_id(vuln_analysis, "vuln_3")
        si = get_target_by_name(v3, "subprocess_info")
        assert si["controllable_region"]["offset_in_target"] == 0
        assert si["controllable_region"]["size"] == 16

    def test_subprocess_info_callback(self, vuln_analysis):
        v3 = get_vuln_by_id(vuln_analysis, "vuln_3")
        si = get_target_by_name(v3, "subprocess_info")
        fields = get_field_entries(si, "callback")
        assert len(fields) >= 1
        assert fields[0]["capability"] == "code_exec"
        assert fields[0]["field_offset"] == 0

    def test_subprocess_info_path_not_reachable(self, vuln_analysis):
        """path at offset 16 is NOT within the 16-byte overflow [0,16)."""
        v3 = get_vuln_by_id(vuln_analysis, "vuln_3")
        si = get_target_by_name(v3, "subprocess_info")
        fields = get_field_entries(si, "path")
        assert len(fields) == 0

    def test_timer_function_controllable(self, vuln_analysis):
        v3 = get_vuln_by_id(vuln_analysis, "vuln_3")
        tl = get_target_by_name(v3, "timer_list_wrapper")
        fields = get_field_entries(tl, "function")
        assert len(fields) >= 1
        assert fields[0]["capability"] == "code_exec"

    def test_timer_expires_controllable(self, vuln_analysis):
        v3 = get_vuln_by_id(vuln_analysis, "vuln_3")
        tl = get_target_by_name(v3, "timer_list_wrapper")
        fields = get_field_entries(tl, "expires")
        assert len(fields) >= 1
        assert fields[0]["capability"] == "info_leak"
        assert fields[0]["field_offset"] == 8
        assert fields[0]["field_size"] == 8


# ============================================================
# Test 7: Mitigation status
# ============================================================
class TestMitigations:
    def test_code_exec_not_mitigated_default(self, vuln_analysis):
        """With CONFIG_CFI_CLANG=false, no code_exec via func_ptr should be mitigated."""
        for v in vuln_analysis:
            for t in v["reachable_targets"]:
                for f in t["controllable_fields"]:
                    if f["capability"] == "code_exec" and f["exploit_method"] == "func_ptr":
                        assert f["mitigated"] is False, (
                            f"code_exec via func_ptr should not be mitigated when CFI is off, "
                            f"but {v['vuln_id']}/{t['structure']}/{f['field_name']} is marked mitigated"
                        )

    def test_no_fields_mitigated_default(self, vuln_analysis):
        """With the default mitigation config, no capability should be blocked
        because the blocking mitigations (CFI, INIT_ON_FREE, RANDOM_KMALLOC)
        are all inactive, and SLAB_FREELIST_HARDENED only blocks freelist_ptr
        method which no field uses."""
        for v in vuln_analysis:
            for t in v["reachable_targets"]:
                for f in t["controllable_fields"]:
                    assert f["mitigated"] is False, (
                        f"No fields should be mitigated with default config, "
                        f"but {v['vuln_id']}/{t['structure']}/{f['field_name']} is marked mitigated"
                    )


# ============================================================
# Test 8: Cross-vulnerability isolation
# ============================================================
class TestCrossVulnIsolation:
    def test_sighand_struct_never_target(self, vuln_analysis):
        """sighand_struct is in unmergeable sighand_cache (has constructor),
        and no vulnerability targets kmalloc-1024, so it should never appear."""
        for v in vuln_analysis:
            targets = get_target_structures(v)
            assert "sighand_struct" not in targets

    def test_user_key_payload_never_target(self, vuln_analysis):
        """user_key_payload is in kmalloc-128. No vulnerability targets this cache."""
        for v in vuln_analysis:
            targets = get_target_structures(v)
            assert "user_key_payload" not in targets

    def test_cred_never_reachable(self, vuln_analysis):
        """cred is in cred_jar (SLAB_TYPESAFE_BY_RCU, standalone).
        It should never be reachable from any vulnerability."""
        for v in vuln_analysis:
            targets = get_target_structures(v)
            assert "cred" not in targets
