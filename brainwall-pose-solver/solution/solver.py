#!/usr/bin/env python3
"""
Brain Wall pose solver — finds valid poses by searching over vertex-to-hole
assignments, filtering by edge-length constraints, validating containment
in (potentially concave) hole polygons, and minimizing dislikes.

"""
import json
import os
import sys
import itertools

EPS = 1e-9


# ── geometry primitives ──────────────────────────────────────────────

def squared_dist(p, q):
    return (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2


def cross2d(ox, oy, ax, ay, bx, by):
    return (ax - ox) * (by - oy) - (ay - oy) * (bx - ox)


def on_segment(px, py, ax, ay, bx, by):
    cp = cross2d(ax, ay, bx, by, px, py)
    if abs(cp) > EPS:
        return False
    return (min(ax, bx) - EPS <= px <= max(ax, bx) + EPS and
            min(ay, by) - EPS <= py <= max(ay, by) + EPS)


def point_on_boundary(px, py, polygon):
    n = len(polygon)
    for i in range(n):
        j = (i + 1) % n
        if on_segment(px, py,
                      polygon[i][0], polygon[i][1],
                      polygon[j][0], polygon[j][1]):
            return True
    return False


def winding_number(px, py, polygon):
    n = len(polygon)
    wn = 0
    for i in range(n):
        j = (i + 1) % n
        yi, yj = polygon[i][1], polygon[j][1]
        if yi <= py:
            if yj > py:
                cp = cross2d(polygon[i][0], yi,
                             polygon[j][0], yj, px, py)
                if cp > EPS:
                    wn += 1
        else:
            if yj <= py:
                cp = cross2d(polygon[i][0], yi,
                             polygon[j][0], yj, px, py)
                if cp < -EPS:
                    wn -= 1
    return wn


def point_in_or_on(px, py, polygon):
    if point_on_boundary(px, py, polygon):
        return True
    return winding_number(px, py, polygon) != 0


def find_intersection_params(p1x, p1y, p2x, p2y, ax, ay, bx, by):
    dx, dy = p2x - p1x, p2y - p1y
    ex, ey = bx - ax, by - ay
    denom = dx * ey - dy * ex

    if abs(denom) < EPS:
        cp = (ax - p1x) * dy - (ay - p1y) * dx
        if abs(cp) > EPS:
            return []
        if abs(dx) > abs(dy):
            if abs(dx) < EPS:
                return []
            ta = (ax - p1x) / dx
            tb = (bx - p1x) / dx
        else:
            if abs(dy) < EPS:
                return []
            ta = (ay - p1y) / dy
            tb = (by - p1y) / dy
        t_lo, t_hi = min(ta, tb), max(ta, tb)
        ov_s = max(0.0, t_lo)
        ov_e = min(1.0, t_hi)
        if ov_s > ov_e + EPS:
            return []
        res = [max(0.0, ov_s)]
        if abs(ov_e - ov_s) > EPS:
            res.append(min(1.0, ov_e))
        return res

    num_t = (ax - p1x) * ey - (ay - p1y) * ex
    num_u = (ax - p1x) * dy - (ay - p1y) * dx
    t = num_t / denom
    u = num_u / denom
    if -EPS <= t <= 1.0 + EPS and -EPS <= u <= 1.0 + EPS:
        return [max(0.0, min(1.0, t))]
    return []


def edge_inside_polygon(p1, p2, polygon):
    if not point_in_or_on(p1[0], p1[1], polygon):
        return False
    if not point_in_or_on(p2[0], p2[1], polygon):
        return False

    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    if abs(dx) < EPS and abs(dy) < EPS:
        return True

    t_set = {0.0, 1.0}
    n = len(polygon)
    for i in range(n):
        j = (i + 1) % n
        for t in find_intersection_params(
                p1[0], p1[1], p2[0], p2[1],
                polygon[i][0], polygon[i][1],
                polygon[j][0], polygon[j][1]):
            t_set.add(t)

    t_sorted = sorted(t_set)
    for k in range(len(t_sorted) - 1):
        if t_sorted[k + 1] - t_sorted[k] < 1e-15:
            continue
        t_mid = (t_sorted[k] + t_sorted[k + 1]) / 2.0
        mx = p1[0] + t_mid * dx
        my = p1[1] + t_mid * dy
        if not point_in_or_on(mx, my, polygon):
            return False
    return True


# ── constraint checks ────────────────────────────────────────────────

def check_edge_length(d_orig, d_new, epsilon):
    return abs(d_new * 1000000 - d_orig * 1000000) <= epsilon * d_orig


def compute_dislikes(hole, pose_verts):
    total = 0
    for h in hole:
        total += min(squared_dist(h, v) for v in pose_verts)
    return total


# ── solver ────────────────────────────────────────────────────────────

def solve_problem(problem):
    hole = problem["hole"]
    figure = problem["figure"]
    epsilon = problem["epsilon"]
    orig = figure["vertices"]
    edges = figure["edges"]
    n = len(orig)
    nh = len(hole)

    # Pre-compute original squared distances for each edge
    orig_d = {}
    for i, j in edges:
        orig_d[(i, j)] = squared_dist(orig[i], orig[j])

    best_pose = None
    best_dl = float("inf")

    # Enumerate all assignments of n figure vertices to nh hole vertices
    for perm in itertools.permutations(range(nh), n):
        cand = [list(hole[perm[k]]) for k in range(n)]

        # Quick-reject: edge length constraints
        ok = True
        for i, j in edges:
            d_new = squared_dist(cand[i], cand[j])
            if not check_edge_length(orig_d[(i, j)], d_new, epsilon):
                ok = False
                break
        if not ok:
            continue

        # Edge containment (critical for concave holes)
        for i, j in edges:
            if not edge_inside_polygon(cand[i], cand[j], hole):
                ok = False
                break
        if not ok:
            continue

        dl = compute_dislikes(hole, cand)
        if dl < best_dl:
            best_dl = dl
            best_pose = {"vertices": cand}
            if dl == 0:
                break

    return best_pose


# ── main ──────────────────────────────────────────────────────────────

def main():
    problems_dir = "/app/problems"
    solutions_dir = "/app/solutions"
    os.makedirs(solutions_dir, exist_ok=True)

    for pid in range(1, 5):
        prob_file = os.path.join(problems_dir, f"prob{pid}.json")
        with open(prob_file) as f:
            problem = json.load(f)

        print(f"Solving problem {pid} "
              f"(hole={len(problem['hole'])}v, "
              f"fig={len(problem['figure']['vertices'])}v/"
              f"{len(problem['figure']['edges'])}e, "
              f"eps={problem['epsilon']})...")

        pose = solve_problem(problem)
        if pose is None:
            print(f"  ERROR: no valid pose found!")
            sys.exit(1)

        dl = compute_dislikes(problem["hole"], pose["vertices"])
        print(f"  Found pose with dislikes = {dl}")

        out_file = os.path.join(solutions_dir, f"pose{pid}.json")
        with open(out_file, "w") as f:
            json.dump(pose, f, indent=2)

    print("All problems solved.")


if __name__ == "__main__":
    main()
