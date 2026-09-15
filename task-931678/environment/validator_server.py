#!/usr/bin/env python3
"""Rubik's Cube validation microservice.

Listens on port 8888 and validates cube definition strings.
Returns JSON with solvability assessment.

KNOWN ISSUES (do not fix — these are part of the audit exercise):
  1. Permutation parity check is not implemented.
  2. All violation types are reported as 'invalid_state'.
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import sys

# ---------- constants ----------

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

# ---------- cubie extraction ----------


def _facelet_to_cubie(s):
    cmap = {'U': CU, 'R': CR, 'F': CF, 'D': CD, 'L': CL, 'B': CB}
    f = [cmap[c] for c in s]
    cp = [-1] * 8
    co = [0] * 8
    ep = [-1] * 12
    eo = [0] * 12

    for i in range(8):
        fac = CORNER_FACELET[i]
        ori = -1
        for o in range(3):
            if f[fac[o]] in (CU, CD):
                ori = o
                break
        if ori == -1:
            return None
        c1 = f[fac[(ori + 1) % 3]]
        c2 = f[fac[(ori + 2) % 3]]
        found = False
        for j in range(8):
            if c1 == CORNER_COLOR[j][1] and c2 == CORNER_COLOR[j][2]:
                cp[i] = j
                co[i] = ori
                found = True
                break
        if not found:
            return None

    for i in range(12):
        found = False
        for j in range(12):
            if (f[EDGE_FACELET[i][0]] == EDGE_COLOR[j][0] and
                    f[EDGE_FACELET[i][1]] == EDGE_COLOR[j][1]):
                ep[i] = j
                eo[i] = 0
                found = True
                break
            if (f[EDGE_FACELET[i][0]] == EDGE_COLOR[j][1] and
                    f[EDGE_FACELET[i][1]] == EDGE_COLOR[j][0]):
                ep[i] = j
                eo[i] = 1
                found = True
                break
        if not found:
            return None

    return cp, co, ep, eo

# ---------- validation ----------


def validate(cubestring):
    if len(cubestring) != 54:
        return {"solvable": False, "violation": "invalid_state"}
    for c in 'URFDLB':
        if cubestring.count(c) != 9:
            return {"solvable": False, "violation": "invalid_state"}

    result = _facelet_to_cubie(cubestring)
    if result is None:
        return {"solvable": False, "violation": "invalid_state"}
    cp, co, ep, eo = result

    if sorted(cp) != list(range(8)) or sorted(ep) != list(range(12)):
        return {"solvable": False, "violation": "invalid_state"}

    if sum(co) % 3 != 0:
        return {"solvable": False, "violation": "invalid_state"}

    if sum(eo) % 2 != 0:
        return {"solvable": False, "violation": "invalid_state"}

    # NOTE: permutation parity check intentionally omitted

    return {"solvable": True, "violation": None}

# ---------- HTTP server ----------


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/validate/'):
            cs = self.path[len('/validate/'):]
            resp = validate(cs)
            body = json.dumps(resp).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == '/health':
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'ok')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, fmt, *args):
        pass  # suppress request logging


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8888
    server = HTTPServer(('localhost', port), Handler)
    print(f"Validator listening on port {port}", flush=True)
    server.serve_forever()
