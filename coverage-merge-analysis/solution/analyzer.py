#!/usr/bin/env python3
"""
Coverage database merge and verification plan analysis tool.
Reads normalized SQLite coverage databases and YAML verification plan.

"""

import json
import sqlite3
import glob
import os
import itertools
import yaml

DATA_DIR = "/data"
DIR_MAP = {0: "0to1", 1: "1to0"}


def load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)


def read_db(db_path):
    """Read a single normalized coverage database and return structured data."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    data = {}

    # Check run status
    cur.execute("SELECT status FROM run_metadata")
    row = cur.fetchone()
    data["status"] = row["status"]

    # Line coverage
    cur.execute("SELECT line_no, hit FROM line_hits")
    rows = cur.fetchall()
    data["line"] = {
        "total": len(rows),
        "hit": {r["line_no"] for r in rows if r["hit"]},
    }

    # Branch coverage
    cur.execute("SELECT branch_id, hit FROM branch_hits")
    rows = cur.fetchall()
    data["branch"] = {
        "total": [r["branch_id"] for r in rows],
        "hit": {r["branch_id"] for r in rows if r["hit"]},
    }

    # Toggle coverage — decode integer direction to string
    cur.execute(
        "SELECT signal_name, bit_idx, direction, hit FROM toggle_hits")
    rows = cur.fetchall()
    data["toggle"] = {
        "total": [
            f"{r['signal_name']}[{r['bit_idx']}]_{DIR_MAP[r['direction']]}"
            for r in rows
        ],
        "hit": {
            f"{r['signal_name']}[{r['bit_idx']}]_{DIR_MAP[r['direction']]}"
            for r in rows if r["hit"]
        },
    }

    # Covergroup definitions
    cur.execute("SELECT cg_id, cg_name FROM cg_inst")
    cg_map = {r["cg_id"]: r["cg_name"] for r in cur.fetchall()}

    # Coverpoint/cross definitions
    cur.execute(
        "SELECT cp_id, cg_id, cp_name, is_cross, threshold FROM cp_defs")
    cp_defs = {}
    for r in cur.fetchall():
        cp_defs[r["cp_id"]] = {
            "cg_id": r["cg_id"],
            "cg_name": cg_map[r["cg_id"]],
            "cp_name": r["cp_name"],
            "is_cross": bool(r["is_cross"]),
            "threshold": r["threshold"],
        }

    # Bin definitions (only for coverpoints, not crosses)
    cur.execute("SELECT bin_id, cp_id, bin_label FROM bin_defs")
    bin_map = {}
    cp_bins = {}
    for r in cur.fetchall():
        bin_map[r["bin_id"]] = (r["cp_id"], r["bin_label"])
        if r["cp_id"] not in cp_bins:
            cp_bins[r["cp_id"]] = []
        cp_bins[r["cp_id"]].append((r["bin_id"], r["bin_label"]))

    # Cross references — resolve component coverpoints
    cur.execute(
        "SELECT cross_cp_id, member_cp_id, axis_order "
        "FROM cross_refs ORDER BY cross_cp_id, axis_order")
    cross_components = {}
    for r in cur.fetchall():
        if r["cross_cp_id"] not in cross_components:
            cross_components[r["cross_cp_id"]] = []
        cross_components[r["cross_cp_id"]].append(r["member_cp_id"])

    # Build coverpoints data structure
    coverpoints_defs = {}
    for cp_id, info in cp_defs.items():
        if not info["is_cross"]:
            key = (info["cg_name"], info["cp_name"])
            bins = [label for _, label in cp_bins.get(cp_id, [])]
            coverpoints_defs[key] = {
                "bins": bins,
                "at_least": info["threshold"],
            }

    # Functional coverage hits for coverpoint bins
    cur.execute("SELECT bin_id, hit_count FROM func_hits")
    func_hits = {}
    for r in cur.fetchall():
        if r["bin_id"] in bin_map:
            cp_id, label = bin_map[r["bin_id"]]
            key = (cp_defs[cp_id]["cg_name"], cp_defs[cp_id]["cp_name"])
            if key not in func_hits:
                func_hits[key] = {}
            func_hits[key][label] = r["hit_count"]

    # Build crosses data structure
    crosses_defs = {}
    for cp_id, info in cp_defs.items():
        if info["is_cross"]:
            key = (info["cg_name"], info["cp_name"])
            component_names = []
            for member_id in cross_components.get(cp_id, []):
                component_names.append(cp_defs[member_id]["cp_name"])
            crosses_defs[key] = {
                "components": component_names,
                "at_least": info["threshold"],
            }

    # Cross bin hits
    cur.execute("SELECT cp_id, bin_label, hit_count FROM cross_bin_hits")
    cx_hits = {}
    for r in cur.fetchall():
        if r["cp_id"] in cp_defs:
            key = (cp_defs[r["cp_id"]]["cg_name"],
                   cp_defs[r["cp_id"]]["cp_name"])
            if key not in cx_hits:
                cx_hits[key] = {}
            cx_hits[key][r["bin_label"]] = r["hit_count"]

    data["coverpoints"] = {"defs": coverpoints_defs, "hits": func_hits}
    data["crosses"] = {"defs": crosses_defs, "hits": cx_hits}

    # FSM states — join defs with hits
    cur.execute(
        "SELECT s.state_id, s.fsm_name, s.state_name, h.hit "
        "FROM fsm_state_defs s JOIN fsm_state_hits h "
        "ON s.state_id = h.state_id")
    fsm_states = {}
    for r in cur.fetchall():
        if r["fsm_name"] not in fsm_states:
            fsm_states[r["fsm_name"]] = {"all": [], "hit": set()}
        fsm_states[r["fsm_name"]]["all"].append(r["state_name"])
        if r["hit"]:
            fsm_states[r["fsm_name"]]["hit"].add(r["state_name"])

    # FSM transitions — join defs with state names and hits
    cur.execute("""
        SELECT t.trans_id, t.fsm_name,
               s1.state_name AS src, s2.state_name AS dst, h.hit
        FROM fsm_trans_defs t
        JOIN fsm_state_defs s1 ON t.src_state_id = s1.state_id
        JOIN fsm_state_defs s2 ON t.dst_state_id = s2.state_id
        JOIN fsm_trans_hits h ON t.trans_id = h.trans_id
    """)
    fsm_transitions = {}
    for r in cur.fetchall():
        if r["fsm_name"] not in fsm_transitions:
            fsm_transitions[r["fsm_name"]] = {"all": [], "hit": set()}
        trans_str = f"{r['src']}->{r['dst']}"
        fsm_transitions[r["fsm_name"]]["all"].append(trans_str)
        if r["hit"]:
            fsm_transitions[r["fsm_name"]]["hit"].add(trans_str)

    data["fsm_states"] = fsm_states
    data["fsm_transitions"] = fsm_transitions

    # Exclusion rules from the database
    cur.execute(
        "SELECT category, target_json, cascade FROM exclusion_rules")
    data["exclusions"] = [
        {"category": r["category"],
         "target": json.loads(r["target_json"]),
         "cascade": bool(r["cascade"])}
        for r in cur.fetchall()
    ]

    conn.close()
    return data


def merge_runs(db_files):
    """Load and merge all completed coverage databases with union semantics."""
    runs = []
    exclusions = None

    for f in sorted(db_files):
        data = read_db(f)
        if data["status"] != "PASSED":
            continue
        runs.append(data)
        if exclusions is None:
            exclusions = data["exclusions"]

    merged = {
        "line": {"total": None, "hit": set()},
        "branch": {"total": None, "hit": set()},
        "toggle": {"total": None, "hit": set()},
        "coverpoints": {"defs": {}, "hits": {}},
        "crosses": {"defs": {}, "hits": {}},
        "fsm_states": {},
        "fsm_transitions": {},
    }

    for run in runs:
        merged["line"]["total"] = run["line"]["total"]
        merged["line"]["hit"].update(run["line"]["hit"])

        if merged["branch"]["total"] is None:
            merged["branch"]["total"] = list(run["branch"]["total"])
        merged["branch"]["hit"].update(run["branch"]["hit"])

        if merged["toggle"]["total"] is None:
            merged["toggle"]["total"] = list(run["toggle"]["total"])
        merged["toggle"]["hit"].update(run["toggle"]["hit"])

        merged["coverpoints"]["defs"].update(run["coverpoints"]["defs"])
        for key, hits in run["coverpoints"]["hits"].items():
            if key not in merged["coverpoints"]["hits"]:
                merged["coverpoints"]["hits"][key] = {}
            for bin_name, count in hits.items():
                merged["coverpoints"]["hits"][key][bin_name] = \
                    merged["coverpoints"]["hits"][key].get(bin_name, 0) + count

        merged["crosses"]["defs"].update(run["crosses"]["defs"])
        for key, hits in run["crosses"]["hits"].items():
            if key not in merged["crosses"]["hits"]:
                merged["crosses"]["hits"][key] = {}
            for bin_name, count in hits.items():
                merged["crosses"]["hits"][key][bin_name] = \
                    merged["crosses"]["hits"][key].get(bin_name, 0) + count

        for fsm_name, state_data in run["fsm_states"].items():
            if fsm_name not in merged["fsm_states"]:
                merged["fsm_states"][fsm_name] = {
                    "all": list(state_data["all"]), "hit": set()}
            merged["fsm_states"][fsm_name]["hit"].update(state_data["hit"])

        for fsm_name, trans_data in run["fsm_transitions"].items():
            if fsm_name not in merged["fsm_transitions"]:
                merged["fsm_transitions"][fsm_name] = {
                    "all": list(trans_data["all"]), "hit": set()}
            merged["fsm_transitions"][fsm_name]["hit"].update(
                trans_data["hit"])

    return merged, exclusions or []


def apply_exclusions(merged, exclusions):
    """Apply coverage exclusions to merged data."""
    for excl in exclusions:
        cat = excl["category"]
        target = excl["target"]

        if cat == 0:  # toggle exclusion
            sig = target["signal"]
            bit = target["bit"]
            dir_str = DIR_MAP[target["dir"]]
            toggle_id = f"{sig}[{bit}]_{dir_str}"
            if toggle_id in merged["toggle"]["total"]:
                merged["toggle"]["total"].remove(toggle_id)
            merged["toggle"]["hit"].discard(toggle_id)

        elif cat == 1:  # cross_bin exclusion
            cg = target["cg"]
            cross = target["cross"]
            bin_name = target["bin"]
            key = (cg, cross)
            if key in merged["crosses"]["defs"]:
                merged["crosses"]["defs"][key].setdefault(
                    "excluded_bins", set()).add(bin_name)
                merged["crosses"]["hits"].get(key, {}).pop(bin_name, None)

        elif cat == 2:  # fsm_state exclusion
            fsm_name = target["fsm"]
            state = target["state"]
            cascade = excl["cascade"]

            if fsm_name in merged["fsm_states"]:
                states = merged["fsm_states"][fsm_name]
                if state in states["all"]:
                    states["all"].remove(state)
                states["hit"].discard(state)

                if cascade and fsm_name in merged["fsm_transitions"]:
                    trans = merged["fsm_transitions"][fsm_name]
                    to_remove = [
                        t for t in trans["all"]
                        if t.startswith(f"{state}->")
                        or t.endswith(f"->{state}")
                    ]
                    for t in to_remove:
                        trans["all"].remove(t)
                        trans["hit"].discard(t)


def compute_metrics(merged):
    """Compute all coverage metrics."""
    metrics = {}

    # Line coverage
    line_total = merged["line"]["total"]
    all_lines = set(range(1, line_total + 1))
    covered_lines = merged["line"]["hit"] & all_lines
    uncovered_lines = all_lines - covered_lines
    metrics["line"] = {
        "coverage_pct": len(covered_lines) / len(all_lines) * 100
        if all_lines else 0,
        "covered_count": len(covered_lines),
        "total_count": len(all_lines),
        "uncovered_items": sorted(uncovered_lines),
    }

    # Branch coverage
    all_branches = set(merged["branch"]["total"])
    hit_branches = merged["branch"]["hit"] & all_branches
    uncovered_branches = all_branches - hit_branches
    metrics["branch"] = {
        "coverage_pct": len(hit_branches) / len(all_branches) * 100
        if all_branches else 0,
        "covered_count": len(hit_branches),
        "total_count": len(all_branches),
        "uncovered_items": sorted(uncovered_branches),
    }

    # Toggle coverage
    all_toggles = set(merged["toggle"]["total"])
    hit_toggles = merged["toggle"]["hit"] & all_toggles
    uncovered_toggles = all_toggles - hit_toggles
    metrics["toggle"] = {
        "coverage_pct": len(hit_toggles) / len(all_toggles) * 100
        if all_toggles else 0,
        "covered_count": len(hit_toggles),
        "total_count": len(all_toggles),
        "uncovered_items": sorted(uncovered_toggles),
    }

    # Organize coverpoints by covergroup
    covergroups = {}
    for (cg, cp), cp_def in merged["coverpoints"]["defs"].items():
        if cg not in covergroups:
            covergroups[cg] = {"coverpoints": {}, "crosses": {}}
        covergroups[cg]["coverpoints"][cp] = {
            "bins": cp_def["bins"],
            "at_least": cp_def["at_least"],
            "hits": merged["coverpoints"]["hits"].get((cg, cp), {}),
        }

    for (cg, cx), cx_def in merged["crosses"]["defs"].items():
        if cg not in covergroups:
            covergroups[cg] = {"coverpoints": {}, "crosses": {}}
        covergroups[cg]["crosses"][cx] = {
            "components": cx_def["components"],
            "at_least": cx_def["at_least"],
            "hits": merged["crosses"]["hits"].get((cg, cx), {}),
            "excluded_bins": cx_def.get("excluded_bins", set()),
        }

    # Compute covergroup metrics
    covergroups_detail = {}
    for cg_name, cg_data in covergroups.items():
        components = {}
        component_pcts = []

        for cp_name, cp_data in cg_data["coverpoints"].items():
            bins = cp_data["bins"]
            at_least = cp_data["at_least"]
            hits = cp_data["hits"]
            covered = sum(1 for b in bins if hits.get(b, 0) >= at_least)
            total = len(bins)
            pct = covered / total * 100 if total else 0
            components[cp_name] = {
                "coverage_pct": pct,
                "covered_count": covered,
                "total_count": total,
            }
            component_pcts.append(pct)

        for cx_name, cx_data in cg_data["crosses"].items():
            at_least = cx_data["at_least"]
            hits = cx_data["hits"]
            excluded = cx_data["excluded_bins"]

            cp_names = cx_data["components"]
            bin_lists = [
                cg_data["coverpoints"][cp]["bins"] for cp in cp_names]
            all_cross_bins = set()
            for combo in itertools.product(*bin_lists):
                all_cross_bins.add(":".join(combo))
            all_cross_bins -= excluded

            covered_bins = {
                b for b in all_cross_bins if hits.get(b, 0) >= at_least}
            total = len(all_cross_bins)
            covered = len(covered_bins)
            pct = covered / total * 100 if total else 0
            components[cx_name] = {
                "coverage_pct": pct,
                "covered_count": covered,
                "total_count": total,
            }
            component_pcts.append(pct)

        cg_pct = (sum(component_pcts) / len(component_pcts)
                  if component_pcts else 0)
        covergroups_detail[cg_name] = {
            "coverage_pct": cg_pct,
            "components": components,
        }

    metrics["covergroups"] = covergroups_detail

    # FSM coverage
    for fsm_name in merged["fsm_states"]:
        all_states = set(merged["fsm_states"][fsm_name]["all"])
        hit_states = merged["fsm_states"][fsm_name]["hit"] & all_states
        uncovered_states = all_states - hit_states
        metrics["fsm_state"] = {
            "coverage_pct": len(hit_states) / len(all_states) * 100
            if all_states else 0,
            "covered_count": len(hit_states),
            "total_count": len(all_states),
            "uncovered_items": sorted(uncovered_states),
        }

        all_transitions = set(merged["fsm_transitions"][fsm_name]["all"])
        hit_transitions = (
            merged["fsm_transitions"][fsm_name]["hit"] & all_transitions)
        uncovered_transitions = all_transitions - hit_transitions
        metrics["fsm_transition"] = {
            "coverage_pct": len(hit_transitions) / len(all_transitions) * 100
            if all_transitions else 0,
            "covered_count": len(hit_transitions),
            "total_count": len(all_transitions),
            "uncovered_items": sorted(uncovered_transitions),
        }

    return metrics


def resolve_leaf_metric(leaf, metrics):
    """Get coverage percentage for a vplan leaf node."""
    mt = leaf["metric_type"]
    if mt == "code":
        return metrics[leaf["metric_name"]]["coverage_pct"]
    elif mt == "functional":
        return metrics["covergroups"][leaf["covergroup"]]["coverage_pct"]
    elif mt == "fsm":
        return metrics[f"fsm_{leaf['metric_name']}"]["coverage_pct"]
    return 0.0


def build_hierarchy(node, metrics):
    """Build hierarchy with weighted roll-up."""
    flat = {}

    def recurse(n):
        if "children" not in n or not n["children"]:
            pct = resolve_leaf_metric(n, metrics)
            flat[n["name"]] = {
                "coverage_pct": pct,
                "weight": n.get("weight", 1),
                "children": [],
            }
            return pct

        child_pcts = {}
        for child in n["children"]:
            child_pcts[child["name"]] = recurse(child)

        total_weight = sum(
            child.get("weight", 1) for child in n["children"])
        weighted_sum = sum(
            child_pcts[child["name"]] * child.get("weight", 1)
            for child in n["children"])
        node_pct = weighted_sum / total_weight if total_weight else 0

        flat[n["name"]] = {
            "coverage_pct": node_pct,
            "weight": n.get("weight", 1),
            "children": [child["name"] for child in n["children"]],
        }
        return node_pct

    recurse(node)
    return flat


def build_report(metrics, vplan, hierarchy):
    """Build the final report JSON."""
    leaf_metrics = {}

    def collect_leaves(node):
        if "children" not in node or not node["children"]:
            name = node["name"]
            mt = node["metric_type"]
            goal = node["goal_pct"]

            if mt == "code":
                m = metrics[node["metric_name"]]
            elif mt == "functional":
                cg = node["covergroup"]
                cg_data = metrics["covergroups"][cg]
                m = {
                    "coverage_pct": cg_data["coverage_pct"],
                    "covered_count": sum(
                        c["covered_count"]
                        for c in cg_data["components"].values()),
                    "total_count": sum(
                        c["total_count"]
                        for c in cg_data["components"].values()),
                    "uncovered_items": [],
                }
            elif mt == "fsm":
                m = metrics[f"fsm_{node['metric_name']}"]
            else:
                return

            leaf_metrics[name] = {
                "coverage_pct": m["coverage_pct"],
                "goal_pct": goal,
                "goal_met": m["coverage_pct"] >= goal,
                "covered_count": m["covered_count"],
                "total_count": m["total_count"],
                "uncovered_items": m.get("uncovered_items", []),
            }
        else:
            for child in node["children"]:
                collect_leaves(child)

    collect_leaves(vplan)

    total_goals = len(leaf_metrics)
    goals_met = sum(1 for lm in leaf_metrics.values() if lm["goal_met"])

    report = {
        "summary": {
            "overall_coverage_pct": hierarchy[vplan["name"]][
                "coverage_pct"],
            "total_goals": total_goals,
            "goals_met": goals_met,
            "goals_failed": total_goals - goals_met,
        },
        "metrics": leaf_metrics,
        "covergroups": metrics["covergroups"],
        "hierarchy": hierarchy,
    }

    failed = []
    for name, lm in leaf_metrics.items():
        if not lm["goal_met"]:
            failed.append({
                "metric": name,
                "achieved_pct": lm["coverage_pct"],
                "goal_pct": lm["goal_pct"],
                "gap_pct": lm["goal_pct"] - lm["coverage_pct"],
            })
    report["failed_goals"] = failed

    return report


def main():
    db_dir = os.path.join(DATA_DIR, "coverage_dbs")
    db_files = sorted(glob.glob(os.path.join(db_dir, "run_*.db")))

    vplan = load_yaml(os.path.join(DATA_DIR, "vplan.yaml"))

    merged, exclusions = merge_runs(db_files)
    apply_exclusions(merged, exclusions)

    metrics = compute_metrics(merged)
    hierarchy = build_hierarchy(vplan, metrics)
    report = build_report(metrics, vplan, hierarchy)

    with open("/app/coverage_report.json", "w") as f:
        json.dump(report, f, indent=2,
                  default=lambda x: sorted(list(x))
                  if isinstance(x, set) else x)

    print(f"Report written to /app/coverage_report.json")
    print(f"Overall coverage: "
          f"{report['summary']['overall_coverage_pct']:.2f}%")
    print(f"Goals met: {report['summary']['goals_met']}"
          f"/{report['summary']['total_goals']}")


if __name__ == "__main__":
    main()
