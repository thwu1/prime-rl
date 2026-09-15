#!/usr/bin/env python3
"""
MySQL HA Failover Analysis Engine - Full Implementation

"""

import json
import sys


def parse_gtid_position(gtid_set):
    """Extract the highest transaction position from a GTID set string.
    Format: UUID:start-end[,UUID:start-end,...]
    """
    if not gtid_set or not gtid_set.strip():
        return 0
    max_pos = 0
    for part in gtid_set.split(","):
        part = part.strip()
        if ":" not in part:
            continue
        range_part = part.split(":")[-1]
        if "-" in range_part:
            end = int(range_part.split("-")[-1])
        else:
            end = int(range_part)
        max_pos = max(max_pos, end)
    return max_pos


class Instance:
    def __init__(self, data):
        self.hostname = data["key"]["host"]
        self.port = data["key"]["port"]
        self.read_only = data["role_info"]["read_only"]
        self.master_host = data["role_info"]["master"]["host"] or ""
        self.master_port = data["role_info"]["master"]["port"] or 0
        self.repl_state = data["replication"]["state"]
        self.lag_sec = data["replication"]["lag_sec"]
        self.sql_delayed = data["replication"]["sql_delayed"]
        self.gtid_executed = data["gtid"]["executed"]
        self.gtid_position = parse_gtid_position(self.gtid_executed)
        self.semi_sync_master_on = data["semi_sync"]["master_on"]
        self.semi_sync_replica_on = data["semi_sync"]["replica_on"]
        self.semi_sync_wait_count = data["semi_sync"]["wait_count"]
        self.semi_sync_timeout_ms = data["semi_sync"]["timeout_ms"]
        self.dc = data["dc"]
        self.reachable = data["status"]["reachable"]
        self.promotion_rule = data["ops"]["promotion_rule"]
        self.downtimed = data["ops"]["downtimed"]

    @property
    def key(self):
        return f"{self.hostname}:{self.port}"

    @property
    def has_master(self):
        return bool(self.master_host)


class OrchestratorNode:
    def __init__(self, data):
        self.hostname = data["host"]
        self.dc = data["dc"]
        self.peers = data["peers"]


def get_replicas(instances, server):
    return [i for i in instances
            if i.master_host == server.hostname and i.master_port == server.port]


def find_masters(instances):
    return [i for i in instances if not i.has_master and not i.read_only]


def find_intermediate_masters(instances):
    result = []
    for inst in instances:
        if inst.has_master:
            if any(i.master_host == inst.hostname and i.master_port == inst.port
                   for i in instances):
                result.append(inst)
    return result


# ---------------------------------------------------------------
# Failure detection
# ---------------------------------------------------------------

def analyze_master(instances, master, config):
    cn = config.get("cluster_name", "unknown")
    replicas = get_replicas(instances, master)

    if not master.reachable:
        return _master_unreachable(instances, master, replicas, cn)
    return _master_reachable(instances, master, replicas, cn, config)


def _master_unreachable(instances, master, replicas, cn):
    if len(replicas) == 0:
        return {"type": "DeadMasterWithoutReplicas", "instance": master.key,
                "actionable": False}

    reachable = [r for r in replicas if r.reachable]
    unreachable = [r for r in replicas if not r.reachable]

    if len(reachable) == 0:
        return {"type": "DeadMasterAndReplicas", "instance": master.key,
                "actionable": False}

    non_delayed = [r for r in reachable if not r.sql_delayed]
    replicating = [r for r in non_delayed if r.repl_state == "running"]
    if replicating:
        return {"type": "UnreachableMaster", "instance": master.key,
                "actionable": False}

    lagging = [r for r in non_delayed if r.repl_state == "lagging"]
    if non_delayed and len(lagging) == len(non_delayed):
        return {"type": "UnreachableMasterWithLaggingReplicas",
                "instance": master.key, "actionable": True}

    if unreachable:
        return {"type": "DeadMasterAndSomeReplicas", "instance": master.key,
                "actionable": True}

    return {"type": "DeadMaster", "instance": master.key, "actionable": True}


def _master_reachable(instances, master, replicas, cn, config):
    if len(replicas) == 0:
        return None

    reachable = [r for r in replicas if r.reachable]
    unreachable = [r for r in replicas if not r.reachable]

    # Semi-sync checks
    if master.semi_sync_master_on:
        connected_ss = [r for r in reachable
                        if r.semi_sync_replica_on and r.repl_state == "running"]
        if len(connected_ss) < master.semi_sync_wait_count:
            if master.semi_sync_timeout_ms >= 30000:
                return {"type": "LockedSemiSyncMaster", "instance": master.key,
                        "actionable": True}
        if len(connected_ss) > master.semi_sync_wait_count:
            if config.get("enforce_semi_sync_count", False):
                return {"type": "MasterWithTooManySemiSyncReplicas",
                        "instance": master.key, "actionable": False}

    if len(reachable) == 0 and unreachable:
        return {"type": "AllMasterReplicasNotReplicatingOrDead",
                "instance": master.key, "actionable": True}

    not_replicating = [r for r in reachable
                       if r.repl_state in ("failed", "stopped")]
    if reachable and len(not_replicating) == len(reachable):
        if unreachable:
            return {"type": "AllMasterReplicasNotReplicatingOrDead",
                    "instance": master.key, "actionable": True}
        return {"type": "AllMasterReplicasNotReplicating",
                "instance": master.key, "actionable": True}

    return None


def analyze_im(instances, im):
    cn = "unknown"
    replicas = get_replicas(instances, im)
    if not im.reachable:
        return _im_unreachable(im, replicas, cn)
    return _im_reachable(im, replicas, cn)


def _im_unreachable(im, replicas, cn):
    reachable = [r for r in replicas if r.reachable]
    unreachable = [r for r in replicas if not r.reachable]

    if len(reachable) == 0:
        if len(replicas) == 1:
            return {"type": "DeadIntermediateMasterWithSingleReplicaFailingToConnect",
                    "instance": im.key, "actionable": False}
        return {"type": "DeadIntermediateMasterAndReplicas",
                "instance": im.key, "actionable": False}

    non_delayed = [r for r in reachable if not r.sql_delayed]
    replicating = [r for r in non_delayed if r.repl_state == "running"]
    if replicating:
        return {"type": "UnreachableIntermediateMaster",
                "instance": im.key, "actionable": False}

    lagging = [r for r in non_delayed if r.repl_state == "lagging"]
    if non_delayed and len(lagging) == len(non_delayed):
        return {"type": "UnreachableIntermediateMasterWithLaggingReplicas",
                "instance": im.key, "actionable": True}

    if unreachable:
        return {"type": "DeadIntermediateMasterAndSomeReplicas",
                "instance": im.key, "actionable": True}

    if len(replicas) == 1:
        return {"type": "DeadIntermediateMasterWithSingleReplica",
                "instance": im.key, "actionable": True}

    return {"type": "DeadIntermediateMaster", "instance": im.key,
            "actionable": True}


def _im_reachable(im, replicas, cn):
    reachable = [r for r in replicas if r.reachable]
    unreachable = [r for r in replicas if not r.reachable]

    if len(reachable) == 0 and unreachable:
        return {"type": "AllIntermediateMasterReplicasFailingToConnectOrDead",
                "instance": im.key, "actionable": True}

    not_replicating = [r for r in reachable
                       if r.repl_state in ("failed", "stopped")]
    if reachable and len(not_replicating) == len(reachable):
        return {"type": "AllIntermediateMasterReplicasNotReplicating",
                "instance": im.key, "actionable": True}

    return None


# ---------------------------------------------------------------
# Recovery decision
# ---------------------------------------------------------------

def should_recover(failure, config, timestamp):
    if not failure["actionable"]:
        return False, "Failure type is not actionable"
    if not config.get("global_recovery", True):
        return False, "Global recoveries disabled"
    if not config.get("auto_recovery", True):
        return False, "Auto-recovery disabled"
    # Check downtime on the failed instance - need to pass downtimed info
    # We pass it via the failure dict
    if failure.get("downtimed", False):
        return False, "Instance is downtimed"
    last_ts = config.get("last_recovery_ts")
    if last_ts is not None:
        elapsed = timestamp - last_ts
        block = config.get("recovery_block_seconds", 3600)
        if elapsed < block:
            return False, f"Anti-flapping: {elapsed:.0f}s since last recovery (block period: {block}s)"
    return True, "All recovery conditions met"


# ---------------------------------------------------------------
# Candidate selection
# ---------------------------------------------------------------

RULE_ORDER = {"prefer": 0, "neutral": 1, "prefer_not": 2, "must_not": 3}


def select_promotion_candidate(instances, failed_server):
    replicas = get_replicas(instances, failed_server)
    candidates = [r for r in replicas
                  if r.reachable and r.promotion_rule != "must_not"]
    if not candidates:
        return None

    def sort_key(s):
        return (
            RULE_ORDER.get(s.promotion_rule, 1),
            0 if s.semi_sync_replica_on else 1,
            -s.gtid_position,
            0 if s.dc == failed_server.dc else 1,
            s.hostname,
        )

    candidates.sort(key=sort_key)
    return candidates[0]


# ---------------------------------------------------------------
# Raft leader
# ---------------------------------------------------------------

def determine_raft_leader(orch_nodes):
    if not orch_nodes:
        return None
    total = len(orch_nodes)
    quorum = (total // 2) + 1
    eligible = []
    for node in orch_nodes:
        reachable_count = 1  # self
        for other in orch_nodes:
            if other.hostname != node.hostname:
                if node.peers.get(other.hostname, False):
                    reachable_count += 1
        if reachable_count >= quorum:
            eligible.append((node, reachable_count))
    if not eligible:
        return None
    eligible.sort(key=lambda x: (-x[1], x[0].hostname))
    return eligible[0][0]


# ---------------------------------------------------------------
# Outage estimation
# ---------------------------------------------------------------

def estimate_outage(failure, candidate, failed_instance):
    if candidate is None:
        return 0.0
    detection = 5.0
    ideal = (candidate.promotion_rule == "prefer"
             and candidate.semi_sync_replica_on)
    promotion = 3.0 if ideal else 10.0
    cross_dc = candidate.dc != failed_instance.dc
    consul_time = 2.0 if cross_dc else 1.0
    haproxy_time = 2.0 if cross_dc else 1.0
    return detection + promotion + consul_time + haproxy_time


# ---------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------

def analyze_topology(topology_path):
    with open(topology_path) as f:
        topo = json.load(f)

    cluster_name = topo["cluster"]["name"]
    timestamp = topo["cluster"]["timestamp"]
    config = topo["cluster"]["config"]

    instances = [Instance(d) for d in topo["instances"]]
    orch_nodes = [OrchestratorNode(d) for d in topo["orchestrator"]["nodes"]]

    # Detect failures
    failures = []
    for master in find_masters(instances):
        f = analyze_master(instances, master, config)
        if f is not None:
            # Carry downtimed info for recovery decision
            f["downtimed"] = master.downtimed
            failures.append(f)

    for im in find_intermediate_masters(instances):
        f = analyze_im(instances, im)
        if f is not None:
            f["downtimed"] = im.downtimed
            failures.append(f)

    report = {
        "cluster_name": cluster_name,
        "failures": [{"type": f["type"], "instance": f["instance"],
                       "actionable": f["actionable"]} for f in failures],
        "recovery_attempted": False,
        "recovery_target_is_master": None,
        "promoted_server": None,
        "raft_leader": None,
        "estimated_outage_seconds": 0.0,
        "recovery_blocked_reason": "",
    }

    if not failures:
        return report

    # Raft leader
    leader = determine_raft_leader(orch_nodes)
    if leader:
        report["raft_leader"] = leader.hostname
    elif len(orch_nodes) > 0:
        report["recovery_blocked_reason"] = "No raft quorum - cannot proceed with recovery"
        return report

    # Select target failure: master-level first
    target = None
    for f in failures:
        if f["actionable"]:
            inst = _find_instance(instances, f["instance"])
            if inst and not inst.has_master:
                target = f
                break
    if target is None:
        for f in failures:
            if f["actionable"]:
                target = f
                break
    if target is None:
        return report

    target_inst = _find_instance(instances, target["instance"])
    is_master = target_inst and not target_inst.has_master

    # Recovery decision
    ok, reason = should_recover(target, config, timestamp)
    if not ok:
        report["recovery_blocked_reason"] = reason
        return report

    # Promote
    candidate = select_promotion_candidate(instances, target_inst)
    report["recovery_attempted"] = True
    report["recovery_target_is_master"] = is_master
    if candidate:
        report["promoted_server"] = candidate.key
    report["estimated_outage_seconds"] = estimate_outage(
        target, candidate, target_inst)

    return report


def _find_instance(instances, key):
    for inst in instances:
        if inst.key == key:
            return inst
    return None


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 analyze.py <topology_json_path>", file=sys.stderr)
        sys.exit(1)
    result = analyze_topology(sys.argv[1])
    print(json.dumps(result, indent=2))
