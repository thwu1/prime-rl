#!/usr/bin/env python3
"""Create reference database for ZNE shot optimizer."""
import sqlite3
import json
import math


def _lagrange(sf):
    n = len(sf)
    g = [1.0] * n
    for j in range(n):
        for k in range(n):
            if k != j:
                g[j] *= sf[k] / (sf[k] - sf[j])
    return g


def _zne_var(gamma, V, N):
    J, K = len(gamma), len(V[0])
    return sum(
        gamma[j] ** 2 * V[j][k] / N[j][k]
        for j in range(J) for k in range(K) if N[j][k] > 0
    )


def _sample_var(vals):
    n = len(vals)
    if n < 2:
        return 0.0
    m = sum(vals) / n
    return sum((v - m) ** 2 for v in vals) / (n - 1)


def _dot(row, w):
    return sum(a * b for a, b in zip(row, w))


def _optimal_alloc(gamma, V, budget):
    J, K = len(gamma), len(V[0])
    nc = J * K
    al = [[1] * K for _ in range(J)]
    rem = budget - nc
    if rem <= 0:
        return al
    w = [[abs(gamma[j]) * math.sqrt(max(V[j][k], 0.0))
          for k in range(K)] for j in range(J)]
    tw = sum(w[j][k] for j in range(J) for k in range(K))
    if tw < 1e-15:
        per = rem // nc
        for j in range(J):
            for k in range(K):
                al[j][k] += per
        left = rem - per * nc
        idx = 0
        for j in range(J):
            for k in range(K):
                if idx < left:
                    al[j][k] += 1
                idx += 1
        return al
    ct = [[rem * w[j][k] / tw for k in range(K)] for j in range(J)]
    for j in range(J):
        for k in range(K):
            al[j][k] += int(math.floor(ct[j][k]))
    cs = sum(al[j][k] for j in range(J) for k in range(K))
    left = budget - cs
    if left > 0:
        fr = []
        for j in range(J):
            for k in range(K):
                fr.append((ct[j][k] - math.floor(ct[j][k]), j, k))
        fr.sort(key=lambda x: -x[0])
        for i in range(int(left)):
            _, j, k = fr[i]
            al[j][k] += 1
    return al


db = sqlite3.connect("/app/reference_data.db")
c = db.cursor()

c.execute("CREATE TABLE schema_info (table_name TEXT PRIMARY KEY, description TEXT)")
c.execute("""CREATE TABLE coefficient_examples (
    id INTEGER PRIMARY KEY, scale_factors TEXT, coefficients TEXT)""")
c.execute("""CREATE TABLE extrapolation_examples (
    id INTEGER PRIMARY KEY, scale_factors TEXT, values_per_level TEXT,
    extrapolated_result REAL)""")
c.execute("""CREATE TABLE variance_formula_examples (
    id INTEGER PRIMARY KEY, gamma TEXT, variance_matrix TEXT,
    shot_allocation TEXT, zne_variance REAL)""")
c.execute("""CREATE TABLE group_variance_examples (
    id INTEGER PRIMARY KEY, measurements TEXT, weights TEXT,
    expected_variance REAL)""")
c.execute("""CREATE TABLE allocation_examples (
    id INTEGER PRIMARY KEY, gamma TEXT, variance_matrix TEXT,
    budget INTEGER, optimal_allocation TEXT)""")

for nm, ds in [
    ("coefficient_examples",
     "Extrapolation coefficients for given scale factor configurations"),
    ("extrapolation_examples",
     "Extrapolated zero-noise value from multi-level noisy measurements"),
    ("variance_formula_examples",
     "Variance of extrapolated estimate from per-cell variances and shot counts"),
    ("group_variance_examples",
     "Per-shot energy variance from weighted joint measurement outcomes"),
    ("allocation_examples",
     "Optimal integer shot allocation minimizing extrapolation variance"),
]:
    c.execute("INSERT INTO schema_info VALUES (?,?)", (nm, ds))

for i, sf in enumerate([
    [1, 2], [1, 2, 3], [1, 3, 5], [1, 2, 4], [2, 3],
    [1, 1.5, 2, 3], [1, 2, 3, 5],
]):
    g = _lagrange(sf)
    c.execute("INSERT INTO coefficient_examples VALUES (?,?,?)",
              (i + 1, json.dumps(sf), json.dumps(g)))

for i, (sf, vs) in enumerate([
    ([1, 2, 3], [5.0, 3.0, 2.0]),
    ([1, 2], [4.0, 3.0]),
    ([1, 3, 5], [10.0, 6.0, 4.2]),
    ([1, 2, 3], [1.5, 1.2, 1.1]),
    ([1, 1.5, 2, 3], [8.0, 6.5, 5.5, 4.0]),
]):
    g = _lagrange(sf)
    r = sum(g[j] * vs[j] for j in range(len(g)))
    c.execute("INSERT INTO extrapolation_examples VALUES (?,?,?,?)",
              (i + 1, json.dumps(sf), json.dumps(vs), r))

for i, (gm, V, N) in enumerate([
    ([2, -1], [[1, 0.5], [0.8, 0.4]], [[100, 50], [80, 40]]),
    ([3, -3, 1], [[0.8, 0.6], [0.7, 0.5], [0.6, 0.4]],
     [[100, 80], [60, 40], [30, 20]]),
    ([1.5, -0.5], [[2, 1], [1.5, 0.8]], [[200, 150], [100, 80]]),
]):
    v = _zne_var(gm, V, N)
    c.execute("INSERT INTO variance_formula_examples VALUES (?,?,?,?,?)",
              (i + 1, json.dumps(gm), json.dumps(V), json.dumps(N), v))

for i, (ms, w) in enumerate([
    ([[1, 1], [-1, 1], [1, -1], [-1, -1]], [1.0, 1.0]),
    ([[1, 1], [-1, -1], [1, 1], [-1, -1]], [1.0, 1.0]),
    ([[1], [-1], [1], [1], [-1]], [3.0]),
    ([[1, 1, 1], [-1, 1, -1], [1, -1, 1], [-1, -1, -1]],
     [1.0, 2.0, 0.5]),
    ([[1, -1], [-1, 1], [1, -1], [-1, 1], [1, 1], [-1, -1]],
     [2.0, 3.0]),
]):
    ws = [_dot(row, w) for row in ms]
    v = _sample_var(ws)
    c.execute("INSERT INTO group_variance_examples VALUES (?,?,?,?)",
              (i + 1, json.dumps(ms), json.dumps(w), v))

for i, (gm, V, bd) in enumerate([
    ([3, -3, 1], [[1.0, 0.5], [0.9, 0.4], [0.8, 0.3]], 100),
    ([3, -3, 1], [[1.0, 0.5], [0.9, 0.4], [0.8, 0.3]], 10000),
    ([2, -1], [[1.0, 0.5, 0.8], [0.9, 0.4, 0.7]], 500),
    ([3, -3, 1], [[1.0, 0.0], [0.9, 0.0], [0.8, 0.0]], 200),
]):
    a = _optimal_alloc(gm, V, bd)
    c.execute("INSERT INTO allocation_examples VALUES (?,?,?,?,?)",
              (i + 1, json.dumps(gm), json.dumps(V), bd, json.dumps(a)))

db.commit()
db.close()
print("Reference database created at /app/reference_data.db")
