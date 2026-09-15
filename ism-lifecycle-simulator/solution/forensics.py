#!/usr/bin/env python3
"""
OpenSearch ISM Forensics — Cross-reference analysis and diagnosis.

Reads jq extraction outputs and raw cluster data to produce a comprehensive
diagnosis report and corrected ISM policies.

"""

import json
import os


def load_json(path):
    with open(path) as f:
        return json.load(f)


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def main():
    # Load cluster data
    explain = load_json("/app/cluster/ism_explain.json")
    cat_indices = load_json("/app/cluster/cat_indices.json")
    cat_aliases = load_json("/app/cluster/cat_aliases.json")
    node_attrs = load_json("/app/cluster/node_attrs.json")

    # Load policies
    policies = {}
    for fname in os.listdir("/app/policies"):
        if fname.endswith(".json"):
            data = load_json(f"/app/policies/{fname}")
            policies[data["policy"]["policy_id"]] = data

    # Load jq extracts
    failed_actions = load_json("/app/output/jq_extracts/failed_actions.json")
    policy_mismatches = load_json("/app/output/jq_extracts/policy_mismatches.json")
    rollover_chains = load_json("/app/output/jq_extracts/rollover_chains.json")

    # Build index lookup from cat_indices
    idx_lookup = {i["index"]: i for i in cat_indices}

    issues = []

    # ---- ISSUE 1: Force merge failure ----
    fm_failures = [fa for fa in failed_actions if fa["action"] == "force_merge"]
    if fm_failures:
        affected = sorted(fa["index"] for fa in fm_failures)
        # Get shard count from cat_indices
        pri_shards = int(idx_lookup[affected[0]]["pri"])
        retries = fm_failures[0]["consumed_retries"]

        issues.append({
            "id": "ISSUE-001",
            "severity": "high",
            "category": "action_failure",
            "title": "Force merge failure due to high shard count",
            "affected_indices": affected,
            "root_cause": (
                f"Index {affected[0]} has {pri_shards} primary shards "
                f"(expected 1 from standard template). Force merge to "
                f"max_num_segments=1 is failing after {retries} retries. "
                f"This blocks the warm-to-cold state transition, preventing "
                f"lifecycle progression."
            ),
            "remediation": (
                f"Reindex {affected[0]} with 1 primary shard to match the "
                f"standard template, or increase the policy force_merge "
                f"max_num_segments to {pri_shards} to allow merging with "
                f"the current shard count."
            )
        })

    # ---- ISSUE 2: Stale policy versions ----
    if policy_mismatches:
        affected = sorted(pm["index"] for pm in policy_mismatches)
        old_seq = policy_mismatches[0]["index_policy_seq_no"]
        new_seq = policy_mismatches[0]["current_policy_seq_no"]
        policy_id = policy_mismatches[0]["policy_id"]

        # Determine actual replica count on stale indices
        stale_replicas = set()
        for idx_name in affected:
            stale_replicas.add(int(idx_lookup[idx_name]["rep"]))

        issues.append({
            "id": "ISSUE-002",
            "severity": "medium",
            "category": "policy_version_mismatch",
            "title": "Stale ISM policy version on security indices",
            "affected_indices": affected,
            "root_cause": (
                f"These indices are running policy version seq_no={old_seq} "
                f"while the current {policy_id} policy is at seq_no={new_seq}. "
                f"The old policy configured replicas="
                f"{sorted(stale_replicas)[0]} in warm state, but the current "
                f"policy sets replicas=1. These indices also lack the "
                f"allocation action added in the newer policy version."
            ),
            "remediation": (
                f"Remove and re-add the ISM policy to affected indices using "
                f"POST _plugins/_ism/remove and POST _plugins/_ism/add to "
                f"pick up the latest policy version."
            )
        })

    # ---- ISSUE 3: Allocation attribute mismatch ----
    alloc_failures = [fa for fa in failed_actions if fa["action"] == "allocation"]
    if alloc_failures:
        affected = sorted(fa["index"] for fa in alloc_failures)

        # Get the cause from ISM explain
        cause_detail = explain[affected[0]].get("info", {}).get("cause", "")

        # Get available node attributes
        avail_attrs = sorted(set(na["attr"] for na in node_attrs))

        issues.append({
            "id": "ISSUE-003",
            "severity": "critical",
            "category": "allocation_failure",
            "title": "Node attribute mismatch in allocation action",
            "affected_indices": affected,
            "root_cause": (
                f"The security-lifecycle policy uses allocation.require.temp "
                f"but cluster data nodes use the attribute 'temperature' "
                f"instead of 'temp'. Available node attributes: {avail_attrs}. "
                f"This causes allocation to fail for all indices entering "
                f"warm state under the current policy version."
            ),
            "remediation": (
                f"Update the security-lifecycle policy to use 'temperature' "
                f"instead of 'temp' in the allocation.require settings for "
                f"both warm and cold states."
            )
        })

    # ---- ISSUE 4: Alias integrity — write alias not transferred ----
    for chain in rollover_chains:
        chain_indices = sorted(chain["indices"])
        alias_target = chain["alias_target"]

        # Find the latest index in the chain that has NOT rolled over
        latest_unrolled = None
        for idx_name in reversed(chain_indices):
            if idx_name in explain and not explain[idx_name]["rolled_over"]:
                latest_unrolled = idx_name
                break

        if latest_unrolled and alias_target and alias_target != latest_unrolled:
            # The alias is pointing to a rolled index instead of the latest
            issues.append({
                "id": "ISSUE-004",
                "severity": "critical",
                "category": "alias_integrity",
                "title": "Write alias not transferred during rollover",
                "affected_indices": sorted([alias_target, latest_unrolled]),
                "root_cause": (
                    f"The {chain['write_alias']} alias points to "
                    f"{alias_target} which has rolled_over=true, but should "
                    f"point to {latest_unrolled} (the latest unrolled index "
                    f"in the {chain['pattern']} chain). New documents are "
                    f"being written to the already-rolled index."
                ),
                "remediation": (
                    f"Update the {chain['write_alias']} alias to point to "
                    f"{latest_unrolled} as the write index using POST "
                    f"_aliases with remove/add actions."
                )
            })

    # ---- Build diagnosis report ----
    diagnosis = {
        "cluster_snapshot_time": "2025-01-15T00:00:00Z",
        "total_indices_analyzed": len(explain),
        "issues": issues,
        "summary": {
            "total_issues": len(issues),
            "critical_count": sum(1 for i in issues if i["severity"] == "critical"),
            "high_count": sum(1 for i in issues if i["severity"] == "high"),
            "medium_count": sum(1 for i in issues if i["severity"] == "medium"),
            "indices_with_failed_actions": len(failed_actions),
            "indices_with_stale_policy": len(policy_mismatches),
            "indices_with_alias_issues": sum(
                len(i["affected_indices"])
                for i in issues if i["category"] == "alias_integrity"
            )
        }
    }

    save_json("/app/output/diagnosis.json", diagnosis)
    print(f"  Diagnosis: {len(issues)} issues found")
    for issue in issues:
        print(f"    [{issue['severity'].upper()}] {issue['category']}: "
              f"{len(issue['affected_indices'])} indices affected")

    # ---- Generate corrected policies ----
    # Fix security-lifecycle: temp → temperature in allocation.require
    import copy
    sec_policy = copy.deepcopy(policies["security-lifecycle"])
    for state in sec_policy["policy"]["states"]:
        for action in state.get("actions", []):
            if "allocation" in action:
                req = action["allocation"].get("require", {})
                if "temp" in req:
                    val = req.pop("temp")
                    req["temperature"] = val

    save_json("/app/output/corrected_policies/security-lifecycle.json", sec_policy)
    print("  Corrected policy: security-lifecycle.json (temp → temperature)")


if __name__ == "__main__":
    main()
