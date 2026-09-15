
import json
import os
import subprocess
import tempfile

import pytest


@pytest.fixture(scope="session")
def tool_output():
    """Run the analysis tool with the default scenario and cache the JSON output."""
    result = subprocess.run(
        [
            "python3", "/app/analyze.py",
            "--slabinfo", "/app/slabinfo.txt",
            "--structs", "/app/structs.json",
            "--scenario", "/app/scenario.json",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        cwd="/app",
    )
    assert result.returncode == 0, (
        f"analyze.py exited with code {result.returncode}\n"
        f"stderr: {result.stderr}\nstdout: {result.stdout[:2000]}"
    )
    try:
        output = json.loads(result.stdout)
    except json.JSONDecodeError:
        pytest.fail(f"Output is not valid JSON:\n{result.stdout[:2000]}")
    return output


def _candidate_names(output):
    """Return set of lowercase candidate names."""
    return {c.get("name", "").lower().strip() for c in output.get("candidates", [])}


def _candidates_list(output):
    return output.get("candidates", [])


def _find_candidate(output, name):
    for c in _candidates_list(output):
        if c.get("name", "").lower().strip() == name.lower():
            return c
    return None


# ---------------------------------------------------------------------------
# Target cache identification
# ---------------------------------------------------------------------------
class TestTargetCache:
    def test_has_target_cache_key(self, tool_output):
        assert "target_cache" in tool_output, "Output must have 'target_cache' key"

    def test_cache_name_is_kmalloc_256(self, tool_output):
        name = tool_output["target_cache"].get("name", "")
        assert name == "kmalloc-256", f"Expected kmalloc-256, got {name}"

    def test_cache_objsize(self, tool_output):
        assert tool_output["target_cache"].get("objsize") == 256

    def test_objs_per_slab(self, tool_output):
        assert tool_output["target_cache"].get("objs_per_slab") == 16

    def test_pages_per_slab(self, tool_output):
        assert tool_output["target_cache"].get("pages_per_slab") == 1


# ---------------------------------------------------------------------------
# Candidate exclusion — objects that must NOT appear
# ---------------------------------------------------------------------------
class TestCandidateExclusion:
    def test_msg_msg_excluded(self, tool_output):
        """msg_msg uses GFP_KERNEL_ACCOUNT -> kmalloc-cg-256, not kmalloc-256."""
        assert "msg_msg" not in _candidate_names(tool_output), (
            "msg_msg must be excluded (GFP_KERNEL_ACCOUNT -> kmalloc-cg cache)"
        )

    def test_cred_excluded(self, tool_output):
        """cred uses dedicated cred_jar cache."""
        assert "cred" not in _candidate_names(tool_output)

    def test_sk_buff_excluded(self, tool_output):
        """sk_buff uses dedicated skbuff_head_cache."""
        assert "sk_buff" not in _candidate_names(tool_output)

    def test_seq_operations_excluded(self, tool_output):
        """seq_operations: 32 bytes + GFP_KERNEL_ACCOUNT -> kmalloc-cg-32."""
        assert "seq_operations" not in _candidate_names(tool_output)

    def test_tty_struct_excluded(self, tool_output):
        """tty_struct: 696 bytes -> kmalloc-1024, wrong cache."""
        assert "tty_struct" not in _candidate_names(tool_output)

    def test_subprocess_info_excluded(self, tool_output):
        """subprocess_info: 96 bytes + not userspace-triggerable."""
        assert "subprocess_info" not in _candidate_names(tool_output)


# ---------------------------------------------------------------------------
# Candidate inclusion — objects that MUST appear
# ---------------------------------------------------------------------------
class TestCandidateInclusion:
    def test_user_key_payload_included(self, tool_output):
        assert "user_key_payload" in _candidate_names(tool_output)

    def test_timerfd_ctx_included(self, tool_output):
        assert "timerfd_ctx" in _candidate_names(tool_output)

    def test_simple_xattr_included(self, tool_output):
        assert "simple_xattr" in _candidate_names(tool_output)

    def test_minimum_candidate_count(self, tool_output):
        assert len(_candidates_list(tool_output)) >= 3


# ---------------------------------------------------------------------------
# Data control assessment at the dereference offset
# ---------------------------------------------------------------------------
class TestDataControl:
    def test_user_key_payload_has_data_control(self, tool_output):
        """user_key_payload: user data at offset 24, deref at 192 -> controlled."""
        c = _find_candidate(tool_output, "user_key_payload")
        assert c is not None
        assert c.get("data_control_at_deref_offset") is True

    def test_simple_xattr_has_data_control(self, tool_output):
        """simple_xattr: user data at offset 32, deref at 192 -> controlled."""
        c = _find_candidate(tool_output, "simple_xattr")
        assert c is not None
        assert c.get("data_control_at_deref_offset") is True

    def test_timerfd_ctx_no_data_control(self, tool_output):
        """timerfd_ctx: no user-controlled data, kernel structure only."""
        c = _find_candidate(tool_output, "timerfd_ctx")
        assert c is not None
        assert c.get("data_control_at_deref_offset") is False

    def test_at_least_one_data_control_candidate(self, tool_output):
        has = any(c.get("data_control_at_deref_offset") for c in _candidates_list(tool_output))
        assert has, "At least one candidate must have data_control_at_deref_offset=True"


# ---------------------------------------------------------------------------
# Scoring and ranking
# ---------------------------------------------------------------------------
class TestScoring:
    def test_candidates_sorted_descending(self, tool_output):
        scores = [c.get("score", 0) for c in _candidates_list(tool_output)]
        assert scores == sorted(scores, reverse=True), "Candidates must be sorted by score descending"

    def test_top_candidate_has_data_control(self, tool_output):
        cands = _candidates_list(tool_output)
        if cands:
            assert cands[0].get("data_control_at_deref_offset") is True

    def test_top_candidate_is_persistent(self, tool_output):
        cands = _candidates_list(tool_output)
        if cands:
            assert cands[0].get("lifetime") == "persistent"

    def test_timerfd_lower_than_data_control_objects(self, tool_output):
        """timerfd_ctx (no data control) must score below objects with data control."""
        tfc = _find_candidate(tool_output, "timerfd_ctx")
        ukp = _find_candidate(tool_output, "user_key_payload")
        if tfc and ukp:
            assert tfc["score"] < ukp["score"]


# ---------------------------------------------------------------------------
# Spray parameters
# ---------------------------------------------------------------------------
class TestSprayParams:
    def test_has_spray_params(self, tool_output):
        assert "spray_params" in tool_output

    def test_spray_objs_per_slab(self, tool_output):
        assert tool_output["spray_params"].get("objs_per_slab") == 16

    def test_spray_count_positive(self, tool_output):
        count = tool_output["spray_params"].get("recommended_spray_count", 0)
        assert count > 0

    def test_spray_count_reasonable(self, tool_output):
        count = tool_output["spray_params"].get("recommended_spray_count", 0)
        objs = tool_output["spray_params"].get("objs_per_slab", 16)
        assert count >= objs * 2, f"Spray count ({count}) should be >= 2 full slabs ({objs * 2})"


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------
class TestStrategy:
    def test_has_strategy(self, tool_output):
        assert "strategy" in tool_output
        assert tool_output["strategy"] is not None

    def test_strategy_object_is_candidate(self, tool_output):
        spray_obj = tool_output["strategy"].get("spray_object", "")
        names = [c.get("name") for c in _candidates_list(tool_output)]
        assert spray_obj in names, f"Strategy spray_object '{spray_obj}' must be a candidate"

    def test_strategy_object_has_data_control(self, tool_output):
        spray_obj = tool_output["strategy"].get("spray_object", "")
        c = _find_candidate(tool_output, spray_obj)
        assert c is not None
        assert c.get("data_control_at_deref_offset") is True, (
            "Strategy spray object must have data control at deref offset"
        )

    def test_strategy_has_attack_type(self, tool_output):
        assert tool_output["strategy"].get("attack_type"), "Strategy must specify attack_type"


# ---------------------------------------------------------------------------
# Generalization — different scenario to ensure tool is not hardcoded
# ---------------------------------------------------------------------------
class TestGeneralization:
    def test_different_size_class(self):
        """Object size 80 with GFP_KERNEL should map to kmalloc-96."""
        alt_scenario = {
            "object_name": "test_obj",
            "object_size": 80,
            "alloc_function": "kmalloc",
            "alloc_flags": "GFP_KERNEL",
            "vulnerability_type": "use-after-free",
            "description": "Test scenario for generalization.",
            "dereference_offsets": [
                {"offset": 64, "type": "function_ptr", "access": "call", "context": "Test"}
            ],
            "additional_constraints": {},
        }
        fd, alt_path = tempfile.mkstemp(suffix=".json")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(alt_scenario, f)

            result = subprocess.run(
                [
                    "python3", "/app/analyze.py",
                    "--slabinfo", "/app/slabinfo.txt",
                    "--structs", "/app/structs.json",
                    "--scenario", alt_path,
                ],
                capture_output=True,
                text=True,
                timeout=120,
                cwd="/app",
            )
            assert result.returncode == 0, f"Tool failed on alt scenario: {result.stderr}"
            output = json.loads(result.stdout)

            cache = output["target_cache"]
            assert cache["name"] == "kmalloc-96", (
                f"Size 80 + GFP_KERNEL should map to kmalloc-96, got {cache['name']}"
            )
            assert cache["objsize"] == 96
            assert cache["objs_per_slab"] == 42
        finally:
            os.unlink(alt_path)

    def test_account_flag_uses_cg_cache(self):
        """Object with GFP_KERNEL_ACCOUNT should map to kmalloc-cg-* cache."""
        alt_scenario = {
            "object_name": "test_acct_obj",
            "object_size": 200,
            "alloc_function": "kmalloc",
            "alloc_flags": "GFP_KERNEL_ACCOUNT",
            "vulnerability_type": "use-after-free",
            "description": "Test ACCOUNT flag handling.",
            "dereference_offsets": [
                {"offset": 64, "type": "function_ptr", "access": "call", "context": "Test"}
            ],
            "additional_constraints": {},
        }
        fd, alt_path = tempfile.mkstemp(suffix=".json")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(alt_scenario, f)

            result = subprocess.run(
                [
                    "python3", "/app/analyze.py",
                    "--slabinfo", "/app/slabinfo.txt",
                    "--structs", "/app/structs.json",
                    "--scenario", alt_path,
                ],
                capture_output=True,
                text=True,
                timeout=120,
                cwd="/app",
            )
            assert result.returncode == 0, f"Tool failed on ACCOUNT scenario: {result.stderr}"
            output = json.loads(result.stdout)

            cache = output["target_cache"]
            assert cache["name"] == "kmalloc-cg-256", (
                f"Size 200 + GFP_KERNEL_ACCOUNT should map to kmalloc-cg-256, got {cache['name']}"
            )
        finally:
            os.unlink(alt_path)
