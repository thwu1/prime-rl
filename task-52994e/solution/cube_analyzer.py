#!/usr/bin/env python3
"""

Rubik's Cube group-theoretic state analyzer.
Implements the full cubie-level algebra from scratch to compute
facelet strings, orientation/permutation coordinates, and group element order.
"""
import json
from math import gcd
from functools import reduce

# ===== Constants =====

SOLVED_FACELET = "UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB"
FACE_CHARS = "URFDLB"

# Facelet indices for each corner position
# URF=0 UFL=1 ULB=2 UBR=3 DFR=4 DLF=5 DBL=6 DRB=7
CORNER_FACELET_MAP = [
    (8, 9, 20), (6, 18, 38), (0, 36, 47), (2, 45, 11),
    (29, 26, 15), (27, 44, 24), (33, 53, 42), (35, 17, 51),
]

# Facelet indices for each edge position
# UR=0 UF=1 UL=2 UB=3 DR=4 DF=5 DL=6 DB=7 FR=8 FL=9 BL=10 BR=11
EDGE_FACELET_MAP = [
    (5, 10), (7, 19), (3, 37), (1, 46),
    (32, 16), (28, 25), (30, 43), (34, 52),
    (23, 12), (21, 41), (50, 39), (48, 14),
]

# Face colors at each corner cubie's facelets
CORNER_COLOR_TABLE = [
    (0, 1, 2), (0, 2, 4), (0, 4, 5), (0, 5, 1),
    (3, 2, 1), (3, 4, 2), (3, 5, 4), (3, 1, 5),
]

# Face colors at each edge cubie's facelets
EDGE_COLOR_TABLE = [
    (0, 1), (0, 2), (0, 4), (0, 5),
    (3, 1), (3, 2), (3, 4), (3, 5),
    (2, 1), (2, 4), (5, 4), (5, 1),
]

# ===== Move Definitions =====
# Each move: (corner_perm, corner_ori, edge_perm, edge_ori)

FACE_MOVES = {
    "U": {
        "cp": [3, 0, 1, 2, 4, 5, 6, 7],
        "co": [0, 0, 0, 0, 0, 0, 0, 0],
        "ep": [3, 0, 1, 2, 4, 5, 6, 7, 8, 9, 10, 11],
        "eo": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    },
    "R": {
        "cp": [4, 1, 2, 0, 7, 5, 6, 3],
        "co": [2, 0, 0, 1, 1, 0, 0, 2],
        "ep": [8, 1, 2, 3, 11, 5, 6, 7, 4, 9, 10, 0],
        "eo": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    },
    "F": {
        "cp": [1, 5, 2, 3, 0, 4, 6, 7],
        "co": [1, 2, 0, 0, 2, 1, 0, 0],
        "ep": [0, 9, 2, 3, 4, 8, 6, 7, 1, 5, 10, 11],
        "eo": [0, 1, 0, 0, 0, 1, 0, 0, 1, 1, 0, 0],
    },
    "D": {
        "cp": [0, 1, 2, 3, 5, 6, 7, 4],
        "co": [0, 0, 0, 0, 0, 0, 0, 0],
        "ep": [0, 1, 2, 3, 5, 6, 7, 4, 8, 9, 10, 11],
        "eo": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    },
    "L": {
        "cp": [0, 2, 6, 3, 4, 1, 5, 7],
        "co": [0, 1, 2, 0, 0, 2, 1, 0],
        "ep": [0, 1, 10, 3, 4, 5, 9, 7, 8, 2, 6, 11],
        "eo": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    },
    "B": {
        "cp": [0, 1, 3, 7, 4, 5, 2, 6],
        "co": [0, 0, 1, 2, 0, 0, 2, 1],
        "ep": [0, 1, 2, 11, 4, 5, 6, 10, 8, 9, 3, 7],
        "eo": [0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 1, 1],
    },
}


# ===== Cube State Operations =====

def make_identity():
    """Create the identity (solved) cube state."""
    return {
        "cp": list(range(8)),
        "co": [0] * 8,
        "ep": list(range(12)),
        "eo": [0] * 12,
    }


def cube_multiply(a, b):
    """Multiply cube states: (A*B).perm[x] = A.perm[B.perm[x]]"""
    result = {}
    result["cp"] = [a["cp"][b["cp"][i]] for i in range(8)]
    result["co"] = [(a["co"][b["cp"][i]] + b["co"][i]) % 3 for i in range(8)]
    result["ep"] = [a["ep"][b["ep"][i]] for i in range(12)]
    result["eo"] = [(a["eo"][b["ep"][i]] + b["eo"][i]) % 2 for i in range(12)]
    return result


def states_equal(a, b):
    """Check if two cube states are identical."""
    return (a["cp"] == b["cp"] and a["co"] == b["co"]
            and a["ep"] == b["ep"] and a["eo"] == b["eo"])


# ===== Conversion Functions =====

def cubie_to_facelet(state):
    """Convert cubie-level state to 54-character facelet string."""
    facelets = [0] * 54
    # Center facelets (always match face color)
    for face in range(6):
        facelets[face * 9 + 4] = face
    # Place corner facelets
    for position in range(8):
        cubie = state["cp"][position]
        orientation = state["co"][position]
        for k in range(3):
            dest_facelet = CORNER_FACELET_MAP[position][(k + orientation) % 3]
            facelets[dest_facelet] = CORNER_COLOR_TABLE[cubie][k]
    # Place edge facelets
    for position in range(12):
        cubie = state["ep"][position]
        orientation = state["eo"][position]
        for k in range(2):
            dest_facelet = EDGE_FACELET_MAP[position][(k + orientation) % 2]
            facelets[dest_facelet] = EDGE_COLOR_TABLE[cubie][k]
    return "".join(FACE_CHARS[c] for c in facelets)


# ===== Coordinate Computation =====

def compute_twist(co):
    """Corner orientation coordinate: base-3 over first 7 corners."""
    value = 0
    for i in range(7):
        value = 3 * value + co[i]
    return value


def compute_flip(eo):
    """Edge orientation coordinate: base-2 over first 11 edges."""
    value = 0
    for i in range(11):
        value = 2 * value + eo[i]
    return value


def compute_corner_permutation(cp):
    """Corner permutation coordinate via rotate-left Lehmer code (0-40319)."""
    working = list(cp)
    coord = 0
    for j in range(7, 0, -1):
        rotations = 0
        while working[j] != j:
            # Rotate working[0..j] left by one
            saved = working[0]
            for i in range(j):
                working[i] = working[i + 1]
            working[j] = saved
            rotations += 1
        coord = (j + 1) * coord + rotations
    return coord


# ===== Order Computation =====

def compute_order(state):
    """
    Compute order of the group element by cycle decomposition.

    For each cycle of length k with orientation sum T:
      - corners: contribute k if T%3==0, else 3k
      - edges: contribute k if T%2==0, else 2k
    Overall order = lcm of all contributions.
    """
    cp, co = state["cp"], state["co"]
    ep, eo = state["ep"], state["eo"]

    contributions = []

    # Corner permutation cycles
    corner_visited = [False] * 8
    for start in range(8):
        if corner_visited[start]:
            continue
        cycle_len = 0
        ori_sum = 0
        pos = start
        while not corner_visited[pos]:
            corner_visited[pos] = True
            ori_sum += co[pos]
            pos = cp[pos]
            cycle_len += 1
        if ori_sum % 3 != 0:
            contributions.append(3 * cycle_len)
        else:
            contributions.append(cycle_len)

    # Edge permutation cycles
    edge_visited = [False] * 12
    for start in range(12):
        if edge_visited[start]:
            continue
        cycle_len = 0
        ori_sum = 0
        pos = start
        while not edge_visited[pos]:
            edge_visited[pos] = True
            ori_sum += eo[pos]
            pos = ep[pos]
            cycle_len += 1
        if ori_sum % 2 != 0:
            contributions.append(2 * cycle_len)
        else:
            contributions.append(cycle_len)

    def lcm(a, b):
        return a * b // gcd(a, b)

    return reduce(lcm, contributions, 1)


# ===== Scramble Parsing =====

def parse_move_token(token):
    """Parse a single move token (e.g., R, R', R2) into (face, repeat_count)."""
    face = token[0]
    if len(token) == 1:
        return face, 1
    elif token[1] == "'":
        return face, 3  # X' = X^3 (since X^4 = identity)
    elif token[1] == "2":
        return face, 2
    else:
        return face, 1


def apply_scramble(scramble_line):
    """Apply a scramble sequence to the identity cube and return resulting state."""
    state = make_identity()
    for token in scramble_line.strip().split():
        if not token:
            continue
        face, count = parse_move_token(token)
        move = FACE_MOVES[face]
        for _ in range(count):
            state = cube_multiply(state, move)
    return state


# ===== Main =====

def main():
    # Read scrambles
    with open("/app/scrambles.txt", "r") as f:
        scrambles = [line.strip() for line in f if line.strip()]

    results = []
    for scramble in scrambles:
        state = apply_scramble(scramble)

        result = {
            "facelet_string": cubie_to_facelet(state),
            "twist": compute_twist(state["co"]),
            "flip": compute_flip(state["eo"]),
            "corners": compute_corner_permutation(state["cp"]),
            "order": compute_order(state),
        }
        results.append(result)

    # Write output
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"Computed results for {len(results)} scrambles -> /app/results.json")


if __name__ == "__main__":
    main()
