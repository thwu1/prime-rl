#!/usr/bin/env python3
"""Apply correct physics fixes to all five buggy simulations.

Bug 1 (ballistic.py): Uses drag = Cd*v/m (missing air density rho, cross-sectional
       area A, and the 0.5 factor from the quadratic drag law). Correct formula:
       drag_accel = 0.5 * rho * Cd * A * v / m  where A = pi * r^2.

Bug 2 (oscillator.py): Coupling spring force signs are flipped. The coupling force
       on m1 should be +kc*(q2-q1) (restoring toward q2) but code has -kc*(q2-q1).
       Similarly for m2: should be -kc*(q2-q1) but code has +kc*(q2-q1).

Bug 3 (diffusion.py): CFL stability parameter r = alpha*dt/dx^2 = 0.6 exceeds the
       FTCS stability limit of 0.5. Fix: use dt = 0.4*dx^2/alpha so r = 0.4.

Bug 4 (orbit.py): Gravitational acceleration uses r^2 in denominator instead of r^3.
       The vectorized form is a = -GM * r_vec / |r|^3 (from F/m = -GM/r^2 * r_hat,
       where r_hat = r_vec/|r|). Code has r^2, giving wrong force law (F ~ 1/r).

Bug 5 (collision.py): Elastic collision formula uses (m1+m2) in numerator where it
       should be (m1-m2). Correct: v1n' = ((m1-m2)*v1n + 2*m2*v2n) / (m1+m2).
       Buggy code has ((m1+m2)*v1n + ...) which doesn't conserve momentum/energy.
"""
import subprocess
import os


# ===== Fix 1: Ballistic =====
ballistic_fixed = '''#!/usr/bin/env python3
"""Projectile trajectory with air resistance — FIXED."""
import math
import sys
import os
sys.path.insert(0, "/app")
from engine import rk4_step, save_trajectory

g = 9.81
rho = 1.225
Cd = 0.47
radius = 0.05
A = math.pi * radius ** 2
m = 0.5
v0 = 50.0
theta = math.radians(45)
dt = 0.001

def derivatives(state, t):
    x, y, vx, vy = state
    v = math.sqrt(vx ** 2 + vy ** 2)
    if v < 1e-12:
        return [vx, vy, 0.0, -g]
    drag_accel = 0.5 * rho * Cd * A * v / m
    return [vx, vy, -drag_accel * vx, -g - drag_accel * vy]

state = [0.0, 0.0, v0 * math.cos(theta), v0 * math.sin(theta)]
times, data = [], []
t = 0.0
while True:
    times.append(round(t, 6))
    data.append([round(s, 10) for s in state])
    state = rk4_step(derivatives, state, t, dt)
    t += dt
    if t > 0.1 and state[1] < 0:
        break

os.makedirs("/app/output", exist_ok=True)
step = max(1, len(times) // 500)
save_trajectory("/app/output/ballistic.json",
                times[::step], data[::step], ["x", "y", "vx", "vy"])
'''

# ===== Fix 2: Oscillator =====
oscillator_fixed = '''#!/usr/bin/env python3
"""Coupled spring-mass oscillator — FIXED."""
import math
import sys
import os
sys.path.insert(0, "/app")
from engine import rk4_step, save_trajectory

m1 = 1.0
m2 = 1.5
k1 = 10.0
k2 = 8.0
k_c = 5.0
dt = 0.001
t_end = 10.0

def derivatives(state, t):
    q1, q2, v1, v2 = state
    f1 = (-k1 * q1 + k_c * (q2 - q1)) / m1
    f2 = (-k2 * q2 - k_c * (q2 - q1)) / m2
    return [v1, v2, f1, f2]

state = [0.5, -0.3, 0.0, 0.0]
times, data = [], []
t = 0.0
while t <= t_end:
    times.append(round(t, 6))
    data.append([round(s, 10) for s in state])
    state = rk4_step(derivatives, state, t, dt)
    t += dt

os.makedirs("/app/output", exist_ok=True)
step = max(1, len(times) // 500)
save_trajectory("/app/output/oscillator.json",
                times[::step], data[::step], ["q1", "q2", "v1", "v2"])
'''

# ===== Fix 3: Diffusion =====
diffusion_fixed = '''#!/usr/bin/env python3
"""1D thermal diffusion (FTCS) — FIXED."""
import json
import os

alpha = 0.01
L = 1.0
nx = 50
dx = L / (nx - 1)
dt = 0.4 * dx ** 2 / alpha
t_end = 5.0

x = [i * dx for i in range(nx)]
u = [100.0 * (1.0 - xi / L) for xi in x]

times = []
snapshots = []
t = 0.0
save_interval = 0.5
next_save = 0.0

while t <= t_end + 1e-10:
    if t >= next_save - 1e-10:
        times.append(round(t, 6))
        snapshots.append([round(ui, 10) for ui in u])
        next_save += save_interval

    u_new = list(u)
    r = alpha * dt / dx ** 2
    for i in range(1, nx - 1):
        u_new[i] = u[i] + r * (u[i + 1] - 2 * u[i] + u[i - 1])
    u_new[0] = 100.0
    u_new[-1] = 0.0
    u = u_new
    t += dt

os.makedirs("/app/output", exist_ok=True)
with open("/app/output/diffusion.json", "w") as fh:
    json.dump({"times": times,
               "headers": [f"x={round(xi, 4)}" for xi in x],
               "data": snapshots}, fh)
'''

# ===== Fix 4: Orbit =====
orbit_fixed = '''#!/usr/bin/env python3
"""Keplerian orbit — FIXED."""
import math
import sys
import os
sys.path.insert(0, "/app")
from engine import rk4_step, save_trajectory

GM = 4.0 * math.pi ** 2
a = 1.0
e = 0.3
r_peri = a * (1 - e)
v_peri = math.sqrt(GM * (1 + e) / (a * (1 - e)))
dt = 0.0001
t_end = 2.0

def derivatives(state, t):
    x, y, vx, vy = state
    r = math.sqrt(x ** 2 + y ** 2)
    r3 = r ** 3
    return [vx, vy, -GM * x / r3, -GM * y / r3]

state = [r_peri, 0.0, 0.0, v_peri]
times, data = [], []
t = 0.0
while t <= t_end:
    times.append(round(t, 6))
    data.append([round(s, 10) for s in state])
    state = rk4_step(derivatives, state, t, dt)
    t += dt

os.makedirs("/app/output", exist_ok=True)
step = max(1, len(times) // 500)
save_trajectory("/app/output/orbit.json",
                times[::step], data[::step], ["x", "y", "vx", "vy"])
'''

# ===== Fix 5: Collision =====
collision_fixed = '''#!/usr/bin/env python3
"""2D elastic collision — FIXED."""
import math
import json
import os

m1, m2 = 2.0, 3.0
v1x, v1y = 3.0, 1.0
v2x, v2y = -2.0, 0.5
r_collision = 0.5

x1_0 = -3.0
y1_0 = -1.1
x2_0 = 2.0
y2_0 = -0.4

dt = 0.001
t_end = 2.0

times, data = [], []
t = 0.0
vx1, vy1 = v1x, v1y
vx2, vy2 = v2x, v2y
x1, y1 = x1_0, y1_0
x2, y2 = x2_0, y2_0
collided = False

while t <= t_end:
    times.append(round(t, 6))
    data.append([round(s, 10) for s in [x1, y1, vx1, vy1, x2, y2, vx2, vy2]])

    ddx = x2 - x1
    ddy = y2 - y1
    dist = math.sqrt(ddx ** 2 + ddy ** 2)

    if not collided and dist <= r_collision:
        collided = True
        nx = ddx / dist
        ny = ddy / dist
        tx, ty = -ny, nx

        v1n = vx1 * nx + vy1 * ny
        v2n = vx2 * nx + vy2 * ny
        v1t = vx1 * tx + vy1 * ty
        v2t = vx2 * tx + vy2 * ty

        v1n_new = ((m1 - m2) * v1n + 2 * m2 * v2n) / (m1 + m2)
        v2n_new = ((m2 - m1) * v2n + 2 * m1 * v1n) / (m1 + m2)

        vx1 = v1n_new * nx + v1t * tx
        vy1 = v1n_new * ny + v1t * ty
        vx2 = v2n_new * nx + v2t * tx
        vy2 = v2n_new * ny + v2t * ty

    x1 += vx1 * dt
    y1 += vy1 * dt
    x2 += vx2 * dt
    y2 += vy2 * dt
    t += dt

os.makedirs("/app/output", exist_ok=True)
step = max(1, len(times) // 500)
with open("/app/output/collision.json", "w") as fh:
    json.dump({"times": times[::step],
               "headers": ["x1", "y1", "vx1", "vy1", "x2", "y2", "vx2", "vy2"],
               "data": data[::step]}, fh)
'''


def main():
    fixes = {
        "/app/simulations/ballistic.py": ballistic_fixed,
        "/app/simulations/oscillator.py": oscillator_fixed,
        "/app/simulations/diffusion.py": diffusion_fixed,
        "/app/simulations/orbit.py": orbit_fixed,
        "/app/simulations/collision.py": collision_fixed,
    }

    for path, code in fixes.items():
        with open(path, "w") as fh:
            fh.write(code)
        print(f"Fixed: {path}")

    # Run all simulations
    for name in ["ballistic", "oscillator", "diffusion", "orbit", "collision"]:
        print(f"Running {name}...")
        result = subprocess.run(
            ["python3", f"/app/simulations/{name}.py"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            print(f"  ERROR: {result.stderr[:200]}")
        else:
            print(f"  OK")


if __name__ == "__main__":
    main()
