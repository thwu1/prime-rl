#!/usr/bin/env python3
"""SDF Scene Query Engine - Reference Implementation.

"""

import json
import math
import sys


# ===== Vector Operations =====

def v3(x, y, z):
    return (x, y, z)

def vadd(a, b):
    return (a[0]+b[0], a[1]+b[1], a[2]+b[2])

def vsub(a, b):
    return (a[0]-b[0], a[1]-b[1], a[2]-b[2])

def vmuls(v, s):
    return (v[0]*s, v[1]*s, v[2]*s)

def vdot(a, b):
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]

def vlen(v):
    return math.sqrt(v[0]*v[0] + v[1]*v[1] + v[2]*v[2])

def vlen2(x, y):
    return math.sqrt(x*x + y*y)

def vnorm(v):
    l = vlen(v)
    if l < 1e-20:
        return (0.0, 0.0, 0.0)
    return (v[0]/l, v[1]/l, v[2]/l)

def vcross(a, b):
    return v3(
        a[1]*b[2] - a[2]*b[1],
        a[2]*b[0] - a[0]*b[2],
        a[0]*b[1] - a[1]*b[0]
    )

def vabs(v):
    return (abs(v[0]), abs(v[1]), abs(v[2]))

def vmax_s(v, s):
    return (max(v[0], s), max(v[1], s), max(v[2], s))

def vmax_v(a, b):
    return (max(a[0], b[0]), max(a[1], b[1]), max(a[2], b[2]))

def clamp(x, lo, hi):
    return max(lo, min(x, hi))

def sign(x):
    if x > 0: return 1.0
    elif x < 0: return -1.0
    return 0.0

def dot2_v(v):
    return v[0]*v[0] + v[1]*v[1] + v[2]*v[2]


# ===== SDF Primitives =====

def sd_sphere(p, radius):
    return vlen(p) - radius


def sd_box(p, b):
    qx = abs(p[0]) - b[0]
    qy = abs(p[1]) - b[1]
    qz = abs(p[2]) - b[2]
    outer = vlen(v3(max(qx, 0.0), max(qy, 0.0), max(qz, 0.0)))
    inner = min(max(qx, max(qy, qz)), 0.0)
    return outer + inner


def sd_torus(p, major_r, minor_r):
    qx = vlen2(p[0], p[2]) - major_r
    qy = p[1]
    return vlen2(qx, qy) - minor_r


def sd_capsule(p, a, b, r):
    pa = vsub(p, a)
    ba = vsub(b, a)
    h = clamp(vdot(pa, ba) / vdot(ba, ba), 0.0, 1.0)
    return vlen(vsub(pa, vmuls(ba, h))) - r


def sd_capped_cylinder(p, r, h):
    dx = abs(vlen2(p[0], p[2])) - r
    dy = abs(p[1]) - h
    return min(max(dx, dy), 0.0) + vlen2(max(dx, 0.0), max(dy, 0.0))


def sd_octahedron(p, s):
    px, py, pz = abs(p[0]), abs(p[1]), abs(p[2])
    m = px + py + pz - s

    if 3.0 * px < m:
        qx, qy, qz = px, py, pz
    elif 3.0 * py < m:
        qx, qy, qz = py, pz, px
    elif 3.0 * pz < m:
        qx, qy, qz = pz, px, py
    else:
        return m * 0.57735027

    k = clamp(0.5 * (qz - qy + s), 0.0, s)
    return vlen(v3(qx, qy - s + k, qz - k))


def sd_ellipsoid(p, r):
    k0 = vlen(v3(p[0]/r[0], p[1]/r[1], p[2]/r[2]))
    k1 = vlen(v3(p[0]/(r[0]*r[0]), p[1]/(r[1]*r[1]), p[2]/(r[2]*r[2])))
    if k1 < 1e-20:
        return -min(r[0], min(r[1], r[2]))
    return k0 * (k0 - 1.0) / k1


def sd_capped_cone(p, h, r1, r2):
    qx = vlen2(p[0], p[2])
    qy = p[1]

    k1x, k1y = r2, h
    k2x, k2y = r2 - r1, 2.0 * h

    ca_x = qx - min(qx, r1 if qy < 0.0 else r2)
    ca_y = abs(qy) - h

    k2_dot = k2x*k2x + k2y*k2y
    if k2_dot < 1e-20:
        k2_dot = 1e-20
    diff_x = k1x - qx
    diff_y = k1y - qy
    dot_val = diff_x * k2x + diff_y * k2y
    t = clamp(dot_val / k2_dot, 0.0, 1.0)
    cb_x = qx - k1x + k2x * t
    cb_y = qy - k1y + k2y * t

    s_val = -1.0 if (cb_x < 0.0 and ca_y < 0.0) else 1.0
    return s_val * math.sqrt(min(ca_x*ca_x + ca_y*ca_y, cb_x*cb_x + cb_y*cb_y))


def sd_pyramid(p_in, h):
    m2 = h * h + 0.25

    px = abs(p_in[0])
    py = p_in[1]
    pz = abs(p_in[2])

    if pz > px:
        px, pz = pz, px

    px -= 0.5
    pz -= 0.5

    qx = pz
    qy = h * py - 0.5 * px
    qz = h * px + 0.5 * py

    s = max(-qx, 0.0)
    denom = m2 + 0.25
    t = clamp((qy - 0.5 * pz) / denom, 0.0, 1.0)

    a = m2 * (qx + s) * (qx + s) + qy * qy
    b = m2 * (qx + 0.5 * t) * (qx + 0.5 * t) + (qy - m2 * t) * (qy - m2 * t)

    d2 = 0.0 if min(qy, -qx * m2 - qy * 0.5) > 0.0 else min(a, b)

    sign_val = sign(max(qz, -py))
    return sign_val * math.sqrt(abs((d2 + qz * qz) / m2))


def sd_round_cone(p, r1, r2, h):
    b_val = (r1 - r2) / h
    a_val = math.sqrt(max(1.0 - b_val * b_val, 0.0))

    qx = vlen2(p[0], p[2])
    qy = p[1]

    k = qx * (-b_val) + qy * a_val
    if k < 0.0:
        return vlen2(qx, qy) - r1
    if k > a_val * h:
        return vlen2(qx, qy - h) - r2
    return qx * a_val + qy * b_val - r1


# ===== Smooth Operations =====

def op_smooth_union(d1, d2, k):
    k4 = k * 4.0
    h = max(k4 - abs(d1 - d2), 0.0)
    return min(d1, d2) - h * h * 0.25 / k4


def op_smooth_subtraction(d1, d2, k):
    return -op_smooth_union(d1, -d2, k)


def op_smooth_intersection(d1, d2, k):
    return -op_smooth_union(-d1, -d2, k)


# ===== Rotation Matrix (axis-angle) =====

def rotation_matrix(axis, angle_deg):
    ax, ay, az = axis
    l = math.sqrt(ax*ax + ay*ay + az*az)
    ax, ay, az = ax/l, ay/l, az/l
    theta = math.radians(angle_deg)
    c = math.cos(theta)
    s = math.sin(theta)
    t = 1.0 - c
    return [
        [t*ax*ax + c,    t*ax*ay - s*az, t*ax*az + s*ay],
        [t*ax*ay + s*az, t*ay*ay + c,    t*ay*az - s*ax],
        [t*ax*az - s*ay, t*ay*az + s*ax, t*az*az + c   ]
    ]


def mat_transpose_mul(R, p):
    return v3(
        R[0][0]*p[0] + R[1][0]*p[1] + R[2][0]*p[2],
        R[0][1]*p[0] + R[1][1]*p[1] + R[2][1]*p[2],
        R[0][2]*p[0] + R[1][2]*p[1] + R[2][2]*p[2]
    )


# ===== Scene Evaluator =====

def evaluate(node, p):
    px, py, pz = float(p[0]), float(p[1]), float(p[2])
    p = (px, py, pz)

    if "primitive" in node:
        ptype = node["primitive"]
        if ptype == "sphere":
            return sd_sphere(p, node["radius"])
        elif ptype == "box":
            return sd_box(p, tuple(node["half_extents"]))
        elif ptype == "torus":
            return sd_torus(p, node["major_radius"], node["minor_radius"])
        elif ptype == "capsule":
            return sd_capsule(p, tuple(node["a"]), tuple(node["b"]), node["radius"])
        elif ptype == "capped_cylinder":
            return sd_capped_cylinder(p, node["radius"], node["height"])
        elif ptype == "octahedron":
            return sd_octahedron(p, node["size"])
        elif ptype == "ellipsoid":
            return sd_ellipsoid(p, tuple(node["radii"]))
        elif ptype == "capped_cone":
            return sd_capped_cone(p, node["height"], node["r1"], node["r2"])
        elif ptype == "pyramid":
            return sd_pyramid(p, node["height"])
        elif ptype == "round_cone":
            return sd_round_cone(p, node["r1"], node["r2"], node["height"])
        else:
            raise ValueError(f"Unknown primitive: {ptype}")

    op = node["op"]

    if op == "translate":
        off = node["offset"]
        return evaluate(node["child"], vsub(p, (off[0], off[1], off[2])))

    elif op == "rotate":
        R = rotation_matrix(node["axis"], node["angle_deg"])
        return evaluate(node["child"], mat_transpose_mul(R, p))

    elif op == "scale":
        s = node["factor"]
        return evaluate(node["child"], vmuls(p, 1.0/s)) * s

    elif op == "symmetry":
        axes = node["axes"]
        px, py, pz = p
        if "x" in axes:
            px = abs(px)
        if "y" in axes:
            py = abs(py)
        if "z" in axes:
            pz = abs(pz)
        return evaluate(node["child"], (px, py, pz))

    elif op == "elongate":
        h = node["h"]
        qx = px - clamp(px, -h[0], h[0])
        qy = py - clamp(py, -h[1], h[1])
        qz = pz - clamp(pz, -h[2], h[2])
        return evaluate(node["child"], (qx, qy, qz))

    elif op == "onion":
        d = evaluate(node["child"], p)
        return abs(d) - node["thickness"]

    elif op == "round":
        d = evaluate(node["child"], p)
        return d - node["radius"]

    elif op == "smooth_union":
        k = node["k"]
        children = node["children"]
        d = evaluate(children[0], p)
        for i in range(1, len(children)):
            d = op_smooth_union(d, evaluate(children[i], p), k)
        return d

    elif op == "smooth_subtraction":
        k = node["k"]
        d1 = evaluate(node["children"][0], p)
        d2 = evaluate(node["children"][1], p)
        return op_smooth_subtraction(d1, d2, k)

    elif op == "smooth_intersection":
        k = node["k"]
        d1 = evaluate(node["children"][0], p)
        d2 = evaluate(node["children"][1], p)
        return op_smooth_intersection(d1, d2, k)

    elif op == "union":
        d1 = evaluate(node["children"][0], p)
        d2 = evaluate(node["children"][1], p)
        return min(d1, d2)

    elif op == "subtraction":
        d1 = evaluate(node["children"][0], p)
        d2 = evaluate(node["children"][1], p)
        return max(-d1, d2)

    elif op == "intersection":
        d1 = evaluate(node["children"][0], p)
        d2 = evaluate(node["children"][1], p)
        return max(d1, d2)

    else:
        raise ValueError(f"Unknown operation: {op}")


# ===== Query Processing =====

def compute_normal(root, p, eps):
    dx = evaluate(root, vadd(p, (eps, 0, 0))) - evaluate(root, vsub(p, (eps, 0, 0)))
    dy = evaluate(root, vadd(p, (0, eps, 0))) - evaluate(root, vsub(p, (0, eps, 0)))
    dz = evaluate(root, vadd(p, (0, 0, eps))) - evaluate(root, vsub(p, (0, 0, eps)))
    l = math.sqrt(dx*dx + dy*dy + dz*dz)
    if l < 1e-20:
        return [0.0, 0.0, 0.0]
    return [dx/l, dy/l, dz/l]


def ray_cast(root, origin, direction, max_t, eps):
    origin = tuple(float(x) for x in origin)
    d = tuple(float(x) for x in direction)
    dl = math.sqrt(d[0]*d[0] + d[1]*d[1] + d[2]*d[2])
    d = (d[0]/dl, d[1]/dl, d[2]/dl)

    t = 0.0
    for _ in range(2000):
        pt = vadd(origin, vmuls(d, t))
        dist = evaluate(root, pt)
        if abs(dist) < eps:
            n = compute_normal(root, pt, eps)
            return {
                "hit": True,
                "t": round(t, 6),
                "point": [round(pt[0], 6), round(pt[1], 6), round(pt[2], 6)],
                "normal": [round(n[0], 6), round(n[1], 6), round(n[2], 6)]
            }
        if t > max_t:
            break
        t += max(dist, eps * 0.5)

    return {"hit": False}


def process_queries(scene, queries):
    root = scene["root"]
    results = []
    for q in queries:
        qid = q["id"]
        qtype = q["type"]

        if qtype == "distance":
            d = evaluate(root, tuple(q["point"]))
            results.append({"id": qid, "type": "distance", "value": round(d, 8)})

        elif qtype == "normal":
            pt = tuple(q["point"])
            n = compute_normal(root, pt, q["epsilon"])
            results.append({"id": qid, "type": "normal", "value": [round(x, 8) for x in n]})

        elif qtype == "ray_cast":
            result = ray_cast(root, q["origin"], q["direction"], q["max_t"], q["epsilon"])
            results.append({"id": qid, "type": "ray_cast", "value": result})

        elif qtype == "classify":
            d = evaluate(root, tuple(q["point"]))
            if d < -1e-6:
                cls = "inside"
            elif d > 1e-6:
                cls = "outside"
            else:
                cls = "surface"
            results.append({"id": qid, "type": "classify", "value": cls})

    return results


def main():
    scene_path = sys.argv[1] if len(sys.argv) > 1 else "/app/scene.json"
    query_path = sys.argv[2] if len(sys.argv) > 2 else "/app/queries.json"
    output_path = sys.argv[3] if len(sys.argv) > 3 else "/app/results.json"

    with open(scene_path) as f:
        scene = json.load(f)
    with open(query_path) as f:
        queries = json.load(f)

    results = process_queries(scene, queries)

    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"Wrote {len(results)} results to {output_path}")


if __name__ == "__main__":
    main()
