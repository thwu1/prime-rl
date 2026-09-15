"""
Tests for OpenSearch ISM Cluster Forensics pipeline outputs.


Verifies jq extraction outputs, diagnosis report, and corrected policies
against expected cluster state analysis for a 15-day OpenSearch cluster
with 4 ISM issues across 26 managed indices.
"""

import json
import os
import pytest


# ========== FIXTURES ==========

@pytest.fixture(scope="module")
def failed_actions():
    path = "/app/output/jq_extracts/failed_actions.json"
    assert os.path.exists(path), f"Missing required output: {path}"
    with open(path) as f:
        data = json.load(f)
    assert isinstance(data, list), "failed_actions.json must be a JSON array"
    return data


@pytest.fixture(scope="module")
def policy_mismatches():
    path = "/app/output/jq_extracts/policy_mismatches.json"
    assert os.path.exists(path), f"Missing required output: {path}"
    with open(path) as f:
        data = json.load(f)
    assert isinstance(data, list), "policy_mismatches.json must be a JSON array"
    return data


@pytest.fixture(scope="module")
def rollover_chains():
    path = "/app/output/jq_extracts/rollover_chains.json"
    assert os.path.exists(path), f"Missing required output: {path}"
    with open(path) as f:
        data = json.load(f)
    assert isinstance(data, list), "rollover_chains.json must be a JSON array"
    return data


@pytest.fixture(scope="module")
def diagnosis():
    path = "/app/output/diagnosis.json"
    assert os.path.exists(path), f"Missing required output: {path}"
    with open(path) as f:
        data = json.load(f)
    assert "issues" in data, "diagnosis.json missing 'issues' key"
    assert "summary" in data, "diagnosis.json missing 'summary' key"
    return data


@pytest.fixture(scope="module")
def corrected_security():
    path = "/app/output/corrected_policies/security-lifecycle.json"
    assert os.path.exists(path), f"Missing required output: {path}"
    with open(path) as f:
        return json.load(f)


# ========== JQ EXTRACT: FAILED ACTIONS ==========

class TestFailedActionsExtract:
    def test_exactly_four_failed(self, failed_actions):
        assert len(failed_actions) == 4, \
            f"Expected 4 failed actions, got {len(failed_actions)}: {[fa.get('index') for fa in failed_actions]}"

    def test_applogs_003_present(self, failed_actions):
        indices = {fa["index"] for fa in failed_actions}
        assert "applogs-000003" in indices

    def test_security_006_present(self, failed_actions):
        indices = {fa["index"] for fa in failed_actions}
        assert "security-000006" in indices

    def test_security_007_present(self, failed_actions):
        indices = {fa["index"] for fa in failed_actions}
        assert "security-000007" in indices

    def test_security_008_present(self, failed_actions):
        indices = {fa["index"] for fa in failed_actions}
        assert "security-000008" in indices

    def test_applogs_003_is_force_merge(self, failed_actions):
        entry = next(fa for fa in failed_actions if fa["index"] == "applogs-000003")
        assert entry["action"] == "force_merge"
        assert entry["failed"] is True
        assert entry["consumed_retries"] == 3

    def test_security_actions_are_allocation(self, failed_actions):
        for idx in ["security-000006", "security-000007", "security-000008"]:
            entry = next(fa for fa in failed_actions if fa["index"] == idx)
            assert entry["action"] == "allocation", \
                f"{idx} should have action=allocation, got {entry['action']}"
            assert entry["failed"] is True

    def test_required_fields_present(self, failed_actions):
        required = {"index", "policy_id", "state", "action", "failed",
                     "consumed_retries", "error_message"}
        for fa in failed_actions:
            missing = required - set(fa.keys())
            assert not missing, \
                f"Entry for {fa.get('index', '?')} missing fields: {missing}"


# ========== JQ EXTRACT: POLICY MISMATCHES ==========

class TestPolicyMismatchesExtract:
    def test_exactly_five_mismatches(self, policy_mismatches):
        assert len(policy_mismatches) == 5, \
            f"Expected 5 policy mismatches, got {len(policy_mismatches)}"

    def test_correct_indices(self, policy_mismatches):
        names = sorted(pm["index"] for pm in policy_mismatches)
        expected = [f"security-{i:06d}" for i in range(1, 6)]
        assert names == expected, f"Expected {expected}, got {names}"

    def test_stale_seq_number(self, policy_mismatches):
        for pm in policy_mismatches:
            assert pm["index_policy_seq_no"] == 2, \
                f"{pm['index']} should have index_policy_seq_no=2"

    def test_current_seq_number(self, policy_mismatches):
        for pm in policy_mismatches:
            assert pm["current_policy_seq_no"] == 3, \
                f"{pm['index']} should have current_policy_seq_no=3"

    def test_policy_id(self, policy_mismatches):
        for pm in policy_mismatches:
            assert pm["policy_id"] == "security-lifecycle"

    def test_required_fields_present(self, policy_mismatches):
        required = {"index", "policy_id", "index_policy_seq_no",
                     "current_policy_seq_no"}
        for pm in policy_mismatches:
            missing = required - set(pm.keys())
            assert not missing, \
                f"Entry for {pm.get('index', '?')} missing fields: {missing}"


# ========== JQ EXTRACT: ROLLOVER CHAINS ==========

class TestRolloverChainsExtract:
    def test_three_chains(self, rollover_chains):
        assert len(rollover_chains) == 3, \
            f"Expected 3 rollover chains, got {len(rollover_chains)}"

    def test_chain_patterns(self, rollover_chains):
        patterns = sorted(c["pattern"] for c in rollover_chains)
        assert patterns == ["applogs", "metrics", "security"]

    def test_applogs_chain_indices(self, rollover_chains):
        chain = next(c for c in rollover_chains if c["pattern"] == "applogs")
        assert len(chain["indices"]) == 8, \
            f"Expected 8 applogs indices, got {len(chain['indices'])}"
        assert chain["indices"][0] == "applogs-000001"
        assert chain["indices"][-1] == "applogs-000008"

    def test_applogs_rolled_count(self, rollover_chains):
        chain = next(c for c in rollover_chains if c["pattern"] == "applogs")
        assert chain["rolled_count"] == 7

    def test_applogs_alias_target(self, rollover_chains):
        chain = next(c for c in rollover_chains if c["pattern"] == "applogs")
        assert chain["alias_target"] == "applogs-000008"

    def test_security_chain_indices(self, rollover_chains):
        chain = next(c for c in rollover_chains if c["pattern"] == "security")
        assert len(chain["indices"]) == 15

    def test_security_rolled_count(self, rollover_chains):
        chain = next(c for c in rollover_chains if c["pattern"] == "security")
        assert chain["rolled_count"] == 14

    def test_security_alias_target(self, rollover_chains):
        chain = next(c for c in rollover_chains if c["pattern"] == "security")
        assert chain["alias_target"] == "security-000015"

    def test_metrics_chain_indices(self, rollover_chains):
        chain = next(c for c in rollover_chains if c["pattern"] == "metrics")
        assert len(chain["indices"]) == 3

    def test_metrics_rolled_count(self, rollover_chains):
        chain = next(c for c in rollover_chains if c["pattern"] == "metrics")
        assert chain["rolled_count"] == 2

    def test_metrics_alias_target_is_stale(self, rollover_chains):
        chain = next(c for c in rollover_chains if c["pattern"] == "metrics")
        assert chain["alias_target"] == "metrics-000007", \
            "metrics alias_target should reflect the actual (buggy) alias state"

    def test_required_fields_present(self, rollover_chains):
        required = {"pattern", "indices", "rolled_count", "write_alias",
                     "alias_target"}
        for chain in rollover_chains:
            missing = required - set(chain.keys())
            assert not missing, \
                f"Chain {chain.get('pattern', '?')} missing fields: {missing}"


# ========== DIAGNOSIS REPORT STRUCTURE ==========

class TestDiagnosisStructure:
    def test_has_issues_list(self, diagnosis):
        assert isinstance(diagnosis["issues"], list)

    def test_has_summary_dict(self, diagnosis):
        assert isinstance(diagnosis["summary"], dict)

    def test_total_indices_analyzed(self, diagnosis):
        assert diagnosis["total_indices_analyzed"] == 26, \
            f"Expected 26 indices analyzed, got {diagnosis['total_indices_analyzed']}"

    def test_exactly_four_issues(self, diagnosis):
        assert len(diagnosis["issues"]) == 4, \
            f"Expected 4 issues, got {len(diagnosis['issues'])}"

    def test_issue_categories_unique(self, diagnosis):
        categories = [i["category"] for i in diagnosis["issues"]]
        assert len(categories) == len(set(categories)), \
            f"Issue categories must be unique, got: {categories}"

    def test_all_categories_present(self, diagnosis):
        categories = {i["category"] for i in diagnosis["issues"]}
        expected = {"action_failure", "policy_version_mismatch",
                    "allocation_failure", "alias_integrity"}
        assert categories == expected, \
            f"Expected categories {expected}, got {categories}"


# ========== DIAGNOSIS: INDIVIDUAL ISSUES ==========

class TestDiagnosisIssues:
    def _get_issue(self, diagnosis, category):
        matches = [i for i in diagnosis["issues"] if i["category"] == category]
        assert len(matches) == 1, \
            f"Expected exactly 1 issue with category={category}"
        return matches[0]

    def test_action_failure_severity(self, diagnosis):
        issue = self._get_issue(diagnosis, "action_failure")
        assert issue["severity"] == "high"

    def test_action_failure_affected(self, diagnosis):
        issue = self._get_issue(diagnosis, "action_failure")
        assert issue["affected_indices"] == ["applogs-000003"]

    def test_action_failure_root_cause_mentions_shards(self, diagnosis):
        issue = self._get_issue(diagnosis, "action_failure")
        assert "10" in issue["root_cause"] or "shard" in issue["root_cause"].lower(), \
            "Root cause should mention the shard count problem"

    def test_policy_mismatch_severity(self, diagnosis):
        issue = self._get_issue(diagnosis, "policy_version_mismatch")
        assert issue["severity"] == "medium"

    def test_policy_mismatch_affected(self, diagnosis):
        issue = self._get_issue(diagnosis, "policy_version_mismatch")
        expected = [f"security-{i:06d}" for i in range(1, 6)]
        assert sorted(issue["affected_indices"]) == expected

    def test_allocation_failure_severity(self, diagnosis):
        issue = self._get_issue(diagnosis, "allocation_failure")
        assert issue["severity"] == "critical"

    def test_allocation_failure_affected(self, diagnosis):
        issue = self._get_issue(diagnosis, "allocation_failure")
        expected = [f"security-{i:06d}" for i in range(6, 9)]
        assert sorted(issue["affected_indices"]) == expected

    def test_allocation_failure_root_cause_mentions_attribute(self, diagnosis):
        issue = self._get_issue(diagnosis, "allocation_failure")
        rc = issue["root_cause"].lower()
        assert "temp" in rc and "temperature" in rc, \
            "Root cause should mention both 'temp' (wrong) and 'temperature' (correct)"

    def test_alias_integrity_severity(self, diagnosis):
        issue = self._get_issue(diagnosis, "alias_integrity")
        assert issue["severity"] == "critical"

    def test_alias_integrity_affected(self, diagnosis):
        issue = self._get_issue(diagnosis, "alias_integrity")
        assert "metrics-000007" in issue["affected_indices"]
        assert "metrics-000008" in issue["affected_indices"]
        assert len(issue["affected_indices"]) == 2

    def test_all_issues_have_required_fields(self, diagnosis):
        required = {"id", "severity", "category", "title",
                    "affected_indices", "root_cause", "remediation"}
        for issue in diagnosis["issues"]:
            missing = required - set(issue.keys())
            assert not missing, \
                f"Issue {issue.get('id', '?')} missing fields: {missing}"


# ========== DIAGNOSIS: SUMMARY ==========

class TestDiagnosisSummary:
    def test_total_issues(self, diagnosis):
        assert diagnosis["summary"]["total_issues"] == 4

    def test_critical_count(self, diagnosis):
        assert diagnosis["summary"]["critical_count"] == 2

    def test_high_count(self, diagnosis):
        assert diagnosis["summary"]["high_count"] == 1

    def test_medium_count(self, diagnosis):
        assert diagnosis["summary"]["medium_count"] == 1

    def test_failed_actions_count(self, diagnosis):
        assert diagnosis["summary"]["indices_with_failed_actions"] == 4

    def test_stale_policy_count(self, diagnosis):
        assert diagnosis["summary"]["indices_with_stale_policy"] == 5

    def test_alias_issues_count(self, diagnosis):
        assert diagnosis["summary"]["indices_with_alias_issues"] == 2


# ========== CORRECTED POLICIES ==========

class TestCorrectedSecurityPolicy:
    def test_has_policy_structure(self, corrected_security):
        assert "policy" in corrected_security
        assert "states" in corrected_security["policy"]

    def test_warm_allocation_uses_temperature(self, corrected_security):
        states = corrected_security["policy"]["states"]
        warm = next(s for s in states if s["name"] == "warm")
        alloc_actions = [a for a in warm["actions"] if "allocation" in a]
        assert len(alloc_actions) >= 1, "Warm state should have allocation action"
        alloc = alloc_actions[0]["allocation"]
        assert "require" in alloc
        assert "temperature" in alloc["require"], \
            "Warm allocation should use 'temperature' not 'temp'"
        assert "temp" not in alloc["require"], \
            "Warm allocation should NOT have 'temp' attribute"

    def test_warm_allocation_value(self, corrected_security):
        states = corrected_security["policy"]["states"]
        warm = next(s for s in states if s["name"] == "warm")
        alloc = next(a for a in warm["actions"] if "allocation" in a)["allocation"]
        assert alloc["require"]["temperature"] == "warm"

    def test_cold_allocation_uses_temperature(self, corrected_security):
        states = corrected_security["policy"]["states"]
        cold = next(s for s in states if s["name"] == "cold")
        alloc_actions = [a for a in cold["actions"] if "allocation" in a]
        assert len(alloc_actions) >= 1, "Cold state should have allocation action"
        alloc = alloc_actions[0]["allocation"]
        assert "require" in alloc
        assert "temperature" in alloc["require"], \
            "Cold allocation should use 'temperature' not 'temp'"
        assert "temp" not in alloc["require"], \
            "Cold allocation should NOT have 'temp' attribute"

    def test_cold_allocation_value(self, corrected_security):
        states = corrected_security["policy"]["states"]
        cold = next(s for s in states if s["name"] == "cold")
        alloc = next(a for a in cold["actions"] if "allocation" in a)["allocation"]
        assert alloc["require"]["temperature"] == "cold"

    def test_policy_id_preserved(self, corrected_security):
        assert corrected_security["policy"]["policy_id"] == "security-lifecycle"

    def test_state_count_preserved(self, corrected_security):
        assert len(corrected_security["policy"]["states"]) == 4
