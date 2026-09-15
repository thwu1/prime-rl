#!/usr/bin/env python3
"""
3D Geometrically Exact Beam Finite Element Solver.

2-node beam elements with rotation vector parameterization.
Strains computed via SO(3) logarithm of relative rotation.
Tangent stiffness via numerical differentiation of energy.
Newton-Raphson with left-multiplicative rotation updates.
"""

import json
import sys

import numpy as np


# ------------------------------------------------------------------ #
#  SO(3) utilities                                                    #
# ------------------------------------------------------------------ #

def rodrigues(v):
    """Rotation vector -> 3x3 rotation matrix (Rodrigues formula)."""
    a2 = v[0] * v[0] + v[1] * v[1] + v[2] * v[2]
    if a2 < 1e-30:
        return np.array([[1.0, -v[2], v[1]],
                         [v[2], 1.0, -v[0]],
                         [-v[1], v[0], 1.0]])
    a = np.sqrt(a2)
    c, s = np.cos(a), np.sin(a)
    t = (1.0 - c) / a2
    sa = s / a
    return np.array([
        [c + t * v[0] * v[0], t * v[0] * v[1] - sa * v[2], t * v[0] * v[2] + sa * v[1]],
        [t * v[0] * v[1] + sa * v[2], c + t * v[1] * v[1], t * v[1] * v[2] - sa * v[0]],
        [t * v[0] * v[2] - sa * v[1], t * v[1] * v[2] + sa * v[0], c + t * v[2] * v[2]],
    ])


def log_rot(R):
    """3x3 rotation matrix -> rotation vector."""
    ct = (R[0, 0] + R[1, 1] + R[2, 2] - 1.0) * 0.5
    ct = max(-1.0, min(1.0, ct))
    ang = np.arccos(ct)
    if ang < 1e-10:
        return np.array([R[2, 1] - R[1, 2],
                         R[0, 2] - R[2, 0],
                         R[1, 0] - R[0, 1]]) * 0.5
    if ang > np.pi - 1e-6:
        B = R + np.eye(3)
        n0 = B[0, 0] ** 2 + B[1, 0] ** 2 + B[2, 0] ** 2
        n1 = B[0, 1] ** 2 + B[1, 1] ** 2 + B[2, 1] ** 2
        n2 = B[0, 2] ** 2 + B[1, 2] ** 2 + B[2, 2] ** 2
        j = 0 if n0 >= n1 and n0 >= n2 else (1 if n1 >= n2 else 2)
        nm = np.sqrt([n0, n1, n2][j])
        ax = B[:, j] / nm
        return ax * ang
    fac = ang / (2.0 * np.sin(ang))
    return np.array([R[2, 1] - R[1, 2],
                     R[0, 2] - R[2, 0],
                     R[1, 0] - R[0, 1]]) * fac


# ------------------------------------------------------------------ #
#  Element computations                                               #
# ------------------------------------------------------------------ #

_E1 = np.array([1.0, 0.0, 0.0])


def _elem_energy(r1, R1, r2, R2, L0, Cg, Ck):
    """Strain energy of one 2-node beam element."""
    phi = log_rot(R1.T @ R2)
    Rm = R1 @ rodrigues(0.5 * phi)
    gam = Rm.T @ (r2 - r1) / L0 - _E1
    kap = phi / L0
    return 0.5 * L0 * (
        gam[0] ** 2 * Cg[0] + gam[1] ** 2 * Cg[1] + gam[2] ** 2 * Cg[2]
        + kap[0] ** 2 * Ck[0] + kap[1] ** 2 * Ck[1] + kap[2] ** 2 * Ck[2]
    )


def _elem_residual(r1, R1, r2, R2, L0, Cg, Ck, h=1e-7):
    """Element internal force vector (12 DOFs) via central FD of energy."""
    f = np.empty(12)
    dth = np.zeros(3)
    for d in range(3):
        # node-1 translation
        r1p = r1.copy(); r1p[d] += h
        r1m = r1.copy(); r1m[d] -= h
        f[d] = (_elem_energy(r1p, R1, r2, R2, L0, Cg, Ck)
                - _elem_energy(r1m, R1, r2, R2, L0, Cg, Ck)) / (2.0 * h)
        # node-1 rotation
        dth[:] = 0.0; dth[d] = h
        Rp1 = rodrigues(dth) @ R1
        dth[d] = -h
        Rm1 = rodrigues(dth) @ R1
        f[3 + d] = (_elem_energy(r1, Rp1, r2, R2, L0, Cg, Ck)
                     - _elem_energy(r1, Rm1, r2, R2, L0, Cg, Ck)) / (2.0 * h)
        # node-2 translation
        r2p = r2.copy(); r2p[d] += h
        r2m = r2.copy(); r2m[d] -= h
        f[6 + d] = (_elem_energy(r1, R1, r2p, R2, L0, Cg, Ck)
                     - _elem_energy(r1, R1, r2m, R2, L0, Cg, Ck)) / (2.0 * h)
        # node-2 rotation
        dth[:] = 0.0; dth[d] = h
        Rp2 = rodrigues(dth) @ R2
        dth[d] = -h
        Rm2 = rodrigues(dth) @ R2
        f[9 + d] = (_elem_energy(r1, R1, r2, Rp2, L0, Cg, Ck)
                     - _elem_energy(r1, R1, r2, Rm2, L0, Cg, Ck)) / (2.0 * h)
    return f


def _elem_tangent(r1, R1, r2, R2, L0, Cg, Ck, h_f=1e-7, h_k=5e-7):
    """Element 12x12 tangent stiffness via FD of the residual."""
    K = np.empty((12, 12))
    dth = np.zeros(3)
    for j in range(12):
        node = j // 6
        loc = j % 6
        d = loc % 3
        is_rot = loc >= 3
        if node == 0:
            if is_rot:
                dth[:] = 0; dth[d] = h_k
                fp = _elem_residual(r1, rodrigues(dth) @ R1, r2, R2, L0, Cg, Ck, h_f)
                dth[d] = -h_k
                fm = _elem_residual(r1, rodrigues(dth) @ R1, r2, R2, L0, Cg, Ck, h_f)
            else:
                r1p = r1.copy(); r1p[d] += h_k
                r1m = r1.copy(); r1m[d] -= h_k
                fp = _elem_residual(r1p, R1, r2, R2, L0, Cg, Ck, h_f)
                fm = _elem_residual(r1m, R1, r2, R2, L0, Cg, Ck, h_f)
        else:
            if is_rot:
                dth[:] = 0; dth[d] = h_k
                fp = _elem_residual(r1, R1, r2, rodrigues(dth) @ R2, L0, Cg, Ck, h_f)
                dth[d] = -h_k
                fm = _elem_residual(r1, R1, r2, rodrigues(dth) @ R2, L0, Cg, Ck, h_f)
            else:
                r2p = r2.copy(); r2p[d] += h_k
                r2m = r2.copy(); r2m[d] -= h_k
                fp = _elem_residual(r1, R1, r2p, R2, L0, Cg, Ck, h_f)
                fm = _elem_residual(r1, R1, r2m, R2, L0, Cg, Ck, h_f)
        K[:, j] = (fp - fm) / (2.0 * h_k)
    return K


# ------------------------------------------------------------------ #
#  Global Newton-Raphson solver                                       #
# ------------------------------------------------------------------ #

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
    nf = 6 * ne  # free DOFs (node 0 clamped)
    L0 = L / ne

    # state
    pos = [np.array([i * L0, 0.0, 0.0]) for i in range(nn)]
    rot = [np.eye(3) for _ in range(nn)]

    # external load on free DOFs
    tip_start = 6 * (ne - 1)

    for step in range(1, nstep + 1):
        lf = step / nstep
        f_ext = np.zeros(nf)
        f_ext[tip_start:tip_start + 3] = lf * tf
        f_ext[tip_start + 3:tip_start + 6] = lf * tm

        ok = False
        for it in range(maxit):
            fint = np.zeros(nf)
            Kg = np.zeros((nf, nf))

            for e in range(ne):
                fe = _elem_residual(pos[e], rot[e], pos[e + 1], rot[e + 1],
                                    L0, Cg, Ck)
                Ke = _elem_tangent(pos[e], rot[e], pos[e + 1], rot[e + 1],
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
            rn = np.linalg.norm(res)
            if rn < tol:
                ok = True
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
                "tip_displacement": (pos[tip] - np.array([L, 0.0, 0.0])).tolist(),
                "tip_rotation": log_rot(rot[tip]).tolist(),
                "num_load_steps_completed": step - 1,
            }

    tip = nn - 1
    return {
        "converged": True,
        "tip_displacement": (pos[tip] - np.array([L, 0.0, 0.0])).tolist(),
        "tip_rotation": log_rot(rot[tip]).tolist(),
        "num_load_steps_completed": nstep,
    }


# ------------------------------------------------------------------ #
#  CLI entry point                                                    #
# ------------------------------------------------------------------ #

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python3 beam_solver.py <input.json> <output.json>",
              file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as fh:
        config = json.load(fh)

    result = solve_beam(config)

    with open(sys.argv[2], "w") as fh:
        json.dump(result, fh, indent=2)

    sys.exit(0)
