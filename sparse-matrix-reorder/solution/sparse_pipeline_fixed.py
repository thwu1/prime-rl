#!/usr/bin/env python3
"""Sparse matrix analysis pipeline (corrected version).

Reads CSR matrices, converts to JDS and ELLPACK, computes SpMV in each format,
applies RCM reordering, computes structural metrics (bandwidth, profile), and
generates a format recommendation report.

Uses a C shared library (libsparse.so) for CSR SpMV, ELLPACK SpMV, and metric
computations.  Python handles format conversions, RCM reordering, and scoring.
"""
import sys
import os
import json
import ctypes
from ctypes import c_int, c_double, POINTER
from collections import deque

# ---------------------------------------------------------------------------
# Load C shared library
# ---------------------------------------------------------------------------
_lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "lib", "libsparse.so")
_lib = ctypes.CDLL(_lib_path)

_lib.csr_spmv.argtypes = [c_int, POINTER(c_int), POINTER(c_int),
                           POINTER(c_double), POINTER(c_double),
                           POINTER(c_double)]
_lib.csr_spmv.restype = None

_lib.ell_spmv.argtypes = [c_int, c_int, POINTER(c_int), POINTER(c_double),
                           POINTER(c_double), POINTER(c_double)]
_lib.ell_spmv.restype = None

_lib.compute_bandwidth.argtypes = [c_int, POINTER(c_int), POINTER(c_int)]
_lib.compute_bandwidth.restype = c_int

_lib.compute_profile.argtypes = [c_int, POINTER(c_int), POINTER(c_int)]
_lib.compute_profile.restype = c_int


def _ci(lst):
    return (c_int * len(lst))(*lst)


def _cd(lst):
    return (c_double * len(lst))(*lst)


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------
def _read_raw(path):
    with open(path) as f:
        n = int(f.readline().strip())
        vals = []
        for _ in range(n):
            tok = f.readline().strip()
            try:
                vals.append(int(tok))
            except ValueError:
                vals.append(float(tok))
    return vals


def load_csr(data_dir):
    rp = _read_raw(os.path.join(data_dir, "row.raw"))
    ci = _read_raw(os.path.join(data_dir, "col.raw"))
    vl = [float(v) for v in _read_raw(os.path.join(data_dir, "data.raw"))]
    vc = [float(v) for v in _read_raw(os.path.join(data_dir, "vec.raw"))]
    return len(rp) - 1, rp, ci, vl, vc


# ---------------------------------------------------------------------------
# CSR SpMV (via C library)
# ---------------------------------------------------------------------------
def csr_spmv(dim, rp, ci, vals, x):
    y = (c_double * dim)()
    _lib.csr_spmv(dim, _ci(rp), _ci(ci), _cd(vals), _cd(x), y)
    return list(y)


# ---------------------------------------------------------------------------
# JDS format — conversion and SpMV in Python
# ---------------------------------------------------------------------------
def csr_to_jds(dim, rp, ci, vals):
    npr = [rp[i + 1] - rp[i] for i in range(dim)]
    perm = sorted(range(dim), key=lambda r: npr[r], reverse=True)
    mx = max(npr) if dim > 0 else 0

    jd, jc, cs = [], [], [0]
    for d in range(mx):
        cnt = 0
        for i in range(dim):
            orig = perm[i]
            if npr[orig] > d:
                src = rp[orig] + d
                jd.append(vals[src])
                jc.append(ci[src])
                cnt += 1
        cs.append(cs[-1] + cnt)

    return perm, jd, jc, cs, mx


def jds_spmv(dim, perm, jd, jc, cs, ndiags, x):
    y = [0.0] * dim
    for d in range(ndiags):
        if d + 1 >= len(cs):
            break
        s, e = cs[d], cs[d + 1]
        for k in range(e - s):
            y[perm[k]] += jd[s + k] * x[jc[s + k]]
    return y


# ---------------------------------------------------------------------------
# ELLPACK format — conversion in Python, SpMV via C library
# ---------------------------------------------------------------------------
def csr_to_ell(dim, rp, ci, vals):
    npr = [rp[i + 1] - rp[i] for i in range(dim)]
    mx = max(npr) if dim > 0 else 0
    total = dim * mx
    ec = [-1] * total
    ev = [0.0] * total
    for i in range(dim):
        for k in range(npr[i]):
            idx = i * mx + k
            ec[idx] = ci[rp[i] + k]
            ev[idx] = vals[rp[i] + k]
    return ec, ev, mx


def ell_spmv(dim, mx, ec, ev, x):
    y = (c_double * dim)()
    _lib.ell_spmv(dim, mx, _ci(ec), _cd(ev), _cd(x), y)
    return list(y)


# ---------------------------------------------------------------------------
# RCM ordering
# ---------------------------------------------------------------------------
def _adjlist(dim, rp, ci):
    a = [set() for _ in range(dim)]
    for i in range(dim):
        for j in range(rp[i], rp[i + 1]):
            c = ci[j]
            if c != i:
                a[i].add(c)
    return a


def rcm_ordering(dim, rp, ci):
    adj = _adjlist(dim, rp, ci)
    vis = [False] * dim
    order = []
    for seed in range(dim):
        if vis[seed]:
            continue
        start, mdeg = seed, len(adj[seed])
        for nd in range(dim):
            if not vis[nd] and len(adj[nd]) < mdeg:
                mdeg = len(adj[nd])
                start = nd
        q = deque([start])
        vis[start] = True
        comp = []
        while q:
            nd = q.popleft()
            comp.append(nd)
            for nb in sorted(adj[nd], key=lambda n: len(adj[n])):
                if not vis[nb]:
                    vis[nb] = True
                    q.append(nb)
        order.extend(comp)
    order.reverse()
    return order


def apply_rcm(dim, rp, ci, vals, perm):
    inv = [0] * dim
    for i in range(dim):
        inv[perm[i]] = i
    nc, nv, nrp = [], [], [0]
    for ni in range(dim):
        oi = perm[ni]
        entries = []
        for j in range(rp[oi], rp[oi + 1]):
            entries.append((inv[ci[j]], vals[j]))
        entries.sort()
        for c, v in entries:
            nc.append(c)
            nv.append(v)
        nrp.append(len(nc))
    return nrp, nc, nv


def rcm_jds_spmv(dim, rp, ci, vals, vec, rcm_p):
    rrp, rci, rv = apply_rcm(dim, rp, ci, vals, rcm_p)
    pvec = [vec[rcm_p[i]] for i in range(dim)]
    jp, jd, jc, jcs, nd = csr_to_jds(dim, rrp, rci, rv)
    ry = jds_spmv(dim, jp, jd, jc, jcs, nd, pvec)
    out = [0.0] * dim
    for i in range(dim):
        out[rcm_p[i]] = ry[i]
    return out


# ---------------------------------------------------------------------------
# Metrics (via C library)
# ---------------------------------------------------------------------------
def bandwidth(dim, rp, ci):
    return _lib.compute_bandwidth(dim, _ci(rp), _ci(ci))


def profile(dim, rp, ci):
    return _lib.compute_profile(dim, _ci(rp), _ci(ci))


# ---------------------------------------------------------------------------
# Format scoring
# ---------------------------------------------------------------------------
def score_formats(dim, rp, nnz):
    npr = [rp[i + 1] - rp[i] for i in range(dim)]
    mx = max(npr) if dim > 0 else 0
    mn = sum(npr) / dim if dim > 0 else 0.0
    if mn > 0:
        std = (sum((x - mn) ** 2 for x in npr) / dim) ** 0.5
        cv = std / mn
    else:
        cv = 0.0
    fill = nnz / (dim * mx) if (dim * mx) > 0 else 0.0

    csr_s = 50.0
    jds_s = 50.0
    if cv > 0.3:
        jds_s += 30.0 * cv
    else:
        jds_s -= 10.0
    ell_s = 50.0
    if cv < 0.3:
        ell_s += 25.0 * fill
    else:
        ell_s -= 20.0 * (1.0 - fill)

    raw = {"CSR": csr_s, "JDS": jds_s, "ELL": ell_s}
    ranked = sorted(raw, key=raw.get, reverse=True)
    scores = {n: {"score": round(raw[n], 2), "recommended_rank": i + 1}
              for i, n in enumerate(ranked)}
    stats = {"cv": round(cv, 4), "ell_fill_ratio": round(fill, 4),
             "max_nnz_per_row": mx, "mean_nnz_per_row": round(mn, 4)}
    return scores, stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if len(sys.argv) != 3:
        print("Usage: sparse_pipeline.py <data_dir> <output.json>",
              file=sys.stderr)
        sys.exit(1)

    data_dir, out_path = sys.argv[1], sys.argv[2]
    dim, rp, ci, vals, vec = load_csr(data_dir)
    nnz = len(vals)

    csr_y = csr_spmv(dim, rp, ci, vals, vec)

    jp, jd, jc, jcs, nd = csr_to_jds(dim, rp, ci, vals)
    jds_y = jds_spmv(dim, jp, jd, jc, jcs, nd, vec)

    ec, ev, emx = csr_to_ell(dim, rp, ci, vals)
    ell_y = ell_spmv(dim, emx, ec, ev, vec)

    rcm_p = rcm_ordering(dim, rp, ci)
    rcm_jds_y = rcm_jds_spmv(dim, rp, ci, vals, vec, rcm_p)

    bw_o = bandwidth(dim, rp, ci)
    pr_o = profile(dim, rp, ci)

    rrp, rci, rv = apply_rcm(dim, rp, ci, vals, rcm_p)
    bw_r = bandwidth(dim, rrp, rci)
    pr_r = profile(dim, rrp, rci)

    fs, st = score_formats(dim, rp, nnz)

    report = {
        "dimension": dim, "nnz": nnz,
        "csr_spmv": csr_y, "jds_spmv": jds_y,
        "ell_spmv": ell_y, "rcm_jds_spmv": rcm_jds_y,
        "jds_row_perm": jp, "jds_col_start": jcs,
        "rcm_perm": rcm_p,
        "bandwidth_original": bw_o, "bandwidth_reordered": bw_r,
        "profile_original": pr_o, "profile_reordered": pr_r,
        "format_scores": fs, "matrix_stats": st,
    }
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)


if __name__ == "__main__":
    main()
