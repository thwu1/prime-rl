#!/usr/bin/env python3
"""
Reference solution: numerical bifurcation analysis engine with C kernel
compilation, ctypes interop, and gnuplot diagram generation.
"""


import json
import sys
import subprocess
import ctypes
from ctypes import c_int, c_double, POINTER
import numpy as np
from scipy import linalg

sys.path.insert(0, "/app")
from systems import SYSTEMS


# ---------- C Library compilation and loading ----------

def compile_c_library():
    subprocess.run([
        "gcc", "-shared", "-fPIC", "-O2",
        "-o", "/app/librhs.so",
        "/app/rhs_eval.c", "-lm"
    ], check=True)


def load_c_library():
    lib = ctypes.CDLL("/app/librhs.so")
    arr_t = POINTER(c_double)
    for prefix in ["cusp", "brusselator", "abc"]:
        for suffix in ["rhs", "jac"]:
            func = getattr(lib, f"{prefix}_{suffix}")
            func.argtypes = [c_int, arr_t, c_double, arr_t]
            func.restype = None
    lib.get_system_count.argtypes = []
    lib.get_system_count.restype = c_int
    return lib


C_PREFIX_MAP = {
    "cusp_normal_form": "cusp",
    "brusselator": "brusselator",
    "abc_reaction": "abc",
}


def make_ctypes_callables(lib, c_prefix, dim):
    c_rhs_fn = getattr(lib, f"{c_prefix}_rhs")
    c_jac_fn = getattr(lib, f"{c_prefix}_jac")

    def rhs(x, p):
        x_c = (c_double * dim)(*np.asarray(x, dtype=float).flat)
        out_c = (c_double * dim)()
        c_rhs_fn(c_int(dim), x_c, c_double(float(p)), out_c)
        return np.array([out_c[i] for i in range(dim)])

    def jac(x, p):
        x_c = (c_double * dim)(*np.asarray(x, dtype=float).flat)
        out_c = (c_double * (dim * dim))()
        c_jac_fn(c_int(dim), x_c, c_double(float(p)), out_c)
        return np.array([out_c[i] for i in range(dim * dim)]).reshape(dim, dim)

    return rhs, jac


# ---------- Newton equilibrium solver ----------

def find_equilibrium(rhs, jac, x0, p, tol=1e-12, maxiter=80):
    x = np.array(x0, dtype=float).copy()
    for _ in range(maxiter):
        f = rhs(x, p)
        if np.linalg.norm(f) < tol:
            return x
        J = jac(x, p)
        try:
            dx = np.linalg.solve(J, -f)
        except np.linalg.LinAlgError:
            dx = np.linalg.lstsq(J, -f, rcond=None)[0]
        x += dx
        if np.linalg.norm(dx) < tol:
            break
    return x


# ---------- Tangent computation ----------

def _tangent(jac, rhs, x, p, prev=None, eps=1e-7):
    n = len(x)
    J = jac(x, p)
    fp = (rhs(x, p + eps) - rhs(x, p - eps)) / (2 * eps)
    aug = np.hstack([J, fp.reshape(-1, 1)])
    _, _, Vt = np.linalg.svd(aug)
    t = Vt[-1].copy()
    t /= np.linalg.norm(t)
    if prev is not None and np.dot(t, prev) < 0:
        t = -t
    return t


# ---------- Pseudo-arclength continuation ----------

def continuation(rhs, jac, x0, p0, prange, ds=0.01, maxsteps=5000, direction=1):
    n = len(x0)
    x = find_equilibrium(rhs, jac, x0, p0)
    p = float(p0)
    tang = _tangent(jac, rhs, x, p)
    if direction < 0:
        tang = -tang

    eps_fd = 1e-7
    pts = [_make_pt(x, p, jac)]
    cur_ds = float(ds) * direction

    for _ in range(maxsteps):
        xp = x + cur_ds * tang[:n]
        pp = p + cur_ds * tang[n]

        xn, pn, ok = _correct(rhs, jac, xp, pp, tang, x, p, cur_ds, eps_fd)
        if not ok:
            cur_ds *= 0.5
            if abs(cur_ds) < 1e-9:
                break
            continue

        if pn < prange[0] - 0.5 or pn > prange[1] + 0.5:
            break

        tang = _tangent(jac, rhs, xn, pn, tang)
        x, p = xn, float(pn)
        pts.append(_make_pt(x, p, jac))

        cur_ds = np.clip(float(ds) * direction, -abs(ds) * 3, abs(ds) * 3)

    return pts


def _correct(rhs, jac, xp, pp, tang, x0, p0, ds, eps):
    n = len(xp)
    x = xp.copy()
    p = float(pp)
    for _ in range(40):
        f = rhs(x, p)
        g = np.dot(tang[:n], x - x0) + tang[n] * (p - p0) - ds
        rv = np.concatenate([f, [g]])

        J = jac(x, p)
        fp = (rhs(x, p + eps) - rhs(x, p - eps)) / (2 * eps)
        M = np.zeros((n + 1, n + 1))
        M[:n, :n] = J
        M[:n, n] = fp
        M[n, :n] = tang[:n]
        M[n, n] = tang[n]
        try:
            d = np.linalg.solve(M, -rv)
        except np.linalg.LinAlgError:
            return x, p, False
        x += d[:n]
        p += d[n]
        if np.linalg.norm(d) < 1e-10:
            return x, float(p), True
    return x, float(p), False


def _make_pt(x, p, jac):
    J = jac(x, p)
    return {"x": x.copy(), "p": float(p), "eigs": linalg.eigvals(J)}


# ---------- Bifurcation detection ----------

def detect_bifurcations(pts, rhs, jac):
    folds, hopfs = [], []
    for i in range(1, len(pts)):
        _check_fold(pts[i - 1], pts[i], rhs, jac, folds)
        _check_hopf(pts[i - 1], pts[i], rhs, jac, hopfs)
    return _dedup(folds), _dedup(hopfs)


def _check_fold(prev, curr, rhs, jac, folds):
    pe = prev["eigs"]
    ce = curr["eigs"]
    matching = _match(pe, ce)
    for i1, i2 in matching:
        e1, e2 = pe[i1], ce[i2]
        if abs(e1.imag) < 0.15 and abs(e2.imag) < 0.15:
            if e1.real * e2.real < 0:
                t = abs(e1.real) / (abs(e1.real) + abs(e2.real))
                xb = (1 - t) * prev["x"] + t * curr["x"]
                pb = (1 - t) * prev["p"] + t * curr["p"]
                xb = find_equilibrium(rhs, jac, xb, pb)
                xr, pr = _refine_fold(rhs, jac, xb, pb)
                J = jac(xr, pr)
                eigs = linalg.eigvals(J)
                real_near0 = [e for e in eigs
                              if abs(e.imag) < 0.2 and abs(e.real) < 0.1]
                if real_near0:
                    folds.append({
                        "parameter_value": float(pr),
                        "state": xr.tolist()
                    })


def _check_hopf(prev, curr, rhs, jac, hopfs):
    pe = prev["eigs"]
    ce = curr["eigs"]
    matching = _match(pe, ce)
    for i1, i2 in matching:
        e1, e2 = pe[i1], ce[i2]
        if abs(e1.imag) > 0.03 and abs(e2.imag) > 0.03:
            if e1.real * e2.real < 0 and abs(e1.imag - e2.imag) < 1.0:
                t = abs(e1.real) / (abs(e1.real) + abs(e2.real))
                xb = (1 - t) * prev["x"] + t * curr["x"]
                pb = (1 - t) * prev["p"] + t * curr["p"]
                w0 = abs((1 - t) * e1.imag + t * e2.imag)
                xb = find_equilibrium(rhs, jac, xb, pb)
                xh, ph, w = _refine_hopf(rhs, jac, xb, pb, w0)
                l1 = _first_lyapunov(rhs, jac, xh, ph, w)
                hopfs.append({
                    "parameter_value": float(ph),
                    "state": xh.tolist(),
                    "omega": float(w),
                    "subcritical": bool(l1 > 0),
                })


def _match(eigs1, eigs2):
    n = len(eigs1)
    used = set()
    pairs = []
    for i in range(n):
        best_j, best_d = -1, 1e30
        for j in range(n):
            if j in used:
                continue
            d = abs(eigs1[i] - eigs2[j])
            if d < best_d:
                best_d = d
                best_j = j
        if best_j >= 0:
            pairs.append((i, best_j))
            used.add(best_j)
    return pairs


def _dedup(lst, tol=0.01):
    if not lst:
        return lst
    out = [lst[0]]
    for item in lst[1:]:
        if all(abs(item["parameter_value"] - u["parameter_value"]) > tol
               for u in out):
            out.append(item)
    return out


# ---------- Fold refinement ----------

def _refine_fold(rhs, jac, x0, p0, maxiter=40):
    n = len(x0)
    x = x0.copy()
    p = float(p0)
    eps = 1e-7

    if n == 1:
        for _ in range(maxiter):
            f = rhs(x, p)[0]
            J = jac(x, p)[0, 0]
            fp = (rhs(x, p + eps)[0] - rhs(x, p - eps)[0]) / (2 * eps)
            xpe = x.copy(); xpe[0] += eps
            xme = x.copy(); xme[0] -= eps
            fxx = (jac(xpe, p)[0, 0] - jac(xme, p)[0, 0]) / (2 * eps)
            fxp = (jac(x, p + eps)[0, 0] - jac(x, p - eps)[0, 0]) / (2 * eps)
            M = np.array([[J, fp], [fxx, fxp]])
            r = np.array([f, J])
            try:
                d = np.linalg.solve(M, -r)
            except np.linalg.LinAlgError:
                break
            x[0] += d[0]
            p += d[1]
            if np.linalg.norm(d) < 1e-11:
                break
        return x, p

    J = jac(x, p)
    eigs, VR = linalg.eig(J)
    idx = np.argmin(np.abs(eigs))
    v = np.real(VR[:, idx])
    v /= np.linalg.norm(v)

    for _ in range(maxiter):
        f = rhs(x, p)
        J = jac(x, p)
        Jv = J @ v
        fp = (rhs(x, p + eps) - rhs(x, p - eps)) / (2 * eps)

        Hv = np.zeros((n, n))
        for k in range(n):
            ek = np.zeros(n); ek[k] = eps
            Hv[:, k] = (jac(x + ek, p) @ v - jac(x - ek, p) @ v) / (2 * eps)
        Jpv = (jac(x, p + eps) @ v - jac(x, p - eps) @ v) / (2 * eps)

        M = np.zeros((2 * n + 1, 2 * n + 1))
        M[:n, :n] = J
        M[:n, n] = fp
        M[n:2*n, :n] = Hv
        M[n:2*n, n] = Jpv
        M[n:2*n, n+1:] = J
        M[2*n, n+1:] = 2 * v

        rhs_ext = np.concatenate([-f, -Jv, [0.0]])
        try:
            d = np.linalg.solve(M, rhs_ext)
        except np.linalg.LinAlgError:
            break
        x += d[:n]
        p += d[n]
        v += d[n+1:]
        v /= np.linalg.norm(v)
        if np.linalg.norm(d[:n+1]) < 1e-11:
            break

    return x, p


# ---------- Hopf refinement ----------

def _refine_hopf(rhs, jac, x0, p0, w0, maxiter=40):
    x = x0.copy()
    p = float(p0)
    eps = 1e-7

    for _ in range(maxiter):
        x = find_equilibrium(rhs, jac, x, p)
        J = jac(x, p)
        eigs = linalg.eigvals(J)
        cpx = [e for e in eigs if abs(e.imag) > 0.01]
        if not cpx:
            break
        best = min(cpx, key=lambda e: abs(e.real))
        re = best.real
        w = abs(best.imag)
        if abs(re) < 1e-8:
            break

        xp = find_equilibrium(rhs, jac, x, p + eps)
        Jp = jac(xp, p + eps)
        ep = linalg.eigvals(Jp)
        cpx_p = [e for e in ep if abs(e.imag) > 0.01]
        if not cpx_p:
            break
        best_p = min(cpx_p, key=lambda e: abs(e.imag - w))
        dre = (best_p.real - re) / eps
        if abs(dre) < 1e-14:
            break
        dp = np.clip(-re / dre, -0.2, 0.2)
        p += dp

    x = find_equilibrium(rhs, jac, x, p)
    J = jac(x, p)
    eigs = linalg.eigvals(J)
    cpx = [e for e in eigs if abs(e.imag) > 0.01]
    if cpx:
        w = abs(min(cpx, key=lambda e: abs(e.real)).imag)
    else:
        w = w0
    return x, float(p), float(w)


# ---------- First Lyapunov coefficient ----------

def _first_lyapunov(rhs, jac, x0, p0, omega):
    n = len(x0)
    J = jac(x0, p0)

    A_mat = J - 1j * omega * np.eye(n)
    _, _, Vh = np.linalg.svd(A_mat)
    q = np.conj(Vh[-1]).astype(complex)

    B_mat = J.T + 1j * omega * np.eye(n)
    _, _, Vh2 = np.linalg.svd(B_mat)
    pv = np.conj(Vh2[-1]).astype(complex)

    pq = np.dot(np.conj(pv), q)
    pv = pv / np.conj(pq)

    h = 1e-5
    h3 = 5e-4

    def B(u, v):
        res = np.zeros(n, dtype=complex)
        for ii in range(n):
            for jj in range(n):
                ei = np.zeros(n); ei[ii] = h
                ej = np.zeros(n); ej[jj] = h
                d2f = (rhs(x0 + ei + ej, p0) - rhs(x0 + ei - ej, p0)
                       - rhs(x0 - ei + ej, p0)
                       + rhs(x0 - ei - ej, p0)) / (4 * h**2)
                res += d2f * u[ii] * v[jj]
        return res

    def C(u, v, w):
        res = np.zeros(n, dtype=complex)
        for ii in range(n):
            for jj in range(n):
                for kk in range(n):
                    ei = np.zeros(n); ei[ii] = h3
                    ej = np.zeros(n); ej[jj] = h3
                    ek = np.zeros(n); ek[kk] = h3
                    d3f = (
                        rhs(x0+ei+ej+ek, p0) - rhs(x0+ei+ej-ek, p0)
                        - rhs(x0+ei-ej+ek, p0) + rhs(x0+ei-ej-ek, p0)
                        - rhs(x0-ei+ej+ek, p0) + rhs(x0-ei+ej-ek, p0)
                        + rhs(x0-ei-ej+ek, p0) - rhs(x0-ei-ej-ek, p0)
                    ) / (8 * h3**3)
                    res += d3f * u[ii] * v[jj] * w[kk]
        return res

    qbar = np.conj(q)
    Bqq = B(q, q)
    Bqqbar = B(q, qbar)
    Cqqqbar = C(q, q, qbar)

    try:
        h11 = np.linalg.solve(J.astype(complex), Bqqbar)
    except np.linalg.LinAlgError:
        h11 = np.linalg.lstsq(J.astype(complex), Bqqbar, rcond=None)[0]
    try:
        h20 = np.linalg.solve(
            2j * omega * np.eye(n) - J.astype(complex), Bqq)
    except np.linalg.LinAlgError:
        h20 = np.linalg.lstsq(
            2j * omega * np.eye(n) - J.astype(complex), Bqq, rcond=None)[0]

    l1 = (1.0 / (2.0 * omega)) * np.real(
        np.dot(np.conj(pv), Cqqqbar)
        - 2.0 * np.dot(np.conj(pv), B(q, h11))
        + np.dot(np.conj(pv), B(qbar, h20))
    )
    return float(l1)


# ---------- Continuation data and diagram ----------

def write_continuation_data(all_data, filename="/app/continuation_data.dat"):
    with open(filename, "w") as f:
        f.write("# system_name\tparameter\tstate_norm\tpoint_type\n")
        for sys_name, (pts, folds, hopfs) in all_data.items():
            fold_params = [fp["parameter_value"] for fp in folds]
            hopf_params = [hp["parameter_value"] for hp in hopfs]
            for pt in pts:
                pv = pt["p"]
                norm = float(np.linalg.norm(pt["x"]))
                is_fold = any(abs(pv - fp) < 0.02 for fp in fold_params)
                is_hopf = any(abs(pv - hp) < 0.02 for hp in hopf_params)
                if is_fold:
                    ptype = "fold"
                elif is_hopf:
                    ptype = "hopf"
                else:
                    ptype = "regular"
                f.write(f"{sys_name}\t{pv:.8f}\t{norm:.8f}\t{ptype}\n")


def generate_gnuplot_diagram():
    script = (
        "set terminal pngcairo size 1200,800 enhanced\n"
        "set output '/app/bifurcation_diagram.png'\n"
        "set xlabel 'Parameter'\n"
        "set ylabel '||x||'\n"
        "set title 'Bifurcation Diagram'\n"
        "set key outside right\n"
        'set datafile separator "\\t"\n'
        "plot '< grep -w regular /app/continuation_data.dat'"
        " using 2:3 with dots notitle lc rgb '#4444FF', \\\n"
        "     '< grep -w fold /app/continuation_data.dat'"
        " using 2:3 with points pt 7 ps 2 lc rgb 'red' title 'Fold', \\\n"
        "     '< grep -w hopf /app/continuation_data.dat'"
        " using 2:3 with points pt 5 ps 2 lc rgb '#00AA00' title 'Hopf'\n"
    )
    with open("/app/plot_bifurcation.gp", "w") as f:
        f.write(script)
    subprocess.run(["gnuplot", "/app/plot_bifurcation.gp"], check=True)


# ---------- Per-system analysis ----------

def analyze_system(name, sysdef, rhs, jac_fn):
    x0 = sysdef["initial_state"].copy()
    p0 = sysdef["initial_param"]
    prange = sysdef["param_range"]

    print(f"  Forward continuation ...")
    pts_fwd = continuation(rhs, jac_fn, x0, p0, prange,
                           ds=0.005, maxsteps=4000, direction=1)
    print(f"    {len(pts_fwd)} points")

    print(f"  Backward continuation ...")
    pts_bwd = continuation(rhs, jac_fn, x0, p0, prange,
                           ds=0.005, maxsteps=4000, direction=-1)
    print(f"    {len(pts_bwd)} points")

    allpts = list(reversed(pts_bwd[1:])) + pts_fwd

    print(f"  Detecting bifurcations among {len(allpts)} points ...")
    folds, hopfs = detect_bifurcations(allpts, rhs, jac_fn)

    lo, hi = prange
    folds = [f for f in folds
             if lo - 0.05 <= f["parameter_value"] <= hi + 0.05]
    hopfs = [h for h in hopfs
             if lo - 0.05 <= h["parameter_value"] <= hi + 0.05]

    print(f"  Result: {len(folds)} folds, {len(hopfs)} Hopf points")
    return {"fold_points": folds, "hopf_points": hopfs}, allpts


# ---------- Main ----------

def main():
    # Step 1: Compile C library
    print("Compiling C library...")
    compile_c_library()
    lib = load_c_library()
    assert lib.get_system_count() == 3, "C library verification failed"
    print(f"  Library loaded, {lib.get_system_count()} systems available")

    # Step 2: Run analysis for each system
    results = {}
    all_data = {}
    for name, sysdef in SYSTEMS.items():
        print(f"\nAnalyzing {name} ...")
        c_prefix = C_PREFIX_MAP[name]
        rhs, jac_fn = make_ctypes_callables(lib, c_prefix, sysdef["dim"])

        res, allpts = analyze_system(name, sysdef, rhs, jac_fn)
        results[name] = res
        all_data[name] = (allpts, res["fold_points"], res["hopf_points"])

    # Step 3: Write results JSON
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nResults written to /app/results.json")

    # Step 4: Generate continuation data and gnuplot diagram
    print("Generating bifurcation diagram...")
    write_continuation_data(all_data)
    generate_gnuplot_diagram()
    print("Diagram written to /app/bifurcation_diagram.png")

    # Summary
    for name, data in results.items():
        print(f"\n{name}:")
        for fp in data["fold_points"]:
            print(f"  FOLD p={fp['parameter_value']:.6f}  x={fp['state']}")
        for hp in data["hopf_points"]:
            print(f"  HOPF p={hp['parameter_value']:.6f}"
                  f"  w={hp['omega']:.6f}  sub={hp['subcritical']}")


if __name__ == "__main__":
    main()
