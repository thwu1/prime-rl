#!/usr/bin/env python3
"""
Fix the three mathematical bugs in /app/lie_ik.py and implement the
two missing functions (compute_body_jacobian, compute_collision_constraint).
"""

with open("/app/lie_ik.py", "r") as f:
    code = f.read()

# =====================================================================
# Bug Fix 1: so3_log near-pi case
# Near theta=pi, R+I is rank-1. The rotation axis is extracted from
# the column with the LARGEST norm (the non-degenerate column).
# The buggy code uses argmin, selecting the near-zero column instead.
# =====================================================================
code = code.replace(
    "np.argmin(np.sum(S * S, axis=0))",
    "np.argmax(np.sum(S * S, axis=0))",
)

# =====================================================================
# Bug Fix 2: se3_adjoint upper-right block
# The SE(3) adjoint is:
#   Ad(T) = [[R, skew(t) @ R],
#            [0,           R]]
# The buggy code computes R @ skew(t) instead of skew(t) @ R.
# This breaks the composition property Ad(T1 @ T2) = Ad(T1) @ Ad(T2).
# =====================================================================
code = code.replace(
    "R @ so3_skew(t)",
    "so3_skew(t) @ R",
)

# =====================================================================
# Bug Fix 3: Q-matrix coefficient C
# The correct coefficient (Eq. 180 from Barfoot) is:
#   C = (1 - theta^2/2 - cos(theta)) / theta^4
# The buggy code has a sign error: (1 + theta^2/2 - cos(theta)).
# This corrupts the SE(3) left Jacobian coupling block.
# =====================================================================
code = code.replace(
    "1.0 + 0.5 * t2 - ct",
    "1.0 - 0.5 * t2 - ct",
)

# =====================================================================
# Implementation 1: compute_body_jacobian
# Compute the body-frame Jacobian by transforming MuJoCo's world-frame
# Jacobian through the inverse adjoint Ad(T_sw).
#
# Steps:
#   1. Get world-frame Jacobians (position, rotation) from mj_jacSite
#   2. Stack as J_world = [jacp; jacr] (translation on top)
#   3. Construct inverse adjoint Ad_sw from site pose
#   4. Return Ad_sw @ J_world
#
# Key subtlety: MuJoCo returns separate position (jacp) and rotation
# (jacr) Jacobians. The SE(3) twist convention is [v; omega] =
# [translation; rotation], so J_world = vstack([jacp, jacr]).
# =====================================================================
code = code.replace(
    '    raise NotImplementedError("compute_body_jacobian not yet implemented")',
    """    jacp = np.zeros((3, model.nv))
    jacr = np.zeros((3, model.nv))
    mujoco.mj_jacSite(model, data, jacp, jacr, site_id)
    J_world = np.vstack([jacp, jacr])

    R_ws = data.site_xmat[site_id].reshape(3, 3)
    t_ws = data.site_xpos[site_id]
    R_sw = R_ws.T
    t_sw = -R_sw @ t_ws

    Ad_sw = np.zeros((6, 6), dtype=np.float64)
    Ad_sw[:3, :3] = R_sw
    Ad_sw[:3, 3:] = so3_skew(t_sw) @ R_sw
    Ad_sw[3:, 3:] = R_sw

    return Ad_sw @ J_world""",
)

# =====================================================================
# Implementation 2: compute_collision_constraint
# Build a linear inequality g_row @ dq <= h_val that limits the
# approach velocity between two geoms.
#
# Steps:
#   1. Query mj_geomDistance for nearest points (fromto) and distance
#   2. If beyond detection range, return inactive constraint (zeros, inf)
#   3. Compute unit normal from fromto[3:] - fromto[:3]
#   4. Get translational Jacobians at contact points via mj_jac
#   5. Compute constraint row: normal @ (jac2 - jac1)
#   6. Apply sign convention: sign = -1 for separated geoms (dist >= 0)
#      so the constraint resists approach; sign = +1 for penetrating
#   7. Compute upper bound: gain * (dist - min_dist) / dt when safe,
#      0 when already too close
# =====================================================================
code = code.replace(
    '    raise NotImplementedError("compute_collision_constraint not yet implemented")',
    """    fromto = np.zeros(6, dtype=np.float64)
    dist = mujoco.mj_geomDistance(
        model, data, geom1_id, geom2_id, detection_dist, fromto
    )

    if abs(dist - detection_dist) < 1e-12:
        return np.zeros(model.nv, dtype=np.float64), np.inf

    normal = fromto[3:] - fromto[:3]
    norm_val = np.linalg.norm(normal)
    if norm_val < 1e-12:
        return np.zeros(model.nv, dtype=np.float64), np.inf
    normal /= norm_val

    body1 = model.geom_bodyid[geom1_id]
    body2 = model.geom_bodyid[geom2_id]
    jac1 = np.zeros((3, model.nv))
    jac2 = np.zeros((3, model.nv))
    mujoco.mj_jac(model, data, jac2, None, fromto[3:], body2)
    mujoco.mj_jac(model, data, jac1, None, fromto[:3], body1)

    g_row = normal @ (jac2 - jac1)
    sign = -1.0 if dist >= 0 else 1.0
    g_row *= sign

    if dist > min_dist:
        h_val = gain * (dist - min_dist) / dt
    else:
        h_val = 0.0

    return g_row, h_val""",
)

with open("/app/lie_ik.py", "w") as f:
    f.write(code)

print("Applied 3 bug fixes and 2 function implementations to /app/lie_ik.py")
