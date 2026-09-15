#!/usr/bin/env python3
"""
Solution for the e-value sequential monitoring task.

Implements mixture supermartingales from Howard et al. (2021),
e-value merging from Vovk & Wang (2024), and confidence sequences.
"""


import json
import numpy as np
from scipy import special, optimize, stats


class TwoSidedNormalMixture:
    def __init__(self, v_opt, alpha_opt):
        la = np.log(1.0 / alpha_opt)
        self.rho = v_opt / (2.0 * la + np.log(1.0 + 2.0 * la))

    def log_superMG(self, s, v):
        return 0.5 * np.log(self.rho / (v + self.rho)) + s ** 2 / (2.0 * (v + self.rho))

    def bound(self, v, log_threshold):
        return np.sqrt(
            (v + self.rho) * (np.log(1.0 + v / self.rho) + 2.0 * log_threshold)
        )


class OneSidedNormalMixture:
    def __init__(self, v_opt, alpha_opt):
        la = np.log(1.0 / (2.0 * alpha_opt))
        self.rho = v_opt / (2.0 * la + np.log(1.0 + 2.0 * la))

    def log_superMG(self, s, v):
        return (
            0.5 * np.log(4.0 * self.rho / (v + self.rho))
            + s ** 2 / (2.0 * (v + self.rho))
            + np.log(stats.norm.cdf(s / np.sqrt(v + self.rho)))
        )

    def bound(self, v, log_threshold):
        def root_fn(s):
            return self.log_superMG(s, v) - log_threshold

        s_upper = max(float(v), 1.0)
        for _ in range(50):
            if self.log_superMG(s_upper, v) > log_threshold:
                break
            s_upper *= 2.0
        if root_fn(s_upper) < 0:
            return s_upper
        return optimize.bisect(root_fn, 0.0, s_upper, xtol=2 ** -40)


class GammaExponentialMixture:
    def __init__(self, v_opt, alpha_opt, c):
        osn = OneSidedNormalMixture(v_opt, alpha_opt)
        self.rho = osn.rho
        self.c = c
        rho_c_sq = self.rho / (c * c)
        self.leading_constant = (
            rho_c_sq * np.log(rho_c_sq)
            - special.gammaln(rho_c_sq)
            - np.log(special.gammainc(rho_c_sq, rho_c_sq))
        )

    def log_superMG(self, s, v):
        c_sq = self.c ** 2
        cs_v_csq = (self.c * s + v) / c_sq
        v_rho_csq = (v + self.rho) / c_sq
        return (
            self.leading_constant
            + special.gammaln(v_rho_csq)
            + np.log(special.gammainc(v_rho_csq, cs_v_csq + self.rho / c_sq))
            - v_rho_csq * np.log(cs_v_csq + self.rho / c_sq)
            + cs_v_csq
        )

    def bound(self, v, log_threshold):
        def root_fn(s):
            return self.log_superMG(s, v) - log_threshold

        s_upper = max(float(v), 1.0)
        for _ in range(50):
            if self.log_superMG(s_upper, v) > log_threshold:
                break
            s_upper *= 2.0
        if root_fn(s_upper) < 0:
            return s_upper
        return optimize.bisect(root_fn, 0.0, s_upper, xtol=2 ** -40)


def solve():
    with open("/app/problem.json") as f:
        problem = json.load(f)

    results = {}

    # ========== Part 1: Mixture Supermartingale Values ==========
    p1_cfg = problem["part1_mixture_supermartingales"]

    tsn_cfg = p1_cfg["two_sided_normal"]
    tsn = TwoSidedNormalMixture(tsn_cfg["v_opt"], tsn_cfg["alpha_opt"])

    osn_cfg = p1_cfg["one_sided_normal"]
    osn = OneSidedNormalMixture(osn_cfg["v_opt"], osn_cfg["alpha_opt"])

    ge_cfg = p1_cfg["gamma_exponential"]
    ge = GammaExponentialMixture(ge_cfg["v_opt"], ge_cfg["alpha_opt"], ge_cfg["c"])

    results["part1"] = {
        "two_sided_normal": {
            "rho": float(tsn.rho),
            "log_superMG_values": [
                float(tsn.log_superMG(pt[0], pt[1])) for pt in tsn_cfg["eval_points"]
            ],
        },
        "one_sided_normal": {
            "rho": float(osn.rho),
            "log_superMG_values": [
                float(osn.log_superMG(pt[0], pt[1])) for pt in osn_cfg["eval_points"]
            ],
        },
        "gamma_exponential": {
            "rho": float(ge.rho),
            "leading_constant": float(ge.leading_constant),
            "log_superMG_values": [
                float(ge.log_superMG(pt[0], pt[1])) for pt in ge_cfg["eval_points"]
            ],
        },
    }

    # ========== Part 2: Mixture Bounds ==========
    p2_cfg = problem["part2_mixture_bounds"]

    tsn_b_cfg = p2_cfg["two_sided_normal"]
    tsn_b = TwoSidedNormalMixture(tsn_b_cfg["v_opt"], tsn_b_cfg["alpha_opt"])
    tsn_log_thresh = np.log(1.0 / tsn_b_cfg["alpha"])

    ge_b_cfg = p2_cfg["gamma_exponential"]
    ge_b = GammaExponentialMixture(ge_b_cfg["v_opt"], ge_b_cfg["alpha_opt"], ge_b_cfg["c"])
    ge_log_thresh = np.log(1.0 / ge_b_cfg["alpha"])

    tsn_bounds = [float(tsn_b.bound(v, tsn_log_thresh)) for v in tsn_b_cfg["v_values"]]
    ge_bounds = [float(ge_b.bound(v, ge_log_thresh)) for v in ge_b_cfg["v_values"]]

    # Comparative evaluation: which family produces tighter bounds
    tighter_family = []
    for i in range(len(tsn_b_cfg["v_values"])):
        if tsn_bounds[i] <= ge_bounds[i]:
            tighter_family.append("two_sided_normal")
        else:
            tighter_family.append("gamma_exponential")

    results["part2"] = {
        "two_sided_normal_bounds": tsn_bounds,
        "gamma_exponential_bounds": ge_bounds,
        "tighter_family": tighter_family,
        "crossover_detected": len(set(tighter_family)) > 1,
    }

    # ========== Part 3: Sequential Mean Test ==========
    p3_cfg = problem["part3_sequential_test"]
    rng3 = np.random.default_rng(p3_cfg["seed"])
    data3 = rng3.normal(p3_cfg["true_mean"], p3_cfg["true_std"], p3_cfg["n_observations"])

    mixture3 = TwoSidedNormalMixture(p3_cfg["v_opt"], p3_cfg["alpha_opt"])

    e_values_at_cp = []
    reject_at_cp = []
    for cp in p3_cfg["checkpoints"]:
        s_t = float(np.sum(data3[:cp] - p3_cfg["null_value"]))
        v_t = float(cp)
        log_mg = mixture3.log_superMG(s_t, v_t)
        e_val = float(np.exp(log_mg))
        e_values_at_cp.append(e_val)
        reject_at_cp.append(bool(e_val >= 1.0 / p3_cfg["alpha"]))

    first_rejection = None
    for t in range(1, p3_cfg["n_observations"] + 1):
        s_t = float(np.sum(data3[:t] - p3_cfg["null_value"]))
        v_t = float(t)
        e_t = np.exp(mixture3.log_superMG(s_t, v_t))
        if e_t >= 1.0 / p3_cfg["alpha"]:
            first_rejection = t
            break

    results["part3"] = {
        "e_values_at_checkpoints": e_values_at_cp,
        "reject_at_checkpoints": reject_at_cp,
        "first_rejection_time": first_rejection,
    }

    # ========== Part 4: E-value Merging ==========
    p4_cfg = problem["part4_evalue_merging"]

    arithmetic_means = []
    geometric_means = []
    f_combinations = []
    calibrated_ps = []

    for ev_set in p4_cfg["sets"]:
        ev = np.array(ev_set)
        K = len(ev)

        arith = float(np.mean(ev))
        geo = float(np.exp(np.mean(np.log(ev))))
        f_comb = float(K * np.min(ev))
        cal_p = float(min(1.0, 1.0 / arith))

        arithmetic_means.append(arith)
        geometric_means.append(geo)
        f_combinations.append(f_comb)
        calibrated_ps.append(cal_p)

    results["part4"] = {
        "arithmetic_mean": arithmetic_means,
        "geometric_mean": geometric_means,
        "f_combination": f_combinations,
        "calibrated_p_values": calibrated_ps,
    }

    # ========== Part 5: Confidence Sequence ==========
    p5_cfg = problem["part5_confidence_sequence"]
    rng5 = np.random.default_rng(p5_cfg["seed"])
    data5 = rng5.normal(p5_cfg["true_mean"], p5_cfg["true_std"], p5_cfg["n_observations"])

    ge5 = GammaExponentialMixture(p5_cfg["v_opt"], p5_cfg["alpha_opt"] / 2.0, p5_cfg["c"])
    log_thresh5 = np.log(2.0 / p5_cfg["alpha"])

    lower_bounds = []
    upper_bounds = []
    widths = []

    for cp in p5_cfg["checkpoints"]:
        obs = data5[:cp]
        n = len(obs)
        x_bar = float(np.mean(obs))

        emp_var = float(np.var(obs, ddof=1))
        intrinsic_time = n * emp_var

        bnd = ge5.bound(intrinsic_time, log_thresh5)
        radius = bnd / n

        lower_bounds.append(float(x_bar - radius))
        upper_bounds.append(float(x_bar + radius))
        widths.append(float(2.0 * radius))

    results["part5"] = {
        "lower_bounds": lower_bounds,
        "upper_bounds": upper_bounds,
        "widths": widths,
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")


if __name__ == "__main__":
    solve()
