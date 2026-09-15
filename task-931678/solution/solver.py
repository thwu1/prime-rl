#!/usr/bin/env python3
"""
Rubik's Cube State Database Audit — Solution.
Reads cube data from SQLite, queries the validation service via HTTP,
performs independent group-theoretic analysis, and produces the audit report.
"""

import json
import sqlite3
import time
import urllib.request

# ---- Constants ----

URF, UFL, ULB, UBR, DFR, DLF, DBL, DRB = range(8)
UR, UF, UL, UB, DR, DF, DL, DB, FR, FL, BL, BR = range(12)
CU, CR, CF, CD, CL, CB = range(6)

CORNER_FACELET = [
    [8, 9, 20], [6, 18, 38], [0, 36, 47], [2, 45, 11],
    [29, 26, 15], [27, 44, 24], [33, 53, 42], [35, 17, 51],
]
CORNER_COLOR = [
    [CU, CR, CF], [CU, CF, CL], [CU, CL, CB], [CU, CB, CR],
    [CD, CF, CR], [CD, CL, CF], [CD, CB, CL], [CD, CR, CB],
]
EDGE_FACELET = [
    [5, 10], [7, 19], [3, 37], [1, 46],
    [32, 16], [28, 25], [30, 43], [34, 52],
    [23, 12], [21, 41], [50, 39], [48, 14],
]
EDGE_COLOR = [
    [CU, CR], [CU, CF], [CU, CL], [CU, CB],
    [CD, CR], [CD, CF], [CD, CL], [CD, CB],
    [CF, CR], [CF, CL], [CB, CL], [CB, CR],
]

MOVE_DEFS = {
    'U': ([UBR, URF, UFL, ULB, DFR, DLF, DBL, DRB], [0, 0, 0, 0, 0, 0, 0, 0],
          [UB, UR, UF, UL, DR, DF, DL, DB, FR, FL, BL, BR], [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
    'R': ([DFR, UFL, ULB, URF, DRB, DLF, DBL, UBR], [2, 0, 0, 1, 1, 0, 0, 2],
          [FR, UF, UL, UB, BR, DF, DL, DB, DR, FL, BL, UR], [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
    'F': ([UFL, DLF, ULB, UBR, URF, DFR, DBL, DRB], [1, 2, 0, 0, 2, 1, 0, 0],
          [UR, FL, UL, UB, DR, FR, DL, DB, UF, DF, BL, BR], [0, 1, 0, 0, 0, 1, 0, 0, 1, 1, 0, 0]),
    'D': ([URF, UFL, ULB, UBR, DLF, DBL, DRB, DFR], [0, 0, 0, 0, 0, 0, 0, 0],
          [UR, UF, UL, UB, DF, DL, DB, DR, FR, FL, BL, BR], [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
    'L': ([URF, ULB, DBL, UBR, DFR, UFL, DLF, DRB], [0, 1, 2, 0, 0, 2, 1, 0],
          [UR, UF, BL, UB, DR, DF, FL, DB, FR, UL, DL, BR], [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
    'B': ([URF, UFL, UBR, DRB, DFR, DLF, ULB, DBL], [0, 0, 1, 2, 0, 0, 2, 1],
          [UR, UF, UL, BR, DR, DF, DL, BL, FR, FL, UB, DB], [0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 1, 1]),
}


class CubieCube:
    def __init__(self, cp=None, co=None, ep=None, eo=None):
        self.cp = list(cp) if cp is not None else list(range(8))
        self.co = list(co) if co is not None else [0] * 8
        self.ep = list(ep) if ep is not None else list(range(12))
        self.eo = list(eo) if eo is not None else [0] * 12

    def copy(self):
        return CubieCube(self.cp, self.co, self.ep, self.eo)

    def is_identity(self):
        return (self.cp == list(range(8)) and self.co == [0] * 8
                and self.ep == list(range(12)) and self.eo == [0] * 12)

    def multiply(self, other):
        new_cp = [self.cp[other.cp[i]] for i in range(8)]
        new_co = [(self.co[other.cp[i]] + other.co[i]) % 3 for i in range(8)]
        new_ep = [self.ep[other.ep[i]] for i in range(12)]
        new_eo = [(self.eo[other.ep[i]] + other.eo[i]) % 2 for i in range(12)]
        self.cp, self.co = new_cp, new_co
        self.ep, self.eo = new_ep, new_eo

    def to_facelet_string(self):
        color_char = 'URFDLB'
        f = [0] * 54
        for i in range(6):
            f[i * 9 + 4] = i
        for i in range(8):
            j = self.cp[i]
            ori = self.co[i]
            for k in range(3):
                f[CORNER_FACELET[i][(k + ori) % 3]] = CORNER_COLOR[j][k]
        for i in range(12):
            j = self.ep[i]
            ori = self.eo[i]
            for k in range(2):
                f[EDGE_FACELET[i][(k + ori) % 2]] = EDGE_COLOR[j][k]
        return ''.join(color_char[c] for c in f)


def make_move(face_char):
    cp, co, ep, eo = MOVE_DEFS[face_char]
    return CubieCube(cp, co, ep, eo)


def parse_and_apply(move_string):
    cc = CubieCube()
    for token in move_string.split():
        face = token[0]
        if len(token) == 1:
            power = 1
        elif token[1] == "'":
            power = 3
        elif token[1] == '2':
            power = 2
        else:
            power = 1
        basic = make_move(face)
        for _ in range(power):
            cc.multiply(basic)
    return cc


def facelet_to_cubie(s):
    color_map = {'U': CU, 'R': CR, 'F': CF, 'D': CD, 'L': CL, 'B': CB}
    f = [color_map[c] for c in s]
    cc = CubieCube()
    cc.cp = [-1] * 8
    cc.ep = [-1] * 12

    for i in range(8):
        fac = CORNER_FACELET[i]
        ori = -1
        for o in range(3):
            if f[fac[o]] in (CU, CD):
                ori = o
                break
        if ori == -1:
            return None
        col1 = f[fac[(ori + 1) % 3]]
        col2 = f[fac[(ori + 2) % 3]]
        for j in range(8):
            if col1 == CORNER_COLOR[j][1] and col2 == CORNER_COLOR[j][2]:
                cc.cp[i] = j
                cc.co[i] = ori
                break
        if cc.cp[i] == -1:
            return None

    for i in range(12):
        for j in range(12):
            if (f[EDGE_FACELET[i][0]] == EDGE_COLOR[j][0] and
                    f[EDGE_FACELET[i][1]] == EDGE_COLOR[j][1]):
                cc.ep[i] = j
                cc.eo[i] = 0
                break
            if (f[EDGE_FACELET[i][0]] == EDGE_COLOR[j][1] and
                    f[EDGE_FACELET[i][1]] == EDGE_COLOR[j][0]):
                cc.ep[i] = j
                cc.eo[i] = 1
                break
        if cc.ep[i] == -1:
            return None

    return cc


def validate_state(facelet_str):
    for c in 'URFDLB':
        if facelet_str.count(c) != 9:
            return False, "invalid_colors"

    cc = facelet_to_cubie(facelet_str)
    if cc is None:
        return False, "invalid_pieces"
    if sorted(cc.cp) != list(range(8)):
        return False, "invalid_pieces"
    if sorted(cc.ep) != list(range(12)):
        return False, "invalid_pieces"

    if sum(cc.co) % 3 != 0:
        return False, "corner_orientation"
    if sum(cc.eo) % 2 != 0:
        return False, "edge_orientation"

    c_inv = sum(1 for i in range(8) for j in range(i + 1, 8) if cc.cp[i] > cc.cp[j])
    e_inv = sum(1 for i in range(12) for j in range(i + 1, 12) if cc.ep[i] > cc.ep[j])
    if c_inv % 2 != e_inv % 2:
        return False, "permutation_parity"

    return True, None


def find_order(cc):
    current = CubieCube()
    for k in range(1, 1261):
        current.multiply(cc)
        if current.is_identity():
            return k
    return -1


def query_service(facelet_str, max_retries=3):
    """Query the validation microservice via HTTP."""
    url = f'http://localhost:8888/validate/{facelet_str}'
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                return json.loads(response.read().decode())
        except Exception:
            if attempt < max_retries - 1:
                time.sleep(1)
    return {"solvable": None, "violation": "service_unavailable"}


def main():
    # Read data from SQLite database
    conn = sqlite3.connect('/app/cubes.db')
    rows = conn.execute('''
        SELECT f.state_id, f.facelet, g.move_sequence, o.claimed_order
        FROM facelets f
        JOIN generators g ON f.state_id = g.state_id
        JOIN order_claims o ON f.state_id = o.state_id
        ORDER BY f.state_id
    ''').fetchall()
    conn.close()

    report = {}
    for sid, facelet, gen, claimed_order in rows:
        # Independent analysis
        solvable, violation = validate_state(facelet)

        if solvable:
            gen_cc = parse_and_apply(gen)
            gen_verified = (gen_cc.to_facelet_string() == facelet)
            state_cc = facelet_to_cubie(facelet)
            correct_order = find_order(state_cc)
        else:
            gen_verified = None
            correct_order = None

        # Query validation service
        service_resp = query_service(facelet)
        service_agrees = (service_resp["solvable"] == solvable)

        report[sid] = {
            "solvable": solvable,
            "violation": violation,
            "generator_verified": gen_verified,
            "correct_order": correct_order,
            "service_response": service_resp,
            "service_agrees": service_agrees,
        }

    with open('/app/report.json', 'w') as f:
        json.dump(report, f, indent=2)


if __name__ == '__main__':
    main()
