#!/usr/bin/env python3
"""Diagnose and fix the three mathematical bugs in the EKF-SLAM implementation.

Derives the correct formulas from the standard EKF-SLAM velocity motion
model and range-bearing observation model, then patches the implementation.

"""


def derive_and_fix():
    """Read ekf_slam.py, identify mathematical errors, apply corrections.

    The correct EKF-SLAM equations for a 2D velocity motion model:

    Motion model (state update):
        x' = x + v * dt * cos(theta)      -- projects velocity along heading
        y' = y + v * dt * sin(theta)
        theta' = theta + omega * dt

    Observation model (predicted measurement):
        range = sqrt(dx^2 + dy^2)
        bearing = atan2(dy, dx) - theta    -- atan2 takes (y-component, x-component)
        where dx = lx - rx, dy = ly - ry

    Landmark initialization (global frame):
        angle = bearing + theta            -- bearing is robot-relative
        lx = rx + range * cos(angle)
        ly = ry + range * sin(angle)
    """
    with open('/app/ekf_slam.py', 'r') as f:
        lines = f.readlines()

    fixed = 0

    for i, line in enumerate(lines):
        # Bug 1: Motion model uses sin(theta) for x and cos(theta) for y.
        # Correct: x += v*dt*cos(theta), y += v*dt*sin(theta)
        # The cos/sin are swapped in the state update (lines with self.mu[0/1]).
        if 'self.mu[0] += v * dt * np.sin(theta)' in line:
            lines[i] = line.replace('np.sin(theta)', 'np.cos(theta)')
            fixed += 1
        elif 'self.mu[1] += v * dt * np.cos(theta)' in line:
            lines[i] = line.replace('np.cos(theta)', 'np.sin(theta)')
            fixed += 1

        # Bug 2: Observation model computes bearing as atan2(dx, dy).
        # Correct: atan2(dy, dx). The arguments are swapped.
        if 'np.arctan2(dx, dy)' in line:
            lines[i] = line.replace('np.arctan2(dx, dy)', 'np.arctan2(dy, dx)')
            fixed += 1

        # Bug 3: Landmark initialization uses z_bearing as global angle.
        # Correct: angle = z_bearing + rtheta (bearing is robot-relative).
        if line.strip() == 'angle = z_bearing':
            lines[i] = line.replace('z_bearing', 'z_bearing + rtheta')
            fixed += 1

    with open('/app/ekf_slam.py', 'w') as f:
        f.writelines(lines)

    print(f"Applied {fixed} fixes to /app/ekf_slam.py")
    if fixed != 4:
        raise RuntimeError(
            f"Expected 4 fixes (2 trig swaps + 1 atan2 + 1 angle) "
            f"but applied {fixed}"
        )


if __name__ == '__main__':
    derive_and_fix()
