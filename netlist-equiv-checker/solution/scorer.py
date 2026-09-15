#!/usr/bin/env python3
"""ISPD 2026 Contest Scoring Pipeline — Solution."""

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, "/app/tools")
from parse_log import parse_log

DESIGNS = ["aes_cipher_top", "jpeg_encoder"]
TEAMS = ["team_alpha", "team_beta", "team_gamma", "team_delta"]
EQUIV_CELLS = "/app/data/equiv_cells.csv"
EQUIV_CHECKER = "/app/tools/equiv_check.py"


def extract_displacement(log_path):
    """Extract avg_displacement from log (not parsed by parse_log.py)."""
    with open(log_path) as f:
        for line in f:
            m = re.search(r"avg_displacement:\s*([\d.]+)", line)
            if m:
                return float(m.group(1))
    return 0.0


def check_equivalence(pre_dir, post_dir):
    """Run equiv_check.py and return True if EQUIVALENT."""
    result = subprocess.run(
        [
            "python3", EQUIV_CHECKER,
            "--pre_opt", pre_dir,
            "--post_opt", post_dir,
            "--equiv_cells", EQUIV_CELLS,
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    return result.returncode == 0


def compute_design_score(baseline_metrics, baseline_disp,
                         team_metrics, team_disp,
                         is_equivalent, weights):
    """Compute Design Score for one design."""
    bm = baseline_metrics
    tm = team_metrics
    W = weights

    # Hard constraints
    if tm.get("placement_legal") == 0:
        return 0.0
    if not is_equivalent:
        return 0.0

    # PPA improvement
    tns_base = abs(bm["tns"]) if bm["tns"] is not None else 0
    tns_cont = abs(tm["tns"]) if tm["tns"] is not None else 0
    s_tns = (tns_base - tns_cont) / tns_base if tns_base > 0 else 0

    # Dynamic power = total - leakage
    dp_base = (bm["total_power"] or 0) - (bm["leakage_power"] or 0)
    dp_cont = (tm["total_power"] or 0) - (tm["leakage_power"] or 0)
    s_dp = (dp_base - dp_cont) / dp_base if dp_base > 0 else 0

    lp_base = bm["leakage_power"] or 0
    lp_cont = tm["leakage_power"] or 0
    s_lp = (lp_base - lp_cont) / lp_base if lp_base > 0 else 0

    ppa = W["w_tns"] * s_tns + W["w_dpower"] * s_dp + W["w_lpower"] * s_lp

    # ERC penalty
    slew_base = bm.get("slew_over_sum", 0) or 0
    slew_cont = tm.get("slew_over_sum", 0) or 0
    cap_base = bm.get("cap_over_sum", 0) or 0
    cap_cont = tm.get("cap_over_sum", 0) or 0
    fanout_base = bm.get("fanout_over_sum", 0) or 0
    fanout_cont = tm.get("fanout_over_sum", 0) or 0

    p_erc = (
        W["w_slew"] * (slew_cont / slew_base if slew_base > 0 else 0)
        + W["w_cap"] * (cap_cont / cap_base if cap_base > 0 else 0)
        + W["w_fanout"] * (fanout_cont / fanout_base if fanout_base > 0 else 0)
    )

    # Runtime penalty
    trt_base = bm.get("tool_runtime") or 0
    trt_cont = tm.get("tool_runtime") or 0
    frt_base = bm.get("flow_runtime") or 0
    frt_cont = tm.get("flow_runtime") or 0

    p_tool = max(0, (trt_cont - trt_base) / trt_base) if trt_base > 0 else 0
    p_flow = max(0, (frt_cont - frt_base) / frt_base) if frt_base > 0 else 0
    p_runtime = W["w_tool_runtime"] * p_tool + W["w_flow_runtime"] * p_flow

    # Displacement penalty
    p_disp = W["w_displacement"] * max(0, (team_disp - baseline_disp) / baseline_disp) if baseline_disp > 0 else 0

    # Overflow penalty
    max_o_base = bm.get("max_gr_overflow") or 0
    max_o_cont = tm.get("max_gr_overflow") or 0
    tot_o_base = bm.get("total_gr_overflow") or 0
    tot_o_cont = tm.get("total_gr_overflow") or 0

    p_max_o = max(0, (max_o_cont - max_o_base) / max_o_base) if max_o_base > 0 else 0
    p_tot_o = max(0, (tot_o_cont - tot_o_base) / tot_o_base) if tot_o_base > 0 else 0
    p_overflow = W["w_max_overflow"] * p_max_o + W["w_total_overflow"] * p_tot_o

    return ppa - p_erc - p_runtime - p_disp - p_overflow


def main():
    # Load weights
    with open("/app/data/scoring_weights.json") as f:
        weights = json.load(f)

    # Parse baseline logs and extract displacement
    baseline = {}
    baseline_disp = {}
    for design in DESIGNS:
        log_path = f"/app/logs/baseline/{design}.log"
        baseline[design] = parse_log(Path(log_path))
        baseline_disp[design] = extract_displacement(log_path)

    # Score each team
    results = []
    for team in TEAMS:
        scores = {}
        for design in DESIGNS:
            log_path = f"/app/logs/submissions/{team}/{design}.log"
            tm = parse_log(Path(log_path))
            td = extract_displacement(log_path)

            pre_dir = f"/app/netlists/pre_opt/{design}"
            post_dir = f"/app/netlists/submissions/{team}/{design}"
            is_equiv = check_equivalence(pre_dir, post_dir)

            score = compute_design_score(
                baseline[design], baseline_disp[design],
                tm, td, is_equiv, weights,
            )
            scores[design] = round(score, 2)

        total = round(sum(scores.values()), 2)
        results.append({"team": team, "scores": scores, "total": total})

    # Sort by total descending
    results.sort(key=lambda x: x["total"], reverse=True)

    # Build leaderboard
    leaderboard = {
        "rankings": [
            {
                "rank": i + 1,
                "team": r["team"],
                "total_score": r["total"],
                "aes_cipher_top": r["scores"]["aes_cipher_top"],
                "jpeg_encoder": r["scores"]["jpeg_encoder"],
            }
            for i, r in enumerate(results)
        ]
    }

    with open("/app/leaderboard.json", "w") as f:
        json.dump(leaderboard, f, indent=2)

    print(json.dumps(leaderboard, indent=2))


if __name__ == "__main__":
    main()
