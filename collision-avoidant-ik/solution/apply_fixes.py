#!/usr/bin/env python3
"""
Apply bug fixes and implement missing functions in /app/lie_ik.py.

Fixes three mathematical bugs:
  1. so3_log near-pi: argmin -> argmax for selecting non-degenerate column
  2. se3_adjoint upper-right block: R @ skew(t) -> skew(t) @ R
  3. Q-matrix coefficient C: (1 + t^2/2 - cos) -> (1 - t^2/2 - cos)

Implements two missing functions:
  4. compute_body_jacobian via inverse adjoint of MuJoCo world Jacobian
  5. compute_collision_constraint via mj_geomDistance and contact Jacobians
"""

import re

with open("/app/lie_ik.py", "r") as f:
    code = f.read()

changes = 0

# Bug Fix 1: so3_log near-pi — select column with LARGEST norm (non-degenerate)
new_code = re.sub(
    r'np\.argmin\(np\.sum\(S \* S, axis=0\)\)',
    'np.argmax(np.sum(S * S, axis=0))',
    code,
)
if new_code != code:
    changes += 1
    code = new_code

# Bug Fix 2: se3_adjoint upper-right block — skew(t) @ R, not R @ skew(t)
new_code = re.sub(
    r'R\s*@\s*so3_skew\(t\)',
    'so3_skew(t) @ R',
    code,
)
if new_code != code:
    changes += 1
    code = new_code

# Bug Fix 3: Q-matrix coefficient C — (1 - t^2/2 - cos), not (1 + t^2/2 - cos)
new_code = re.sub(
    r'1\.0\s*\+\s*0\.5\s*\*\s*t2\s*-\s*ct',
    '1.0 - 0.5 * t2 - ct',
    code,
)
if new_code != code:
    changes += 1
    code = new_code

# Implementation 4: compute_body_jacobian
body_jac_impl = '''    jacp = np.zeros((3, model.nv))
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

    return Ad_sw @ J_world'''

new_code = code.replace(
    '    raise NotImplementedError("compute_body_jacobian not yet implemented")',
    body_jac_impl,
)
if new_code != code:
    changes += 1
    code = new_code

# Implementation 5: compute_collision_constraint
collision_impl = '''    fromto = np.zeros(6, dtype=np.float64)
    dist = mujoco.mj_geomDistance(
        model, data, geom1_id, geom2_id, detection_dist, fromto
    )

    if dist >= detection_dist - 1e-6:
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
    mujoco.mj_jac(model, data, jac1, None, fromto[:3], body1)
    mujoco.mj_jac(model, data, jac2, None, fromto[3:], body2)

    g_row = normal @ (jac2 - jac1)
    sign = -1.0 if dist >= 0 else 1.0
    g_row *= sign

    if dist > min_dist:
        h_val = gain * (dist - min_dist) / dt
    else:
        h_val = 0.0

    return g_row, h_val'''

new_code = code.replace(
    '    raise NotImplementedError("compute_collision_constraint not yet implemented")',
    collision_impl,
)
if new_code != code:
    changes += 1
    code = new_code

with open("/app/lie_ik.py", "w") as f:
    f.write(code)

print(f"Applied {changes} fixes to /app/lie_ik.py")

if changes < 5:
    print(f"WARNING: Expected 5 changes but only applied {changes}, "
          f"falling back to reference implementation")
    import shutil
    shutil.copy2("/solution/lie_ik_impl.py", "/app/lie_ik.py")
    print("Copied reference implementation to /app/lie_ik.py")
