#!/bin/bash
# OpenSearch ISM Forensics Pipeline
# Uses jq for cluster state extraction and Python for cross-reference analysis.
#

set -euo pipefail

mkdir -p /app/output/jq_extracts /app/output/corrected_policies

echo "=== Phase 1: jq extraction from cluster state ==="

# Read current policy seq_nos
APPLOG_SEQ=$(jq '._seq_no' /app/policies/applog-lifecycle.json)
SECURITY_SEQ=$(jq '._seq_no' /app/policies/security-lifecycle.json)
METRICS_SEQ=$(jq '._seq_no' /app/policies/metrics-lifecycle.json)

echo "  Policy seq_nos: applog=$APPLOG_SEQ security=$SECURITY_SEQ metrics=$METRICS_SEQ"

# 1. Extract indices with failed ISM actions
jq '[to_entries[] | select(.value.action.failed == true) | {
  index: .key,
  policy_id: .value.policy_id,
  state: .value.state.name,
  action: .value.action.name,
  failed: .value.action.failed,
  consumed_retries: .value.action.consumed_retries,
  error_message: .value.info.message
}] | sort_by(.index)' /app/cluster/ism_explain.json \
  > /app/output/jq_extracts/failed_actions.json

echo "  Failed actions: $(jq length /app/output/jq_extracts/failed_actions.json) indices"

# 2. Extract indices with stale policy versions
jq --argjson as "$APPLOG_SEQ" --argjson ss "$SECURITY_SEQ" --argjson ms "$METRICS_SEQ" '
[to_entries[] |
  (if .value.policy_id == "applog-lifecycle" then $as
   elif .value.policy_id == "security-lifecycle" then $ss
   elif .value.policy_id == "metrics-lifecycle" then $ms
   else -1 end) as $current |
  select(.value.policy_seq_no != $current) |
  {
    index: .key,
    policy_id: .value.policy_id,
    index_policy_seq_no: .value.policy_seq_no,
    current_policy_seq_no: $current
  }
] | sort_by(.index)' /app/cluster/ism_explain.json \
  > /app/output/jq_extracts/policy_mismatches.json

echo "  Policy mismatches: $(jq length /app/output/jq_extracts/policy_mismatches.json) indices"

# 3. Reconstruct rollover chains by grouping indices by prefix pattern
jq --slurpfile aliases /app/cluster/cat_aliases.json '
[to_entries |
 group_by(.key | split("-") | .[0]) |
 .[] |
 (.[0].key | split("-") | .[0]) as $pattern |
 ([$aliases[0][] | select(.alias == ($pattern + "-write"))] | .[0].index // null) as $alias_target |
 {
   pattern: $pattern,
   indices: ([.[] | .key] | sort),
   rolled_count: ([.[] | select(.value.rolled_over == true)] | length),
   write_alias: ($pattern + "-write"),
   alias_target: $alias_target
 }
] | sort_by(.pattern)' /app/cluster/ism_explain.json \
  > /app/output/jq_extracts/rollover_chains.json

echo "  Rollover chains: $(jq length /app/output/jq_extracts/rollover_chains.json) patterns"

echo ""
echo "=== Phase 2: Python cross-reference analysis ==="

python3 /app/forensics.py

echo ""
echo "=== Forensics pipeline complete ==="
