#!/usr/bin/env python3

"""FPGA Design Space Exploration Pipeline — reads JSONL, builds SQLite DB, writes report."""

import json
import sqlite3

DIMS = ["LUT", "FF", "DSP", "BRAM"]
KEY_MAP = {"LUT": "lut", "FF": "ff", "DSP": "dsp", "BRAM": "bram"}


def main():
    with open("/app/resource_weights.json") as f:
        weights = json.load(f)

    # Read JSONL produced by jq
    entries = []
    with open("/app/validated_solutions.jsonl") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))

    # Determine validity and compute weighted cost
    for e in entries:
        ps = e.get("pass_status", "")
        pass_ok = isinstance(ps, str) and ps.strip().lower() == "true"
        dims_ok = all(
            e.get(KEY_MAP[d]) is not None and isinstance(e.get(KEY_MAP[d]), (int, float))
            for d in DIMS
        )
        e["is_valid"] = 1 if (pass_ok and dims_ok) else 0
        if e["is_valid"]:
            e["weighted_cost"] = sum(e[KEY_MAP[d]] * weights[d] for d in DIMS)
        else:
            e["weighted_cost"] = None

    # Create SQLite database
    conn = sqlite3.connect("/app/synthesis.db")
    cur = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS solutions")
    cur.execute("DROP TABLE IF EXISTS pareto_solutions")
    cur.execute("DROP TABLE IF EXISTS module_stats")

    cur.execute("""CREATE TABLE solutions (
        model TEXT, category TEXT, module TEXT, solution_index INTEGER,
        pass_status TEXT, lut INTEGER, ff INTEGER, dsp INTEGER, bram INTEGER,
        weighted_cost REAL, is_valid INTEGER
    )""")

    cur.execute("""CREATE TABLE pareto_solutions (
        module TEXT, model TEXT, solution_index INTEGER,
        lut INTEGER, ff INTEGER, dsp INTEGER, bram INTEGER, weighted_cost REAL
    )""")

    cur.execute("""CREATE TABLE module_stats (
        module TEXT, total_valid INTEGER, pareto_count INTEGER,
        best_cost REAL, worst_cost REAL
    )""")

    for e in entries:
        cur.execute(
            "INSERT INTO solutions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (e["model"], e["category"], e["module"], e["solution_index"],
             e["pass_status"], e.get("lut"), e.get("ff"), e.get("dsp"),
             e.get("bram"), e["weighted_cost"], e["is_valid"]))
    conn.commit()

    # Group valid solutions by module
    module_solutions = {}
    for e in entries:
        if not e["is_valid"]:
            continue
        mod = e["module"]
        if mod not in module_solutions:
            module_solutions[mod] = []
        module_solutions[mod].append({
            "model": e["model"],
            "solution_index": e["solution_index"],
            "resources": {d: int(e[KEY_MAP[d]]) for d in DIMS},
            "cost": e["weighted_cost"],
        })

    report = {"modules": {}, "model_summary": {}}
    module_best_costs = {}
    module_pareto_sets = {}

    for mod_name in sorted(module_solutions.keys()):
        sols = module_solutions[mod_name]
        n = len(sols)

        # Pareto frontier via pairwise dominance
        is_pf = [True] * n
        for i in range(n):
            if not is_pf[i]:
                continue
            for j in range(n):
                if i == j:
                    continue
                ri, rj = sols[i]["resources"], sols[j]["resources"]
                if all(rj[k] <= ri[k] for k in DIMS) and any(rj[k] < ri[k] for k in DIMS):
                    is_pf[i] = False
                    break

        pf_idx = [i for i in range(n) if is_pf[i]]
        pf_set = {(sols[i]["model"], sols[i]["solution_index"]) for i in pf_idx}
        module_pareto_sets[mod_name] = pf_set

        # Rankings
        ranked = sorted(sols, key=lambda s: (
            s["cost"], s["resources"]["LUT"], s["resources"]["FF"],
            s["model"], s["solution_index"]))

        best_cost = ranked[0]["cost"]
        worst_cost = ranked[-1]["cost"]
        module_best_costs[mod_name] = best_cost

        # Pareto frontier sorted for output
        pf_sols = sorted(
            [sols[i] for i in pf_idx],
            key=lambda s: (s["cost"], s["resources"]["LUT"], s["model"]))

        # Hypervolume indicator via inclusion-exclusion
        ref = {k: max(s["resources"][k] for s in sols) + 1 for k in DIMS}
        pf_res = [sols[i]["resources"] for i in pf_idx]
        hv = 0.0
        for mask in range(1, 1 << len(pf_res)):
            corner = {k: 0 for k in DIMS}
            cnt = 0
            for i in range(len(pf_res)):
                if mask & (1 << i):
                    cnt += 1
                    for k in DIMS:
                        corner[k] = max(corner[k], pf_res[i][k])
            vol = 1.0
            for k in DIMS:
                vol *= max(0, ref[k] - corner[k])
            hv += vol if cnt % 2 == 1 else -vol

        rankings = []
        for rank, s in enumerate(ranked, 1):
            rankings.append({
                "rank": rank,
                "model": s["model"],
                "solution_index": s["solution_index"],
                "weighted_cost": s["cost"],
                "is_pareto": (s["model"], s["solution_index"]) in pf_set,
            })

        report["modules"][mod_name] = {
            "total_passing": len(sols),
            "pareto_frontier_size": len(pf_idx),
            "pareto_frontier": [{
                "model": s["model"], "solution_index": s["solution_index"],
                "LUT": s["resources"]["LUT"], "FF": s["resources"]["FF"],
                "DSP": s["resources"]["DSP"], "BRAM": s["resources"]["BRAM"],
                "weighted_cost": s["cost"],
            } for s in pf_sols],
            "rankings": rankings,
            "best_cost": best_cost,
            "cost_spread": worst_cost - best_cost,
            "hypervolume": hv,
        }

        # Populate pareto_solutions in SQLite
        for s in pf_sols:
            cur.execute(
                "INSERT INTO pareto_solutions VALUES (?,?,?,?,?,?,?,?)",
                (mod_name, s["model"], s["solution_index"],
                 s["resources"]["LUT"], s["resources"]["FF"],
                 s["resources"]["DSP"], s["resources"]["BRAM"], s["cost"]))

        # Populate module_stats
        cur.execute(
            "INSERT INTO module_stats VALUES (?,?,?,?,?)",
            (mod_name, len(sols), len(pf_idx), best_cost, worst_cost))

    conn.commit()

    # Model summary
    model_stats = {}
    for mod_name, sols in module_solutions.items():
        bc = module_best_costs[mod_name]
        pf_set = module_pareto_sets[mod_name]
        for s in sols:
            m = s["model"]
            if m not in model_stats:
                model_stats[m] = {"costs": [], "pareto_count": 0, "nres": []}
            model_stats[m]["costs"].append(s["cost"])
            model_stats[m]["nres"].append(bc / s["cost"] if s["cost"] > 0 else 0.0)
            if (s["model"], s["solution_index"]) in pf_set:
                model_stats[m]["pareto_count"] += 1

    for m_name in sorted(model_stats.keys()):
        st = model_stats[m_name]
        total = len(st["costs"])
        report["model_summary"][m_name] = {
            "total_passing": total,
            "total_pareto": st["pareto_count"],
            "pareto_fraction": st["pareto_count"] / total if total > 0 else 0.0,
            "avg_weighted_cost": sum(st["costs"]) / total if total > 0 else 0.0,
            "avg_nre": sum(st["nres"]) / total if total > 0 else 0.0,
        }

    conn.close()

    with open("/app/dse_report.json", "w") as f:
        json.dump(report, f, indent=2)


if __name__ == "__main__":
    main()
