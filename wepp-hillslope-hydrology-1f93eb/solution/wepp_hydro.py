#!/usr/bin/env python3
"""
WEPP Single-OFE Surface Hydrology Simulator

Implements the Green-Ampt Mein-Larson (GAML) infiltration model with
unsteady rainfall (Chu 1978), coupled with kinematic wave peak discharge
estimation and depression storage.

Reference: WEPP Technical Documentation, Chapter 4 (USDA-ARS NSERL, 1995)
"""

import json
import sys
import math


def gaml_G(F, Ns_td):
    """Auxiliary function G(F) = F - Ns*theta_d * ln(1 + F/(Ns*theta_d))"""
    if F <= 0:
        return 0.0
    return F - Ns_td * math.log(1.0 + F / Ns_td)


def solve_gaml_F(target_G, Ns_td, F_guess, tol=1e-10, max_iter=200):
    """
    Solve G(F) = target_G for F using Newton-Raphson.
    G(F) = F - Ns_td * ln(1 + F/Ns_td)
    G'(F) = F / (F + Ns_td)
    """
    F = max(F_guess, 1e-12)
    for _ in range(max_iter):
        gval = gaml_G(F, Ns_td) - target_G
        gprime = F / (F + Ns_td)
        if abs(gprime) < 1e-15:
            break
        dF = gval / gprime
        F_new = F - dF
        if F_new <= 0:
            F_new = F / 2.0
        if abs(F_new - F) < tol:
            return F_new
        F = F_new
    return F


def simulate(config):
    """Run the full single-OFE hydrology simulation."""
    Ke = config["soil"]["Ke"]
    Ns = config["soil"]["Ns"]
    theta_d = config["soil"]["theta_d"]
    Ns_td = Ns * theta_d

    slope = config["surface"]["slope"]
    chezy_c = config["surface"]["chezy_c"]
    length = config["surface"]["length"]
    rr = config["surface"]["random_roughness"]

    rainfall = config["rainfall"]
    alpha = chezy_c * math.sqrt(slope)
    m_exp = 1.5

    rainfall = sorted(rainfall, key=lambda x: x["time_min"])

    intervals = []
    for i in range(len(rainfall) - 1):
        t_start = rainfall[i]["time_min"]
        t_end = rainfall[i + 1]["time_min"]
        r = rainfall[i]["intensity_mm_hr"]
        if t_end > t_start:
            intervals.append((t_start, t_end, r))

    if not intervals:
        return _zero_result()

    storm_duration_min = intervals[-1][1]

    dt_min = 0.02
    n_steps = int(math.ceil(storm_duration_min / dt_min))
    if n_steps < 1:
        n_steps = 1
    dt_min_actual = storm_duration_min / n_steps
    dt_hr = dt_min_actual / 60.0

    def get_intensity(t_min):
        for (ts, te, r) in intervals:
            if ts <= t_min < te:
                return r
        return 0.0

    F_cum = 0.0
    R_cum = 0.0
    ponded = False
    tp_min = -1.0
    ponded_elapsed_hr = 0.0
    ponded_G_base = 0.0
    ponded_F_base = 0.0

    excess_rates = []
    total_excess = 0.0
    f_last_nonzero_excess = Ke
    first_excess_time = -1.0
    last_excess_time = -1.0

    for step in range(n_steps):
        t = step * dt_min_actual
        r = get_intensity(t)
        rain_depth = r * dt_hr

        if not ponded:
            if r <= Ke:
                F_cum += rain_depth
                R_cum += rain_depth
                excess_rates.append((t, 0.0))
            else:
                F_p = Ke * Ns_td / (r - Ke)
                if F_cum >= F_p:
                    # Immediate re-ponding: F already exceeds ponding threshold
                    ponded = True
                    if tp_min < 0:
                        tp_min = t
                    ponded_F_base = F_cum
                    ponded_G_base = gaml_G(F_cum, Ns_td)
                    ponded_elapsed_hr = 0.0

                    ponded_elapsed_hr += dt_hr
                    target_G = ponded_G_base + Ke * ponded_elapsed_hr
                    F_new = solve_gaml_F(target_G, Ns_td, F_cum + Ke * dt_hr)
                    infil_depth = F_new - F_cum
                    excess_depth = rain_depth - infil_depth
                    F_cum = F_new
                    R_cum += rain_depth

                    if excess_depth > 1e-12:
                        excess_rate = excess_depth / dt_hr
                        excess_rates.append((t, excess_rate))
                        total_excess += excess_depth
                        f_last_nonzero_excess = Ke * (1 + Ns_td / F_cum)
                        if first_excess_time < 0:
                            first_excess_time = t
                        last_excess_time = t + dt_min_actual
                    else:
                        excess_rates.append((t, 0.0))

                elif F_cum + rain_depth >= F_p:
                    # Ponding begins within this timestep
                    ponded = True
                    rain_to_ponding = F_p - F_cum
                    dt_to_ponding_min = (rain_to_ponding / r) * 60.0 if r > 0 else 0.0

                    if tp_min < 0:
                        tp_min = t + dt_to_ponding_min

                    ponded_F_base = F_p
                    ponded_G_base = gaml_G(F_p, Ns_td)
                    ponded_elapsed_hr = 0.0

                    dt_remaining_hr = (dt_min_actual - dt_to_ponding_min) / 60.0
                    if dt_remaining_hr > 1e-12:
                        ponded_elapsed_hr = dt_remaining_hr
                        target_G = ponded_G_base + Ke * ponded_elapsed_hr
                        F_new = solve_gaml_F(target_G, Ns_td, F_p + Ke * dt_remaining_hr)
                        infil_depth = F_new - F_cum
                        excess_depth = rain_depth - infil_depth
                        F_cum = F_new
                        R_cum += rain_depth

                        if excess_depth > 1e-12:
                            excess_rate = excess_depth / dt_hr
                            excess_rates.append((t, excess_rate))
                            total_excess += excess_depth
                            f_last_nonzero_excess = Ke * (1 + Ns_td / F_cum)
                            if first_excess_time < 0:
                                first_excess_time = t + dt_to_ponding_min
                            last_excess_time = t + dt_min_actual
                        else:
                            excess_rates.append((t, 0.0))
                    else:
                        F_cum = F_p
                        R_cum += rain_depth
                        excess_rates.append((t, 0.0))
                else:
                    F_cum += rain_depth
                    R_cum += rain_depth
                    excess_rates.append((t, 0.0))
        else:
            # Currently ponded
            R_cum += rain_depth

            if r <= 0:
                ponded = False
                excess_rates.append((t, 0.0))
                continue

            # Check if infiltration capacity exceeds rainfall rate
            f_current = Ke * (1 + Ns_td / F_cum) if F_cum > 1e-12 else 1e12
            if r < f_current:
                ponded = False
                F_cum += rain_depth
                excess_rates.append((t, 0.0))
                continue

            # Still ponded: advance GAML
            ponded_elapsed_hr += dt_hr
            target_G = ponded_G_base + Ke * ponded_elapsed_hr
            F_new = solve_gaml_F(target_G, Ns_td, F_cum + Ke * dt_hr)
            infil_depth = F_new - F_cum
            excess_depth = rain_depth - infil_depth
            F_cum = F_new

            if excess_depth > 1e-12:
                excess_rate = excess_depth / dt_hr
                excess_rates.append((t, excess_rate))
                total_excess += excess_depth
                f_last_nonzero_excess = Ke * (1 + Ns_td / F_cum)
                if first_excess_time < 0:
                    first_excess_time = t
                last_excess_time = t + dt_min_actual
            else:
                excess_rates.append((t, 0.0))

    total_rainfall = R_cum

    # Depression storage (Onstad 1984)
    S_pct = slope * 100.0
    Sd = 0.112 * rr + 0.031 * rr * rr - 0.012 * rr * S_pct
    Sd = max(0.0, Sd)

    V_gross = total_excess
    V_net = max(0.0, V_gross - Sd)

    if V_net <= 1e-10 or V_gross <= 1e-10:
        return {
            "ponding_time_min": round(tp_min, 4) if tp_min >= 0 else -1.0,
            "cumulative_infiltration_mm": round(F_cum, 4),
            "total_rainfall_mm": round(total_rainfall, 4),
            "rainfall_excess_mm": round(V_gross, 4),
            "depression_storage_mm": round(Sd, 4),
            "net_runoff_mm": 0.0,
            "peak_discharge_mm_hr": 0.0,
            "effective_duration_hr": 0.0,
            "time_to_equilibrium_sec": 0.0,
            "t_star": 0.0,
            "v_star": 0.0,
            "q_star": 0.0,
            "recession_factor": 1.0,
        }

    # Duration of rainfall excess
    if first_excess_time >= 0 and last_excess_time > first_excess_time:
        Dr_min = last_excess_time - first_excess_time
    else:
        Dr_min = 0.0
    Dr_hr = Dr_min / 60.0
    Dr_sec = Dr_min * 60.0

    v_bar = V_gross / Dr_hr if Dr_hr > 0 else 0.0
    v_peak = max(er[1] for er in excess_rates) if excess_rates else 0.0

    if v_bar <= 1e-10 or v_peak <= 1e-10:
        return {
            "ponding_time_min": round(tp_min, 4) if tp_min >= 0 else -1.0,
            "cumulative_infiltration_mm": round(F_cum, 4),
            "total_rainfall_mm": round(total_rainfall, 4),
            "rainfall_excess_mm": round(V_gross, 4),
            "depression_storage_mm": round(Sd, 4),
            "net_runoff_mm": round(V_net, 4),
            "peak_discharge_mm_hr": 0.0,
            "effective_duration_hr": 0.0,
            "time_to_equilibrium_sec": 0.0,
            "t_star": 0.0,
            "v_star": 0.0,
            "q_star": 0.0,
            "recession_factor": 1.0,
        }

    v_bar_si = v_bar / 3.6e6

    te = (length / (alpha * v_bar_si ** (m_exp - 1))) ** (1.0 / m_exp)

    t_star = Dr_sec / te if te > 0 else 0.0
    v_star = v_peak / v_bar if v_bar > 0 else 1.0

    if t_star <= 1.0:
        q_star = t_star
    else:
        q_star = 1.0 + (v_star - 1.0) * (1.0 - 1.0 / (t_star ** 2))
        q_star = min(q_star, v_star)

    q_peak = q_star * v_bar

    f_star = f_last_nonzero_excess / v_bar if v_bar > 0 else 0.0
    recession_factor = 1.0
    if t_star < 1.0 and 0 < f_star < 1.0:
        Q_star = 1.0 - 0.6 * f_star * (t_star ** 0.6)
        recession_factor = max(0.0, Q_star)
        V_net = V_net * recession_factor

    De = V_net / q_peak if q_peak > 0 else 0.0

    return {
        "ponding_time_min": round(tp_min, 4) if tp_min >= 0 else -1.0,
        "cumulative_infiltration_mm": round(F_cum, 4),
        "total_rainfall_mm": round(total_rainfall, 4),
        "rainfall_excess_mm": round(V_gross, 4),
        "depression_storage_mm": round(Sd, 4),
        "net_runoff_mm": round(V_net, 4),
        "peak_discharge_mm_hr": round(q_peak, 4),
        "effective_duration_hr": round(De, 6),
        "time_to_equilibrium_sec": round(te, 4),
        "t_star": round(t_star, 6),
        "v_star": round(v_star, 6),
        "q_star": round(q_star, 6),
        "recession_factor": round(recession_factor, 6),
    }


def _zero_result():
    return {
        "ponding_time_min": -1.0,
        "cumulative_infiltration_mm": 0.0,
        "total_rainfall_mm": 0.0,
        "rainfall_excess_mm": 0.0,
        "depression_storage_mm": 0.0,
        "net_runoff_mm": 0.0,
        "peak_discharge_mm_hr": 0.0,
        "effective_duration_hr": 0.0,
        "time_to_equilibrium_sec": 0.0,
        "t_star": 0.0,
        "v_star": 0.0,
        "q_star": 0.0,
        "recession_factor": 1.0,
    }


def main():
    if len(sys.argv) < 2:
        config = json.load(sys.stdin)
    else:
        with open(sys.argv[1]) as f:
            config = json.load(f)

    result = simulate(config)

    if len(sys.argv) >= 3:
        with open(sys.argv[2], "w") as f:
            json.dump(result, f, indent=2)
    else:
        json.dump(result, sys.stdout, indent=2)
        print()


if __name__ == "__main__":
    main()
