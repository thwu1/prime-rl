"""
WEC time-domain simulation pipeline: reference solution.
Multi-sea-state analysis with constrained PTO optimization.
"""

import json
import math
import sys
import numpy as np
from scipy.linalg import svd, expm, logm


def load_json(path):
    with open(path) as f:
        return json.load(f)


def compute_irf(omegas, B33, t_array):
    """K_r(t) via cosine transform of B(omega), with fine interpolation."""
    omegas = np.asarray(omegas, dtype=float)
    B33 = np.asarray(B33, dtype=float)
    n_fine = max(len(omegas) * 10, 300)
    omega_fine = np.linspace(0, omegas[-1], n_fine)
    B_fine = np.interp(omega_fine, omegas, B33, left=0.0)
    B_fine[0] = 0.0
    K_r = np.zeros(len(t_array))
    for i, t in enumerate(t_array):
        integrand = B_fine * np.cos(omega_fine * t)
        K_r[i] = (2.0 / math.pi) * np.trapezoid(integrand, omega_fine)
    return K_r


def hankel_svd_ss(K_r_samples, dt, max_order, r2_threshold):
    """State-space identification via Hankel SVD (Kung's method)."""
    M = len(K_r_samples)
    N = min(M // 2, 300)

    H0 = np.zeros((N, N))
    H1 = np.zeros((N, N))
    for i in range(N):
        for j in range(N):
            if i + j < M:
                H0[i, j] = K_r_samples[i + j]
            if i + j + 1 < M:
                H1[i, j] = K_r_samples[i + j + 1]

    U, s, Vt = svd(H0, full_matrices=False)

    total_energy = np.sum(s ** 2)
    cum_energy = np.cumsum(s ** 2) / total_energy
    order = int(np.searchsorted(cum_energy, r2_threshold)) + 1
    order = max(2, min(order, max_order, len(s)))

    best_R2 = -1.0
    best_result = None

    for trial_order in range(max(2, order - 1), min(max_order, order + 3) + 1):
        if trial_order > len(s):
            break

        Un = U[:, :trial_order]
        sn = s[:trial_order]
        Vn = Vt[:trial_order, :].T
        Sn_half = np.diag(np.sqrt(sn))
        Sn_half_inv = np.diag(1.0 / np.sqrt(sn))

        A_d = Sn_half_inv @ Un.T @ H1 @ Vn @ Sn_half_inv
        C_d = (Un @ Sn_half)[0:1, :]
        B_d = (Sn_half @ Vn.T)[:, 0:1]

        eig_vals, V_eig = np.linalg.eig(A_d)
        for k in range(len(eig_vals)):
            if abs(eig_vals[k]) >= 1.0:
                eig_vals[k] = 0.98 * eig_vals[k] / abs(eig_vals[k])
        A_d = np.real(V_eig @ np.diag(eig_vals) @ np.linalg.inv(V_eig))

        A_c = np.real(logm(A_d)) / dt
        C_c = np.real(C_d)
        B_c = np.real(B_d)

        n_check = min(M, 600)
        K_r_ss = np.zeros(n_check)
        for k in range(n_check):
            val = C_c @ expm(A_c * k * dt) @ B_c
            K_r_ss[k] = float(np.squeeze(val))

        ref = K_r_samples[:n_check]
        ss_res = np.sum((ref - K_r_ss) ** 2)
        ss_tot = np.sum((ref - np.mean(ref)) ** 2)
        R2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-30 else 0.0

        if R2 > best_R2:
            best_R2 = R2
            eigs_c = np.linalg.eigvals(A_c)
            best_result = (A_c.copy(), B_c.copy(), C_c.copy(),
                           trial_order, R2, eigs_c)

    if best_result is None:
        raise ValueError("State-space identification failed")
    return best_result


def jonswap_spectrum(f, Hs, Tp, gamma):
    fp = 1.0 / Tp
    if f <= 0:
        return 0.0
    sigma = 0.07 if f <= fp else 0.09
    alpha_exp = math.exp(-((f / fp - 1.0) ** 2) / (2.0 * sigma ** 2))
    C_gamma = 1.0 - 0.287 * math.log(gamma)
    S_pm = ((5.0 / 16.0) * Hs ** 2 * fp ** 4 * f ** (-5) *
            math.exp(-1.25 * (fp / f) ** 4))
    return C_gamma * S_pm * gamma ** alpha_exp


def generate_wave_excitation(sea_state, sim_cfg, hydro_omegas,
                             Fexc_re_data, Fexc_im_data):
    """Generate excitation force time series for one sea state."""
    Hs, Tp, gamma = sea_state["Hs"], sea_state["Tp"], sea_state["gamma"]
    Nf = sea_state["n_frequencies"]
    f_min, f_max = sea_state["f_min"], sea_state["f_max"]
    seed = sea_state["phase_seed"]
    dt = sim_cfg["dt"]
    duration = sim_cfg["duration"]
    ramp_time = sim_cfg["ramp_time"]

    df = (f_max - f_min) / Nf
    freqs = np.array([f_min + (i + 0.5) * df for i in range(Nf)])
    omega_wave = 2.0 * math.pi * freqs

    S = np.array([jonswap_spectrum(f, Hs, Tp, gamma) for f in freqs])
    m0 = float(np.sum(S) * df)
    m2 = float(np.sum(freqs ** 2 * S) * df)
    a = np.sqrt(2.0 * S * df)

    rng = np.random.default_rng(seed)
    phi = rng.uniform(0, 2.0 * math.pi, Nf)

    hydro_omegas = np.asarray(hydro_omegas)
    Fexc_re_interp = np.interp(omega_wave, hydro_omegas, Fexc_re_data)
    Fexc_im_interp = np.interp(omega_wave, hydro_omegas, Fexc_im_data)

    t = np.arange(0, duration, dt)
    Nt = len(t)

    ramp = np.ones(Nt)
    mask = t < ramp_time
    ramp[mask] = 0.5 * (1.0 + np.cos(math.pi + math.pi * t[mask] / ramp_time))

    F_exc = np.zeros(Nt)
    for j in range(Nf):
        phase_j = omega_wave[j] * t + phi[j]
        F_exc += a[j] * (Fexc_re_interp[j] * np.cos(phase_j) -
                         Fexc_im_interp[j] * np.sin(phase_j))
    F_exc *= ramp

    Hm0 = 4.0 * math.sqrt(m0)
    Tm02 = math.sqrt(m0 / m2) if m2 > 0 else 0.0

    return t, F_exc, m0, m2, Hm0, Tm02


def simulate_cummins(t, F_exc, mass, A_inf, K_hs, C_pto, K_pto,
                     A_ss, B_ss, C_ss):
    """Solve Cummins equation with state-space radiation using RK4."""
    n_ss = A_ss.shape[0]
    dt = t[1] - t[0]
    M_eff = mass + A_inf

    B_ss_flat = B_ss.flatten()
    C_ss_flat = C_ss.flatten()

    def rhs(state, F_t):
        x, xdot = state[0], state[1]
        x_r = state[2:]
        F_rad = np.dot(C_ss_flat, x_r)
        F_pto = -C_pto * xdot - K_pto * x
        xddot = (F_t - K_hs * x - F_rad + F_pto) / M_eff
        dxr = A_ss @ x_r + B_ss_flat * xdot
        return np.concatenate(([xdot, xddot], dxr))

    n_state = 2 + n_ss
    state = np.zeros(n_state)
    x_hist = np.zeros(len(t))
    xdot_hist = np.zeros(len(t))

    for i in range(len(t)):
        x_hist[i] = state[0]
        xdot_hist[i] = state[1]
        if i < len(t) - 1:
            Fi = F_exc[i]
            Fmid = 0.5 * (F_exc[i] + F_exc[i + 1])
            Fnext = F_exc[i + 1]
            k1 = rhs(state, Fi)
            k2 = rhs(state + 0.5 * dt * k1, Fmid)
            k3 = rhs(state + 0.5 * dt * k2, Fmid)
            k4 = rhs(state + dt * k3, Fnext)
            state = state + (dt / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)

    return x_hist, xdot_hist


def main():
    print("Loading input files...")
    config = load_json("/app/config.json")
    hydro = load_json("/app/hydro_data.json")

    # Diagnostic output
    print(f"  config.json keys: {sorted(config.keys())}")
    print(f"  hydro_data.json keys: {sorted(hydro.keys())}")

    # Validate required config sections
    required_sections = ["sea_states", "simulation", "pto", "constraints", "state_space"]
    for sec in required_sections:
        if sec not in config:
            print(f"ERROR: Missing required config section '{sec}'", file=sys.stderr)
            print(f"  Available keys: {sorted(config.keys())}", file=sys.stderr)
            sys.exit(1)

    omegas = hydro["omega"]
    B33 = hydro["B33"]
    Fexc_re = hydro["Fexc_re"]
    Fexc_im = hydro["Fexc_im"]

    mass = hydro["body"]["mass"]
    K_hs = hydro["body"]["hydrostatic_stiffness"]
    A_inf = hydro["body"]["added_mass_inf"]

    ss_cfg = config["state_space"]
    irf_dt = ss_cfg["irf_dt"]
    irf_dur = ss_cfg["irf_duration"]

    # Radiation IRF
    print("Computing radiation IRF...")
    t_irf = np.arange(0, irf_dur + irf_dt * 0.5, irf_dt)
    K_r = compute_irf(omegas, B33, t_irf)
    K_r_at_zero = float(K_r[0])
    print(f"  K_r(0) = {K_r_at_zero:.2f}, IRF length = {len(t_irf)}")

    # State-space identification
    print("Identifying state-space model...")
    A_ss, B_ss, C_ss, ss_order, ss_R2, eig_vals = hankel_svd_ss(
        K_r, irf_dt, ss_cfg["max_order"], ss_cfg["r2_threshold"]
    )
    print(f"  order = {ss_order}, R2 = {ss_R2:.4f}")

    # PTO sweep config
    pto_cfg = config["pto"]
    d_min = pto_cfg["damping_sweep"]["min"]
    d_max = pto_cfg["damping_sweep"]["max"]
    n_pts = pto_cfg["damping_sweep"]["n_points"]
    K_pto = pto_cfg["stiffness"]
    ramp_time = config["simulation"]["ramp_time"]
    dt_sim = config["simulation"]["dt"]
    i_ramp = int(ramp_time / dt_sim)
    dampings = np.linspace(d_min, d_max, n_pts)

    max_heave_limit = config["constraints"]["max_heave_amplitude"]
    n_sea = len(config["sea_states"])
    probabilities = np.array([ss["probability"] for ss in config["sea_states"]])

    # Storage for sweep results
    all_powers = np.zeros((n_pts, n_sea))
    all_heave_max = np.zeros((n_pts, n_sea))
    all_heave_std = np.zeros((n_pts, n_sea))
    all_heave_mean = np.zeros((n_pts, n_sea))
    power_curves = [[] for _ in range(n_sea)]

    # Pre-compute wave excitations
    print("Generating wave excitations...")
    wave_data = []
    for ss in config["sea_states"]:
        t_sim, F_exc, m0, m2, Hm0, Tm02 = generate_wave_excitation(
            ss, config["simulation"], omegas, Fexc_re, Fexc_im
        )
        wave_data.append({
            "t": t_sim, "F_exc": F_exc,
            "m0": m0, "m2": m2, "Hm0": Hm0, "Tm02": Tm02,
            "id": ss["id"]
        })
        print(f"  [{ss['id']}] Hm0={Hm0:.3f} m, Tm02={Tm02:.2f} s")

    # Sweep all dampings for all sea states
    print(f"Running {n_pts} x {n_sea} simulations...")
    for si, wd in enumerate(wave_data):
        print(f"  Sweeping sea state '{wd['id']}'...")
        for di, C_pto_val in enumerate(dampings):
            x_hist, xdot_hist = simulate_cummins(
                wd["t"], wd["F_exc"], mass, A_inf, K_hs, C_pto_val, K_pto,
                A_ss, B_ss, C_ss
            )
            heave_post = x_hist[i_ramp:]
            P_inst = C_pto_val * xdot_hist[i_ramp:] ** 2
            avg_power = float(np.mean(P_inst))

            power_curves[si].append([float(C_pto_val), avg_power])
            all_powers[di, si] = avg_power
            all_heave_max[di, si] = float(np.max(np.abs(heave_post)))
            all_heave_std[di, si] = float(np.std(heave_post))
            all_heave_mean[di, si] = float(np.mean(heave_post))

    # Unconstrained optimization: maximize weighted power
    weighted_powers = all_powers @ probabilities
    unc_best_di = int(np.argmax(weighted_powers))
    unc_optimal_damping = float(dampings[unc_best_di])
    unc_max_power = float(weighted_powers[unc_best_di])

    # Constrained optimization: weighted power with heave limit
    feasible = np.all(all_heave_max <= max_heave_limit, axis=1)
    if np.any(feasible):
        feasible_weighted = np.where(feasible, weighted_powers, -np.inf)
        con_best_di = int(np.argmax(feasible_weighted))
    else:
        # No feasible point: pick damping with smallest max violation
        max_violations = np.max(all_heave_max, axis=1)
        con_best_di = int(np.argmin(max_violations))

    con_optimal_damping = float(dampings[con_best_di])
    con_max_power = float(weighted_powers[con_best_di])

    # Binding sea states: heave within 5% of constraint at constrained optimal
    binding = []
    for si, ss in enumerate(config["sea_states"]):
        if all_heave_max[con_best_di, si] >= 0.95 * max_heave_limit:
            binding.append(ss["id"])

    # Build per-sea-state results (simulation stats at unconstrained optimal)
    sea_states_results = {}
    for si, ss in enumerate(config["sea_states"]):
        ss_id = ss["id"]
        sea_states_results[ss_id] = {
            "wave": {
                "m0": wave_data[si]["m0"],
                "m2": wave_data[si]["m2"],
                "Hm0": wave_data[si]["Hm0"],
                "Tm02": wave_data[si]["Tm02"],
            },
            "simulation": {
                "heave_max": float(all_heave_max[unc_best_di, si]),
                "heave_std": float(all_heave_std[unc_best_di, si]),
                "heave_mean": float(all_heave_mean[unc_best_di, si]),
            },
            "power_curve": power_curves[si],
        }

    results = {
        "irf": {
            "time": t_irf.tolist(),
            "K_r": K_r.tolist(),
            "K_r_at_zero": K_r_at_zero,
        },
        "state_space": {
            "order": int(ss_order),
            "R2": float(ss_R2),
            "A": A_ss.tolist(),
            "B": B_ss.tolist(),
            "C": C_ss.tolist(),
            "eigenvalues_real": [float(e.real) for e in eig_vals],
        },
        "sea_states": sea_states_results,
        "pto_optimization": {
            "unconstrained": {
                "optimal_damping": unc_optimal_damping,
                "weighted_avg_power": unc_max_power,
            },
            "constrained": {
                "optimal_damping": con_optimal_damping,
                "weighted_avg_power": con_max_power,
                "binding_sea_states": binding,
            },
        },
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("\nResults written to /app/results.json")
    for ss_id, ss_res in sea_states_results.items():
        print(f"  [{ss_id}] Hm0={ss_res['wave']['Hm0']:.3f}, "
              f"heave_max={ss_res['simulation']['heave_max']:.3f}, "
              f"power_peak={max(p for _, p in ss_res['power_curve']):.0f} W")
    print(f"  Unconstrained: damping={unc_optimal_damping:.0f}, "
          f"power={unc_max_power:.0f} W")
    print(f"  Constrained: damping={con_optimal_damping:.0f}, "
          f"power={con_max_power:.0f} W, binding={binding}")


if __name__ == "__main__":
    main()
