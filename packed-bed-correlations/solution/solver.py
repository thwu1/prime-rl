#!/usr/bin/env python3

"""Standalone packed-bed analysis solver.

Corrects all bugs present in the original pipeline:
- Ergun inertial coefficient (1.56 -> 1.75)
- Hicks voidage exponent (1.0 -> 1.2)
- Fahien-Schriver exponential decay term (missing holdup factor)
- Idelchik Reynolds number (missing (1-voidage) in denominator) [C bug]
- Harrison-Brunner-Hecker wall correction A (missing holdup in denominator) [C bug]
- Barati drag sign error (+ -> - on 4th tanh term)
- Fluidization bracket too small (0.5 -> dynamic widening)
- Pipeline vmf never passes Dt to wall-corrected correlations

Writes results to SQLite database at /app/results.db.
"""

import json
import math
import sqlite3
import tomllib

G = 9.80665
PI = math.pi


# ============================================================
# Packed-bed pressure drop correlations (all correct)
# ============================================================

def ergun(dp, voidage, vs, rho, mu, L=1.0, **_):
    Re = dp * rho * vs / mu
    h = 1.0 - voidage
    e3 = voidage * voidage * voidage
    fp = (150.0 + 1.75 * (Re / h)) * h * h / (e3 * Re)
    return fp * rho * vs * vs * L / dp


def kuo_nydegger(dp, voidage, vs, rho, mu, L=1.0, **_):
    Re = dp * rho * vs / mu
    h = 1.0 - voidage
    e3 = voidage * voidage * voidage
    fp = (276.23 + 5.05 * (Re / h) ** 0.87) * h * h / (e3 * Re)
    return fp * rho * vs * vs * L / dp


def tallmadge(dp, voidage, vs, rho, mu, L=1.0, **_):
    Re = dp * rho * vs / mu
    h = 1.0 - voidage
    e3 = voidage * voidage * voidage
    fp = (150.0 + 4.2 * (Re / h) ** (5.0 / 6.0)) * h * h / (e3 * Re)
    return fp * rho * vs * vs * L / dp


def jones_krier(dp, voidage, vs, rho, mu, L=1.0, **_):
    Re = dp * rho * vs / mu
    h = 1.0 - voidage
    e3 = voidage * voidage * voidage
    fp = (150.0 + 3.89 * (Re / h) ** 0.87) * h * h / (e3 * Re)
    return fp * rho * vs * vs * L / dp


def carman(dp, voidage, vs, rho, mu, L=1.0, **_):
    Re = dp * rho * vs / mu
    h = 1.0 - voidage
    e3 = voidage * voidage * voidage
    fp = (180.0 + 2.871 * (Re / h) ** 0.9) * h * h / (e3 * Re)
    return fp * rho * vs * vs * L / dp


def hicks(dp, voidage, vs, rho, mu, L=1.0, **_):
    Re = dp * rho * vs / mu
    h = 1.0 - voidage
    e3 = voidage * voidage * voidage
    fp = 6.8 * h ** 1.2 / (Re ** 0.2 * e3)
    return fp * rho * vs * vs * L / dp


def brauer(dp, voidage, vs, rho, mu, L=1.0, **_):
    Re = dp * rho * vs / mu
    h = 1.0 - voidage
    e3 = voidage * voidage * voidage
    fp = (160.0 + 3.1 * (Re / h) ** 0.9) * h * h / (e3 * Re)
    return fp * rho * vs * vs * L / dp


def kta(dp, voidage, vs, rho, mu, L=1.0, **_):
    Re = dp * rho * vs / mu
    h = 1.0 - voidage
    e3 = voidage * voidage * voidage
    fp = (160.0 + 3.0 * (Re / h) ** 0.9) * h * h / (e3 * Re)
    return fp * rho * vs * vs * L / dp


def erdim_akgiray_demir(dp, voidage, vs, rho, mu, L=1.0, **_):
    h = 1.0 - voidage
    e3 = voidage * voidage * voidage
    Rem = dp * rho * vs / (h * mu)
    fv = 160.0 + 2.81 * Rem ** 0.904
    return fv * (mu * vs * L / (dp * dp)) * h * h / e3


def fahien_schriver(dp, voidage, vs, rho, mu, L=1.0, **_):
    h = 1.0 - voidage
    v2 = voidage * voidage
    e3 = v2 * voidage
    Rem = dp * rho * vs / (h * mu)
    q = math.exp(-v2 * h * (1.0 / 12.6) * Rem)
    f1L = 136.0 / h ** 0.38
    f1T = 29.0 / (h ** 1.45 * v2)
    f2 = 1.87 * voidage ** 0.75 / h ** 0.26
    fp = (q * f1L / Rem + (1.0 - q) * (f2 + f1T / Rem)) * h / e3
    return fp * rho * vs * vs * L / dp


def idelchik(dp, voidage, vs, rho, mu, L=1.0, **_):
    Re = rho * vs * dp / (mu * (1.0 - voidage))
    Re = (0.45 / math.sqrt(voidage)) * Re
    right = 0.765 * voidage ** (-4.2) * (30.0 / Re + 3.0 * Re ** (-0.7) + 0.3)
    left = dp / (L * rho * vs * vs)
    return right / left


def harrison_brunner_hecker(dp, voidage, vs, rho, mu, L=1.0, Dt=None, **_):
    Re = dp * rho * vs / mu
    h = 1.0 - voidage
    e3 = voidage * voidage * voidage
    if Dt is None:
        A, B = 1.0, 1.0
    else:
        A = 1.0 + PI * dp / (6.0 * h * Dt)
        A = A * A
        B = 1.0 - PI * PI * dp / 24.0 / Dt * (1.0 - dp / (2.0 * Dt))
    fp = (119.8 * A + 4.63 * B * (Re / h) ** (5.0 / 6.0)) * h * h / (e3 * Re)
    return fp * rho * vs * vs * L / dp


def montillet_akkari_comiti(dp, voidage, vs, rho, mu, L=1.0, Dt=None, **_):
    Re = rho * vs * dp / mu
    a = 0.061 if voidage < 0.4 else 0.05
    if Dt is None or Dt / dp > 50:
        Dterm = 2.2
    else:
        Dterm = (Dt / dp) ** 0.2
    right = a * Dterm * (1000.0 / Re + 60.0 / math.sqrt(Re) + 12.0)
    e3 = voidage * voidage * voidage
    left = dp / (L * rho * vs * vs * (1.0 - voidage)) * e3
    return right / left


# ============================================================
# Drag coefficient and terminal velocity (correct)
# ============================================================

def _barati(Re):
    Re_inv = 1.0 / Re
    return (
        5.4856e9 * math.tanh(4.3774e-9 * Re_inv)
        + 0.0709 * math.tanh(700.6574 * Re_inv)
        + 0.3894 * math.tanh(74.1539 * Re_inv)
        - 0.1198 * math.tanh(7429.0843 * Re_inv)
        + 1.7174 * math.tanh(9.9851 / (Re + 2.3384))
        + 0.4744
    )


def _barati_high(Re):
    if Re > 1e6:
        Re = 1e6
    Re2 = Re * Re
    t0 = 1.0 / Re
    t1 = Re / 6530.0
    t2 = Re / 1620.0
    t3 = math.log10(Re2 + 10.7563)
    t4 = 1.0 / (Re + Re2)
    t4 = t4 * t4 * t4 * t4
    tanhRe = math.tanh(Re)
    return (
        8e-6 * (t1 * t1 + tanhRe - 8.0 * math.log10(Re))
        - 0.4119 * math.exp(-2.08e43 * t4)
        - 2.1344 * math.exp(-t0 * (t3 * t3 + 9.9867))
        + 0.1357 * math.exp(-t0 * (t2 * t2 + 10370.0))
        - 8.5e-3 * t0 * (2.0 * math.log10(math.tanh(tanhRe)) - 2825.7162)
        + 2.4795
    )


def _drag_sphere(Re):
    if Re > 0.1:
        if Re <= 212963.26847812787:
            return _barati(Re)
        else:
            return _barati_high(Re)
    elif Re >= 0.01:
        ratio = (Re - 0.01) / (0.1 - 0.01)
        return ratio * _barati(Re) + (1.0 - ratio) * (24.0 / Re)
    else:
        return 24.0 / Re


def _v_terminal(dp, rho_p, rho_f, mu):
    v_lam = G * dp * dp * (rho_p - rho_f) / (18.0 * mu)
    Re_lam = rho_f * v_lam * dp / mu
    if Re_lam < 0.01:
        return v_lam

    Re_almost = rho_f * dp / mu
    main = 4.0 / 3.0 * G * dp * (rho_p - rho_f) / rho_f
    V_max = 1e6 / rho_f / dp * mu

    def err(V):
        Cd = _drag_sphere(Re_almost * V)
        return V - math.sqrt(main / Cd)

    x0 = V_max * 1e-2
    f0 = err(x0)
    x1 = x0 * 1.0001 if x0 != 0 else 1e-6
    for _ in range(300):
        f1 = err(x1)
        if abs(f1) < 1e-12 * max(abs(x1), 1e-30):
            return x1
        denom = f1 - f0
        if abs(denom) < 1e-30:
            x1 = x1 * 1.1
            f0 = err(x1 * 0.9)
            x0 = x1 * 0.9
            continue
        x_new = x1 - f1 * (x1 - x0) / denom
        if x_new <= 0:
            x_new = x1 * 0.5
        x0, f0 = x1, f1
        x1 = x_new
    return x1


# ============================================================
# Minimum fluidization velocity (correct bracket widening)
# ============================================================

CORRELATIONS = {
    "Ergun": ergun,
    "Kuo_Nydegger": kuo_nydegger,
    "Tallmadge": tallmadge,
    "Jones_Krier": jones_krier,
    "Carman": carman,
    "Hicks": hicks,
    "Brauer": brauer,
    "KTA": kta,
    "Erdim_Akgiray_Demir": erdim_akgiray_demir,
    "Fahien_Schriver": fahien_schriver,
    "Idelchik": idelchik,
    "Harrison_Brunner_Hecker": harrison_brunner_hecker,
    "Montillet_Akkari_Comiti": montillet_akkari_comiti,
}


def _compute_vmf(corr_func, dp, voidage, rho_f, mu, rho_p, Dt=None):
    bed_weight = (1.0 - voidage) * (rho_p - rho_f) * G

    def obj(vs):
        return corr_func(
            dp=dp, voidage=voidage, vs=vs, rho=rho_f, mu=mu, L=1.0, Dt=Dt
        ) - bed_weight

    lo = 1e-15
    hi = 10.0
    for _ in range(40):
        if obj(hi) >= 0:
            break
        hi *= 10.0
    else:
        return hi

    for _ in range(300):
        mid = 0.5 * (lo + hi)
        if mid <= 0:
            mid = 1e-15
        if obj(mid) > 0:
            hi = mid
        else:
            lo = mid
        if hi - lo < 1e-14 * max(mid, 1e-30):
            break
    return 0.5 * (lo + hi)


# ============================================================
# Main — write to SQLite
# ============================================================

def process_scenario(conn, s):
    dp = s["dp"]
    voidage = s["voidage"]
    vs = s["vs"]
    rho = s["rho_fluid"]
    mu = s["mu"]
    L = s["L"]
    rho_p = s["rho_particle"]
    Dt = s.get("Dt")
    name = s["name"]

    c = conn.cursor()

    for corr_name, func in CORRELATIONS.items():
        dp_val = func(dp=dp, voidage=voidage, vs=vs, rho=rho, mu=mu, L=L, Dt=Dt)
        c.execute(
            "INSERT OR REPLACE INTO pressure_drops VALUES (?, ?, ?)",
            (name, corr_name, dp_val),
        )

        vmf_val = _compute_vmf(func, dp, voidage, rho, mu, rho_p, Dt=Dt)
        c.execute(
            "INSERT OR REPLACE INTO fluidization VALUES (?, ?, ?)",
            (name, corr_name, vmf_val),
        )

    vt = _v_terminal(dp, rho_p, rho, mu)
    c.execute(
        "INSERT OR REPLACE INTO terminal_velocity VALUES (?, ?)",
        (name, vt),
    )
    conn.commit()


def main():
    import os
    db_path = "/app/results.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    with open("/app/scenarios.toml", "rb") as f:
        config = tomllib.load(f)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""CREATE TABLE pressure_drops (
        scenario TEXT NOT NULL,
        correlation TEXT NOT NULL,
        value REAL NOT NULL,
        PRIMARY KEY (scenario, correlation)
    )""")
    cur.execute("""CREATE TABLE fluidization (
        scenario TEXT NOT NULL,
        correlation TEXT NOT NULL,
        vmf REAL NOT NULL,
        PRIMARY KEY (scenario, correlation)
    )""")
    cur.execute("""CREATE TABLE terminal_velocity (
        scenario TEXT NOT NULL,
        vt REAL NOT NULL,
        PRIMARY KEY (scenario)
    )""")
    conn.commit()

    for s in config["scenarios"]:
        process_scenario(conn, s)

    conn.close()


if __name__ == "__main__":
    main()
