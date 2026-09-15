#!/usr/bin/env python3
"""
Minimal-coordinate ODE reference for a planar double pendulum
(uniform rigid rods, pin joints, gravity).

Uses classical 4th-order Runge-Kutta with a fine time step (1e-4) for
high-accuracy reference trajectories.  No external dependencies beyond
the Python standard library.

Usage:
  python3 pendulum_ref.py theta1 theta2 omega1 omega2 t_end output.csv

Physical parameters match the C++ model defaults:
  L1 = L2 = 1, m1 = m2 = 1, g = 9.81
"""

import math
import sys

L1, L2 = 1.0, 1.0
M1, M2 = 1.0, 1.0
G = 9.81


def rhs(y):
    """Right-hand side of the double pendulum ODE in minimal coordinates."""
    theta1, theta2, omega1, omega2 = y
    c = math.cos(theta1 - theta2)
    s = math.sin(theta1 - theta2)

    a11 = (M1 / 3.0 + M2) * L1 * L1
    a12 = 0.5 * M2 * L1 * L2 * c
    a22 = M2 * L2 * L2 / 3.0

    b1 = (-0.5 * M2 * L1 * L2 * s * omega2 * omega2
          - G * math.cos(theta1) * (M1 * L1 / 2.0 + M2 * L1))
    b2 = (0.5 * M2 * L1 * L2 * s * omega1 * omega1
          - M2 * G * (L2 / 2.0) * math.cos(theta2))

    det = a11 * a22 - a12 * a12
    return [omega1, omega2,
            (a22 * b1 - a12 * b2) / det,
            (a11 * b2 - a12 * b1) / det]


def integrate(y0, t_end, h=1e-4):
    """RK4 integration with output at 0.001-second intervals."""
    n = int(round(t_end / h))
    out_dt = min(0.001, t_end)
    out_every = max(1, int(round(out_dt / h)))

    y = list(y0)
    times = [0.0]
    states = [list(y)]

    for i in range(1, n + 1):
        k1 = rhs(y)
        y2 = [y[j] + 0.5 * h * k1[j] for j in range(4)]
        k2 = rhs(y2)
        y3 = [y[j] + 0.5 * h * k2[j] for j in range(4)]
        k3 = rhs(y3)
        y4 = [y[j] + h * k3[j] for j in range(4)]
        k4 = rhs(y4)
        y = [y[j] + h / 6.0 * (k1[j] + 2 * k2[j] + 2 * k3[j] + k4[j])
             for j in range(4)]

        if i % out_every == 0:
            times.append(i * h)
            states.append(list(y))

    if abs(times[-1] - t_end) > 1e-12:
        times.append(n * h)
        states.append(list(y))

    return times, states


def main():
    if len(sys.argv) != 7:
        sys.exit("Usage: pendulum_ref.py theta1 theta2 omega1 omega2 t_end output.csv")

    theta1 = float(sys.argv[1])
    theta2 = float(sys.argv[2])
    omega1 = float(sys.argv[3])
    omega2 = float(sys.argv[4])
    t_end = float(sys.argv[5])
    out_file = sys.argv[6]

    times, states = integrate([theta1, theta2, omega1, omega2], t_end)

    with open(out_file, "w") as f:
        f.write("time,theta1,theta2,omega1,omega2\n")
        for t, s in zip(times, states):
            f.write(f"{t:.15e},{s[0]:.15e},{s[1]:.15e},"
                    f"{s[2]:.15e},{s[3]:.15e}\n")


if __name__ == "__main__":
    main()
