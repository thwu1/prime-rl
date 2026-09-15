#!/usr/bin/env python3
"""
B-Rep surface geometry pipeline.
Reads JSON surface definitions, computes geometric properties,
exports STEP files (pure Python ISO 10303-21 writer), and generates
triangulated surface meshes in Gmsh MSH 2.2 format.

No external dependencies — uses only Python stdlib.
"""

import json
import math
import os
import glob


# =====================================================================
# Vector utilities
# =====================================================================

def vadd(a, b):
    return [a[i] + b[i] for i in range(3)]

def vsub(a, b):
    return [a[i] - b[i] for i in range(3)]

def vscale(a, s):
    return [a[i] * s for i in range(3)]

def vdot(a, b):
    return sum(a[i] * b[i] for i in range(3))

def vcross(a, b):
    return [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]

def vnorm(a):
    return math.sqrt(vdot(a, a))

def vnormalize(a):
    m = vnorm(a)
    return [a[i] / m for i in range(3)] if m > 1e-15 else [0.0, 0.0, 0.0]


# =====================================================================
# B-spline basis functions (Cox-de Boor algorithm)
# =====================================================================

def find_span(knots, n, p, u):
    """Find knot span index for parameter u."""
    if u >= knots[n]:
        return n - 1
    if u <= knots[p]:
        return p
    lo, hi = p, n
    mid = (lo + hi) // 2
    while u < knots[mid] or u >= knots[mid + 1]:
        if u < knots[mid]:
            hi = mid
        else:
            lo = mid
        mid = (lo + hi) // 2
    return mid

def basis_funs(knots, span, p, u):
    """Compute all non-zero basis functions at u. Returns p+1 values."""
    N = [0.0] * (p + 1)
    left = [0.0] * (p + 1)
    right = [0.0] * (p + 1)
    N[0] = 1.0
    for j in range(1, p + 1):
        left[j] = u - knots[span + 1 - j]
        right[j] = knots[span + j] - u
        saved = 0.0
        for r in range(j):
            denom = right[r + 1] + left[j - r]
            if abs(denom) < 1e-15:
                temp = 0.0
            else:
                temp = N[r] / denom
            N[r] = saved + right[r + 1] * temp
            saved = left[j - r] * temp
        N[j] = saved
    return N

def basis_funs_derivs(knots, span, p, u, n_deriv):
    """Compute basis functions and derivatives up to order n_deriv.
    Returns ders[k][j] = d^k N_{span-p+j, p}(u) / du^k.
    """
    ndu = [[0.0] * (p + 1) for _ in range(p + 1)]
    a = [[0.0] * (p + 1) for _ in range(2)]
    left = [0.0] * (p + 1)
    right = [0.0] * (p + 1)

    ndu[0][0] = 1.0
    for j in range(1, p + 1):
        left[j] = u - knots[span + 1 - j]
        right[j] = knots[span + j] - u
        saved = 0.0
        for r in range(j):
            ndu[j][r] = right[r + 1] + left[j - r]
            temp = ndu[r][j - 1] / ndu[j][r] if abs(ndu[j][r]) > 1e-15 else 0.0
            ndu[r][j] = saved + right[r + 1] * temp
            saved = left[j - r] * temp
        ndu[j][j] = saved

    ders = [[0.0] * (p + 1) for _ in range(n_deriv + 1)]
    for j in range(p + 1):
        ders[0][j] = ndu[j][p]

    for r in range(p + 1):
        s1, s2 = 0, 1
        a[0][0] = 1.0
        for k in range(1, n_deriv + 1):
            d = 0.0
            rk = r - k
            pk = p - k
            if rk >= 0:
                a[s2][0] = a[s1][0] / ndu[pk + 1][rk] if abs(ndu[pk + 1][rk]) > 1e-15 else 0.0
                d = a[s2][0] * ndu[rk][pk]
            j1 = 1 if rk >= -1 else -rk
            j2 = k - 1 if r - 1 <= pk else p - r
            for j in range(j1, j2 + 1):
                denom = ndu[pk + 1][rk + j]
                a[s2][j] = (a[s1][j] - a[s1][j - 1]) / denom if abs(denom) > 1e-15 else 0.0
                d += a[s2][j] * ndu[rk + j][pk]
            if r <= pk:
                denom = ndu[pk + 1][r]
                a[s2][k] = -a[s1][k - 1] / denom if abs(denom) > 1e-15 else 0.0
                d += a[s2][k] * ndu[r][pk]
            ders[k][r] = d
            s1, s2 = s2, s1

    r = p
    for k in range(1, n_deriv + 1):
        for j in range(p + 1):
            ders[k][j] *= r
        r *= (p - k)

    return ders


# =====================================================================
# Surface evaluation
# =====================================================================

def eval_surface(surf, u, v):
    """Evaluate B-spline/NURBS surface point at (u, v)."""
    pu = surf["degree_u"]
    pv = surf["degree_v"]
    ku = surf["knots_u"]
    kv = surf["knots_v"]
    cp = surf["control_points"]
    weights = surf.get("weights")

    nu = len(cp)
    nv = len(cp[0])

    span_u = find_span(ku, nu, pu, u)
    span_v = find_span(kv, nv, pv, v)
    Nu = basis_funs(ku, span_u, pu, u)
    Nv = basis_funs(kv, span_v, pv, v)

    if weights is not None:
        sw = [0.0, 0.0, 0.0]
        w_sum = 0.0
        for i in range(pu + 1):
            ci = span_u - pu + i
            for j in range(pv + 1):
                cj = span_v - pv + j
                w = weights[ci][cj]
                b = Nu[i] * Nv[j] * w
                for k in range(3):
                    sw[k] += b * cp[ci][cj][k]
                w_sum += b
        return [sw[k] / w_sum for k in range(3)]
    else:
        pt = [0.0, 0.0, 0.0]
        for i in range(pu + 1):
            ci = span_u - pu + i
            for j in range(pv + 1):
                cj = span_v - pv + j
                b = Nu[i] * Nv[j]
                for k in range(3):
                    pt[k] += b * cp[ci][cj][k]
        return pt


def eval_surface_derivs(surf, u, v, d=2):
    """Evaluate surface derivatives up to order d.
    For NURBS, uses finite differences to avoid quotient rule complexity.
    """
    weights = surf.get("weights")
    if weights is not None:
        return _eval_nurbs_derivs_numerical(surf, u, v, d)

    pu = surf["degree_u"]
    pv = surf["degree_v"]
    ku = surf["knots_u"]
    kv = surf["knots_v"]
    cp = surf["control_points"]

    nu = len(cp)
    nv = len(cp[0])

    span_u = find_span(ku, nu, pu, u)
    span_v = find_span(kv, nv, pv, v)

    du = min(d, pu)
    dv = min(d, pv)

    Nu_ders = basis_funs_derivs(ku, span_u, pu, u, du)
    Nv_ders = basis_funs_derivs(kv, span_v, pv, v, dv)

    SKL = [[[0.0, 0.0, 0.0] for _ in range(d + 1)] for _ in range(d + 1)]
    for ku_d in range(du + 1):
        for kv_d in range(dv + 1):
            for i in range(pu + 1):
                ci = span_u - pu + i
                for j in range(pv + 1):
                    cj = span_v - pv + j
                    b = Nu_ders[ku_d][i] * Nv_ders[kv_d][j]
                    for c in range(3):
                        SKL[ku_d][kv_d][c] += b * cp[ci][cj][c]
    return SKL


def _eval_nurbs_derivs_numerical(surf, u, v, d=2):
    """Numerical derivatives for NURBS surfaces via central differences."""
    SKL = [[[0.0, 0.0, 0.0] for _ in range(d + 1)] for _ in range(d + 1)]
    SKL[0][0] = eval_surface(surf, u, v)

    h = 1e-6
    u_lo = max(u - h, 0.0)
    u_hi = min(u + h, 1.0)
    v_lo = max(v - h, 0.0)
    v_hi = min(v + h, 1.0)
    hu = (u_hi - u_lo) / 2.0
    hv = (v_hi - v_lo) / 2.0

    Su_p = eval_surface(surf, u_hi, v)
    Su_m = eval_surface(surf, u_lo, v)
    Sv_p = eval_surface(surf, u, v_hi)
    Sv_m = eval_surface(surf, u, v_lo)

    SKL[1][0] = [(Su_p[k] - Su_m[k]) / (2 * hu) for k in range(3)]
    SKL[0][1] = [(Sv_p[k] - Sv_m[k]) / (2 * hv) for k in range(3)]

    if d >= 2:
        S0 = SKL[0][0]
        SKL[2][0] = [(Su_p[k] - 2 * S0[k] + Su_m[k]) / (hu * hu) for k in range(3)]
        SKL[0][2] = [(Sv_p[k] - 2 * S0[k] + Sv_m[k]) / (hv * hv) for k in range(3)]

        Spp = eval_surface(surf, u_hi, v_hi)
        Spm = eval_surface(surf, u_hi, v_lo)
        Smp = eval_surface(surf, u_lo, v_hi)
        Smm = eval_surface(surf, u_lo, v_lo)
        SKL[1][1] = [(Spp[k] - Spm[k] - Smp[k] + Smm[k]) / (4 * hu * hv) for k in range(3)]

    return SKL


# =====================================================================
# Differential geometry
# =====================================================================

def compute_normal(surf, u, v):
    """Compute unit surface normal at (u, v)."""
    SKL = eval_surface_derivs(surf, u, v, d=1)
    Su = SKL[1][0]
    Sv = SKL[0][1]
    n = vcross(Su, Sv)
    return vnormalize(n)


def compute_curvatures(surf, u, v):
    """Compute Gaussian and mean curvature at (u, v)."""
    SKL = eval_surface_derivs(surf, u, v, d=2)
    Su = SKL[1][0]
    Sv = SKL[0][1]
    Suu = SKL[2][0]
    Svv = SKL[0][2]
    Suv = SKL[1][1]

    n = vcross(Su, Sv)
    mag = vnorm(n)
    if mag < 1e-12:
        return 0.0, 0.0
    n = vscale(n, 1.0 / mag)

    E = vdot(Su, Su)
    F = vdot(Su, Sv)
    G = vdot(Sv, Sv)
    eL = vdot(Suu, n)
    eM = vdot(Suv, n)
    eN = vdot(Svv, n)

    denom = E * G - F * F
    if abs(denom) < 1e-14:
        return 0.0, 0.0

    K = (eL * eN - eM * eM) / denom
    H = (E * eN - 2 * F * eM + G * eL) / (2 * denom)
    return K, H


# =====================================================================
# Surface area via composite Gauss-Legendre quadrature
# =====================================================================

def gauss_legendre_nodes(n):
    """Compute Gauss-Legendre nodes and weights on [-1, 1]."""
    nodes = []
    weights = []
    for i in range(n):
        x = math.cos(math.pi * (i + 0.75) / (n + 0.5))
        for _ in range(100):
            p0, p1 = 1.0, x
            for j in range(2, n + 1):
                p2 = ((2 * j - 1) * x * p1 - (j - 1) * p0) / j
                p0, p1 = p1, p2
            dp = n * (x * p1 - p0) / (x * x - 1.0) if abs(x * x - 1.0) > 1e-15 else 0.0
            dx = p1 / dp if abs(dp) > 1e-15 else 0.0
            x -= dx
            if abs(dx) < 1e-15:
                break
        nodes.append(x)
        dp = n * (x * p1 - p0) / (x * x - 1.0) if abs(x * x - 1.0) > 1e-15 else 1.0
        weights.append(2.0 / ((1.0 - x * x) * dp * dp) if abs(dp) > 1e-15 else 0.0)
    return nodes, weights


def compute_area(surf, n_gauss=12, n_sub=6):
    """Compute surface area using composite Gauss-Legendre quadrature on [0,1]^2."""
    nodes, weights = gauss_legendre_nodes(n_gauss)
    sub_h = 1.0 / n_sub
    h = 1e-6
    area = 0.0

    for si in range(n_sub):
        for sj in range(n_sub):
            u_start = si * sub_h
            v_start = sj * sub_h
            for i, nd_u in enumerate(nodes):
                u = u_start + (nd_u + 1.0) / 2.0 * sub_h
                for j, nd_v in enumerate(nodes):
                    v = v_start + (nd_v + 1.0) / 2.0 * sub_h

                    u_lo = max(u - h, 0.0)
                    u_hi = min(u + h, 1.0)
                    v_lo = max(v - h, 0.0)
                    v_hi = min(v + h, 1.0)
                    hu = (u_hi - u_lo) / 2.0
                    hv = (v_hi - v_lo) / 2.0

                    Su_p = eval_surface(surf, u_hi, v)
                    Su_m = eval_surface(surf, u_lo, v)
                    Sv_p = eval_surface(surf, u, v_hi)
                    Sv_m = eval_surface(surf, u, v_lo)

                    Su = [(Su_p[k] - Su_m[k]) / (2 * hu) for k in range(3)]
                    Sv = [(Sv_p[k] - Sv_m[k]) / (2 * hv) for k in range(3)]

                    c = vcross(Su, Sv)
                    area += vnorm(c) * weights[i] / 2.0 * sub_h * weights[j] / 2.0 * sub_h

    return area


# =====================================================================
# Point projection (closest point on surface)
# =====================================================================

def project_point(surf, query, n_init=20, max_iter=100, tol=1e-10):
    """Find closest point on surface to query point via Newton iteration."""
    best_u, best_v = 0.5, 0.5
    best_dist2 = float("inf")

    for i in range(n_init + 1):
        for j in range(n_init + 1):
            u = i / n_init
            v = j / n_init
            pt = eval_surface(surf, u, v)
            d2 = sum((pt[k] - query[k]) ** 2 for k in range(3))
            if d2 < best_dist2:
                best_dist2 = d2
                best_u, best_v = u, v

    u, v = best_u, best_v
    h = 1e-6

    for iteration in range(max_iter):
        pt = eval_surface(surf, u, v)
        diff = vsub(pt, query)

        u_lo = max(u - h, 0.0)
        u_hi = min(u + h, 1.0)
        v_lo = max(v - h, 0.0)
        v_hi = min(v + h, 1.0)
        hu = (u_hi - u_lo) / 2.0
        hv = (v_hi - v_lo) / 2.0

        Su_p = eval_surface(surf, u_hi, v)
        Su_m = eval_surface(surf, u_lo, v)
        Sv_p = eval_surface(surf, u, v_hi)
        Sv_m = eval_surface(surf, u, v_lo)

        Su = [(Su_p[k] - Su_m[k]) / (2 * hu) for k in range(3)]
        Sv = [(Sv_p[k] - Sv_m[k]) / (2 * hv) for k in range(3)]

        gu = 2 * vdot(diff, Su)
        gv = 2 * vdot(diff, Sv)

        if abs(gu) < tol and abs(gv) < tol:
            break

        Suu = [(Su_p[k] - 2 * pt[k] + Su_m[k]) / (hu * hu) for k in range(3)]
        Svv = [(Sv_p[k] - 2 * pt[k] + Sv_m[k]) / (hv * hv) for k in range(3)]

        Spp = eval_surface(surf, u_hi, v_hi)
        Spm = eval_surface(surf, u_hi, v_lo)
        Smp = eval_surface(surf, u_lo, v_hi)
        Smm = eval_surface(surf, u_lo, v_lo)
        Suv = [(Spp[k] - Spm[k] - Smp[k] + Smm[k]) / (4 * hu * hv) for k in range(3)]

        Huu = 2 * (vdot(Su, Su) + vdot(diff, Suu))
        Hvv = 2 * (vdot(Sv, Sv) + vdot(diff, Svv))
        Huv = 2 * (vdot(Su, Sv) + vdot(diff, Suv))

        det = Huu * Hvv - Huv * Huv
        if abs(det) < 1e-14:
            break

        du = -(Hvv * gu - Huv * gv) / det
        dv = -(-Huv * gu + Huu * gv) / det

        alpha = 1.0
        old_dist2 = vdot(diff, diff)
        for _ in range(20):
            nu = max(0.0, min(1.0, u + alpha * du))
            nv = max(0.0, min(1.0, v + alpha * dv))
            npt = eval_surface(surf, nu, nv)
            nd = vsub(npt, query)
            nd2 = vdot(nd, nd)
            if nd2 < old_dist2:
                u, v = nu, nv
                break
            alpha *= 0.5
        else:
            break

    pt = eval_surface(surf, u, v)
    dist = math.sqrt(sum((pt[k] - query[k]) ** 2 for k in range(3)))
    return u, v, pt, dist


# =====================================================================
# STEP file writer (ISO 10303-21, pure Python)
# =====================================================================

def decompose_knot_vector(knots):
    """Convert full knot vector to (unique_knots, multiplicities)."""
    unique = []
    mults = []
    for val in knots:
        if not unique or abs(val - unique[-1]) > 1e-10:
            unique.append(val)
            mults.append(1)
        else:
            mults[-1] += 1
    return unique, mults


def fmt_real(x):
    """Format a real number for STEP output."""
    s = f"{x:.10g}"
    if "." not in s and "e" not in s and "E" not in s:
        s += "."
    return s


def write_step_file(surf, filepath):
    """Write a valid ISO 10303-21 STEP file for the B-spline/NURBS surface."""
    cp = surf["control_points"]
    nu_cp = len(cp)
    nv_cp = len(cp[0])
    deg_u = surf["degree_u"]
    deg_v = surf["degree_v"]
    weights = surf.get("weights")
    sid = surf["id"]

    lines = []
    lines.append("ISO-10303-21;")
    lines.append("HEADER;")
    lines.append("FILE_DESCRIPTION(('B-spline surface geometry'),'2;1');")
    lines.append(f"FILE_NAME('{sid}.step','2024-01-01T00:00:00',(''),(''),'','','');")
    lines.append("FILE_SCHEMA(('AUTOMOTIVE_DESIGN'));")
    lines.append("ENDSEC;")
    lines.append("DATA;")

    # Write CARTESIAN_POINT entities for each control point
    eid = 1
    cp_ids = []
    for i in range(nu_cp):
        row = []
        for j in range(nv_cp):
            x, y, z = cp[i][j]
            lines.append(f"#{eid}=CARTESIAN_POINT('',({fmt_real(x)},{fmt_real(y)},{fmt_real(z)}));")
            row.append(f"#{eid}")
            eid += 1
        cp_ids.append(row)

    # Control points grid as STEP nested list
    cp_list = ",".join("(" + ",".join(row) + ")" for row in cp_ids)

    # Decompose knot vectors
    ku_unique, mu = decompose_knot_vector(surf["knots_u"])
    kv_unique, mv = decompose_knot_vector(surf["knots_v"])

    mu_s = ",".join(str(m) for m in mu)
    mv_s = ",".join(str(m) for m in mv)
    ku_s = ",".join(fmt_real(k) for k in ku_unique)
    kv_s = ",".join(fmt_real(k) for k in kv_unique)

    if weights is None:
        # Non-rational B-spline surface
        lines.append(
            f"#{eid}=B_SPLINE_SURFACE_WITH_KNOTS('{sid}',"
            f"{deg_u},{deg_v},"
            f"({cp_list}),"
            f".UNSPECIFIED.,.F.,.F.,.F.,"
            f"({mu_s}),({mv_s}),"
            f"({ku_s}),({kv_s}),"
            f".UNSPECIFIED.);"
        )
    else:
        # Rational B-spline surface (NURBS) — complex entity
        w_list = ",".join(
            "(" + ",".join(fmt_real(weights[i][j]) for j in range(nv_cp)) + ")"
            for i in range(nu_cp)
        )
        lines.append(
            f"#{eid}=("
            f"BOUNDED_SURFACE()"
            f"B_SPLINE_SURFACE({deg_u},{deg_v},"
            f"({cp_list}),.UNSPECIFIED.,.F.,.F.,.F.)"
            f"B_SPLINE_SURFACE_WITH_KNOTS(({mu_s}),({mv_s}),"
            f"({ku_s}),({kv_s}),.UNSPECIFIED.)"
            f"GEOMETRIC_REPRESENTATION_ITEM()"
            f"RATIONAL_B_SPLINE_SURFACE(({w_list}))"
            f"REPRESENTATION_ITEM('{sid}')"
            f"SURFACE());"
        )

    lines.append("ENDSEC;")
    lines.append("END-ISO-10303-21;")

    with open(filepath, "w") as f:
        f.write("\n".join(lines) + "\n")


# =====================================================================
# Mesh generation and MSH 2.2 writer (pure Python)
# =====================================================================

def generate_mesh(surf, filepath, grid_n=20):
    """Generate triangulated surface mesh and write in Gmsh MSH 2.2 format.

    Creates a regular grid on the [0,1]^2 parameter domain, evaluates
    the surface at each grid point, and forms triangles from adjacent cells.
    grid_n=20 yields 441 nodes and 800 triangles.
    """
    n = grid_n + 1  # nodes per direction

    # Evaluate surface at grid points
    points = []
    for i in range(n):
        for j in range(n):
            u = i / grid_n
            v = j / grid_n
            pt = eval_surface(surf, u, v)
            points.append(pt)

    # Generate two triangles per grid cell
    triangles = []
    for i in range(grid_n):
        for j in range(grid_n):
            # 1-indexed node IDs
            n00 = i * n + j + 1
            n10 = (i + 1) * n + j + 1
            n01 = i * n + (j + 1) + 1
            n11 = (i + 1) * n + (j + 1) + 1
            triangles.append((n00, n10, n11))
            triangles.append((n00, n11, n01))

    # Write Gmsh MSH 2.2 ASCII format
    with open(filepath, "w") as f:
        f.write("$MeshFormat\n2.2 0 8\n$EndMeshFormat\n")
        f.write(f"$Nodes\n{len(points)}\n")
        for idx, pt in enumerate(points):
            f.write(f"{idx + 1} {pt[0]:.12g} {pt[1]:.12g} {pt[2]:.12g}\n")
        f.write("$EndNodes\n")
        f.write(f"$Elements\n{len(triangles)}\n")
        for idx, (a, b, c) in enumerate(triangles):
            f.write(f"{idx + 1} 2 2 1 1 {a} {b} {c}\n")
        f.write("$EndElements\n")


# =====================================================================
# Main pipeline
# =====================================================================

def process_surface_geometry(surf):
    """Compute all geometric properties for a surface."""
    result = {
        "points": [],
        "normals": [],
        "gaussian_curvature": [],
        "mean_curvature": [],
        "area": 0.0,
        "projections": [],
    }

    for uv in surf["eval_params"]:
        u, v = uv[0], uv[1]
        pt = eval_surface(surf, u, v)
        n = compute_normal(surf, u, v)
        K, H = compute_curvatures(surf, u, v)

        result["points"].append(pt)
        result["normals"].append(n)
        result["gaussian_curvature"].append(K)
        result["mean_curvature"].append(H)

    result["area"] = compute_area(surf, n_gauss=12, n_sub=6)

    for qp in surf.get("query_points", []):
        u, v, pt, dist = project_point(surf, qp)
        result["projections"].append({
            "u": u,
            "v": v,
            "point": pt,
            "distance": dist,
        })

    return result


def main():
    surfaces_dir = "/app/surfaces"
    output_dir = "/app/output"
    step_dir = os.path.join(output_dir, "step")
    mesh_dir = os.path.join(output_dir, "mesh")

    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(step_dir, exist_ok=True)
    os.makedirs(mesh_dir, exist_ok=True)

    results = {}

    for fpath in sorted(glob.glob(os.path.join(surfaces_dir, "*.json"))):
        with open(fpath) as f:
            surf = json.load(f)
        sid = surf["id"]
        print(f"Processing surface: {sid}")

        # Geometric analysis
        results[sid] = process_surface_geometry(surf)
        print(f"  Area: {results[sid]['area']:.6f}")

        # STEP export
        step_path = os.path.join(step_dir, f"{sid}.step")
        write_step_file(surf, step_path)
        print(f"  STEP: {step_path}")

        # Mesh generation
        mesh_path = os.path.join(mesh_dir, f"{sid}.msh")
        generate_mesh(surf, mesh_path)
        print(f"  Mesh: {mesh_path}")

    # Write results
    output_path = os.path.join(output_dir, "results.json")
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Results written to {output_path}")


if __name__ == "__main__":
    main()
