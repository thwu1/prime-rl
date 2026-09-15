"""RealAI Score computation for acrobot swing-up evaluation.

Score formula:
    S = success * (1 - 0.2 * sum(tanh(c_i / n_i)))

Components: swingup_time, actuator_energy, torque_cost, torque_smoothness, velocity_cost
Normalizations: 20s, 60J, 20Nm^2s, 0.1Nm, 400(rad/s)^2s
"""

import math


def compute_realai_score(trajectory, params):
    """Compute RealAI Score from a simulation trajectory.

    Args:
        trajectory: list of (t, q1, q2, q1d, q2d, tau) tuples
        params: dict with l1, l2, dt, ee_height_threshold, stabilization_time

    Returns:
        (score, details_dict) tuple
    """
    if len(trajectory) < 2:
        return 0.0, {'success': False}

    dt = params['dt']
    l1 = params['l1']
    l2 = params['l2']
    h_thresh = params['ee_height_threshold']
    stab_time = params.get('stabilization_time', 2.0)

    above_start = None
    swingup_time = None
    success = False

    for t, q1, q2, q1d, q2d, tau in trajectory:
        y_ee = -l1 * math.cos(q1) - l2 * math.cos(q1 + q2)
        if y_ee >= h_thresh:
            if above_start is None:
                above_start = t
            if t - above_start >= stab_time:
                if not success:
                    swingup_time = above_start
                    success = True
        else:
            above_start = None

    if not success:
        return 0.0, {'success': False, 'swingup_time': None}

    n = len(trajectory)
    c_energy = 0.0
    c_torque = 0.0
    c_velocity = 0.0

    for i in range(n):
        _, q1, q2, q1d, q2d, tau = trajectory[i]
        c_energy += abs(tau * q2d) * dt
        c_torque += tau * tau * dt
        c_velocity += (q1d * q1d + q2d * q2d) * dt

    taus = [row[5] for row in trajectory]
    dtaus = [taus[i + 1] - taus[i] for i in range(n - 1)]
    mean_dt = sum(dtaus) / len(dtaus)
    c_smooth = math.sqrt(sum((d - mean_dt) ** 2 for d in dtaus) / len(dtaus))

    score = 1.0 - 0.2 * (
        math.tanh(swingup_time / 20.0)
        + math.tanh(c_energy / 60.0)
        + math.tanh(c_torque / 20.0)
        + math.tanh(c_smooth / 0.1)
        + math.tanh(c_velocity / 400.0)
    )

    details = {
        'success': True,
        'swingup_time': round(swingup_time, 4),
        'energy': round(c_energy, 4),
        'torque_cost': round(c_torque, 4),
        'torque_smooth': round(c_smooth, 6),
        'velocity_cost': round(c_velocity, 4),
        'realai_score': round(score, 6),
    }
    return score, details
