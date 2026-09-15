#!/usr/bin/env python3
"""SMT-COMP 2026 Single Query Track Scoring Engine.

"""

import json
import math
import functools
from collections import defaultdict


def load_data(path):
    with open(path) as f:
        return json.load(f)


def benchmark_score_sq(result_entry, benchmark_status):
    """Compute parallel benchmark score (e, n, w, c) for Single Query Track."""
    res = result_entry["result"]
    wt = result_entry["wallclock_time"]
    ct = result_entry["cpu_time"]

    if res in ("unknown", "timeout"):
        return (0, 0, 0.0, 0.0)

    if benchmark_status in ("sat", "unsat"):
        if res == benchmark_status:
            return (0, 1, wt, ct)
        else:
            return (1, 0, 0.0, 0.0)
    elif benchmark_status == "unknown":
        return (0, 1, wt, ct)
    else:
        return (0, 0, 0.0, 0.0)


def sequential_score(e, n, w, c, T):
    """Derive sequential score (eS, nS, cS) from parallel score."""
    if c > T:
        return (0, 0, 0.0)
    return (e, n, c)


def is_sound(solver_scores_known):
    """Check if solver is sound: no errors on known-status benchmarks."""
    return all(e == 0 for (e, n, w, c) in solver_scores_known)


def find_disagreements(division_benchmarks, benchmark_map, results_by,
                       sound_competitive_solvers):
    """Find unknown-status benchmarks where sound competitive solvers disagree."""
    removals = []
    for bench in division_benchmarks:
        if benchmark_map[bench]["status"] != "unknown":
            continue
        sat_solvers = set()
        unsat_solvers = set()
        for solver in sound_competitive_solvers:
            key = (bench, solver)
            if key not in results_by:
                continue
            res = results_by[key]["result"]
            if res == "sat":
                sat_solvers.add(solver)
            elif res == "unsat":
                unsat_solvers.add(solver)
        if sat_solvers and unsat_solvers:
            removals.append(bench)
    return removals


def par2_benchmark(result_entry, benchmark_status, T, m):
    """Compute PAR-2 wallclock and cpu for a single benchmark."""
    e, n, w, c = benchmark_score_sq(result_entry, benchmark_status)
    if e == 0 and n == 1:
        return (result_entry["wallclock_time"], result_entry["cpu_time"])
    else:
        return (2 * T, 2 * m * T)


def rank_parallel(solver_scores):
    """Rank solvers by parallel score (e, n, w, c). Lower e, higher n, lower w, lower c."""
    def cmp(a, b):
        ea, na, wa, ca = solver_scores[a]
        eb, nb, wb, cb = solver_scores[b]
        if ea != eb:
            return -1 if ea < eb else 1
        if na != nb:
            return -1 if na > nb else 1
        if wa != wb:
            return -1 if wa < wb else 1
        if ca != cb:
            return -1 if ca < cb else 1
        return 0
    return sorted(solver_scores.keys(), key=functools.cmp_to_key(cmp))


def rank_sequential(solver_scores):
    """Rank solvers by sequential score (e, n, c)."""
    def cmp(a, b):
        ea, na, ca = solver_scores[a]
        eb, nb, cb = solver_scores[b]
        if ea != eb:
            return -1 if ea < eb else 1
        if na != nb:
            return -1 if na > nb else 1
        if ca != cb:
            return -1 if ca < cb else 1
        return 0
    return sorted(solver_scores.keys(), key=functools.cmp_to_key(cmp))


def compute_vbs_parallel(benchmarks, solver_set, bench_scores, T, mT):
    """Compute Virtual Best Solver for parallel mode. Returns (n, w, c)."""
    vbs_n = 0
    vbs_w = 0.0
    vbs_c = 0.0
    for bench in benchmarks:
        best_n = 0
        min_w = None
        min_c = None
        for solver in solver_set:
            score = bench_scores.get((bench, solver))
            if score is None:
                continue
            e, n, w, c = score
            if n > 0:
                best_n = 1
                if min_w is None or w < min_w:
                    min_w = w
                if min_c is None or c < min_c:
                    min_c = c
        vbs_n += best_n
        vbs_w += min_w if min_w is not None else T
        vbs_c += min_c if min_c is not None else mT
    return (vbs_n, vbs_w, vbs_c)


def compute_vbs_sequential(benchmarks, solver_set, bench_scores, T):
    """Compute Virtual Best Solver for sequential mode. Returns (n, c)."""
    vbs_n = 0
    vbs_c = 0.0
    for bench in benchmarks:
        best_n = 0
        min_c = None
        for solver in solver_set:
            score = bench_scores.get((bench, solver))
            if score is None:
                continue
            e, n, c = score
            if n > 0:
                best_n = 1
                if min_c is None or c < min_c:
                    min_c = c
        vbs_n += best_n
        vbs_c += min_c if min_c is not None else T
    return (vbs_n, vbs_c)


def main():
    data = load_data("/app/competition_data.json")
    config = data["config"]
    T = config["time_limit_s"]
    m = config["cpu_cores"]
    mT = m * T

    solvers = data["solvers"]
    benchmarks = {b["id"]: b for b in data["benchmarks"]}

    # Index results by (benchmark, solver)
    results_by = {}
    for r in data["results"]:
        results_by[(r["benchmark"], r["solver"])] = r

    # Group benchmarks by division
    div_benchmarks = defaultdict(list)
    for b in data["benchmarks"]:
        div_benchmarks[b["division"]].append(b["id"])

    # Solvers by division
    div_solvers = defaultdict(list)
    for sname, sinfo in solvers.items():
        for d in sinfo["divisions"]:
            div_solvers[d].append(sname)

    output = {
        "disagreement_removals": {},
        "divisions": {},
        "derived_eligibility": {},
        "best_overall": {"parallel": {}, "sequential": {}},
        "biggest_lead": {"parallel": {}, "sequential": {}},
        "largest_contribution": {"parallel": {}, "sequential": {}},
    }

    # Storage for cross-division computations
    all_div_parallel = {}
    all_div_sequential = {}
    all_div_par2 = {}
    all_div_benchmarks_used = {}
    all_bench_parallel = {}
    all_bench_sequential = {}

    # ============================================================
    # PER-DIVISION SCORING
    # ============================================================

    for div_name in data["divisions"]:
        bench_ids = div_benchmarks[div_name]
        solver_list = div_solvers[div_name]

        # Compute benchmark scores on ALL benchmarks (before removal)
        bench_scores = {}
        for bid in bench_ids:
            bstatus = benchmarks[bid]["status"]
            for solver in solver_list:
                key = (bid, solver)
                if key in results_by:
                    bench_scores[key] = benchmark_score_sq(results_by[key], bstatus)
                else:
                    bench_scores[key] = (0, 0, 0.0, 0.0)

        # Determine sound competitive solvers on known-status benchmarks
        known_bench = [b for b in bench_ids if benchmarks[b]["status"] in ("sat", "unsat")]
        sound_competitive = []
        for solver in solver_list:
            if not solvers[solver].get("competitive", True):
                continue
            solver_known = [bench_scores[(b, solver)] for b in known_bench]
            if is_sound(solver_known):
                sound_competitive.append(solver)

        # Disagreement removal
        removals = find_disagreements(bench_ids, benchmarks, results_by, sound_competitive)
        output["disagreement_removals"][div_name] = sorted(removals)

        # Filter benchmarks
        used_benchmarks = [b for b in bench_ids if b not in removals]
        all_div_benchmarks_used[div_name] = used_benchmarks

        # Compute division scores on filtered benchmarks
        parallel_scores = {}
        sequential_scores = {}
        par2_scores = {}

        for solver in solver_list:
            E, N, W, C = 0, 0, 0.0, 0.0
            ES, NS, CS = 0, 0, 0.0
            PAR2_W, PAR2_C = 0.0, 0.0

            for bid in used_benchmarks:
                key = (bid, solver)
                e, n, w, c = bench_scores[key]
                E += e
                N += n
                W += w
                C += c

                eS, nS, cS = sequential_score(e, n, w, c, T)
                ES += eS
                NS += nS
                CS += cS

                if key in results_by:
                    p2w, p2c = par2_benchmark(results_by[key], benchmarks[bid]["status"], T, m)
                else:
                    p2w, p2c = (2 * T, 2 * mT)
                PAR2_W += p2w
                PAR2_C += p2c

                all_bench_parallel[(bid, solver)] = (e, n, w, c)
                all_bench_sequential[(bid, solver)] = (eS, nS, cS)

            parallel_scores[solver] = (E, N, W, C)
            sequential_scores[solver] = (ES, NS, CS)
            par2_scores[solver] = (PAR2_W, PAR2_C)

        all_div_parallel[div_name] = parallel_scores
        all_div_sequential[div_name] = sequential_scores
        all_div_par2[div_name] = par2_scores

        p_ranking = rank_parallel(parallel_scores)
        s_ranking = rank_sequential(sequential_scores)

        div_out = {
            "num_benchmarks": len(used_benchmarks),
            "parallel": {},
            "sequential": {},
            "par2": {},
            "parallel_ranking": p_ranking,
            "sequential_ranking": s_ranking,
        }
        for solver in solver_list:
            E, N, W, C = parallel_scores[solver]
            div_out["parallel"][solver] = {
                "errors": E, "correct": N,
                "wallclock": round(W, 6), "cpu": round(C, 6)
            }
            ES, NS, CS = sequential_scores[solver]
            div_out["sequential"][solver] = {
                "errors": ES, "correct": NS, "cpu": round(CS, 6)
            }
            P2W, P2C = par2_scores[solver]
            div_out["par2"][solver] = {
                "wallclock": round(P2W, 6), "cpu": round(P2C, 6)
            }
        output["divisions"][div_name] = div_out

    # ============================================================
    # DERIVED SOLVER ELIGIBILITY
    # ============================================================

    for sname, sinfo in solvers.items():
        if sinfo["type"] != "derived":
            continue
        base_solver = sinfo["base_solver"]
        eligibility = {}
        any_eligible = False

        for div_name in sinfo["divisions"]:
            if div_name not in all_div_par2:
                continue
            par2 = all_div_par2[div_name]
            if sname not in par2 or base_solver not in par2:
                eligibility[div_name] = {"eligible": False, "improvement_pct": 0.0}
                continue
            base_p2w = par2[base_solver][0]
            derived_p2w = par2[sname][0]
            if base_p2w > 0:
                improvement = (base_p2w - derived_p2w) / base_p2w
            else:
                improvement = 0.0
            eligible = improvement >= 0.10
            if eligible:
                any_eligible = True
            eligibility[div_name] = {
                "eligible": eligible,
                "improvement_pct": round(improvement * 100, 6)
            }

        eligibility["competition_wide"] = any_eligible
        output["derived_eligibility"][sname] = eligibility

    # ============================================================
    # BEST OVERALL RANKING
    # ============================================================

    for mode in ("parallel", "sequential"):
        scores = {}
        tiebreakers = {}

        for sname in solvers:
            total_score = 0.0
            total_time = 0.0

            for div_name in solvers[sname]["divisions"]:
                if div_name not in all_div_parallel:
                    continue
                num_b = len(all_div_benchmarks_used[div_name])
                if num_b == 0:
                    continue

                if mode == "parallel":
                    E, N, W, C = all_div_parallel[div_name][sname]
                    time_component = W
                else:
                    ES, NS, CS = all_div_sequential[div_name][sname]
                    E, N = ES, NS
                    time_component = CS

                if E > 0:
                    nn = -2.0
                else:
                    nn = (N / num_b) ** 2

                total_score += nn * math.log10(num_b)
                total_time += time_component

            scores[sname] = round(total_score, 6)
            tiebreakers[sname] = total_time

        def cmp_overall(a, b):
            if scores[a] != scores[b]:
                return 1 if scores[a] > scores[b] else -1
            if tiebreakers[a] != tiebreakers[b]:
                return 1 if tiebreakers[a] < tiebreakers[b] else -1
            return 0

        ranking = sorted(scores.keys(), key=functools.cmp_to_key(lambda a, b: -cmp_overall(a, b)))
        output["best_overall"][mode] = {"scores": scores, "ranking": ranking}

    # ============================================================
    # BIGGEST LEAD RANKING
    # ============================================================

    for mode in ("parallel", "sequential"):
        div_leads = {}

        for div_name in data["divisions"]:
            if mode == "parallel":
                ranking = output["divisions"][div_name]["parallel_ranking"]
                score_dict = all_div_parallel[div_name]
            else:
                ranking = output["divisions"][div_name]["sequential_ranking"]
                score_dict = all_div_sequential[div_name]

            if len(ranking) < 2:
                continue

            winner = ranking[0]
            second = ranking[1]

            if mode == "parallel":
                n1 = score_dict[winner][1]
                n2 = score_dict[second][1]
                w1 = score_dict[winner][2]
                w2 = score_dict[second][2]
                corr_rank = (n1 + 1) / (n2 + 1)
                time_rank = (w2 + 1) / (w1 + 1)
                div_leads[div_name] = {
                    "winner": winner,
                    "correctness_rank": round(corr_rank, 6),
                    "wallclock_rank": round(time_rank, 6),
                }
            else:
                n1 = score_dict[winner][1]
                n2 = score_dict[second][1]
                c1 = score_dict[winner][2]
                c2 = score_dict[second][2]
                corr_rank = (n1 + 1) / (n2 + 1)
                time_rank = (c2 + 1) / (c1 + 1)
                div_leads[div_name] = {
                    "winner": winner,
                    "correctness_rank": round(corr_rank, 6),
                    "cpu_rank": round(time_rank, 6),
                }

        best_div = None
        best_corr = -1
        best_time = -1
        for d, info in div_leads.items():
            cr = info["correctness_rank"]
            tr = info.get("wallclock_rank", info.get("cpu_rank", 0))
            if cr > best_corr or (cr == best_corr and tr > best_time):
                best_div = d
                best_corr = cr
                best_time = tr

        output["biggest_lead"][mode] = {
            "divisions": div_leads,
            "overall_winner": div_leads[best_div]["winner"] if best_div else None,
            "overall_division": best_div,
        }

    # ============================================================
    # LARGEST CONTRIBUTION RANKING
    # ============================================================

    # Compute total competitive solver/benchmark pairs
    total_pairs = 0
    for div_name in data["divisions"]:
        num_b = len(all_div_benchmarks_used[div_name])
        competitive = [s for s in div_solvers[div_name]
                       if solvers[s].get("competitive", True)]
        total_pairs += len(competitive) * num_b

    for mode in ("parallel", "sequential"):
        div_contributions = {}

        for div_name in data["divisions"]:
            used_b = all_div_benchmarks_used[div_name]
            num_b = len(used_b)
            if num_b == 0:
                continue

            if mode == "parallel":
                score_dict = all_div_parallel[div_name]
            else:
                score_dict = all_div_sequential[div_name]

            # Sound competitive solvers (E=0)
            sound_comp = []
            for solver in div_solvers[div_name]:
                if not solvers[solver].get("competitive", True):
                    continue
                if score_dict[solver][0] == 0:  # E == 0
                    sound_comp.append(solver)

            if len(sound_comp) <= 2:
                continue

            competitive_in_div = [s for s in div_solvers[div_name]
                                  if solvers[s].get("competitive", True)]
            nD = len(competitive_in_div) * num_b
            norm_factor = nD / total_pairs if total_pairs > 0 else 0

            S = set(sound_comp)

            if mode == "parallel":
                vbs_n, vbs_w, vbs_c = compute_vbs_parallel(used_b, S, all_bench_parallel, T, mT)
                contributions = {}
                for solver in sound_comp:
                    S_minus = S - {solver}
                    vn_m, vw_m, vc_m = compute_vbs_parallel(used_b, S_minus, all_bench_parallel, T, mT)
                    cr = 1 - (vn_m / vbs_n) if vbs_n > 0 else 0
                    wr = 1 - (vbs_w / vw_m) if vw_m > 0 else 0
                    contributions[solver] = {
                        "correctness_rank": round(cr, 6),
                        "wallclock_rank": round(wr, 6),
                        "normalized_correctness": round(cr * norm_factor, 6),
                        "normalized_wallclock": round(wr * norm_factor, 6),
                    }
                div_contributions[div_name] = contributions
            else:
                vbs_n, vbs_c = compute_vbs_sequential(used_b, S, all_bench_sequential, T)
                contributions = {}
                for solver in sound_comp:
                    S_minus = S - {solver}
                    vn_m, vc_m = compute_vbs_sequential(used_b, S_minus, all_bench_sequential, T)
                    cr = 1 - (vn_m / vbs_n) if vbs_n > 0 else 0
                    cpur = 1 - (vbs_c / vc_m) if vc_m > 0 else 0
                    contributions[solver] = {
                        "correctness_rank": round(cr, 6),
                        "cpu_rank": round(cpur, 6),
                        "normalized_correctness": round(cr * norm_factor, 6),
                        "normalized_cpu": round(cpur * norm_factor, 6),
                    }
                div_contributions[div_name] = contributions

        # Find overall winner
        best_solver = None
        best_ncr = -1
        best_ntr = -1
        best_div = None
        for d, contribs in div_contributions.items():
            for solver, ranks in contribs.items():
                ncr = ranks["normalized_correctness"]
                if mode == "parallel":
                    ntr = ranks["normalized_wallclock"]
                else:
                    ntr = ranks["normalized_cpu"]
                if ncr > best_ncr or (ncr == best_ncr and ntr > best_ntr):
                    best_solver = solver
                    best_ncr = ncr
                    best_ntr = ntr
                    best_div = d

        output["largest_contribution"][mode] = {
            "divisions": div_contributions,
            "overall_winner": best_solver,
            "overall_division": best_div if best_solver else None,
        }

    with open("/app/output.json", "w") as f:
        json.dump(output, f, indent=2)

    print("Scoring complete. Output written to /app/output.json")


if __name__ == "__main__":
    main()
