#!/usr/bin/env python3
"""Rubik's Cube group-theoretic analysis solver.

"""

import json
import csv
import os
from math import gcd
from collections import Counter

import kociemba

SOLVED = "UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB"

# ── Facelet permutation cycles for each clockwise face turn ─────────────────

MOVES = {
    "U": [(0,2,8,6),(1,5,7,3),(9,18,36,45),(10,19,37,46),(11,20,38,47)],
    "R": [(9,11,17,15),(10,14,16,12),(8,45,35,26),(20,2,51,29),(5,48,32,23)],
    "F": [(18,20,26,24),(19,23,25,21),(6,9,29,44),(38,8,15,27),(7,12,28,41)],
    "D": [(27,29,35,33),(28,32,34,30),(24,15,51,42),(26,17,53,44),(25,16,52,43)],
    "L": [(36,38,44,42),(37,41,43,39),(0,18,27,53),(47,6,24,33),(3,21,30,50)],
    "B": [(45,47,53,51),(46,50,52,48),(2,36,33,17),(11,0,42,35),(1,39,34,14)],
}

# ── Cubie conventions (Kociemba standard) ───────────────────────────────────

CORNER_FACELETS = [
    (8, 9, 20),    # URF=0
    (6, 18, 38),   # UFL=1
    (0, 36, 47),   # ULB=2
    (2, 45, 11),   # UBR=3
    (29, 26, 15),  # DFR=4
    (27, 44, 24),  # DLF=5
    (33, 53, 42),  # DBL=6
    (35, 17, 51),  # DRB=7
]

CORNER_COLORS = [
    ('U', 'R', 'F'), ('U', 'F', 'L'), ('U', 'L', 'B'), ('U', 'B', 'R'),
    ('D', 'F', 'R'), ('D', 'L', 'F'), ('D', 'B', 'L'), ('D', 'R', 'B'),
]

EDGE_FACELETS = [
    (5, 10),   # UR=0
    (7, 19),   # UF=1
    (3, 37),   # UL=2
    (1, 46),   # UB=3
    (32, 16),  # DR=4
    (28, 25),  # DF=5
    (30, 43),  # DL=6
    (34, 52),  # DB=7
    (23, 12),  # FR=8
    (21, 41),  # FL=9
    (50, 39),  # BL=10
    (48, 14),  # BR=11
]

EDGE_COLORS = [
    ('U', 'R'), ('U', 'F'), ('U', 'L'), ('U', 'B'),
    ('D', 'R'), ('D', 'F'), ('D', 'L'), ('D', 'B'),
    ('F', 'R'), ('F', 'L'), ('B', 'L'), ('B', 'R'),
]


def apply_cycles(state, cycles):
    new = list(state)
    for cycle in cycles:
        temp = new[cycle[-1]]
        for i in range(len(cycle) - 1, 0, -1):
            new[cycle[i]] = new[cycle[i - 1]]
        new[cycle[0]] = temp
    return "".join(new)


def apply_move(state, face):
    return apply_cycles(state, MOVES[face])


def apply_move_sequence(state, sequence_str):
    for token in sequence_str.strip().split():
        face = token[0]
        if len(token) == 1:
            state = apply_move(state, face)
        elif token[1] == "'":
            for _ in range(3):
                state = apply_move(state, face)
        elif token[1] == "2":
            for _ in range(2):
                state = apply_move(state, face)
    return state


# ── Cubie decomposition ────────────────────────────────────────────────────

def get_corner_cubie(state, pos):
    """Return (cubie_id, orientation) for corner at position pos."""
    f = CORNER_FACELETS[pos]
    colors = tuple(state[i] for i in f)
    color_set = set(colors)
    for cid, cc in enumerate(CORNER_COLORS):
        if set(cc) == color_set:
            ref_color = cc[0]  # U or D
            for ori in range(3):
                if colors[ori] == ref_color:
                    return cid, ori
    raise ValueError(f"Invalid corner at position {pos}: {colors}")


def get_edge_cubie(state, pos):
    """Return (cubie_id, orientation) for edge at position pos."""
    f = EDGE_FACELETS[pos]
    colors = tuple(state[i] for i in f)
    color_set = set(colors)
    for eid, ec in enumerate(EDGE_COLORS):
        if set(ec) == color_set:
            ref_color = ec[0]
            if colors[0] == ref_color:
                return eid, 0
            else:
                return eid, 1
    raise ValueError(f"Invalid edge at position {pos}: {colors}")


def full_cubie_analysis(state):
    """Decompose a facelet string into cubie-level coordinates."""
    cp, co, ep, eo = [], [], [], []
    for i in range(8):
        cid, ori = get_corner_cubie(state, i)
        cp.append(cid)
        co.append(ori)
    for i in range(12):
        eid, ori = get_edge_cubie(state, i)
        ep.append(eid)
        eo.append(ori)
    return cp, co, ep, eo


# ── Cycle analysis and algebraic order computation ──────────────────────────

def get_cycles(perm):
    n = len(perm)
    visited = [False] * n
    cycles = []
    for i in range(n):
        if not visited[i]:
            cycle = []
            j = i
            while not visited[j]:
                visited[j] = True
                cycle.append(j)
                j = perm[j]
            cycles.append(cycle)
    return cycles


def lcm(a, b):
    return a * b // gcd(a, b)


def perm_parity(perm):
    n = len(perm)
    visited = [False] * n
    parity = 0
    for i in range(n):
        if not visited[i]:
            j = i
            cycle_len = 0
            while not visited[j]:
                visited[j] = True
                j = perm[j]
                cycle_len += 1
            if cycle_len > 1:
                parity ^= (cycle_len + 1) % 2
    return parity


def compute_algebraic_order(cp, co, ep, eo):
    """Compute permutation order using wreath product cycle analysis."""
    order = 1
    aug_c_orders = []
    aug_e_orders = []

    for cycle in get_cycles(cp):
        k = len(cycle)
        twist_sum = sum(co[j] for j in cycle)
        aug = k if twist_sum % 3 == 0 else 3 * k
        aug_c_orders.append(aug)
        order = lcm(order, aug)

    for cycle in get_cycles(ep):
        k = len(cycle)
        flip_sum = sum(eo[j] for j in cycle)
        aug = k if flip_sum % 2 == 0 else 2 * k
        aug_e_orders.append(aug)
        order = lcm(order, aug)

    c_cycle_type = sorted(len(c) for c in get_cycles(cp))
    e_cycle_type = sorted(len(c) for c in get_cycles(ep))

    return {
        "corner_cycle_type": c_cycle_type,
        "edge_cycle_type": e_cycle_type,
        "augmented_corner_orders": sorted(aug_c_orders),
        "augmented_edge_orders": sorted(aug_e_orders),
        "permutation_order": order,
    }


# ── Solvability analysis ───────────────────────────────────────────────────

def analyze_solvability(state):
    """Check the three solvability invariants of the Rubik's cube group."""
    cp, co, ep, eo = full_cubie_analysis(state)
    cts = sum(co) % 3
    efs = sum(eo) % 2
    c_par = perm_parity(cp)
    e_par = perm_parity(ep)

    violations = []
    if cts != 0:
        violations.append("corner_twist")
    if efs != 0:
        violations.append("edge_flip")
    if c_par != e_par:
        violations.append("parity_mismatch")

    return {
        "corner_twist_sum_mod3": cts,
        "edge_flip_sum_mod2": efs,
        "corner_parity": c_par,
        "edge_parity": e_par,
        "violations": violations,
        "solvable": len(violations) == 0,
    }


def main():
    os.makedirs("/app/output", exist_ok=True)

    scrambles = json.load(open("/app/scrambles.json"))
    invalid_states = json.load(open("/app/invalid_states.json"))

    # ── 1. Cubie decomposition ──────────────────────────────────────────
    cubie_decomposition = []
    valid_states = []
    for scramble in scrambles:
        state = apply_move_sequence(SOLVED, scramble)
        valid_states.append(state)
        cp, co, ep, eo = full_cubie_analysis(state)
        cubie_decomposition.append({
            "corner_permutation": cp,
            "corner_orientation": co,
            "edge_permutation": ep,
            "edge_orientation": eo,
        })

    with open("/app/output/cubie_decomposition.json", "w") as f:
        json.dump(cubie_decomposition, f, indent=2)

    # ── 2. Algebraic orders ─────────────────────────────────────────────
    algebraic_orders = []
    for cd in cubie_decomposition:
        result = compute_algebraic_order(
            cd["corner_permutation"], cd["corner_orientation"],
            cd["edge_permutation"], cd["edge_orientation"])
        algebraic_orders.append(result)

    with open("/app/output/algebraic_orders.json", "w") as f:
        json.dump(algebraic_orders, f, indent=2)

    # ── 3. Solvability analysis ─────────────────────────────────────────
    solvability_analysis = []
    for inv_state in invalid_states:
        result = analyze_solvability(inv_state)
        solvability_analysis.append(result)

    with open("/app/output/solvability_analysis.json", "w") as f:
        json.dump(solvability_analysis, f, indent=2)

    # ── 4. Solutions ────────────────────────────────────────────────────
    solutions = []
    for i, state in enumerate(valid_states):
        sol_str = kociemba.solve(state)
        move_count = len(sol_str.split())
        result = apply_move_sequence(state, sol_str)
        verified = result == SOLVED
        solutions.append({
            "solution": sol_str,
            "move_count": move_count,
            "verified": verified,
        })

    with open("/app/output/solutions.json", "w") as f:
        json.dump(solutions, f, indent=2)

    # ── 5. Statistics ───────────────────────────────────────────────────
    results = []
    with open("/app/fmc_results.tsv", "r") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            results.append(row)

    sub20 = set()
    for r in results:
        best = int(r["best"])
        if 0 < best <= 20:
            sub20.add(r["person_id"])

    comp_pids = {}
    for r in results:
        comp = r["competition_id"]
        pid = r["person_id"]
        if comp not in comp_pids:
            comp_pids[comp] = set()
        comp_pids[comp].add(pid)
    largest_competition = max(comp_pids.items(), key=lambda x: len(x[1]))[0]

    person_counts = Counter()
    for r in results:
        if int(r["best"]) > 0:
            person_counts[r["person_id"]] += 1
    most_results_person = person_counts.most_common(1)[0][0]

    statistics = {
        "sub20_count": len(sub20),
        "largest_competition": largest_competition,
        "most_results_person": most_results_person,
    }

    with open("/app/output/statistics.json", "w") as f:
        json.dump(statistics, f, indent=2)

    # ── Summary ─────────────────────────────────────────────────────────
    print("Pipeline complete.")
    print(f"  Cubie decompositions: {len(cubie_decomposition)}")
    print(f"  Algebraic orders: {[ao['permutation_order'] for ao in algebraic_orders]}")
    print(f"  Solvability reports: {[sa['violations'] for sa in solvability_analysis]}")
    print(f"  Solutions: {len(solutions)} (all verified: {all(s['verified'] for s in solutions)})")
    print(f"  Statistics: {statistics}")


if __name__ == "__main__":
    main()
