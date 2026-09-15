#!/usr/bin/env python3
"""
Beam analysis pipeline: parse MBDyn .mbd files, compile/use C SO(3)
library, solve nonlinear beam FE problems, validate convergence.
"""

import ctypes
import glob
import json
import math
import os
import re
import subprocess
import sys

import numpy as np

# ------------------------------------------------------------------ #
#  C library build / load                                             #
# ------------------------------------------------------------------ #

_lib = None
_dp = ctypes.POINTER(ctypes.c_double)


def _get_lib():
    global _lib
    if _lib is not None:
        return _lib
    kdir = "/app/kernels"
    so_path = os.path.join(kdir, "libso3.so")
    if not os.path.isfile(so_path):
        subprocess.run(["make", "-C", kdir], check=True,
                       capture_output=True, text=True)
    _lib = ctypes.CDLL(so_path)
    _lib.so3_rodrigues.argtypes = [_dp, _dp]
    _lib.so3_rodrigues.restype = None
    _lib.so3_log.argtypes = [_dp, _dp]
    _lib.so3_log.restype = None
    return _lib


def rodrigues(v):
    lib = _get_lib()
    v_c = np.ascontiguousarray(v, dtype=np.float64)
    R_c = np.empty(9, dtype=np.float64)
    lib.so3_rodrigues(v_c.ctypes.data_as(_dp), R_c.ctypes.data_as(_dp))
    return R_c.reshape(3, 3, order='F')  # column-major -> numpy


def log_rot(R):
    lib = _get_lib()
    R_c = np.ascontiguousarray(R.flatten(order='F'), dtype=np.float64)
    v_c = np.empty(3, dtype=np.float64)
    lib.so3_log(R_c.ctypes.data_as(_dp), v_c.ctypes.data_as(_dp))
    return v_c.copy()


# ------------------------------------------------------------------ #
#  MBDyn parser                                                       #
# ------------------------------------------------------------------ #

def parse_mbd(filepath):
    with open(filepath) as f:
        text = f.read()

    # Strip comments
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
    text = re.sub(r'#[^\n]*', '', text)

    # Collect set: definitions
    variables = {}
    for m in re.finditer(r'set\s*:\s*(?:real|integer)\s+(\w+)\s*=\s*([^;]+);',
                         text):
        name = m.group(1).strip()
        val_s = m.group(2).strip()
        try:
            variables[name] = float(val_s)
        except ValueError:
            try:
                variables[name] = eval(val_s, {"__builtins__": {}}, variables)
            except Exception:
                pass

    def _sub(tok):
        tok = tok.strip()
        return str(variables[tok]) if tok in variables else tok

    def _extract(bname):
        pat = (r'begin\s*:\s*' + re.escape(bname) +
               r'\s*;(.*?)end\s*:\s*' + re.escape(bname) + r'\s*;')
        m = re.search(pat, text, re.DOTALL)
        return m.group(1) if m else ""

    # ---- initial value block ----
    iv = _extract("initial value")

    def _param(name, default):
        p = name.replace(' ', r'\s+') + r'\s*:\s*([^;]+);'
        m = re.search(p, iv)
        return float(_sub(m.group(1).strip())) if m else default

    max_iter = int(_param("max iterations", 50))
    tol = _param("tolerance", 1e-6)
    t0 = _param("initial time", 0.0)
    t1 = _param("final time", 1.0)
    dt = _param("time step", 1.0)
    num_steps = max(1, int(round((t1 - t0) / dt)))

    # ---- nodes ----
    ntext = _extract("nodes")
    nodes = {}
    for m in re.finditer(
            r'structural\s*:\s*(\d+)\s*,\s*\w+\s*,\s*([^;]+);', ntext):
        nid = int(m.group(1))
        parts = m.group(2).split(',')
        coords = [float(_sub(parts[i])) for i in range(3)]
        nodes[nid] = coords

    # ---- elements ----
    etext = _extract("elements")

    # clamped node
    clamp_node = None
    cm = re.search(r'joint\s*:\s*\d+\s*,\s*clamp\s*,\s*(\d+)', etext)
    if cm:
        clamp_node = int(cm.group(1))

    # beam stiffness (first diag occurrence)
    stiffness = None
    dm = re.search(
        r'diag\s*,\s*([\w.eE+-]+)\s*,\s*([\w.eE+-]+)\s*,\s*([\w.eE+-]+)'
        r'\s*,\s*([\w.eE+-]+)\s*,\s*([\w.eE+-]+)\s*,\s*([\w.eE+-]+)',
        etext)
    if dm:
        vals = [float(_sub(dm.group(i))) for i in range(1, 7)]
        stiffness = dict(zip(
            ["EA", "GAy", "GAz", "GJ", "EIy", "EIz"], vals))

    # forces
    tip_force = np.zeros(3)
    sorted_ids = sorted(nodes.keys(), key=lambda i: nodes[i][0])
    tip_nid = sorted_ids[-1]

    for fm in re.finditer(
            r'force\s*:\s*\d+\s*,\s*absolute\s*,\s*(\d+)\s*,'
            r'\s*position\s*,\s*null\s*,'
            r'\s*([\d.eE+-]+)\s*,\s*([\d.eE+-]+)\s*,\s*([\d.eE+-]+)\s*,'
            r'\s*const\s*,\s*([\d.eE+-]+)', etext):
        nd = int(fm.group(1))
        if nd == tip_nid:
            dx = float(fm.group(2))
            dy = float(fm.group(3))
            dz = float(fm.group(4))
            mag = float(fm.group(5))
            tip_force += mag * np.array([dx, dy, dz])

    # couples
    tip_moment = np.zeros(3)
    for cm2 in re.finditer(
            r'couple\s*:\s*\d+\s*,\s*absolute\s*,\s*(\d+)\s*,'
            r'\s*([\d.eE+-]+)\s*,\s*([\d.eE+-]+)\s*,\s*([\d.eE+-]+)\s*,'
            r'\s*const\s*,\s*([\d.eE+-]+)', etext):
        nd = int(cm2.group(1))
        if nd == tip_nid:
            dx = float(cm2.group(2))
            dy = float(cm2.group(3))
            dz = float(cm2.group(4))
            mag = float(cm2.group(5))
            tip_moment += mag * np.array([dx, dy, dz])

    beam_length = np.linalg.norm(
        np.array(nodes[sorted_ids[-1]]) - np.array(nodes[sorted_ids[0]]))
    num_elements = len(sorted_ids) - 1

    return {
        "beam": {
            "length": float(beam_length),
            "num_elements": num_elements,
            "stiffness": stiffness,
        },
        "loading": {
            "tip_force": tip_force.tolist(),
            "tip_moment": tip_moment.tolist(),
        },
        "solver": {
            "num_load_steps": num_steps,
            "tolerance": tol,
            "max_iterations": max_iter,
        },
    }


# ------------------------------------------------------------------ #
#  Beam FE solver                                                     #
# ------------------------------------------------------------------ #

_E1 = np.array([1.0, 0.0, 0.0])


def _energy(r1, R1, r2, R2, L0, Cg, Ck):
    phi = log_rot(R1.T @ R2)
    Rm = R1 @ rodrigues(0.5 * phi)
    gam = Rm.T @ (r2 - r1) / L0 - _E1
    kap = phi / L0
    return 0.5 * L0 * (
        gam[0]**2 * Cg[0] + gam[1]**2 * Cg[1] + gam[2]**2 * Cg[2]
        + kap[0]**2 * Ck[0] + kap[1]**2 * Ck[1] + kap[2]**2 * Ck[2])


def _residual(r1, R1, r2, R2, L0, Cg, Ck, h=1e-7):
    f = np.empty(12)
    dth = np.zeros(3)
    for d in range(3):
        r1p = r1.copy(); r1p[d] += h
        r1m = r1.copy(); r1m[d] -= h
        f[d] = (_energy(r1p, R1, r2, R2, L0, Cg, Ck)
                - _energy(r1m, R1, r2, R2, L0, Cg, Ck)) / (2 * h)
        dth[:] = 0; dth[d] = h
        Rp = rodrigues(dth) @ R1
        dth[d] = -h
        Rm = rodrigues(dth) @ R1
        f[3 + d] = (_energy(r1, Rp, r2, R2, L0, Cg, Ck)
                     - _energy(r1, Rm, r2, R2, L0, Cg, Ck)) / (2 * h)
        r2p = r2.copy(); r2p[d] += h
        r2m = r2.copy(); r2m[d] -= h
        f[6 + d] = (_energy(r1, R1, r2p, R2, L0, Cg, Ck)
                     - _energy(r1, R1, r2m, R2, L0, Cg, Ck)) / (2 * h)
        dth[:] = 0; dth[d] = h
        Rp2 = rodrigues(dth) @ R2
        dth[d] = -h
        Rm2 = rodrigues(dth) @ R2
        f[9 + d] = (_energy(r1, R1, r2, Rp2, L0, Cg, Ck)
                     - _energy(r1, R1, r2, Rm2, L0, Cg, Ck)) / (2 * h)
    return f


def _tangent(r1, R1, r2, R2, L0, Cg, Ck, hf=1e-7, hk=5e-7):
    K = np.empty((12, 12))
    dth = np.zeros(3)
    for j in range(12):
        nd = j // 6
        loc = j % 6
        d = loc % 3
        rot = loc >= 3
        if nd == 0:
            if rot:
                dth[:] = 0; dth[d] = hk
                fp = _residual(r1, rodrigues(dth) @ R1, r2, R2, L0, Cg, Ck, hf)
                dth[d] = -hk
                fm = _residual(r1, rodrigues(dth) @ R1, r2, R2, L0, Cg, Ck, hf)
            else:
                rp = r1.copy(); rp[d] += hk
                rm = r1.copy(); rm[d] -= hk
                fp = _residual(rp, R1, r2, R2, L0, Cg, Ck, hf)
                fm = _residual(rm, R1, r2, R2, L0, Cg, Ck, hf)
        else:
            if rot:
                dth[:] = 0; dth[d] = hk
                fp = _residual(r1, R1, r2, rodrigues(dth) @ R2, L0, Cg, Ck, hf)
                dth[d] = -hk
                fm = _residual(r1, R1, r2, rodrigues(dth) @ R2, L0, Cg, Ck, hf)
            else:
                rp = r2.copy(); rp[d] += hk
                rm = r2.copy(); rm[d] -= hk
                fp = _residual(r1, R1, rp, R2, L0, Cg, Ck, hf)
                fm = _residual(r1, R1, rm, R2, L0, Cg, Ck, hf)
        K[:, j] = (fp - fm) / (2 * hk)
    return K


def solve_beam(cfg):
    L = cfg["beam"]["length"]
    ne = cfg["beam"]["num_elements"]
    st = cfg["beam"]["stiffness"]
    Cg = np.array([st["EA"], st["GAy"], st["GAz"]])
    Ck = np.array([st["GJ"], st["EIy"], st["EIz"]])
    tf = np.array(cfg["loading"]["tip_force"], dtype=float)
    tm = np.array(cfg["loading"]["tip_moment"], dtype=float)
    nstep = cfg["solver"]["num_load_steps"]
    tol = cfg["solver"]["tolerance"]
    maxit = cfg["solver"]["max_iterations"]

    nn = ne + 1
    nf = 6 * ne
    L0 = L / ne

    pos = [np.array([i * L0, 0.0, 0.0]) for i in range(nn)]
    rot = [np.eye(3) for _ in range(nn)]

    tip_off = 6 * (ne - 1)
    last_residual = 0.0

    for step in range(1, nstep + 1):
        lf = step / nstep
        f_ext = np.zeros(nf)
        f_ext[tip_off:tip_off + 3] = lf * tf
        f_ext[tip_off + 3:tip_off + 6] = lf * tm

        ok = False
        rn = float('inf')
        for _ in range(maxit):
            fint = np.zeros(nf)
            Kg = np.zeros((nf, nf))
            for e in range(ne):
                fe = _residual(pos[e], rot[e], pos[e + 1], rot[e + 1],
                               L0, Cg, Ck)
                Ke = _tangent(pos[e], rot[e], pos[e + 1], rot[e + 1],
                              L0, Cg, Ck)
                for a in range(12):
                    an = e + a // 6
                    al = a % 6
                    if an == 0:
                        continue
                    ai = 6 * (an - 1) + al
                    fint[ai] += fe[a]
                    for b in range(12):
                        bn = e + b // 6
                        bl = b % 6
                        if bn == 0:
                            continue
                        bi = 6 * (bn - 1) + bl
                        Kg[ai, bi] += Ke[a, b]

            res = f_ext - fint
            rn = float(np.linalg.norm(res))
            if rn < tol:
                ok = True
                last_residual = rn
                break
            try:
                du = np.linalg.solve(Kg, res)
            except np.linalg.LinAlgError:
                break
            for n in range(1, nn):
                idx = 6 * (n - 1)
                pos[n] = pos[n] + du[idx:idx + 3]
                rot[n] = rodrigues(du[idx + 3:idx + 6]) @ rot[n]

        if not ok:
            tip = nn - 1
            return {
                "converged": False,
                "tip_displacement": (
                    pos[tip] - np.array([L, 0.0, 0.0])).tolist(),
                "tip_rotation": log_rot(rot[tip]).tolist(),
                "final_residual": rn,
            }

    tip = nn - 1
    return {
        "converged": True,
        "tip_displacement": (pos[tip] - np.array([L, 0.0, 0.0])).tolist(),
        "tip_rotation": log_rot(rot[tip]).tolist(),
        "final_residual": last_residual,
    }


# ------------------------------------------------------------------ #
#  Main pipeline                                                      #
# ------------------------------------------------------------------ #

def main():
    _get_lib()  # compile + load

    model_dir = "/app/models"
    res_dir = "/app/results"
    os.makedirs(res_dir, exist_ok=True)

    mbd_files = sorted(glob.glob(os.path.join(model_dir, "*.mbd")))
    if not mbd_files:
        print("No .mbd files found in", model_dir, file=sys.stderr)
        sys.exit(1)

    validation = {"models": {}, "all_pass": True}

    for mf in mbd_files:
        stem = os.path.splitext(os.path.basename(mf))[0]
        print(f"[pipeline] {stem} ...", end=" ", flush=True)

        cfg = parse_mbd(mf)
        result = solve_beam(cfg)
        result["model"] = stem

        out_path = os.path.join(res_dir, f"{stem}.json")
        with open(out_path, "w") as f:
            json.dump(result, f, indent=2)

        converged = result["converged"]
        final_res = result.get("final_residual", 0.0)
        passed = converged

        validation["models"][stem] = {
            "converged": converged,
            "final_residual": final_res,
            "pass": passed,
        }
        if not passed:
            validation["all_pass"] = False
        print("PASS" if passed else "FAIL", flush=True)

    with open("/app/validation.json", "w") as f:
        json.dump(validation, f, indent=2)

    if not validation["all_pass"]:
        print("[pipeline] VALIDATION FAILED", file=sys.stderr)
        sys.exit(1)

    print("[pipeline] All models validated.")
    sys.exit(0)


if __name__ == "__main__":
    main()
