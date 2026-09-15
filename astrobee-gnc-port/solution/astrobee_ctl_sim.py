#!/usr/bin/env python3
"""
Astrobee GNC Controller Simulation — faithful Python port of ctl_src.cc.

Implements the NASA Astrobee free-flyer PID controller with quaternion-based
attitude control and closed-loop rigid-body dynamics simulation.
"""

import json
import sys

import numpy as np
from scipy.linalg import expm


# ── Quaternion helpers (Eigen [x,y,z,w] coeffs order) ──────────────


def quat_multiply(q1, q2):
    """Hamilton product of two quaternions in [x,y,z,w] storage."""
    x1, y1, z1, w1 = q1
    x2, y2, z2, w2 = q2
    return np.array([
        w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
        w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
        w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
        w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
    ])


def quat_conjugate(q):
    """Conjugate: negate vector part, keep scalar."""
    return np.array([-q[0], -q[1], -q[2], q[3]])


def normalize_quaternion(q):
    """Normalize and enforce positive w (scalar). Mirrors C++ NormalizeQuaternion."""
    q = np.array(q, dtype=float).copy()
    if q[3] < 0:
        q = -q
    mag = np.sqrt(q[0] ** 2 + q[1] ** 2 + q[2] ** 2 + q[3] ** 2)
    if mag > 1e-7:
        q /= mag
    return q


def quat_to_rotation_matrix(q):
    """Convert [x,y,z,w] quaternion to 3x3 rotation matrix (Eigen convention)."""
    x, y, z, w = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def omega_matrix(v):
    """4x4 Omega matrix for quaternion kinematics.
    From Trawny & Roumeliotis, 'Indirect Kalman Filter for 3D Attitude
    Estimation', Eq. 63.  Operates on [x,y,z,w] quaternion vectors."""
    return np.array([
        [0, v[2], -v[1], v[0]],
        [-v[2], 0, v[0], v[1]],
        [v[1], -v[0], 0, v[2]],
        [-v[0], -v[1], -v[2], 0],
    ])


# ── Controller ──────────────────────────────────────────────────────


class AstrobeeController:
    """Faithful port of the Astrobee GNC controller (ctl namespace)."""

    def __init__(self, config, constants):
        # Tuning parameters (from gnc_config.txt / scenarios.json)
        self.tun_vel_gain = float(config["tun_vel_gain"])
        self.tun_accel_gain = np.array(config["tun_accel_gain"], dtype=float)
        self.tun_alpha_gain = np.array(config["tun_alpha_gain"], dtype=float)
        self.tun_ctl_linear_force_limit = float(config["tun_ctl_linear_force_limit"])
        self.tun_ctl_att_sat_lower = float(config["tun_ctl_att_sat_lower"])
        self.tun_ctl_att_sat_upper = float(config["tun_ctl_att_sat_upper"])
        self.tun_ctl_pos_sat_lower = float(config["tun_ctl_pos_sat_lower"])
        self.tun_ctl_pos_sat_upper = float(config["tun_ctl_pos_sat_upper"])
        self.tun_ctl_stopped_pos_thresh = float(config["tun_ctl_stopped_pos_thresh"])
        self.tun_ctl_stopped_quat_thresh = float(config["tun_ctl_stopped_quat_thresh"])
        self.tun_ctl_stopping_vel_thresh = float(config["tun_ctl_stopping_vel_thresh"])
        self.tun_ctl_stopping_omega_thresh = float(config["tun_ctl_stopping_omega_thresh"])

        # Mode constants
        self.CTL_IDLE = int(constants["ctl_idle_mode"])
        self.CTL_STOPPING = int(constants["ctl_stopping_mode"])
        self.CTL_STOPPED = int(constants["ctl_stopped_mode"])
        self.ASE_CONVERGED = int(constants["ase_status_converged"])

        self._initialize()

    # ---- Control::Initialize ----------------------------------------

    def _initialize(self):
        self.mode_cmd = 0
        self.stopped_mode = False
        self.prev_filter_vel = np.zeros(3)
        self.prev_filter_omega = np.zeros(3)
        self.prev_mode_cmd = np.zeros(5, dtype=int)
        self.prev_position = np.zeros(3)
        # C++ initialises prev_att_ to (x=0,y=0,z=0,w=0) — a zero quaternion.
        self.prev_att = np.array([0.0, 0.0, 0.0, 0.0])
        self.linear_integrator = np.zeros(3)
        self.rotational_integrator = np.zeros(3)

    # ---- Utility functions ------------------------------------------

    @staticmethod
    def _safe_divide(num, denom):
        out = np.zeros(3)
        for i in range(3):
            out[i] = num[i] / denom[i] if denom[i] != 0 else 0.0
        return out

    @staticmethod
    def _saturate_vector(v, limit):
        mag = np.linalg.norm(v)
        if mag < limit:
            return v.copy()
        return (limit / mag) * v

    @staticmethod
    def _rotate_a_to_b(v, q):
        """q.normalized().conjugate().toRotationMatrix() * v"""
        qn = q / np.linalg.norm(q)
        R = quat_to_rotation_matrix(quat_conjugate(qn))
        return R @ v

    @staticmethod
    def _quat_error(cmd, actual):
        """Scalar quaternion error angle (radians)."""
        out = quat_multiply(quat_conjugate(actual), cmd)
        out = normalize_quaternion(out)
        return abs(float(np.arccos(np.clip(out[3], -1.0, 1.0)))) * 2

    # ---- Butterworth / filter threshold -----------------------------

    @staticmethod
    def _butterworth(inp, delay):
        g1 = 0.0031317642291927056
        g2 = -0.993736471541614597
        tmp = inp * g1 - delay * g2
        output = tmp + delay
        return tmp, output * output  # new_delay, contribution to sum

    def _filter_threshold(self, vec, threshold, prev):
        total = 0.0
        new_prev = prev.copy()
        for i in range(3):
            new_prev[i], c = self._butterworth(vec[i], prev[i])
            total += c
        return total < threshold, new_prev

    # ---- Discrete-time integrator (62.5 Hz) -------------------------

    def _integrate(self, inp, acc, status, hi, lo):
        if status <= 1:
            return np.zeros(3), np.zeros(3)
        acc = acc + inp / 62.5
        out = acc.copy()
        for i in range(3):
            out[i] = max(lo, min(hi, out[i]))
        return out, acc

    # ---- Main step --------------------------------------------------

    def step(self, dt, state, cmd):
        """Execute one control cycle.  Returns dict with body_force_cmd,
        body_torque_cmd and diagnostic fields."""
        out = {}

        # ── ForwardTrajectory ──
        traj_pos = cmd["P"] + cmd["V"] * dt + 0.5 * cmd["A"] * dt ** 2
        traj_vel = cmd["V"] + cmd["A"] * dt
        traj_accel = cmd["A"].copy()
        traj_alpha = cmd["alpha"].copy()
        traj_omega = cmd["omega"] + cmd["alpha"] * dt

        Om_w = omega_matrix(cmd["omega"])
        Om_a = omega_matrix(cmd["alpha"])
        M = 0.5 * dt * (0.5 * dt * Om_a + Om_w)
        M = expm(M)
        M += (1.0 / 48.0) * dt ** 3 * (Om_a @ Om_w - Om_w @ Om_a)
        traj_quat = normalize_quaternion(M @ cmd["quat"])

        # ── UpdateMode ──
        if state["confidence"] != self.ASE_CONVERGED:
            self.mode_cmd = self.CTL_IDLE
        else:
            self.mode_cmd = cmd["mode"]

        for i in range(3, -1, -1):
            self.prev_mode_cmd[i + 1] = self.prev_mode_cmd[i]
        self.prev_mode_cmd[0] = self.mode_cmd

        vb, self.prev_filter_vel = self._filter_threshold(
            state["V"], self.tun_ctl_stopping_vel_thresh, self.prev_filter_vel
        )
        ob, self.prev_filter_omega = self._filter_threshold(
            state["omega"], self.tun_ctl_stopping_omega_thresh, self.prev_filter_omega
        )

        self.stopped_mode = False
        if vb and ob:
            p = self.prev_mode_cmd
            if (
                p[4] == self.CTL_STOPPING
                and p[4] == p[3]
                and p[3] == p[2]
                and p[2] == p[1]
            ):
                self.stopped_mode = True

        # ── UpdateCtlStatus ──
        pe_sq = float(np.sum((self.prev_position - state["P"]) ** 2))
        qe = self._quat_error(state["quat"], self.prev_att)

        if (
            (pe_sq > self.tun_ctl_stopped_pos_thresh or abs(qe) > self.tun_ctl_stopped_quat_thresh)
            and self.mode_cmd == self.CTL_STOPPED
        ):
            ctl_status = self.CTL_STOPPING
        elif self.stopped_mode:
            ctl_status = self.CTL_STOPPED
        else:
            ctl_status = self.mode_cmd
        out["ctl_status"] = ctl_status

        # ── FindPosErr ──
        target_p = self.prev_position.copy() if self.stopped_mode else traj_pos
        pos_err = target_p - state["P"]

        Ki_lin = self._safe_divide(state["pos_ki"], state["vel_kd"])
        pos_err_int, self.linear_integrator = self._integrate(
            Ki_lin * pos_err,
            self.linear_integrator,
            ctl_status,
            self.tun_ctl_pos_sat_upper,
            self.tun_ctl_pos_sat_lower,
        )

        # ── FindBodyForceCmd ──
        if ctl_status == 0:
            body_force = np.zeros(3)
        else:
            t_vel = np.zeros(3) if self.stopped_mode else traj_vel
            t_acc = np.zeros(3) if self.stopped_mode else traj_accel
            Kp_lin = self._safe_divide(state["pos_kp"], state["vel_kd"])

            if ctl_status > 1:
                v = (
                    self.tun_vel_gain * (t_vel - state["V"])
                    + Kp_lin * pos_err
                    + pos_err_int
                )
            else:
                v = -state["V"].copy()

            a = self._rotate_a_to_b(v, state["quat"]) * state["vel_kd"]
            b = self._rotate_a_to_b(t_acc * self.tun_accel_gain, state["quat"])
            body_force = self._saturate_vector(
                state["mass"] * (a + b), self.tun_ctl_linear_force_limit
            )
        out["body_force_cmd"] = body_force

        # ── FindAttErr ──
        q_cmd = self.prev_att.copy() if self.stopped_mode else traj_quat
        q_out = normalize_quaternion(quat_multiply(quat_conjugate(state["quat"]), q_cmd))
        att_err = q_out[:3].copy()

        Ki_rot = self._safe_divide(state["att_ki"], state["omega_kd"])
        att_err_int, self.rotational_integrator = self._integrate(
            att_err * Ki_rot,
            self.rotational_integrator,
            ctl_status,
            self.tun_ctl_att_sat_upper,
            self.tun_ctl_att_sat_lower,
        )

        # ── FindBodyAlphaTorqueCmd ──
        c_omega = np.zeros(3) if self.stopped_mode else traj_omega
        c_alpha = np.zeros(3) if self.stopped_mode else traj_alpha
        I = state["inertia"]

        if ctl_status > 1:
            Kp_rot = self._safe_divide(state["att_kp"], state["omega_kd"])
            rate_err = c_omega + att_err_int + Kp_rot * att_err - state["omega"]
        else:
            rate_err = -state["omega"].copy()

        Kd_rot = state["omega_kd"] * np.diag(I)
        rate_err_s = rate_err * Kd_rot

        if ctl_status == 0:
            body_torque = np.zeros(3)
        else:
            Iw = I @ state["omega"]
            body_torque = (
                I @ (self.tun_alpha_gain * c_alpha)
                + rate_err_s
                - np.cross(Iw, state["omega"])
            )
        out["body_torque_cmd"] = body_torque

        # ── UpdatePrevious ──
        if not self.stopped_mode:
            self.prev_position = state["P"].copy()
            self.prev_att = state["quat"].copy()

        return out


# ── Closed-loop simulation ──────────────────────────────────────────


def simulate_scenario(scenario, config, robot, constants):
    dt = 1.0 / constants["controller_rate_hz"]
    n_steps = scenario["num_steps"]

    # Plant state
    p = np.array(scenario["initial"]["position"], dtype=float)
    v = np.array(scenario["initial"]["velocity"], dtype=float)
    q = np.array(scenario["initial"]["quaternion"], dtype=float)
    w = np.array(scenario["initial"]["omega"], dtype=float)

    mass = float(robot["mass"])
    I = np.array(robot["inertia"], dtype=float)
    I_inv = np.linalg.inv(I)

    # Fixed command
    cmd = {
        "mode": scenario["target"]["mode"],
        "P": np.array(scenario["target"]["position"], dtype=float),
        "V": np.array(scenario["target"]["velocity"], dtype=float),
        "A": np.array(scenario["target"]["acceleration"], dtype=float),
        "quat": np.array(scenario["target"]["quaternion"], dtype=float),
        "omega": np.array(scenario["target"]["omega"], dtype=float),
        "alpha": np.array(scenario["target"]["alpha"], dtype=float),
    }

    ctl = AstrobeeController(config, constants)

    s1_force = s1_torque = None

    for i in range(n_steps):
        state = {
            "P": p.copy(),
            "V": v.copy(),
            "quat": q.copy(),
            "omega": w.copy(),
            "confidence": scenario["confidence"],
            "mass": mass,
            "inertia": I,
            "pos_kp": np.array(robot["pos_kp"], dtype=float),
            "pos_ki": np.array(robot["pos_ki"], dtype=float),
            "vel_kd": np.array(robot["vel_kd"], dtype=float),
            "att_kp": np.array(robot["att_kp"], dtype=float),
            "att_ki": np.array(robot["att_ki"], dtype=float),
            "omega_kd": np.array(robot["omega_kd"], dtype=float),
        }

        out = ctl.step(dt, state, cmd)

        if i == 0:
            s1_force = out["body_force_cmd"].tolist()
            s1_torque = out["body_torque_cmd"].tolist()

        # Plant dynamics
        R = quat_to_rotation_matrix(q)          # body -> ISS
        F_ISS = R @ out["body_force_cmd"]

        # Semi-implicit Euler (linear)
        v = v + (F_ISS / mass) * dt
        p = p + v * dt

        # Angular dynamics (body frame, Newton-Euler)
        alpha = I_inv @ (out["body_torque_cmd"] - np.cross(w, I @ w))
        w = w + alpha * dt

        # Quaternion kinematic integration (ISS-frame omega, OmegaMatrix)
        w_ISS = R @ w
        q = q + 0.5 * dt * omega_matrix(w_ISS) @ q
        q = normalize_quaternion(q)

    return {
        "final_position": p.tolist(),
        "final_velocity": v.tolist(),
        "final_quaternion": q.tolist(),
        "final_omega": w.tolist(),
        "step_1_force": s1_force,
        "step_1_torque": s1_torque,
    }


# ── Main ────────────────────────────────────────────────────────────


def main():
    sc_path = "/app/scenarios.json"
    out_path = "/app/results.json"
    if len(sys.argv) >= 3:
        sc_path, out_path = sys.argv[1], sys.argv[2]

    with open(sc_path) as f:
        data = json.load(f)

    cfg = data["config"]
    robot = data["robot"]
    consts = data["constants"]

    results = {}
    for sc in data["scenarios"]:
        name = sc["name"]
        print(f"Simulating: {name} ({sc['num_steps']} steps)")
        results[name] = simulate_scenario(sc, cfg, robot, consts)
        fp = results[name]["final_position"]
        print(f"  final_pos = [{fp[0]:.6f}, {fp[1]:.6f}, {fp[2]:.6f}]")

    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Results written to {out_path}")


if __name__ == "__main__":
    main()
