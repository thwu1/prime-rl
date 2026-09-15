#!/usr/bin/env python3
"""Fix the three mathematical bugs in /app/schur_ba.py.

Bug 1 (reproj_jac - S matrix column 0 sign error):
    The first column of S = -R @ skew(pw) has a sign error on the pz terms.
    -R @ skew(pw) column 0 = [-pz*R[:,1] + py*R[:,2]].
    The code uses +pz instead of -pz for the r01/r11/r21 terms.

Bug 2 (back-substitution sign error):
    The Schur back-substitution formula is:
        delta_point = C^{-1} (g_point - B^T delta_pose)
    The code uses += instead of -= when accumulating B^T delta_pose.

Bug 3 (depth point Jacobian wrong rotation row):
    The depth residual r_z = (Z_cam - d_meas)/sigma depends on Z_cam,
    which is the third (index 2) component of R @ pw + t.
    Therefore dZ_cam/dpw = R[2,:] = [r20, r21, r22].
    The code uses R[0,:] = [r00, r01, r02] instead.
"""

with open('/app/schur_ba.py', 'r') as f:
    code = f.read()

# Bug 1: Fix sign in S matrix column 0 (reproj_jac function)
# The pattern " pz * rX1 + py * rX2" (with leading space before pz)
# only appears in the buggy reproj_jac, not in depth_jac which has "-pz".
code = code.replace(
    's00 =  pz * r01 + py * r02',
    's00 = -pz * r01 + py * r02',
)
code = code.replace(
    's10 =  pz * r11 + py * r12',
    's10 = -pz * r11 + py * r12',
)
code = code.replace(
    's20 =  pz * r21 + py * r22',
    's20 = -pz * r21 + py * r22',
)

# Bug 2: Fix back-substitution sign (bundle_adjust_schur function)
code = code.replace(
    'rhs += b_block.T @ delta_pose[pli * 6:(pli + 1) * 6]',
    'rhs -= b_block.T @ delta_pose[pli * 6:(pli + 1) * 6]',
)

# Bug 3: Fix depth point Jacobian to use R[2,:] instead of R[0,:]
code = code.replace(
    'jx = np.array([[r00 * ivs, r01 * ivs, r02 * ivs]])',
    'jx = np.array([[r20 * ivs, r21 * ivs, r22 * ivs]])',
)

with open('/app/schur_ba.py', 'w') as f:
    f.write(code)

print("Applied 3 fixes to /app/schur_ba.py")
