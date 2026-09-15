"""
KUKA youBot mobile manipulator feedback controller.

Parses kinematic parameters from URDF, implements screw-theory SE(3)/SO(3)
operations, mecanum-wheel odometry, and a task-space feedback controller.
"""

import numpy as np
import xml.etree.ElementTree as ET

# ---------------------------------------------------------------------------
# Parse URDF for kinematic parameters
# ---------------------------------------------------------------------------
_tree = ET.parse('/app/youbot.urdf')
_root = _tree.getroot()


def _find_joint(name):
    for j in _root.findall('joint'):
        if j.get('name') == name:
            return j
    return None


def _origin_xyz(joint_elem):
    origin = joint_elem.find('origin')
    return [float(v) for v in origin.get('xyz').split()]


def _joint_axis(joint_elem):
    ax = joint_elem.find('axis')
    return [float(v) for v in ax.get('xyz').split()]


# Chassis height from base_footprint_to_base fixed joint
_z = _origin_xyz(_find_joint('base_footprint_to_base'))[2]

# Wheel radius from visual geometry of wheel_1
_r = None
for link in _root.findall('link'):
    if link.get('name') == 'wheel_1':
        cyl = link.find('.//cylinder')
        _r = float(cyl.get('radius'))
        break

# Wheel positions and roller angles
_wheels = {}
for i in range(1, 5):
    jname = f'wheel_{i}_joint'
    j = _find_joint(jname)
    xyz = _origin_xyz(j)
    _wheels[i] = {'x': xyz[0], 'y': xyz[1]}

for gz in _root.findall('gazebo'):
    ref = gz.get('reference', '')
    if ref.startswith('wheel_'):
        wnum = int(ref.split('_')[1])
        roller_el = gz.find('mecanum_roller_angle')
        _wheels[wnum]['gamma'] = float(roller_el.text)

# Construct H matrix: h_i = (1/(r*cos(gamma_i))) * [x*sin(g)-y*cos(g), cos(g), sin(g)]
_H = np.zeros((4, 3))
for i in range(1, 5):
    w = _wheels[i]
    cg = np.cos(w['gamma'])
    sg = np.sin(w['gamma'])
    _H[i - 1, :] = (1.0 / (_r * cg)) * np.array([
        w['x'] * sg - w['y'] * cg,
        cg,
        sg,
    ])
_F = np.linalg.pinv(_H)  # 3x4: maps wheel speeds -> (wbz, vbx, vby)

# Base-to-arm transform Tb0
_j_b2a = _find_joint('base_to_arm_base')
_tb0_xyz = _origin_xyz(_j_b2a)
_Tb0 = np.eye(4)
_Tb0[:3, 3] = _tb0_xyz

# Arm joint origins and axes (joints 1..5)
_arm_joints = []
for i in range(1, 6):
    j = _find_joint(f'arm_joint_{i}')
    _arm_joints.append({
        'origin': np.array(_origin_xyz(j)),
        'axis': np.array(_joint_axis(j)),
    })

# End-effector fixed offset
_j_ee = _find_joint('ee_fixed_joint')
_ee_offset = np.array(_origin_xyz(_j_ee))

# Compute M0e (arm-base to EE at home config) by chain of translations
_M0e = np.eye(4)
for aj in _arm_joints:
    T = np.eye(4)
    T[:3, 3] = aj['origin']
    _M0e = _M0e @ T
T_ee = np.eye(4)
T_ee[:3, 3] = _ee_offset
_M0e = _M0e @ T_ee

# Compute Blist: body screw axes in EE frame at home config
_p0e = _M0e[:3, 3]
_R0e = _M0e[:3, :3]  # Identity at home config (no rpy rotations)

_Blist = np.zeros((6, 5))
_pos_accum = np.zeros(3)
for i, aj in enumerate(_arm_joints):
    _pos_accum = _pos_accum + aj['origin']
    omega_0 = aj['axis']
    q_0 = _pos_accum.copy()
    # Transform to EE frame
    omega_e = _R0e.T @ omega_0
    q_e = _R0e.T @ (q_0 - _p0e)
    v_e = -np.cross(omega_e, q_e)
    _Blist[:, i] = np.concatenate([omega_e, v_e])

# ---------------------------------------------------------------------------
# Screw-theory helpers
# ---------------------------------------------------------------------------

def _near_zero(z):
    return abs(z) < 1e-6


def _vec_to_so3(omg):
    return np.array([
        [0, -omg[2], omg[1]],
        [omg[2], 0, -omg[0]],
        [-omg[1], omg[0], 0],
    ])


def _so3_to_vec(so3mat):
    return np.array([so3mat[2, 1], so3mat[0, 2], so3mat[1, 0]])


def _matrix_exp3(so3mat):
    omgtheta = _so3_to_vec(so3mat)
    theta = np.linalg.norm(omgtheta)
    if _near_zero(theta):
        return np.eye(3)
    omgmat = so3mat / theta
    return (np.eye(3)
            + np.sin(theta) * omgmat
            + (1 - np.cos(theta)) * omgmat @ omgmat)


def _matrix_log3(R):
    acosinput = (np.trace(R) - 1) / 2.0
    if acosinput >= 1:
        return np.zeros((3, 3))
    elif acosinput <= -1:
        if not _near_zero(1 + R[2, 2]):
            omg = (1.0 / np.sqrt(2 * (1 + R[2, 2]))) * np.array(
                [R[0, 2], R[1, 2], 1 + R[2, 2]])
        elif not _near_zero(1 + R[1, 1]):
            omg = (1.0 / np.sqrt(2 * (1 + R[1, 1]))) * np.array(
                [R[0, 1], 1 + R[1, 1], R[2, 1]])
        else:
            omg = (1.0 / np.sqrt(2 * (1 + R[0, 0]))) * np.array(
                [1 + R[0, 0], R[1, 0], R[2, 0]])
        return _vec_to_so3(np.pi * omg)
    else:
        theta = np.arccos(acosinput)
        return theta / (2.0 * np.sin(theta)) * (R - R.T)


def _vec_to_se3(V):
    return np.r_[
        np.c_[_vec_to_so3(V[:3]), V[3:6]],
        np.zeros((1, 4)),
    ]


def _se3_to_vec(se3mat):
    return np.array([
        se3mat[2, 1], se3mat[0, 2], se3mat[1, 0],
        se3mat[0, 3], se3mat[1, 3], se3mat[2, 3],
    ])


def _trans_inv(T):
    R = T[:3, :3]
    p = T[:3, 3]
    Rt = R.T
    return np.r_[np.c_[Rt, -Rt @ p], [[0, 0, 0, 1]]]


def _adjoint(T):
    R = T[:3, :3]
    p = T[:3, 3]
    return np.r_[
        np.c_[R, np.zeros((3, 3))],
        np.c_[_vec_to_so3(p) @ R, R],
    ]


def _matrix_exp6(se3mat):
    omgtheta = _so3_to_vec(se3mat[:3, :3])
    theta = np.linalg.norm(omgtheta)
    if _near_zero(theta):
        return np.r_[np.c_[np.eye(3), se3mat[:3, 3]], [[0, 0, 0, 1]]]
    omgmat = se3mat[:3, :3] / theta
    R = _matrix_exp3(se3mat[:3, :3])
    G = (np.eye(3) * theta
         + (1 - np.cos(theta)) * omgmat
         + (theta - np.sin(theta)) * omgmat @ omgmat)
    p = G @ se3mat[:3, 3] / theta
    return np.r_[np.c_[R, p], [[0, 0, 0, 1]]]


def _matrix_log6(T):
    R = T[:3, :3]
    p = T[:3, 3]
    omgmat = _matrix_log3(R)
    if np.allclose(omgmat, 0):
        return np.r_[np.c_[np.zeros((3, 3)), p.reshape(3, 1)],
                     [[0, 0, 0, 0]]]
    theta = np.arccos((np.trace(R) - 1) / 2.0)
    Ginv = (np.eye(3) - omgmat / 2.0
            + (1.0 / theta - 1.0 / np.tan(theta / 2.0) / 2)
            * omgmat @ omgmat / theta)
    return np.r_[np.c_[omgmat, (Ginv @ p).reshape(3, 1)],
                 [[0, 0, 0, 0]]]


def _fk_body(M, Blist, thetalist):
    T = np.array(M, dtype=float)
    for i in range(len(thetalist)):
        T = T @ _matrix_exp6(_vec_to_se3(Blist[:, i] * thetalist[i]))
    return T


def _jacobian_body(Blist, thetalist):
    n = len(thetalist)
    Jb = np.array(Blist, dtype=float).copy()
    T = np.eye(4)
    for i in range(n - 2, -1, -1):
        T = T @ _matrix_exp6(_vec_to_se3(Blist[:, i + 1] * -thetalist[i + 1]))
        Jb[:, i] = _adjoint(T) @ Blist[:, i]
    return Jb


# ---------------------------------------------------------------------------
# Exported API
# ---------------------------------------------------------------------------

def next_state(config, controls, dt, speed_limit):
    controls = np.clip(np.asarray(controls, dtype=float),
                       -speed_limit, speed_limit)
    config = np.asarray(config, dtype=float).copy()

    phi, x, y = config[0], config[1], config[2]
    theta = config[3:8]
    wheels = config[8:12]

    u = controls[:4]
    dtheta = controls[4:9]

    new_theta = theta + dtheta * dt
    new_wheels = wheels + u * dt

    dwheel = u * dt
    Vb = _F @ dwheel   # (wbz, vbx, vby)
    wbz, vbx, vby = Vb

    if abs(wbz) < 1e-10:
        dx_b, dy_b = vbx, vby
    else:
        dx_b = (vbx * np.sin(wbz) + vby * (np.cos(wbz) - 1)) / wbz
        dy_b = (vby * np.sin(wbz) + vbx * (1 - np.cos(wbz))) / wbz

    new_phi = phi + wbz
    new_x = x + np.cos(phi) * dx_b - np.sin(phi) * dy_b
    new_y = y + np.sin(phi) * dx_b + np.cos(phi) * dy_b

    return np.array([new_phi, new_x, new_y,
                     *new_theta, *new_wheels])


def compute_end_effector_config(config):
    config = np.asarray(config, dtype=float)
    phi, x, y = config[0], config[1], config[2]
    theta = config[3:8]

    Tsb = np.array([
        [np.cos(phi), -np.sin(phi), 0, x],
        [np.sin(phi),  np.cos(phi), 0, y],
        [0, 0, 1, _z],
        [0, 0, 0, 1],
    ])

    T0e = _fk_body(_M0e, _Blist, theta)
    return Tsb @ _Tb0 @ T0e


def mobile_manipulator_jacobian(config):
    config = np.asarray(config, dtype=float)
    theta = config[3:8]

    T0e = _fk_body(_M0e, _Blist, theta)
    Tbe = _Tb0 @ T0e
    Teb = _trans_inv(Tbe)

    Jarm = _jacobian_body(_Blist, theta)

    F6 = np.zeros((6, 4))
    F6[2, :] = _F[0, :]   # omega_z
    F6[3, :] = _F[1, :]   # v_x
    F6[4, :] = _F[2, :]   # v_y

    Jbase = _adjoint(Teb) @ F6

    return np.hstack([Jbase, Jarm])


def feedback_control(X, Xd, Xd_next, Kp, Ki, error_integral, dt):
    X = np.asarray(X, dtype=float)
    Xd = np.asarray(Xd, dtype=float)
    Xd_next = np.asarray(Xd_next, dtype=float)
    Kp = np.asarray(Kp, dtype=float)
    Ki = np.asarray(Ki, dtype=float)
    error_integral = np.asarray(error_integral, dtype=float)

    Xerr = _se3_to_vec(_matrix_log6(_trans_inv(X) @ Xd))
    Vd = _se3_to_vec(_matrix_log6(_trans_inv(Xd) @ Xd_next)) / dt
    Ad = _adjoint(_trans_inv(X) @ Xd)

    new_error_integral = error_integral + Xerr * dt
    V = Ad @ Vd + Kp @ Xerr + Ki @ new_error_integral

    return V, Xerr, new_error_integral


def compute_controls(V, config):
    Je = mobile_manipulator_jacobian(config)
    return np.linalg.pinv(Je) @ V
