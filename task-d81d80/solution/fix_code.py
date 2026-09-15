#!/usr/bin/env python3
"""Fix defects in the multi-language EKF-SLAM system.

Identifies and corrects mathematical bugs in both the C motion model
and the Python observation/initialization code.

"""


def fix_c_motion_model():
    """Fix the C motion model state update."""
    with open('/app/motion_model.c', 'r') as f:
        code = f.read()

    # The motion_update function uses sin(theta) for x and cos(theta) for y.
    # The Jacobians are derived for the correct equations (cos for x, sin for y),
    # creating a function/linearization inconsistency that causes divergence.
    code = code.replace(
        'state[0] += v * dt * sin(theta)',
        'state[0] += v * dt * cos(theta)',
    )
    code = code.replace(
        'state[1] += v * dt * cos(theta)',
        'state[1] += v * dt * sin(theta)',
    )

    with open('/app/motion_model.c', 'w') as f:
        f.write(code)

    print("Fixed C motion model: corrected trig functions in motion_update")


def fix_python_ekf():
    """Fix the Python observation model and landmark initialization."""
    with open('/app/ekf_slam.py', 'r') as f:
        lines = f.readlines()

    fixed = 0
    for i, line in enumerate(lines):
        # The observation model computes bearing as atan2(dx, dy) but the
        # Jacobian is derived for atan2(dy, dx). Fix the function to match.
        if 'np.arctan2(dx, dy)' in line:
            lines[i] = line.replace('np.arctan2(dx, dy)', 'np.arctan2(dy, dx)')
            fixed += 1

        # Landmark initialization uses the bearing as a global angle, but
        # it is robot-relative and must be converted: angle = bearing + theta
        if line.strip() == 'angle = z_bearing':
            lines[i] = line.replace('z_bearing', 'z_bearing + rtheta')
            fixed += 1

    with open('/app/ekf_slam.py', 'w') as f:
        f.writelines(lines)

    print(f"Fixed Python EKF: applied {fixed} corrections")
    if fixed != 2:
        raise RuntimeError(f"Expected 2 Python fixes but applied {fixed}")


if __name__ == '__main__':
    fix_c_motion_model()
    fix_python_ekf()
