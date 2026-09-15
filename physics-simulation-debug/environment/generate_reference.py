#!/usr/bin/env python3
"""Generate reference trajectory data using correct physics.

This script runs during Docker build (builder stage) and is NOT
included in the final image.  It produces the golden reference
JSON files that the tests compare against.
"""
import json
import math
import os

os.makedirs("/app/reference", exist_ok=True)


def rk4_step(f, state, t, dt):
    k1 = f(state, t)
    s2 = [s + 0.5 * dt * k for s, k in zip(state, k1)]
    k2 = f(s2, t + 0.5 * dt)
    s3 = [s + 0.5 * dt * k for s, k in zip(state, k2)]
    k3 = f(s3, t + 0.5 * dt)
    s4 = [s + dt * k for s, k in zip(state, k3)]
    k4 = f(s4, t + dt)
    return [s + dt / 6.0 * (a + 2 * b + 2 * c + d)
            for s, a, b, c, d in zip(state, k1, k2, k3, k4)]


def verlet_step(pos, vel, dt, accel_fn):
    dim = len(pos)
    acc_old = accel_fn(pos)
    pos_new = [pos[i] + vel[i] * dt + 0.5 * acc_old[i] * dt * dt
               for i in range(dim)]
    acc_new = accel_fn(pos_new)
    vel_new = [vel[i] + 0.5 * (acc_old[i] + acc_new[i]) * dt
               for i in range(dim)]
    return pos_new, vel_new


def save_ref(filepath, times, data, headers):
    with open(filepath, "w") as fh:
        json.dump({"times": times, "headers": headers, "data": data}, fh)


# ========== 1. Ballistic trajectory with QUADRATIC drag ==========

def gen_ballistic():
    g = 9.81
    rho = 1.225
    Cd = 0.47
    radius = 0.05
    A = math.pi * radius ** 2        # correct: projected area
    m = 0.5
    v0 = 50.0
    theta = math.radians(45)
    dt = 0.001

    def derivs(state, t):
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
        state = rk4_step(derivs, state, t, dt)
        t += dt
        if t > 0.1 and state[1] < 0:
            break

    step = max(1, len(times) // 500)
    save_ref("/app/reference/ballistic.json",
             times[::step], data[::step], ["x", "y", "vx", "vy"])


# ========== 2. Coupled spring-mass oscillators ==========

def gen_oscillator():
    m1, m2 = 1.0, 1.5
    k1, k2, k_c = 10.0, 8.0, 5.0
    dt = 0.001
    t_end = 10.0

    def derivs(state, t):
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
        state = rk4_step(derivs, state, t, dt)
        t += dt

    step = max(1, len(times) // 500)
    save_ref("/app/reference/oscillator.json",
             times[::step], data[::step], ["q1", "q2", "v1", "v2"])


# ========== 3. 1D thermal diffusion (stable FTCS) ==========

def gen_diffusion():
    alpha = 0.01
    L = 1.0
    T_left = 100.0
    T_right = 0.0
    nx = 50
    dx = L / (nx - 1)
    dt = 0.4 * dx ** 2 / alpha
    t_end = 5.0

    x = [i * dx for i in range(nx)]
    u = [T_left * (1.0 - xi / L) + T_right * (xi / L) for xi in x]
    u[0] = T_left
    u[-1] = T_right

    times, snapshots = [], []
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
        u_new[0] = T_left
        u_new[-1] = T_right
        u = u_new
        t += dt

    save_ref("/app/reference/diffusion.json", times, snapshots,
             [f"x={round(xi, 4)}" for xi in x])


# ========== 4. Keplerian orbit (Verlet) ==========

def gen_orbit():
    GM = 4.0 * math.pi ** 2
    a = 1.0
    e = 0.3
    r_peri = a * (1 - e)
    v_peri = math.sqrt(GM * (1 + e) / (a * (1 - e)))
    dt = 0.0001
    t_end = 2.0

    def grav_accel(pos):
        x, y = pos
        r = math.sqrt(x * x + y * y)
        r3 = r ** 3
        return [-GM * x / r3, -GM * y / r3]

    pos = [r_peri, 0.0]
    vel = [0.0, v_peri]
    times, data = [], []
    t = 0.0
    while t <= t_end:
        times.append(round(t, 6))
        data.append([round(s, 10) for s in pos + vel])
        pos, vel = verlet_step(pos, vel, dt, grav_accel)
        t += dt

    step = max(1, len(times) // 500)
    save_ref("/app/reference/orbit.json",
             times[::step], data[::step], ["x", "y", "vx", "vy"])


# ========== 5. 2D elastic collision ==========

def gen_collision():
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

    step = max(1, len(times) // 500)
    save_ref("/app/reference/collision.json",
             times[::step], data[::step],
             ["x1", "y1", "vx1", "vy1", "x2", "y2", "vx2", "vy2"])


if __name__ == "__main__":
    gen_ballistic()
    gen_oscillator()
    gen_diffusion()
    gen_orbit()
    gen_collision()
    print("Reference data generated successfully.")
