#!/usr/bin/env python3
"""
Multi-resource cluster scheduler with gang scheduling and anti-affinity.
Implements fair-share and priority scheduling modes.

"""

import json
import sqlite3
from datetime import datetime


def load_state(path="/app/cluster_state.json"):
    with open(path) as f:
        return json.load(f)


def write_output(output, path="/app/schedule_output.json"):
    with open(path, "w") as f:
        json.dump(output, f, indent=2)


def parse_time(ts):
    if ts is None:
        return datetime.min
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def load_anti_affinity(db_path="/app/cluster_config.db"):
    """Load anti-affinity pairs from the cluster configuration database.
    Returns a set of (group_a, group_b) tuples, made bidirectional."""
    conn = sqlite3.connect(db_path)
    cursor = conn.execute("SELECT group_a, group_b FROM anti_affinity")
    rules = set()
    for row in cursor:
        rules.add((row[0], row[1]))
        rules.add((row[1], row[0]))
    conn.close()
    return rules


def load_policy(db_path="/app/cluster_config.db"):
    """Load scheduling policy configuration."""
    conn = sqlite3.connect(db_path)
    cursor = conn.execute("SELECT key, value FROM scheduling_policy")
    policy = {row[0]: row[1] for row in cursor}
    conn.close()
    return policy


def violates_anti_affinity(agent_id, group_id, agent_groups, anti_affinity):
    """Check if placing group_id on agent_id violates any anti-affinity rule."""
    if agent_id not in agent_groups:
        return False
    for other_gid in agent_groups[agent_id]:
        if (group_id, other_gid) in anti_affinity:
            return True
    return False


def find_agent(task, group_id, agents_avail, agent_groups, anti_affinity):
    """Find an agent with enough GPU and memory, respecting anti-affinity.
    Returns agent_id or None. Iterates agents in insertion order."""
    for aid, res in agents_avail.items():
        if res["gpu"] >= task["gpu_slots"] and res["mem"] >= task["mem_mb"]:
            if not violates_anti_affinity(aid, group_id, agent_groups, anti_affinity):
                return aid
    return None


def place_task(task, agent_id, agents_avail, agent_groups, group_id):
    """Place a task on an agent, consuming resources."""
    agents_avail[agent_id]["gpu"] -= task["gpu_slots"]
    agents_avail[agent_id]["mem"] -= task["mem_mb"]
    agent_groups.setdefault(agent_id, set()).add(group_id)


def unplace_task(task, agent_id, agents_avail):
    """Reverse a task placement, returning resources."""
    agents_avail[agent_id]["gpu"] += task["gpu_slots"]
    agents_avail[agent_id]["mem"] += task["mem_mb"]


# =====================================================================
# Fair-share helpers
# =====================================================================

def get_total_weight(states):
    return sum(
        s["weight"] for s in states
        if not s["disabled"] and s["offered"] < s["slot_demand"]
    )


def account_for_preoffers(preoffers_val, offer):
    if preoffers_val > 0:
        if preoffers_val == offer:
            return 0, 0
        elif preoffers_val > offer:
            return preoffers_val - offer, 0
        else:
            return 0, offer - preoffers_val
    return preoffers_val, offer


def smallest_pending_gpu(gs):
    if not gs["pending_tasks"]:
        return None
    return min(t["gpu_slots"] for t in gs["pending_tasks"])


def progressive_fill(states, capacity):
    """Progressive filling algorithm for weighted max-min fair-share."""
    preoffers = {}
    for s in states:
        if s["presubscribed"] > 0:
            s["offered"] = s["presubscribed"]
            preoffers[s["group_id"]] = s["presubscribed"]
            capacity -= s["presubscribed"]

    states.sort(key=lambda s: (s["slot_demand"], s["registered_time"]))
    by_time = sorted(states, key=lambda s: s["registered_time"], reverse=True)

    total_weight = get_total_weight(states)
    n_left = len(
        [s for s in states if not s["disabled"] and s["offered"] < s["slot_demand"]]
    )

    while n_left > 0:
        progress = False
        start_cap = capacity

        for s in states:
            if s["disabled"] or s["offered"] == s["slot_demand"]:
                continue
            if total_weight == 0:
                break

            fair = max(1, int(start_cap * s["weight"] / total_weight))
            progress = True
            offer = min(fair, capacity, s["slot_demand"] - s["offered"])

            gid = s["group_id"]
            pre = preoffers.get(gid, 0)
            pre, offer = account_for_preoffers(pre, offer)
            preoffers[gid] = pre

            s["offered"] += offer
            capacity -= offer

            if s["offered"] == s["slot_demand"]:
                n_left -= 1
                total_weight = get_total_weight(states)

        if capacity == 0:
            adjusted = False
            for s in by_time:
                sp = smallest_pending_gpu(s)
                if (
                    not s["disabled"]
                    and s["offered"] != s["slot_demand"]
                    and sp is not None
                    and sp > s["offered"]
                ):
                    capacity += s["offered"]
                    s["offered"] = 0
                    s["disabled"] = True
                    adjusted = True
                    n_left -= 1
                    total_weight = get_total_weight(states)
                    break
            if not adjusted:
                return
        elif not progress:
            return


# =====================================================================
# Fair-share scheduler
# =====================================================================

def fair_share_schedule(state, anti_affinity):
    agents = state["agents"]
    groups_cfg = {g["group_id"]: g for g in state["groups"]}
    tasks = state["tasks"]

    agents_avail = {
        a["agent_id"]: {"gpu": a["gpu_slots"], "mem": a["mem_mb"]}
        for a in agents
    }
    agent_groups = {}

    capacity = sum(a["gpu_slots"] for a in agents)

    # Build group states
    gstates = {}
    for task in tasks:
        gid = task["group_id"]
        if gid not in gstates:
            gcfg = groups_cfg[gid]
            gstates[gid] = {
                "group_id": gid,
                "weight": gcfg["weight"],
                "max_slots": gcfg.get("max_slots"),
                "gang": gcfg.get("gang", False),
                "registered_time": parse_time(gcfg["registered_time"]),
                "disabled": False,
                "slot_demand": 0,
                "active_slots": 0,
                "presubscribed": 0,
                "offered": 0,
                "pending_tasks": [],
                "allocated_tasks": [],
            }
        gs = gstates[gid]

        if task["allocation_id"] is not None:
            gs["allocated_tasks"].append(task)
            gs["active_slots"] += task["gpu_slots"]
            if not task["preemptible"]:
                gs["presubscribed"] += task["gpu_slots"]
            aid = task.get("allocated_agent_id")
            if aid and aid in agents_avail:
                agents_avail[aid]["gpu"] -= task["gpu_slots"]
                agents_avail[aid]["mem"] -= task["mem_mb"]
                agent_groups.setdefault(aid, set()).add(gid)
        else:
            gs["pending_tasks"].append(task)

    for gs in gstates.values():
        gs["pending_tasks"].sort(
            key=lambda t: (t["position"], parse_time(t["submitted_time"]))
        )

    # Slot demand with max_slots cap
    for gs in gstates.values():
        raw = sum(t["gpu_slots"] for t in gs["pending_tasks"]) + gs["active_slots"]
        if gs["max_slots"] is not None:
            raw = min(raw, gs["max_slots"])
        gs["slot_demand"] = raw

    slist = list(gstates.values())

    # Phase 2: Progressive filling
    progressive_fill(slist, capacity)

    # Phase 3: Gang scheduling check
    gang_reclaimed = 0
    for gs in slist:
        if gs["gang"] and not gs["disabled"]:
            pending_demand = sum(t["gpu_slots"] for t in gs["pending_tasks"])
            avail_in_offer = gs["offered"] - gs["active_slots"]
            if pending_demand > 0 and avail_in_offer < pending_demand:
                reclaim = gs["offered"] - gs["presubscribed"]
                gang_reclaimed += reclaim
                gs["offered"] = gs["presubscribed"]
                gs["disabled"] = True

    # Redistribute reclaimed gang slots
    if gang_reclaimed > 0:
        beneficiaries = [
            gs for gs in slist
            if not gs["disabled"] and gs["offered"] < gs["slot_demand"]
        ]
        remaining = gang_reclaimed
        for gs in sorted(beneficiaries, key=lambda g: g["slot_demand"]):
            if remaining <= 0:
                break
            extra = min(gs["slot_demand"] - gs["offered"], remaining)
            gs["offered"] += extra
            remaining -= extra

    # Phase 4: Release first, then allocate (freed resources must be
    # available for allocation in the same scheduling round).
    to_allocate = {}
    to_release = []

    # Phase 4a: Releases
    for gs in slist:
        if gs["active_slots"] > gs["offered"]:
            for task in sorted(
                gs["allocated_tasks"], key=lambda t: -t["position"]
            ):
                if task["preemptible"]:
                    to_release.append(task["allocation_id"])
                    gs["active_slots"] -= task["gpu_slots"]
                    aid = task.get("allocated_agent_id")
                    if aid and aid in agents_avail:
                        unplace_task(task, aid, agents_avail)
                    if gs["active_slots"] <= gs["offered"]:
                        break

    # Phase 4b: Allocations
    for gs in slist:
        if gs["active_slots"] < gs["offered"] and not gs["disabled"]:
            remaining_offer = gs["offered"] - gs["active_slots"]

            if gs["gang"]:
                # All-or-nothing: try placing ALL pending tasks
                placements = []
                can_place_all = True
                for task in gs["pending_tasks"]:
                    if task["gpu_slots"] > remaining_offer:
                        can_place_all = False
                        break
                    aid = find_agent(
                        task, gs["group_id"], agents_avail, agent_groups,
                        anti_affinity,
                    )
                    if aid is None:
                        can_place_all = False
                        break
                    placements.append((task, aid))
                    place_task(task, aid, agents_avail, agent_groups, gs["group_id"])
                    remaining_offer -= task["gpu_slots"]

                if can_place_all:
                    for task, aid in placements:
                        to_allocate[task["task_id"]] = aid
                else:
                    # Roll back all placements for this gang group
                    for task, aid in placements:
                        unplace_task(task, aid, agents_avail)
            else:
                for task in gs["pending_tasks"]:
                    if task["gpu_slots"] <= remaining_offer:
                        aid = find_agent(
                            task, gs["group_id"], agents_avail, agent_groups,
                            anti_affinity,
                        )
                        if aid:
                            to_allocate[task["task_id"]] = aid
                            place_task(
                                task, aid, agents_avail, agent_groups,
                                gs["group_id"],
                            )
                            remaining_offer -= task["gpu_slots"]

    group_offers = {gs["group_id"]: gs["offered"] for gs in slist}
    return {
        "to_allocate": to_allocate,
        "to_release": to_release,
        "group_offers": group_offers,
    }


# =====================================================================
# Priority scheduler
# =====================================================================

def priority_schedule(state, anti_affinity):
    agents = state["agents"]
    groups_cfg = {g["group_id"]: g for g in state["groups"]}
    tasks = state["tasks"]
    preemption_enabled = state.get("preemption_enabled", False)

    agents_avail = {
        a["agent_id"]: {"gpu": a["gpu_slots"], "mem": a["mem_mb"]}
        for a in agents
    }
    agent_groups = {}

    # Account for running tasks
    scheduled_by_priority = {}
    for t in tasks:
        if t["allocation_id"] is not None:
            aid = t.get("allocated_agent_id")
            if aid and aid in agents_avail:
                agents_avail[aid]["gpu"] -= t["gpu_slots"]
                agents_avail[aid]["mem"] -= t["mem_mb"]
                agent_groups.setdefault(aid, set()).add(t["group_id"])
            pri = groups_cfg[t["group_id"]]["priority"]
            if pri is None:
                pri = 50
            scheduled_by_priority.setdefault(pri, []).append(t)

    # Sort scheduled tasks by position within each priority
    for p in scheduled_by_priority:
        scheduled_by_priority[p].sort(
            key=lambda t: (t["position"], parse_time(t["submitted_time"]))
        )

    # Group pending by priority
    pending_by_priority = {}
    for t in tasks:
        if t["allocation_id"] is None:
            pri = groups_cfg[t["group_id"]]["priority"]
            if pri is None:
                pri = 50
            pending_by_priority.setdefault(pri, []).append(t)

    for p in pending_by_priority:
        pending_by_priority[p].sort(
            key=lambda t: (t["position"], parse_time(t["submitted_time"]))
        )

    all_priorities = sorted(
        set(list(pending_by_priority.keys()) + list(scheduled_by_priority.keys()))
    )

    to_allocate = {}
    to_release = set()
    backfilling = False
    skipped_tasks = []

    for priority in all_priorities:
        pending = pending_by_priority.get(priority, [])
        if not pending:
            continue

        placed_this_round = []
        unsuccessful = []

        for task in pending:
            gid = task["group_id"]
            aid = find_agent(task, gid, agents_avail, agent_groups, anti_affinity)
            if aid:
                place_task(task, aid, agents_avail, agent_groups, gid)
                placed_this_round.append((task, aid))
            else:
                unsuccessful.append(task)

        # Commit decision
        if len(to_release) == 0:
            if not backfilling:
                for task, aid in placed_this_round:
                    to_allocate[task["task_id"]] = aid
            elif preemption_enabled:
                for task, aid in placed_this_round:
                    if task["preemptible"]:
                        to_allocate[task["task_id"]] = aid
                    else:
                        unplace_task(task, aid, agents_avail)
            else:
                for task, aid in placed_this_round:
                    unplace_task(task, aid, agents_avail)
        else:
            for task, aid in placed_this_round:
                unplace_task(task, aid, agents_avail)

        if unsuccessful:
            backfilling = True

        # Preemption for unsuccessful tasks
        if preemption_enabled:
            for task in unsuccessful:
                placed = try_preempt_and_place(
                    task, priority, groups_cfg, scheduled_by_priority,
                    to_release, agents_avail, agent_groups, anti_affinity,
                    to_allocate,
                )
                if not placed:
                    skipped_tasks.append(task)
        else:
            skipped_tasks.extend(unsuccessful)

    # Backfilling: try to place skipped preemptible tasks
    for task in skipped_tasks:
        if task["preemptible"]:
            gid = task["group_id"]
            aid = find_agent(task, gid, agents_avail, agent_groups, anti_affinity)
            if aid:
                to_allocate[task["task_id"]] = aid
                place_task(task, aid, agents_avail, agent_groups, gid)

    return {
        "to_allocate": to_allocate,
        "to_release": list(to_release),
        "group_offers": {},
    }


def try_preempt_and_place(
    task, task_pri, groups_cfg, scheduled_by_priority,
    to_release, agents_avail, agent_groups, anti_affinity, to_allocate,
):
    """Try to preempt lower-priority tasks to make room for task."""
    task_gid = task["group_id"]
    task_pos = task["position"]

    # Find preemption candidates
    candidates = []
    for pri, sched_list in scheduled_by_priority.items():
        for st in sched_list:
            if st["allocation_id"] in to_release:
                continue
            if not st["preemptible"]:
                continue
            st_pri = groups_cfg[st["group_id"]]["priority"]
            if st_pri is None:
                st_pri = 50
            if st_pri > task_pri:
                candidates.append(st)
            elif st_pri == task_pri and st["position"] > task_pos:
                candidates.append(st)

    # Sort: lowest priority first (highest number), then highest position
    candidates.sort(
        key=lambda t: (
            -(groups_cfg[t["group_id"]]["priority"] or 50),
            -t["position"],
        )
    )

    # Simulate preemptions one at a time
    preempted = []
    for cand in candidates:
        aid = cand.get("allocated_agent_id")
        if aid and aid in agents_avail:
            preempted.append(cand)
            agents_avail[aid]["gpu"] += cand["gpu_slots"]
            agents_avail[aid]["mem"] += cand["mem_mb"]

            # Check if task can now be placed
            target_aid = find_agent(
                task, task_gid, agents_avail, agent_groups, anti_affinity,
            )
            if target_aid:
                # Commit all preemptions
                for p in preempted:
                    to_release.add(p["allocation_id"])
                to_allocate[task["task_id"]] = target_aid
                place_task(task, target_aid, agents_avail, agent_groups, task_gid)
                return True

    # Roll back all simulated preemptions
    for cand in preempted:
        aid = cand.get("allocated_agent_id")
        if aid and aid in agents_avail:
            agents_avail[aid]["gpu"] -= cand["gpu_slots"]
            agents_avail[aid]["mem"] -= cand["mem_mb"]

    return False


# =====================================================================
# Main
# =====================================================================

def schedule(state):
    """Main scheduling entry point."""
    anti_affinity = load_anti_affinity()
    scheduler_type = state["scheduler_type"]
    if scheduler_type == "fair_share":
        return fair_share_schedule(state, anti_affinity)
    elif scheduler_type == "priority":
        return priority_schedule(state, anti_affinity)
    else:
        raise ValueError(f"Unknown scheduler_type: {scheduler_type}")


def main():
    state = load_state()
    output = schedule(state)
    write_output(output)


if __name__ == "__main__":
    main()
