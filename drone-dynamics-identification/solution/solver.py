#!/usr/bin/env python3
"""Gradient-based quadrotor system identification using JAX."""

import json
import os
import numpy as np

import jax
jax.config.update("jax_enable_x64", True)
import jax.numpy as jnp
import optax

# ── configuration ────────────────────────────────────────────────────────────

with open("/app/config.json") as _f:
    CFG = json.load(_f)

MASS = CFG["mass"]
L = CFG["L"]
G = CFG["g"]
DT = CFG["dt"]
A = L / np.sqrt(2.0)

PARAM_NAMES = ["Ixx", "Iyy", "Izz", "kf", "km", "drag", "motor_tau"]


# ── differentiable dynamics ──────────────────────────────────────────────────

def quat_multiply(q1, q2):
    x1, y1, z1, w1 = q1[0], q1[1], q1[2], q1[3]
    x2, y2, z2, w2 = q2[0], q2[1], q2[2], q2[3]
    return jnp.array([
        w1*x2 + x1*w2 + y1*z2 - z1*y2,
        w1*y2 - x1*z2 + y1*w2 + z1*x2,
        w1*z2 + x1*y2 - y1*x2 + z1*w2,
        w1*w2 - x1*x2 - y1*y2 - z1*z2,
    ])


def quat_rotate(q, v):
    qv = jnp.array([v[0], v[1], v[2], 0.0])
    qc = jnp.array([-q[0], -q[1], -q[2], q[3]])
    return quat_multiply(quat_multiply(q, qv), qc)[:3]


def rotvec_to_quat(rv):
    # NaN-safe: avoid division by zero in both forward and backward passes.
    # The naive jnp.where(angle > eps, sin(half)/angle, 0.5) produces NaN
    # gradients because JAX evaluates both branches and 0 * NaN = NaN.
    angle_sq = jnp.dot(rv, rv)
    safe_angle = jnp.sqrt(angle_sq + 1e-16)
    half = safe_angle / 2.0
    s = jnp.sin(half) / safe_angle   # -> 0.5 as angle -> 0
    c = jnp.cos(half)
    return jnp.array([rv[0]*s, rv[1]*s, rv[2]*s, c])


def normalize_q(q):
    return q / jnp.sqrt(jnp.dot(q, q) + 1e-16)


def step_fn(state, cmd, params):
    """Single Euler step.  params = (Ixx, Iyy, Izz, kf, km, drag, motor_tau)."""
    pos, quat, vel, ang_vel, rotor_vel = state
    Ixx, Iyy, Izz, kf, km, drag, motor_tau = params

    # motor dynamics
    rotor_vel_new = rotor_vel + motor_tau * (cmd - rotor_vel) * DT

    w_sq = rotor_vel ** 2
    F_thrust = kf * jnp.sum(w_sq)
    tau_x = kf * A * (-w_sq[0] - w_sq[1] + w_sq[2] + w_sq[3])
    tau_y = kf * A * (-w_sq[0] + w_sq[1] + w_sq[2] - w_sq[3])
    tau_z = km * (-w_sq[0] + w_sq[1] - w_sq[2] + w_sq[3])
    tau = jnp.array([tau_x, tau_y, tau_z])

    J = jnp.array([Ixx, Iyy, Izz])
    gyro = jnp.cross(ang_vel, J * ang_vel)
    ang_acc = (tau - gyro) / J

    thrust_w = quat_rotate(quat, jnp.array([0.0, 0.0, F_thrust]))
    gravity = jnp.array([0.0, 0.0, -MASS * G])
    acc = (thrust_w + gravity - drag * vel) / MASS

    new_pos = pos + vel * DT
    new_vel = vel + acc * DT
    new_ang_vel = ang_vel + ang_acc * DT
    new_quat = normalize_q(quat_multiply(quat, rotvec_to_quat(ang_vel * DT)))
    return (new_pos, new_quat, new_vel, new_ang_vel, rotor_vel_new)


def rollout(params_tuple, init_state, commands):
    """Forward-simulate using jax.lax.scan."""
    def scan_body(carry, cmd):
        ns = step_fn(carry, cmd, params_tuple)
        return ns, (ns[0], ns[1])  # carry, (pos, quat)
    _, (positions, quaternions) = jax.lax.scan(scan_body, init_state, commands)
    return positions, quaternions


# ── loss function ────────────────────────────────────────────────────────────

def trajectory_loss(log_params, init_state, commands, true_pos, true_quat):
    params = jnp.exp(log_params)
    pred_pos, pred_quat = rollout(tuple(params), init_state, commands)

    pos_loss = jnp.mean((pred_pos - true_pos) ** 2)
    # quaternion distance: 1 - |dot|^2, averaged
    dots = jnp.sum(pred_quat * true_quat, axis=-1)
    quat_loss = jnp.mean(1.0 - dots ** 2)
    return pos_loss + 0.5 * quat_loss


# ── data loading ─────────────────────────────────────────────────────────────

def load_trajectories(data_dir):
    trajs = []
    for fname in sorted(os.listdir(data_dir)):
        if not fname.endswith(".npz"):
            continue
        d = np.load(os.path.join(data_dir, fname))
        init = (
            jnp.array(d["initial_pos"], dtype=jnp.float64),
            jnp.array(d["initial_quat"], dtype=jnp.float64),
            jnp.array(d["initial_vel"], dtype=jnp.float64),
            jnp.array(d["initial_ang_vel"], dtype=jnp.float64),
            jnp.array(d["initial_rotor_vel"], dtype=jnp.float64),
        )
        cmds = jnp.array(d["commands"], dtype=jnp.float64)
        pos = jnp.array(d["positions"], dtype=jnp.float64)
        quat = jnp.array(d["quaternions"], dtype=jnp.float64)
        trajs.append((init, cmds, pos, quat))
    return trajs


# ── optimisation ─────────────────────────────────────────────────────────────

def make_total_loss(trajs):
    """Return a scalar loss function over all trajectories."""
    @jax.jit
    def total_loss(log_params):
        s = jnp.float64(0.0)
        for init, cmds, tpos, tquat in trajs:
            s = s + trajectory_loss(log_params, init, cmds, tpos, tquat)
        return s / len(trajs)
    return total_loss


def optimise(trajs, n_phases):
    # initial guesses (log-space)
    init_vals = jnp.array([
        2.0e-5,   # Ixx
        2.0e-5,   # Iyy
        3.0e-5,   # Izz
        4.0e-10,  # kf
        1.0e-11,  # km
        0.005,    # drag
        20.0,     # motor_tau
    ], dtype=jnp.float64)
    log_params = jnp.log(init_vals)

    loss_fn = make_total_loss(trajs)
    grad_fn = jax.jit(jax.grad(loss_fn))

    # Verify initial loss is finite
    init_loss = float(loss_fn(log_params))
    print(f"  initial loss = {init_loss:.8f}")

    best_loss = float("inf")
    best_log = log_params

    for lr, epochs in n_phases:
        opt = optax.chain(optax.clip_by_global_norm(5.0), optax.adam(lr))
        opt_state = opt.init(log_params)
        for ep in range(epochs):
            g = grad_fn(log_params)
            updates, opt_state = opt.update(g, opt_state)
            log_params = optax.apply_updates(log_params, updates)
            if ep % 100 == 0 or ep == epochs - 1:
                loss_val = float(loss_fn(log_params))
                tag = ""
                if loss_val < best_loss:
                    best_loss = loss_val
                    best_log = log_params
                    tag = " *"
                print(f"  lr={lr:.0e}  ep={ep:4d}  loss={loss_val:.8f}{tag}")

    return jnp.exp(best_log)


# ── write model.py ───────────────────────────────────────────────────────────

MODEL_PY = r'''
import jax
import jax.numpy as jnp


def _qm(q1, q2):
    x1,y1,z1,w1 = q1[0],q1[1],q1[2],q1[3]
    x2,y2,z2,w2 = q2[0],q2[1],q2[2],q2[3]
    return jnp.array([w1*x2+x1*w2+y1*z2-z1*y2,
                       w1*y2-x1*z2+y1*w2+z1*x2,
                       w1*z2+x1*y2-y1*x2+z1*w2,
                       w1*w2-x1*x2-y1*y2-z1*z2])

def _qr(q, v):
    qv = jnp.array([v[0],v[1],v[2],0.0])
    qc = jnp.array([-q[0],-q[1],-q[2],q[3]])
    return _qm(_qm(q, qv), qc)[:3]

def _rv2q(rv):
    asq = jnp.dot(rv, rv)
    sa = jnp.sqrt(asq + 1e-10)
    h = sa / 2.0
    s = jnp.sin(h) / sa
    c = jnp.cos(h)
    return jnp.array([rv[0]*s, rv[1]*s, rv[2]*s, c])

def _nq(q):
    return q / jnp.sqrt(jnp.dot(q, q) + 1e-10)


def simulate(params_dict, initial_state_dict, commands, dt, n_steps):
    mass = params_dict["mass"]
    L    = params_dict["L"]
    g    = params_dict["g"]
    Ixx  = params_dict["Ixx"]
    Iyy  = params_dict["Iyy"]
    Izz  = params_dict["Izz"]
    kf   = params_dict["kf"]
    km   = params_dict["km"]
    drag = params_dict["drag"]
    mtau = params_dict["motor_tau"]
    aa   = L / jnp.sqrt(2.0)

    init = (
        jnp.asarray(initial_state_dict["pos"],       dtype=jnp.float32),
        jnp.asarray(initial_state_dict["quat"],      dtype=jnp.float32),
        jnp.asarray(initial_state_dict["vel"],       dtype=jnp.float32),
        jnp.asarray(initial_state_dict["ang_vel"],   dtype=jnp.float32),
        jnp.asarray(initial_state_dict["rotor_vel"], dtype=jnp.float32),
    )

    def _step(state, cmd):
        pos, quat, vel, ang_vel, rv = state
        rv_new = rv + mtau * (cmd - rv) * dt
        ws = rv ** 2
        Ft = kf * jnp.sum(ws)
        tx = kf * aa * (-ws[0]-ws[1]+ws[2]+ws[3])
        ty = kf * aa * (-ws[0]+ws[1]+ws[2]-ws[3])
        tz = km * (-ws[0]+ws[1]-ws[2]+ws[3])
        tau = jnp.array([tx, ty, tz])
        J = jnp.array([Ixx, Iyy, Izz])
        gyro = jnp.cross(ang_vel, J * ang_vel)
        aa_ = (tau - gyro) / J
        tw = _qr(quat, jnp.array([0.,0.,Ft]))
        gv = jnp.array([0.,0.,-mass*g])
        acc = (tw + gv - drag*vel) / mass
        np_ = pos + vel * dt
        nv  = vel + acc * dt
        nw  = ang_vel + aa_ * dt
        nq  = _nq(_qm(quat, _rv2q(ang_vel * dt)))
        ns = (np_, nq, nv, nw, rv_new)
        return ns, ns

    _, traj = jax.lax.scan(_step, init, commands[:n_steps])
    return {
        "positions":          traj[0],
        "quaternions":        traj[1],
        "velocities":         traj[2],
        "angular_velocities": traj[3],
    }
'''


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    print("Loading training data …")
    trajs = load_trajectories("/app/data/training")
    print(f"  {len(trajs)} trajectories loaded")

    phases = [
        (1e-2, 600),
        (3e-3, 600),
        (5e-4, 400),
    ]
    print("Optimising …")
    final = optimise(trajs, phases)

    result = {n: float(final[i]) for i, n in enumerate(PARAM_NAMES)}
    with open("/app/identified_params.json", "w") as f:
        json.dump(result, f, indent=2)
    print(f"Identified parameters: {result}")

    with open("/app/model.py", "w") as f:
        f.write(MODEL_PY)
    print("Wrote /app/model.py")


if __name__ == "__main__":
    main()
