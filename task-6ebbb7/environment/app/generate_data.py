#!/usr/bin/env python3
"""
Build-time data generation for CFD verification task.
Reads a DNA seed from /opt/dna_seed.txt, generates randomized input data
(BL profile, CFD Cf grids, config), computes reference answers, and stores
them in a pickle for test verification.

ALL data is generated from the DNA seed — no static data files exist.
"""

import math
import json
import os
import pickle
import random
import hashlib


DATA_DIR = "/opt/cfd_data"
DNA_PATH = "/opt/dna_seed.txt"
REF_PATH = os.path.join(DATA_DIR, ".ref.pkl")


def spalding_yplus(uplus, kappa, B):
    """Spalding's law of the wall: y+(u+)"""
    ku = kappa * uplus
    return uplus + math.exp(-kappa * B) * (
        math.exp(ku) - 1.0 - ku - ku ** 2 / 2.0 - ku ** 3 / 6.0
    )


def spalding_dyplus(uplus, kappa, B):
    """d(y+)/d(u+) for Newton iteration"""
    ku = kappa * uplus
    return 1.0 + math.exp(-kappa * B) * kappa * (
        math.exp(ku) - 1.0 - ku - ku ** 2 / 2.0
    )


def solve_uplus(yp_target, kappa, B):
    """Invert Spalding's law: find u+ given y+ via Newton's method"""
    if yp_target < 5:
        up = yp_target
    elif yp_target < 30:
        up = 5.0 + (yp_target - 5.0) * 0.3
    else:
        up = (1.0 / kappa) * math.log(max(yp_target, 1.0)) + B
    for _ in range(200):
        yp = spalding_yplus(up, kappa, B)
        dyp = spalding_dyplus(up, kappa, B)
        delta = (yp - yp_target) / dyp
        up -= delta
        up = max(up, 0.0)
        if abs(delta) < 1e-13:
            break
    return up


def golden_section_min(f, a, b, tol=1e-12, max_iter=500):
    """Golden section search for minimum of f on [a, b]"""
    gr = (math.sqrt(5) + 1) / 2
    c = b - (b - a) / gr
    d = a + (b - a) / gr
    fc, fd = f(c), f(d)
    for _ in range(max_iter):
        if abs(b - a) < tol:
            break
        if fc < fd:
            b = d
            d = c
            fd = fc
            c = b - (b - a) / gr
            fc = f(c)
        else:
            a = c
            c = d
            fc = fd
            d = a + (b - a) / gr
            fd = f(d)
    return (a + b) / 2


def main():
    # Read DNA seed
    with open(DNA_PATH) as f:
        dna_str = f.read().strip()

    seed = int(hashlib.sha256(dna_str.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)

    # Create output directories
    os.makedirs(os.path.join(DATA_DIR, "data/experimental"), exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, "data/cfd"), exist_ok=True)

    # ── Flow parameters (randomised by DNA) ──
    U_e = round(19.5 + rng.random() * 6.0, 1)
    nu = round(1.40e-5 + rng.random() * 0.65e-5, 7)
    u_tau_gen = round(0.70 + rng.random() * 0.30, 4)
    kappa = 0.41
    B = 5.0
    delta = round(0.035 + rng.random() * 0.015, 3)
    y_max_fit = round(0.003 + rng.random() * 0.003, 4)
    rho = round(1.05 + rng.random() * 0.25, 3)
    Pi_wake = 0.3 + rng.random() * 0.5

    # ── Generate BL profile ──
    n_inner, n_outer = 15, 13
    log_s = math.log10(1e-4)
    log_e = math.log10(y_max_fit)
    y_inner = [10 ** (log_s + i / (n_inner - 1) * (log_e - log_s)) for i in range(n_inner)]
    y_o_s = y_max_fit + 0.002
    y_o_e = delta + 0.015
    y_outer = [y_o_s + i / (n_outer - 1) * (y_o_e - y_o_s) for i in range(n_outer)]
    y_all = sorted(set(round(y, 7) for y in y_inner + y_outer))

    U_all = []
    for yi in y_all:
        yp = u_tau_gen * yi / nu
        up = solve_uplus(yp, kappa, B)
        Ui = up * u_tau_gen
        eta = yi / delta
        if eta < 1.0:
            Ui += u_tau_gen * (2 * Pi_wake / kappa) * math.sin(math.pi / 2 * eta) ** 2
        Ui = min(Ui, U_e)
        Ui += rng.gauss(0, 0.008 * u_tau_gen)
        Ui = max(Ui, 0.05)
        U_all.append(Ui)

    for i in range(len(y_all)):
        if y_all[i] >= delta:
            U_all[i] = U_e + rng.gauss(0, 0.012)
            U_all[i] = max(U_all[i], U_e * 0.995)

    with open(os.path.join(DATA_DIR, "data/experimental/bl_profile.dat"), "w") as f:
        f.write("# Boundary layer velocity profile data\n")
        f.write(f"# Edge velocity U_e = {U_e} m/s, BL thickness delta ~ {delta} m\n")
        f.write("# Columns: y [m]    U [m/s]\n")
        for yi, Ui in zip(y_all, U_all):
            f.write(f"{yi:.6e}\t{Ui:.6f}\n")

    # ── Generate CFD Cf data ──
    x_stations = [-0.5, 0.0, 0.3, 0.6, 0.9, 1.2, 1.5]
    r = 2.0
    Fs = 1.25

    def gen_model(offset):
        rm = random.Random(seed + offset)
        rows = []
        for x in x_stations:
            f_ex = 0.0025 + rm.random() * 0.004
            p_tr = 1.5 + rm.random() * 0.7
            C_frac = 0.005 + rm.random() * 0.015
            C = C_frac * f_ex * rm.choice([-1, 1])
            if f_ex + C * 8.0 ** p_tr < f_ex * 0.1:
                C = abs(C)
            grids = {}
            for gi in range(1, 5):
                h = r ** (gi - 1)
                grids[f"Cf_grid{gi}"] = f_ex + C * h ** p_tr
            rows.append({"x": x, **grids})
        return rows

    sa_data = gen_model(1000)
    sst_data = gen_model(2000)

    def write_csv(path, data, model):
        with open(path, "w") as f:
            f.write(f"# Skin friction coefficient (Cf) for {model}\n")
            f.write("# Refinement ratio r = 2.0\n")
            f.write("x,Cf_grid1,Cf_grid2,Cf_grid3,Cf_grid4\n")
            for row in data:
                f.write(
                    f"{row['x']},{row['Cf_grid1']:.7f},{row['Cf_grid2']:.7f},"
                    f"{row['Cf_grid3']:.7f},{row['Cf_grid4']:.7f}\n"
                )

    write_csv(
        os.path.join(DATA_DIR, "data/cfd/bump_cf_sa.csv"),
        sa_data, "Spalart-Allmaras",
    )
    write_csv(
        os.path.join(DATA_DIR, "data/cfd/bump_cf_sst.csv"),
        sst_data, "Menter k-omega SST",
    )

    # Write config (DNA-derived values)
    config = {
        "flow_conditions": {"U_e": U_e, "nu": nu, "rho": rho, "delta": delta},
        "wall_model_constants": {"kappa": kappa, "B": B},
        "grid_convergence": {"refinement_ratio": r, "safety_factor": Fs},
        "spalding_fit": {"y_max_for_fit": y_max_fit},
    }
    with open(os.path.join(DATA_DIR, "config.json"), "w") as f:
        json.dump(config, f, indent=2)

    # Write DNA fingerprint so tests can verify data is DNA-derived
    dna_fp = hashlib.sha256(dna_str.encode()).hexdigest()
    with open(os.path.join(DATA_DIR, ".dna_fingerprint"), "w") as f:
        f.write(dna_fp)

    # ── Compute reference answers ──

    # BL integrals (trapezoidal, including wall-to-first-point contribution)
    ds = 0.5 * ((1.0 - 0.0) + (1.0 - U_all[0] / U_e)) * y_all[0]
    th = 0.5 * (0.0 + (U_all[0] / U_e) * (1.0 - U_all[0] / U_e)) * y_all[0]
    for i in range(1, len(y_all)):
        dy = y_all[i] - y_all[i - 1]
        f0d = 1.0 - U_all[i - 1] / U_e
        f1d = 1.0 - U_all[i] / U_e
        ds += 0.5 * (f0d + f1d) * dy
        f0t = (U_all[i - 1] / U_e) * (1.0 - U_all[i - 1] / U_e)
        f1t = (U_all[i] / U_e) * (1.0 - U_all[i] / U_e)
        th += 0.5 * (f0t + f1t) * dy
    H_ref = ds / th

    # Spalding fit
    y_fit = [y_all[i] for i in range(len(y_all)) if y_all[i] <= y_max_fit]
    U_fit = [U_all[i] for i in range(len(y_all)) if y_all[i] <= y_max_fit]

    def spald_obj(ut):
        s = 0.0
        for yi, Ui in zip(y_fit, U_fit):
            yp_d = ut * yi / nu
            up_d = Ui / ut
            yp_m = spalding_yplus(up_d, kappa, B)
            s += (yp_d - yp_m) ** 2
        return s

    ut_ref = golden_section_min(spald_obj, 0.3, 2.0)
    Cf_ref = 2.0 * (ut_ref / U_e) ** 2

    bl_ref = {
        "delta_star": ds, "theta": th, "shape_factor": H_ref,
        "u_tau": ut_ref, "Cf": Cf_ref,
    }

    # Richardson extrapolation
    def rich_ext(f1, f2, f3, f4, r_val, Fs_val):
        e21 = f2 - f1
        e32 = f3 - f2
        if e21 == 0 or e32 == 0:
            return None
        p = math.log(abs(e32 / e21)) / math.log(r_val)
        rp = r_val ** p
        f_ext = f1 + (f1 - f2) / (rp - 1.0)
        ea21 = abs(e21 / f1)
        gf = Fs_val * ea21 / (rp - 1.0)
        ea32 = abs(e32 / f2)
        gm = Fs_val * ea32 / (rp - 1.0)
        ar = gm / (rp * gf)
        return {
            "p": p, "f_ext": f_ext, "gci_fine": gf,
            "gci_medium": gm, "asymp_ratio": ar,
        }

    def gc_ref(cf_rows):
        out = []
        for row in cf_rows:
            res = rich_ext(
                row["Cf_grid1"], row["Cf_grid2"],
                row["Cf_grid3"], row["Cf_grid4"], r, Fs,
            )
            if res:
                res["x"] = row["x"]
                out.append(res)
        return out

    sa_gc = gc_ref(sa_data)
    sst_gc = gc_ref(sst_data)

    # Model comparison
    cmp_st = []
    diffs = []
    for s_sa, s_sst in zip(sa_gc, sst_gc):
        sa_e = s_sa["f_ext"]
        sst_e = s_sst["f_ext"]
        rd = abs(sa_e - sst_e) / max(abs(sa_e), abs(sst_e)) * 100.0
        diffs.append(rd)
        cmp_st.append({
            "x": s_sa["x"], "sa_ext": sa_e,
            "sst_ext": sst_e, "rel_diff_pct": rd,
        })
    rms_d = math.sqrt(sum(d ** 2 for d in diffs) / len(diffs))
    mx_d = max(diffs)
    mx_i = diffs.index(mx_d)

    cmp_ref = {
        "stations": cmp_st,
        "rms_rel_diff_pct": rms_d,
        "max_rel_diff_pct": mx_d,
        "max_diff_station": cmp_st[mx_i]["x"],
    }

    ref = {
        "dna_fingerprint": dna_fp,
        "bl_analysis": bl_ref,
        "grid_convergence_sa": {"stations": sa_gc},
        "grid_convergence_sst": {"stations": sst_gc},
        "model_comparison": cmp_ref,
    }
    with open(REF_PATH, "wb") as f:
        pickle.dump(ref, f)

    print(f"DNA: {dna_str[:16]}... | fingerprint: {dna_fp[:16]}...")
    print(f"Generated: U_e={U_e} nu={nu} ut_ref={ut_ref:.6f}")
    print(f"Data written to {DATA_DIR}")


if __name__ == "__main__":
    main()
