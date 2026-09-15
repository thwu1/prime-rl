#!/usr/bin/env python3
"""
Generate OpenSearch cluster state snapshot data for the ISM forensics task.
Produces realistic API response format JSON files representing a 15-day-old cluster
with multiple ISM issues to diagnose.

"""

import json
import os
import hashlib
from datetime import datetime, timedelta, timezone

BASE_TIME = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
SNAPSHOT_TIME = datetime(2025, 1, 15, 0, 0, 0, tzinfo=timezone.utc)
DAY = timedelta(days=1)


def epoch_ms(dt):
    return int(dt.timestamp() * 1000)


def fake_uuid(name):
    h = hashlib.md5(name.encode()).hexdigest()
    return f"{h[:8]}-{h[8:12]}-4{h[13:16]}-{h[16:20]}-{h[20:32]}"


def iso_str(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


os.makedirs("/app/cluster", exist_ok=True)

ism_explain = {}
cat_indices = []
cat_aliases = []


def add_index(name, created, state, state_start, action_name, action_failed,
              action_retries, info_msg, rolled_over, policy_id, policy_seq_no,
              pri_shards, replicas, doc_count, size_bytes, health="green",
              info_cause=None):
    explain = {
        "index.plugins.index_state_management.policy_id": policy_id,
        "index": name,
        "index_uuid": fake_uuid(name),
        "policy_id": policy_id,
        "policy_seq_no": policy_seq_no,
        "policy_primary_term": 1,
        "rolled_over": rolled_over,
        "index_creation_date": epoch_ms(created),
        "state": {
            "name": state,
            "start_time": epoch_ms(state_start)
        },
        "action": {
            "name": action_name,
            "start_time": epoch_ms(state_start + timedelta(minutes=5)),
            "index": 0 if action_name in ("rollover", "transition") else 1,
            "failed": action_failed,
            "consumed_retries": action_retries,
            "last_retry_time": epoch_ms(SNAPSHOT_TIME - timedelta(hours=1)) if action_failed else 0
        },
        "retry_info": {
            "failed": action_failed,
            "consumed_retries": action_retries
        },
        "info": {"message": info_msg},
        "enabled": True
    }
    if info_cause:
        explain["info"]["cause"] = info_cause

    ism_explain[name] = explain

    cat_indices.append({
        "health": health,
        "status": "open",
        "index": name,
        "uuid": fake_uuid(name),
        "pri": str(pri_shards),
        "rep": str(replicas),
        "docs.count": str(doc_count),
        "docs.deleted": "0",
        "store.size": str(size_bytes),
        "pri.store.size": str(size_bytes),
        "creation.date": str(epoch_ms(created)),
        "creation.date.string": iso_str(created)
    })


# ============================================================
# APPLOGS: applog-lifecycle policy (seq_no=5)
# Rollover: 10M docs OR 2d age. Warm: 5d. Cold: 10d. Delete: 15d.
# Ingestion: ~5M docs/day, rollover every 2 days by doc count.
#
# ISSUE: applogs-000003 has 10 primary shards (misconfigured
# index template), causing force_merge to fail in warm state.
# This blocks warm->cold transition.
# ============================================================

applog_entries = [
    # (name, created_day_offset, rolled_over, state, state_start_day, action, failed, retries, info, cause, pri, rep, docs, size_gb)
    ("applogs-000001", 0, True, "cold", 10, "transition", False, 0,
     "Evaluating transition conditions", None, 1, 0, 10000000, 60),
    ("applogs-000002", 2, True, "cold", 12, "transition", False, 0,
     "Evaluating transition conditions", None, 1, 0, 10000000, 60),
    ("applogs-000003", 4, True, "warm", 9, "force_merge", True, 3,
     "Failed to force merge index [applogs-000003]",
     "java.io.IOException: merge failed - index [applogs-000003] has 10 primary shards with 50+ segments each, unable to force merge to max_num_segments=1 within timeout",
     10, 1, 10000000, 60),
    ("applogs-000004", 6, True, "warm", 11, "transition", False, 0,
     "Evaluating transition conditions", None, 1, 1, 10000000, 60),
    ("applogs-000005", 8, True, "warm", 13, "transition", False, 0,
     "Evaluating transition conditions", None, 1, 1, 10000000, 60),
    ("applogs-000006", 10, True, "hot", 10, "transition", False, 0,
     "Evaluating transition conditions", None, 1, 1, 10000000, 60),
    ("applogs-000007", 12, True, "hot", 12, "transition", False, 0,
     "Evaluating transition conditions", None, 1, 1, 10000000, 60),
    ("applogs-000008", 14, False, "hot", 14, "rollover", False, 0,
     "Attempting to rollover index", None, 1, 1, 0, 0),
]

for (name, day, rolled, state, state_day, action, failed, retries,
     info, cause, pri, rep, docs, size_gb) in applog_entries:
    created = BASE_TIME + day * DAY
    state_start = BASE_TIME + state_day * DAY
    health = "yellow" if failed else "green"
    add_index(name, created, state, state_start, action, failed, retries,
              info, rolled, "applog-lifecycle", 5, pri, rep, docs,
              size_gb * 1_000_000_000, health=health, info_cause=cause)

cat_aliases.append({
    "alias": "applogs-write",
    "index": "applogs-000008",
    "filter": "-",
    "routing.index": "-",
    "routing.search": "-",
    "is_write_index": "true"
})


# ============================================================
# SECURITY: security-lifecycle policy (current seq_no=3, was 2)
# Rollover: 5M docs OR 1d. Warm: 7d. Cold: 30d. Delete: 90d.
# Ingestion: ~6M docs/day, rollover daily.
#
# ISSUES:
#   - security-000001 through 000005: running stale policy
#     version (seq_no=2). Old policy had replicas=2 in warm,
#     no allocation action. Current policy has replicas=1 and
#     allocation action.
#   - security-000006 through 000008: allocation action failing
#     because policy uses attribute "temp" but cluster nodes
#     use attribute "temperature".
# ============================================================

for i in range(1, 16):
    name = f"security-{i:06d}"
    created = BASE_TIME + (i - 1) * DAY
    age_days = (SNAPSHOT_TIME - created).total_seconds() / 86400
    rolled = i < 15

    if age_days >= 7 and rolled:
        state = "warm"
        state_start = created + 7 * DAY
    else:
        state = "hot"
        state_start = created

    is_stale = i <= 5
    policy_seq = 2 if is_stale else 3

    if state == "warm":
        if is_stale:
            replicas = 2
            action_name = "transition"
            action_failed = False
            retries = 0
            info = "Evaluating transition conditions"
            cause = None
        else:
            replicas = 1
            action_name = "allocation"
            action_failed = True
            retries = 3
            info = "Failed to update index allocation settings"
            cause = ("index allocation routing requires attribute [temp] "
                     "which is not present on any data nodes in the cluster; "
                     "available node attributes: [temperature]")
    else:
        replicas = 1
        action_name = "transition" if rolled else "rollover"
        action_failed = False
        retries = 0
        info = ("Evaluating transition conditions" if rolled
                else "Attempting to rollover index")
        cause = None

    docs = 6000000 if rolled else 0
    size = 12_000_000_000 if rolled else 0
    health = "yellow" if action_failed else "green"

    add_index(name, created, state, state_start, action_name, action_failed,
              retries, info, rolled, "security-lifecycle", policy_seq,
              1, replicas, docs, size, health=health, info_cause=cause)

cat_aliases.append({
    "alias": "security-write",
    "index": "security-000015",
    "filter": "-",
    "routing.index": "-",
    "routing.search": "-",
    "is_write_index": "true"
})


# ============================================================
# METRICS: metrics-lifecycle policy (seq_no=2)
# Rollover: 8M docs OR 2d. Delete: 5d.
# Ingestion: ~5M docs/day, rollover every 2 days.
#
# Indices 000001-000005 deleted (>5d old).
# Only 000006, 000007, 000008 exist.
#
# ISSUE: Write alias metrics-write not transferred during
# rollover of 000007. Alias still points to 000007 (rolled)
# instead of 000008 (current).
# ============================================================

metrics_entries = [
    ("metrics-000006", 10, True, "hot", 10, "transition", False, 0,
     "Evaluating transition conditions", None, 1, 1, 10000000, 40),
    ("metrics-000007", 12, True, "hot", 12, "transition", False, 0,
     "Evaluating transition conditions", None, 1, 1, 10000000, 40),
    ("metrics-000008", 14, False, "hot", 14, "rollover", False, 0,
     "Attempting to rollover index", None, 1, 1, 0, 0),
]

for (name, day, rolled, state, state_day, action, failed, retries,
     info, cause, pri, rep, docs, size_gb) in metrics_entries:
    created = BASE_TIME + day * DAY
    state_start = BASE_TIME + state_day * DAY
    add_index(name, created, state, state_start, action, failed, retries,
              info, rolled, "metrics-lifecycle", 2, pri, rep, docs,
              size_gb * 1_000_000_000, info_cause=cause)

# BUG: alias points to metrics-000007 (rolled) instead of metrics-000008
cat_aliases.append({
    "alias": "metrics-write",
    "index": "metrics-000007",
    "filter": "-",
    "routing.index": "-",
    "routing.search": "-",
    "is_write_index": "true"
})


# ============================================================
# NODE ATTRIBUTES
# Cluster nodes use "temperature" attribute, NOT "temp".
# This is evidence for diagnosing the allocation failure.
# ============================================================

node_attrs = [
    {"node": "data-node-01", "host": "10.0.1.1", "ip": "10.0.1.1",
     "attr": "temperature", "value": "hot"},
    {"node": "data-node-02", "host": "10.0.1.2", "ip": "10.0.1.2",
     "attr": "temperature", "value": "hot"},
    {"node": "data-node-03", "host": "10.0.2.1", "ip": "10.0.2.1",
     "attr": "temperature", "value": "warm"},
    {"node": "data-node-04", "host": "10.0.2.2", "ip": "10.0.2.2",
     "attr": "temperature", "value": "warm"},
    {"node": "data-node-05", "host": "10.0.3.1", "ip": "10.0.3.1",
     "attr": "temperature", "value": "cold"},
]


# ============================================================
# WRITE OUTPUT FILES
# ============================================================

with open("/app/cluster/ism_explain.json", "w") as f:
    json.dump(ism_explain, f, indent=2)

with open("/app/cluster/cat_indices.json", "w") as f:
    json.dump(cat_indices, f, indent=2)

with open("/app/cluster/cat_aliases.json", "w") as f:
    json.dump(cat_aliases, f, indent=2)

with open("/app/cluster/node_attrs.json", "w") as f:
    json.dump(node_attrs, f, indent=2)

print(f"Generated cluster data: {len(ism_explain)} indices in ISM explain")
print(f"  cat_indices: {len(cat_indices)} entries")
print(f"  cat_aliases: {len(cat_aliases)} entries")
print(f"  node_attrs: {len(node_attrs)} entries")
