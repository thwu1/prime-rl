#!/usr/bin/env python3

"""
Kalah multi-variant game-theoretic solver with C FFI validation
and gnuplot visualization. Produces results.json, analysis.db,
libkalah.so, validation_report.json, and game_analysis.svg.
"""

import json
import sys
import sqlite3
import subprocess
import ctypes
import os

sys.setrecursionlimit(2_000_000)


# ── Build shared library ─────────────────────────────────────

def build_shared_library():
    subprocess.run(
        ["gcc", "-shared", "-fPIC", "-O2",
         "-o", "/app/libkalah.so", "/solution/kalah_lib.c"],
        check=True
    )
    print("Built /app/libkalah.so")


# ── Solver ────────────────────────────────────────────────────

def solve_problem(problem):
    n = problem["pits_per_side"]
    k = problem["seeds_per_pit"]
    captures = problem["capture_rule"] == "standard"
    misere = problem["objective"] == "misere"
    pie_rule = problem.get("pie_rule", False)

    bsz = 2 * n + 2
    ss = n
    ns = 2 * n + 1

    if problem["starting_position"] == "initial":
        board = tuple([k] * n + [0] + [k] * n + [0])
        player = 0
    else:
        sp = problem["starting_position"]
        board = tuple(
            sp["south_pits"] + [sp["south_store"]]
            + sp["north_pits"] + [sp["north_store"]]
        )
        player = 0 if sp["side_to_move"] == "south" else 1

    memo = {}
    stats = {"nodes": 0, "max_depth": 0}

    def get_moves(b, p):
        if p == 0:
            return [i for i in range(n) if b[i] > 0]
        return [i for i in range(n + 1, 2 * n + 1) if b[i] > 0]

    def do_move(b, p, pit):
        bl = list(b)
        seeds = bl[pit]
        bl[pit] = 0
        skip = ns if p == 0 else ss
        c = pit
        while seeds:
            c = (c + 1) % bsz
            if c == skip:
                continue
            bl[c] += 1
            seeds -= 1
        my_store = ss if p == 0 else ns
        extra = (c == my_store)
        if captures and not extra:
            if p == 0 and 0 <= c < n and bl[c] == 1:
                opp = 2 * n - c
                if bl[opp] > 0:
                    bl[ss] += 1 + bl[opp]
                    bl[c] = 0
                    bl[opp] = 0
            elif p == 1 and n + 1 <= c <= 2 * n and bl[c] == 1:
                opp = 2 * n - c
                if bl[opp] > 0:
                    bl[ns] += 1 + bl[opp]
                    bl[c] = 0
                    bl[opp] = 0
        se = all(bl[i] == 0 for i in range(n))
        ne = all(bl[i] == 0 for i in range(n + 1, 2 * n + 1))
        if se or ne:
            for i in range(n):
                bl[ss] += bl[i]; bl[i] = 0
            for i in range(n + 1, 2 * n + 1):
                bl[ns] += bl[i]; bl[i] = 0
            return tuple(bl), -1, True
        next_p = p if extra else 1 - p
        return tuple(bl), next_p, False

    def minimax(b, p, depth=0):
        key = (b, p)
        if key in memo:
            return memo[key]
        stats["nodes"] += 1
        if depth > stats["max_depth"]:
            stats["max_depth"] = depth
        moves = get_moves(b, p)
        if not moves:
            bl = list(b)
            for i in range(n):
                bl[ss] += bl[i]; bl[i] = 0
            for i in range(n + 1, 2 * n + 1):
                bl[ns] += bl[i]; bl[i] = 0
            v = bl[ss] - bl[ns]
            memo[key] = v
            return v
        vals = []
        for m in moves:
            nb, np_v, go = do_move(b, p, m)
            if go:
                vals.append(nb[ss] - nb[ns])
            else:
                vals.append(minimax(nb, np_v, depth + 1))
        if misere:
            v = min(vals) if p == 0 else max(vals)
        else:
            v = max(vals) if p == 0 else min(vals)
        memo[key] = v
        return v

    value = minimax(board, player)

    # Per-move values
    moves = get_moves(board, player)
    all_mv = {}
    for m in moves:
        nb, np_v, go = do_move(board, player, m)
        if go:
            mv_val = nb[ss] - nb[ns]
        else:
            mv_val = minimax(nb, np_v)
        local = m if player == 0 else m - (n + 1)
        all_mv[str(local)] = mv_val

    # Optimal first move
    if misere:
        opt_val = (min(all_mv.values()) if player == 0
                   else max(all_mv.values()))
    else:
        opt_val = (max(all_mv.values()) if player == 0
                   else min(all_mv.values()))
    opt_move = int(min(int(mk) for mk, mv in all_mv.items()
                       if mv == opt_val))

    # Extract principal variation
    pv = []
    b, p = board, player
    for _ in range(1000):
        ms = get_moves(b, p)
        if not ms:
            break
        best_m = None
        best_v = None
        for m in ms:
            nb, np_v, go = do_move(b, p, m)
            if go:
                v = nb[ss] - nb[ns]
            else:
                v = memo.get((nb, np_v))
                if v is None:
                    v = minimax(nb, np_v)
            is_better = False
            if best_v is None:
                is_better = True
            elif misere:
                is_better = (v < best_v) if p == 0 else (v > best_v)
            else:
                is_better = (v > best_v) if p == 0 else (v < best_v)
            if is_better:
                best_v = v
                best_m = m
        local_m = best_m if p == 0 else best_m - (n + 1)
        pv.append({"player": "south" if p == 0 else "north", "pit": local_m})
        nb, np_v, go = do_move(b, p, best_m)
        if go:
            break
        b = nb
        p = np_v

    result = {
        "id": problem["id"],
        "game_theoretic_value": value,
        "optimal_first_move": opt_move,
        "all_move_values": all_mv,
        "principal_variation": pv,
    }

    if pie_rule:
        abs_vals = {m: abs(v) for m, v in all_mv.items()}
        min_abs = min(abs_vals.values())
        pie_value = -min_abs
        pie_opening = int(min(int(m) for m, v in abs_vals.items()
                              if v == min_abs))
        result["pie_rule_value"] = pie_value
        result["pie_rule_optimal_opening"] = pie_opening

    tree_stat = {
        "nodes_evaluated": stats["nodes"],
        "unique_positions": len(memo),
        "max_depth": stats["max_depth"],
        "branching_factor": round(stats["nodes"] / max(1, len(memo)), 4),
    }

    return result, tree_stat


# ── Cross-validate via ctypes ─────────────────────────────────

def validate_via_ctypes(results, problems):
    lib = ctypes.CDLL("/app/libkalah.so")
    lib.kalah_init.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
    lib.kalah_init.restype = None
    lib.kalah_load.argtypes = [
        ctypes.c_int, ctypes.c_int,
        ctypes.POINTER(ctypes.c_int), ctypes.c_int, ctypes.c_int
    ]
    lib.kalah_load.restype = None
    lib.kalah_play.argtypes = [ctypes.c_int]
    lib.kalah_play.restype = ctypes.c_int
    lib.kalah_get_score.argtypes = []
    lib.kalah_get_score.restype = ctypes.c_int

    report = []
    for prob, res in zip(problems, results):
        n = prob["pits_per_side"]
        k = prob["seeds_per_pit"]
        cap = 1 if prob["capture_rule"] == "standard" else 0

        if prob["starting_position"] == "initial":
            lib.kalah_init(n, k, cap)
        else:
            sp = prob["starting_position"]
            board_list = (sp["south_pits"] + [sp["south_store"]]
                          + sp["north_pits"] + [sp["north_store"]])
            bsz = 2 * n + 2
            BArr = ctypes.c_int * bsz
            board_arr = BArr(*board_list)
            player_val = 0 if sp["side_to_move"] == "south" else 1
            lib.kalah_load(n, cap, board_arr, bsz, player_val)

        pv = res["principal_variation"]
        moves_ok = 0
        for step in pv:
            ret = lib.kalah_play(step["pit"])
            if ret < 0:
                break
            moves_ok += 1

        engine_score = lib.kalah_get_score()

        report.append({
            "problem_id": res["id"],
            "moves_validated": moves_ok,
            "engine_final_score": engine_score,
            "solver_final_score": res["game_theoretic_value"],
            "match": engine_score == res["game_theoretic_value"]
        })

    return report


# ── Generate gnuplot visualization ────────────────────────────

def generate_visualization(tree_stats, problem_ids):
    with open("/app/tree_stats.dat", "w") as f:
        for pid in problem_ids:
            ts = tree_stats[pid]
            f.write(f"{pid} {ts['unique_positions']} "
                    f"{ts['max_depth']} {ts['branching_factor']}\n")

    gnuplot_script = (
        "set terminal svg size 1000,500 enhanced font 'Arial,11'\n"
        "set output '/app/game_analysis.svg'\n"
        "set title 'Kalah Game Tree Statistics'\n"
        "set style data histogram\n"
        "set style histogram clustered gap 1\n"
        "set style fill solid 0.7 border -1\n"
        "set boxwidth 0.8\n"
        "set xlabel 'Problem'\n"
        "set ylabel 'Value'\n"
        "set grid ytics\n"
        "set key outside right top\n"
        "set xtics rotate by -30\n"
        "plot '/app/tree_stats.dat' using 2:xtic(1) title 'Unique Positions'"
        " lc rgb '#4472C4',"
        " '' using 3 title 'Max Depth' lc rgb '#ED7D31',"
        " '' using 4 title 'Branching Factor' lc rgb '#70AD47'\n"
    )

    with open("/app/plot.gnuplot", "w") as f:
        f.write(gnuplot_script)

    subprocess.run(["gnuplot", "/app/plot.gnuplot"], check=True)
    print("Generated /app/game_analysis.svg")


# ── Main ──────────────────────────────────────────────────────

def main():
    build_shared_library()

    with open("/app/problems.json") as f:
        problems = json.load(f)["problems"]

    results = []
    tree_stats = {}

    for prob in problems:
        print(
            f"Solving {prob['id']}: Kalah({prob['pits_per_side']},"
            f"{prob['seeds_per_pit']}) capture={prob['capture_rule']} "
            f"obj={prob['objective']} pie={prob.get('pie_rule', False)}",
            flush=True
        )
        result, ts = solve_problem(prob)
        tree_stats[prob["id"]] = ts
        print(
            f"  -> value={result['game_theoretic_value']}, "
            f"opt_move={result['optimal_first_move']}, "
            f"pv_len={len(result['principal_variation'])}, "
            f"nodes={ts['nodes_evaluated']}, "
            f"unique={ts['unique_positions']}",
            flush=True
        )
        results.append(result)

    # Write JSON results
    with open("/app/results.json", "w") as f:
        json.dump({"results": results}, f, indent=2)
    print("Wrote /app/results.json")

    # Write SQLite database
    db = sqlite3.connect("/app/analysis.db")
    db.execute("DROP TABLE IF EXISTS principal_variations")
    db.execute("DROP TABLE IF EXISTS move_values")
    db.execute("DROP TABLE IF EXISTS tree_stats")
    db.execute("DROP TABLE IF EXISTS solutions")

    db.execute("""CREATE TABLE solutions (
        problem_id TEXT PRIMARY KEY,
        game_theoretic_value INTEGER NOT NULL,
        optimal_first_move INTEGER NOT NULL,
        pv_length INTEGER NOT NULL,
        pie_rule_value INTEGER,
        pie_rule_optimal_opening INTEGER
    )""")
    db.execute("""CREATE TABLE move_values (
        problem_id TEXT NOT NULL,
        move_index INTEGER NOT NULL,
        value INTEGER NOT NULL,
        PRIMARY KEY (problem_id, move_index)
    )""")
    db.execute("""CREATE TABLE principal_variations (
        problem_id TEXT NOT NULL,
        step INTEGER NOT NULL,
        player TEXT NOT NULL,
        pit INTEGER NOT NULL,
        PRIMARY KEY (problem_id, step)
    )""")
    db.execute("""CREATE TABLE tree_stats (
        problem_id TEXT PRIMARY KEY,
        nodes_evaluated INTEGER NOT NULL,
        unique_positions INTEGER NOT NULL,
        max_depth INTEGER NOT NULL,
        branching_factor REAL NOT NULL
    )""")

    for r in results:
        db.execute(
            "INSERT INTO solutions VALUES (?, ?, ?, ?, ?, ?)",
            (r["id"], r["game_theoretic_value"], r["optimal_first_move"],
             len(r["principal_variation"]),
             r.get("pie_rule_value"), r.get("pie_rule_optimal_opening"))
        )
        for m_str, v in r["all_move_values"].items():
            db.execute(
                "INSERT INTO move_values VALUES (?, ?, ?)",
                (r["id"], int(m_str), v)
            )
        for i, step in enumerate(r["principal_variation"]):
            db.execute(
                "INSERT INTO principal_variations VALUES (?, ?, ?, ?)",
                (r["id"], i, step["player"], step["pit"])
            )

    for pid, ts in tree_stats.items():
        db.execute(
            "INSERT INTO tree_stats VALUES (?, ?, ?, ?, ?)",
            (pid, ts["nodes_evaluated"], ts["unique_positions"],
             ts["max_depth"], ts["branching_factor"])
        )

    db.commit()
    db.close()
    print("Wrote /app/analysis.db")

    # Cross-validate via ctypes
    report = validate_via_ctypes(results, problems)
    with open("/app/validation_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print("Wrote /app/validation_report.json")

    for r in report:
        if not r["match"]:
            print(f"WARNING: {r['problem_id']}: engine={r['engine_final_score']}"
                  f" solver={r['solver_final_score']}")

    # Generate visualization
    problem_ids = [p["id"] for p in problems]
    generate_visualization(tree_stats, problem_ids)


if __name__ == "__main__":
    main()
