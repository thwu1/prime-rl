#!/usr/bin/env python3
"""
WEPP Surface Hydrology Pipeline

Integrates Fortran-compiled GAML routines (via ctypes), CLIGEN station
file parsing, SQLite storage, and gnuplot visualization.

"""

import sys
import json
import math
import sqlite3
import os
import re
import ctypes
import subprocess
from ctypes import c_double, c_int, byref, CDLL
from collections import defaultdict

DB_PATH = "/app/results.db"
LIB_PATH = "/app/libgaml.so"

_gaml_lib = None


def _load_lib():
    global _gaml_lib
    if _gaml_lib is None:
        _gaml_lib = CDLL(LIB_PATH)
    return _gaml_lib


# ====================== FORTRAN FFI ======================

def gaml_G(F, Ns_td):
    """Call Fortran gaml_g_func: G(F) = F - Ns_td * ln(1 + F/Ns_td)"""
    lib = _load_lib()
    f_val = c_double(F)
    ns_val = c_double(Ns_td)
    result = c_double()
    lib.gaml_g_func(byref(f_val), byref(ns_val), byref(result))
    return result.value


def solve_gaml_F(target_G, Ns_td, F_guess, tol=1e-10, max_iter=200):
    """Call Fortran gaml_solve_f: solve G(F) = target_G for F"""
    lib = _load_lib()
    target = c_double(target_G)
    ns = c_double(Ns_td)
    guess = c_double(F_guess)
    t = c_double(tol)
    mi = c_int(max_iter)
    result = c_double()
    lib.gaml_solve_f(byref(target), byref(ns), byref(guess),
                     byref(t), byref(mi), byref(result))
    return result.value


def gaml_infil_rate_f(Ke, Ns_td, F_cum):
    """Call Fortran gaml_infil_rate: f = Ke * (1 + Ns_td / F_cum)"""
    lib = _load_lib()
    ke = c_double(Ke)
    ns = c_double(Ns_td)
    fc = c_double(F_cum)
    result = c_double()
    lib.gaml_infil_rate(byref(ke), byref(ns), byref(fc), byref(result))
    return result.value


# ====================== DATABASE ======================

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS stations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            latitude REAL,
            longitude REAL,
            elevation_ft REAL,
            years INTEGER
        );
        CREATE TABLE IF NOT EXISTS monthly_precip (
            station_id INTEGER REFERENCES stations(id),
            month INTEGER CHECK(month BETWEEN 1 AND 12),
            mean_in REAL,
            sd_in REAL,
            skew REAL,
            prob_ww REAL,
            prob_wd REAL,
            max_30min_in_hr REAL,
            PRIMARY KEY (station_id, month)
        );
        CREATE TABLE IF NOT EXISTS simulations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scenario TEXT UNIQUE,
            ponding_time_min REAL,
            cumulative_infiltration_mm REAL,
            total_rainfall_mm REAL,
            rainfall_excess_mm REAL,
            depression_storage_mm REAL,
            net_runoff_mm REAL,
            peak_discharge_mm_hr REAL,
            effective_duration_hr REAL
        );
    """)
    conn.commit()
    conn.close()


# ====================== PAR FILE PARSER ======================

def parse_12_values(line, offset=8, width=6):
    """Parse 12 fixed-width monthly values from a line."""
    data = line[offset:]
    values = []
    for i in range(12):
        start = i * width
        end = start + width
        val_str = data[start:end].strip()
        if val_str:
            values.append(float(val_str))
        else:
            values.append(0.0)
    return values


def parse_par_file(filepath):
    """Parse a CLIGEN .PAR station parameter file."""
    with open(filepath) as f:
        lines = f.readlines()

    name = lines[0][:41].strip()

    m = re.search(
        r'LATT=\s*([\d.+-]+)\s*LONG=\s*([\d.+-]+)\s*YEARS=\s*([\d.]+)',
        lines[1]
    )
    latitude = float(m.group(1))
    longitude = float(m.group(2))
    years = int(float(m.group(3)))

    m = re.search(r'ELEVATION\s*=\s*([\d.]+)', lines[2])
    elevation = float(m.group(1))

    mean_p = parse_12_values(lines[3])
    sd_p = parse_12_values(lines[4])
    skew_p = parse_12_values(lines[5])
    pww = parse_12_values(lines[6])
    pwd = parse_12_values(lines[7])
    max_30min = parse_12_values(lines[14])

    return {
        "name": name,
        "latitude": latitude,
        "longitude": longitude,
        "elevation_ft": elevation,
        "years": years,
        "monthly": {
            month + 1: {
                "mean_in": mean_p[month],
                "sd_in": sd_p[month],
                "skew": skew_p[month],
                "prob_ww": pww[month],
                "prob_wd": pwd[month],
                "max_30min_in_hr": max_30min[month],
            }
            for month in range(12)
        },
    }


# ====================== INGEST COMMAND ======================

def cmd_ingest(par_file):
    init_db()
    data = parse_par_file(par_file)
    conn = get_db()

    conn.execute(
        "INSERT OR REPLACE INTO stations "
        "(name, latitude, longitude, elevation_ft, years) VALUES (?, ?, ?, ?, ?)",
        (data["name"], data["latitude"], data["longitude"],
         data["elevation_ft"], data["years"]),
    )

    row = conn.execute(
        "SELECT id FROM stations WHERE name = ?", (data["name"],)
    ).fetchone()
    station_id = row[0]

    for month, stats in data["monthly"].items():
        conn.execute(
            "INSERT OR REPLACE INTO monthly_precip "
            "(station_id, month, mean_in, sd_in, skew, prob_ww, prob_wd, max_30min_in_hr) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (station_id, month, stats["mean_in"], stats["sd_in"],
             stats["skew"], stats["prob_ww"], stats["prob_wd"],
             stats["max_30min_in_hr"]),
        )

    conn.commit()
    conn.close()


# ====================== HYDROLOGY SIMULATION ======================

def simulate(config):
    """Run the full single-OFE hydrology simulation using Fortran GAML routines.
    Returns (summary_dict, excess_rates_list)."""
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
        return _zero_result(), []

    storm_duration_min = intervals[-1][1]

    dt_min = 0.02
    n_steps = int(math.ceil(storm_duration_min / dt_min))
    if n_steps < 1:
        n_steps = 1
    dt_min_actual = storm_duration_min / n_steps
    dt_hr = dt_min_actual / 60.0

    def get_intensity(t_min):
        for ts, te, r in intervals:
            if ts <= t_min < te:
                return r
        return 0.0

    F_cum = 0.0
    R_cum = 0.0
    ponded = False
    tp_min = -1.0
    ponded_elapsed_hr = 0.0
    ponded_G_base = 0.0

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
                    ponded = True
                    if tp_min < 0:
                        tp_min = t
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
                        f_last_nonzero_excess = gaml_infil_rate_f(Ke, Ns_td, F_cum)
                        if first_excess_time < 0:
                            first_excess_time = t
                        last_excess_time = t + dt_min_actual
                    else:
                        excess_rates.append((t, 0.0))

                elif F_cum + rain_depth >= F_p:
                    ponded = True
                    rain_to_ponding = F_p - F_cum
                    dt_to_ponding_min = (rain_to_ponding / r) * 60.0 if r > 0 else 0.0

                    if tp_min < 0:
                        tp_min = t + dt_to_ponding_min

                    ponded_G_base = gaml_G(F_p, Ns_td)
                    ponded_elapsed_hr = 0.0

                    dt_remaining_hr = (dt_min_actual - dt_to_ponding_min) / 60.0
                    if dt_remaining_hr > 1e-12:
                        ponded_elapsed_hr = dt_remaining_hr
                        target_G = ponded_G_base + Ke * ponded_elapsed_hr
                        F_new = solve_gaml_F(
                            target_G, Ns_td, F_p + Ke * dt_remaining_hr
                        )
                        infil_depth = F_new - F_cum
                        excess_depth = rain_depth - infil_depth
                        F_cum = F_new
                        R_cum += rain_depth

                        if excess_depth > 1e-12:
                            excess_rate = excess_depth / dt_hr
                            excess_rates.append((t, excess_rate))
                            total_excess += excess_depth
                            f_last_nonzero_excess = gaml_infil_rate_f(Ke, Ns_td, F_cum)
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
            R_cum += rain_depth

            if r <= 0:
                ponded = False
                excess_rates.append((t, 0.0))
                continue

            f_current = gaml_infil_rate_f(Ke, Ns_td, F_cum)
            if r < f_current:
                ponded = False
                F_cum += rain_depth
                excess_rates.append((t, 0.0))
                continue

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
                f_last_nonzero_excess = gaml_infil_rate_f(Ke, Ns_td, F_cum)
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
        summary = {
            "ponding_time_min": round(tp_min, 4) if tp_min >= 0 else -1.0,
            "cumulative_infiltration_mm": round(F_cum, 4),
            "total_rainfall_mm": round(total_rainfall, 4),
            "rainfall_excess_mm": round(V_gross, 4),
            "depression_storage_mm": round(Sd, 4),
            "net_runoff_mm": 0.0,
            "peak_discharge_mm_hr": 0.0,
            "effective_duration_hr": 0.0,
        }
        return summary, excess_rates

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
        summary = {
            "ponding_time_min": round(tp_min, 4) if tp_min >= 0 else -1.0,
            "cumulative_infiltration_mm": round(F_cum, 4),
            "total_rainfall_mm": round(total_rainfall, 4),
            "rainfall_excess_mm": round(V_gross, 4),
            "depression_storage_mm": round(Sd, 4),
            "net_runoff_mm": round(V_net, 4),
            "peak_discharge_mm_hr": 0.0,
            "effective_duration_hr": 0.0,
        }
        return summary, excess_rates

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
    if t_star < 1.0 and 0 < f_star < 1.0:
        Q_star = 1.0 - 0.6 * f_star * (t_star ** 0.6)
        recession_factor = max(0.0, Q_star)
        V_net = V_net * recession_factor

    De = V_net / q_peak if q_peak > 0 else 0.0

    summary = {
        "ponding_time_min": round(tp_min, 4) if tp_min >= 0 else -1.0,
        "cumulative_infiltration_mm": round(F_cum, 4),
        "total_rainfall_mm": round(total_rainfall, 4),
        "rainfall_excess_mm": round(V_gross, 4),
        "depression_storage_mm": round(Sd, 4),
        "net_runoff_mm": round(V_net, 4),
        "peak_discharge_mm_hr": round(q_peak, 4),
        "effective_duration_hr": round(De, 6),
    }
    return summary, excess_rates


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
    }


# ====================== SIMULATE COMMAND ======================

def cmd_simulate(scenario_file):
    init_db()
    with open(scenario_file) as f:
        config = json.load(f)

    result, _ = simulate(config)

    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO simulations "
        "(scenario, ponding_time_min, cumulative_infiltration_mm, "
        "total_rainfall_mm, rainfall_excess_mm, depression_storage_mm, "
        "net_runoff_mm, peak_discharge_mm_hr, effective_duration_hr) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            config["name"],
            result["ponding_time_min"],
            result["cumulative_infiltration_mm"],
            result["total_rainfall_mm"],
            result["rainfall_excess_mm"],
            result["depression_storage_mm"],
            result["net_runoff_mm"],
            result["peak_discharge_mm_hr"],
            result["effective_duration_hr"],
        ),
    )
    conn.commit()
    conn.close()


# ====================== PLOT COMMAND ======================

def cmd_plot(scenario_file):
    """Generate hydrograph plot using gnuplot."""
    with open(scenario_file) as f:
        config = json.load(f)

    name = config["name"]
    _, excess_rates = simulate(config)

    os.makedirs("/app/plots", exist_ok=True)

    # Write gnuplot data file
    data_path = f"/tmp/wepp_plot_{name}.dat"
    with open(data_path, "w") as f:
        f.write("# time_min excess_rate_mm_hr\n")
        for t, rate in excess_rates:
            f.write(f"{t:.4f} {rate:.4f}\n")

    # Write gnuplot script
    script_path = f"/tmp/wepp_plot_{name}.gp"
    png_path = f"/app/plots/{name}.png"

    with open(script_path, "w") as f:
        f.write(f"set terminal png size 800,600 enhanced\n")
        f.write(f"set output '{png_path}'\n")
        f.write(f"set title '{name}'\n")
        f.write("set xlabel 'Time (min)'\n")
        f.write("set ylabel 'Rainfall Excess Rate (mm/hr)'\n")
        f.write("set grid\n")
        f.write("set style fill solid 0.3\n")
        f.write(f"plot '{data_path}' using 1:2 with lines lw 2 "
                f"lc rgb '#0066CC' title 'Excess Rate'\n")

    subprocess.run(["gnuplot", script_path], check=True)


# ====================== REPORT COMMAND ======================

def cmd_report(query_name):
    conn = get_db()
    conn.row_factory = sqlite3.Row

    if query_name == "wettest-months":
        rows = conn.execute(
            "SELECT s.name as station, mp.month, mp.mean_in "
            "FROM monthly_precip mp "
            "JOIN stations s ON mp.station_id = s.id "
            "ORDER BY s.name ASC, mp.mean_in DESC"
        ).fetchall()

        by_station = defaultdict(list)
        for row in rows:
            by_station[row["station"]].append(
                {
                    "station": row["station"],
                    "month": row["month"],
                    "mean_in": row["mean_in"],
                }
            )

        result = []
        for station in sorted(by_station.keys()):
            result.extend(by_station[station][:3])

        print(json.dumps(result, indent=2))

    elif query_name == "runoff-ranking":
        rows = conn.execute(
            "SELECT scenario, net_runoff_mm, peak_discharge_mm_hr "
            "FROM simulations "
            "ORDER BY net_runoff_mm DESC"
        ).fetchall()

        result = [
            {
                "scenario": row["scenario"],
                "net_runoff_mm": row["net_runoff_mm"],
                "peak_discharge_mm_hr": row["peak_discharge_mm_hr"],
            }
            for row in rows
        ]

        print(json.dumps(result, indent=2))

    else:
        print(f"Unknown query: {query_name}", file=sys.stderr)
        sys.exit(1)

    conn.close()


# ====================== MAIN ======================

def main():
    if len(sys.argv) < 3:
        print(
            "Usage: wepp_pipeline.py <command> <args...>\n"
            "Commands: ingest, simulate, plot, report",
            file=sys.stderr,
        )
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "ingest":
        cmd_ingest(sys.argv[2])
    elif cmd == "simulate":
        cmd_simulate(sys.argv[2])
    elif cmd == "plot":
        cmd_plot(sys.argv[2])
    elif cmd == "report":
        cmd_report(sys.argv[2])
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
