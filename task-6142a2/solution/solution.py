"""
Multi-format FluSight forecast evaluation pipeline.
Reads CSV, Parquet (via DuckDB), and NDJSON forecast files.
Reads target observations from SQLite database.
Writes CSV outputs and stores all results in SQLite results.db.

"""
import csv
import json
import math
import os
import datetime
import sqlite3
from collections import defaultdict

import duckdb


###############################################################################
# 1. Multi-Format Data Loading
###############################################################################

def load_hub_config(path):
    with open(path) as f:
        config = json.load(f)
    round_cfg = config["rounds"][0]
    model_task = round_cfg["model_tasks"][0]
    qt_params = model_task["output_type"]["quantile"]
    required_quantiles = set(qt_params["output_type_id_params"]["required"])
    value_minimum = qt_params["value"]["minimum"]
    required_horizons = set(model_task["task_ids"]["horizon"]["required"])
    required_locations = set(model_task["task_ids"]["location"]["required"])
    return {
        "required_quantiles": required_quantiles,
        "value_minimum": value_minimum,
        "required_horizons": required_horizons,
        "required_locations": required_locations,
    }


def load_csv_forecast(path):
    rows = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            row["horizon"] = int(row["horizon"])
            row["value"] = float(row["value"])
            row["output_type_id"] = float(row["output_type_id"])
            rows.append(row)
    return rows


def load_parquet_forecast(path):
    """Read a Parquet forecast file using DuckDB."""
    conn = duckdb.connect()
    result = conn.execute(f"SELECT * FROM read_parquet('{path}')").fetchall()
    columns = [desc[0] for desc in conn.description]
    conn.close()
    rows = []
    for record in result:
        row = dict(zip(columns, record))
        # DuckDB auto-detects date columns as datetime.date objects in Parquet;
        # normalize to ISO format strings for consistency with CSV/NDJSON loaders
        for k in ("reference_date", "target_end_date"):
            if k in row and hasattr(row[k], 'isoformat'):
                row[k] = row[k].isoformat()
        row["horizon"] = int(row["horizon"])
        row["value"] = float(row["value"])
        row["output_type_id"] = float(row["output_type_id"])
        rows.append(row)
    return rows


def load_ndjson_forecast(path):
    """Read a newline-delimited JSON forecast file."""
    rows = []
    with open(path) as f:
        for line in f:
            row = json.loads(line.strip())
            row["horizon"] = int(row["horizon"])
            row["value"] = float(row["value"])
            row["output_type_id"] = float(row["output_type_id"])
            rows.append(row)
    return rows


def load_forecasts(forecast_dir):
    """Load all forecasts from mixed-format directory."""
    models = {}
    loaders = {
        ".csv": load_csv_forecast,
        ".parquet": load_parquet_forecast,
        ".ndjson": load_ndjson_forecast,
    }
    for fname in sorted(os.listdir(forecast_dir)):
        name, ext = os.path.splitext(fname)
        if ext not in loaders:
            continue
        path = os.path.join(forecast_dir, fname)
        print(f"  Loading {fname} (format: {ext})")
        models[name] = loaders[ext](path)
    return models


def load_target_data_from_sqlite(db_path):
    """Read target observations from SQLite database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.execute("SELECT date, location, value FROM weekly_admissions")
    targets = {}
    for row in cursor.fetchall():
        targets[(row[1], row[0])] = float(row[2])
    conn.close()
    return targets


def load_locations(path):
    locs = {}
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            locs[row["location"]] = {
                "name": row["location_name"],
                "population": int(row["population"]),
            }
    return locs


def validate_model(model_rows, config):
    required_q = config["required_quantiles"]
    val_min = config["value_minimum"]
    tasks = defaultdict(set)
    for row in model_rows:
        key = (row["reference_date"], row["location"], row["horizon"])
        tasks[key].add(row["output_type_id"])
        if row["value"] < val_min:
            return False
    for key, q_set in tasks.items():
        if not required_q.issubset(q_set):
            return False
    return True


###############################################################################
# 2. WIS Computation
###############################################################################

QUANTILE_LEVELS = [
    0.01, 0.025, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4,
    0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9,
    0.95, 0.975, 0.99
]

INTERVALS = [
    (0.01, 0.99, 0.02),
    (0.025, 0.975, 0.05),
    (0.05, 0.95, 0.10),
    (0.1, 0.9, 0.20),
    (0.15, 0.85, 0.30),
    (0.2, 0.8, 0.40),
    (0.25, 0.75, 0.50),
    (0.3, 0.7, 0.60),
    (0.35, 0.65, 0.70),
    (0.4, 0.6, 0.80),
    (0.45, 0.55, 0.90),
]

K = len(INTERVALS)


def compute_wis(quantile_dict, observed):
    median = quantile_dict[0.5]
    median_overp = 0.5 * max(0, median - observed)
    median_underp = 0.5 * max(0, observed - median)

    total_disp = 0.0
    total_overp = 0.0
    total_underp = 0.0

    for lower_q, upper_q, alpha in INTERVALS:
        l = quantile_dict[lower_q]
        u = quantile_dict[upper_q]
        w = alpha / 2.0
        total_disp += w * (u - l)
        total_overp += w * (2.0 / alpha) * max(0, l - observed)
        total_underp += w * (2.0 / alpha) * max(0, observed - u)

    normalization = 1.0 / (K + 0.5)
    wis = normalization * (0.5 * abs(observed - median) + total_disp + total_overp + total_underp)
    dispersion = normalization * total_disp
    overprediction = normalization * (median_overp + total_overp)
    underprediction = normalization * (median_underp + total_underp)
    return wis, dispersion, overprediction, underprediction


###############################################################################
# 3. Coverage
###############################################################################

def compute_coverage(quantile_dict, observed):
    l50, u50 = quantile_dict[0.25], quantile_dict[0.75]
    l95, u95 = quantile_dict[0.025], quantile_dict[0.975]
    in_50 = 1 if l50 <= observed <= u50 else 0
    in_95 = 1 if l95 <= observed <= u95 else 0
    return in_50, in_95


###############################################################################
# 4. Relative WIS (Pairwise Geometric Mean)
###############################################################################

def compute_relative_wis(wis_by_model):
    model_ids = sorted(wis_by_model.keys())
    relative_wis = {}
    for mi in model_ids:
        log_thetas = []
        for mj in model_ids:
            common_keys = set(wis_by_model[mi].keys()) & set(wis_by_model[mj].keys())
            if not common_keys:
                continue
            mean_wis_i = sum(wis_by_model[mi][k] for k in common_keys) / len(common_keys)
            mean_wis_j = sum(wis_by_model[mj][k] for k in common_keys) / len(common_keys)
            if mean_wis_j == 0:
                continue
            log_thetas.append(math.log(mean_wis_i / mean_wis_j))
        if log_thetas:
            relative_wis[mi] = math.exp(sum(log_thetas) / len(log_thetas))
        else:
            relative_wis[mi] = float('inf')
    return relative_wis


###############################################################################
# 5. Ensemble Optimization
###############################################################################

def optimize_ensemble_weights(all_forecasts, forecast_targets, model_ids):
    def evaluate_weights(wvec):
        total_wis = 0.0
        count = 0
        for key, model_quants in all_forecasts.items():
            if key not in forecast_targets:
                continue
            observed = forecast_targets[key]
            ens_q = {}
            for q in QUANTILE_LEVELS:
                ens_q[q] = sum(wvec[i] * model_quants[m][q]
                               for i, m in enumerate(model_ids) if m in model_quants)
            wis, _, _, _ = compute_wis(ens_q, observed)
            total_wis += wis
            count += 1
        return total_wis / count if count > 0 else float('inf')

    def simplex_grid(n, step):
        pts = int(round(1.0 / step))
        if n == 1:
            yield [1.0]
            return
        for i in range(pts + 1):
            w = i * step
            if w > 1.0 + 1e-9:
                break
            remaining = 1.0 - w
            for rest in simplex_grid(n - 1, step):
                rs = sum(rest)
                if rs < 1e-12:
                    continue
                scaled = [r * remaining / rs for r in rest]
                yield [w] + scaled

    n = len(model_ids)
    best_wis = float('inf')
    best_w = [1.0 / n] * n
    for wvec in simplex_grid(n, 0.1):
        w = evaluate_weights(wvec)
        if w < best_wis:
            best_wis = w
            best_w = wvec[:]

    fine_step = 0.02
    radius = 0.15
    best_fine_wis = best_wis
    best_fine_w = best_w[:]

    def fine_search(idx, current):
        nonlocal best_fine_wis, best_fine_w
        if idx == n - 1:
            last = 1.0 - sum(current)
            if last >= -1e-9:
                wvec = current + [max(0, last)]
                w = evaluate_weights(wvec)
                if w < best_fine_wis:
                    best_fine_wis = w
                    best_fine_w = wvec[:]
            return
        lo = max(0, best_w[idx] - radius)
        hi = min(1, best_w[idx] + radius)
        v = lo
        while v <= hi + 1e-9:
            if sum(current) + v <= 1.0 + 1e-9:
                fine_search(idx + 1, current + [v])
            v += fine_step

    fine_search(0, [])
    weights = {model_ids[i]: best_fine_w[i] for i in range(n)}
    return weights, best_fine_wis


###############################################################################
# 6. Helper
###############################################################################

def target_end_date_calc(ref_date, horizon):
    y, m, d = map(int, ref_date.split("-"))
    dt = datetime.date(y, m, d) + datetime.timedelta(days=horizon * 7)
    return dt.isoformat()


###############################################################################
# 7. SQLite Results Database
###############################################################################

def create_results_db(output_dir):
    """Create and return a connection to the results SQLite database."""
    db_path = os.path.join(output_dir, "results.db")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS wis_scores ("
        "model_id TEXT, reference_date TEXT, location TEXT, horizon INTEGER, "
        "target_end_date TEXT, observed REAL, wis REAL, dispersion REAL, "
        "overprediction REAL, underprediction REAL)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS coverage ("
        "model_id TEXT, coverage_50 REAL, coverage_95 REAL, n_forecasts INTEGER)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS model_rankings ("
        "rank INTEGER, model_id TEXT, mean_wis REAL, relative_wis REAL)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS ensemble_weights ("
        "model_id TEXT, weight REAL)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS ensemble_evaluation ("
        "model_id TEXT, mean_wis REAL, relative_wis REAL)")
    conn.commit()
    return conn


###############################################################################
# 8. Main Pipeline
###############################################################################

def main():
    data_dir = "/app/data"
    config_path = "/app/hub-config/tasks.json"
    output_dir = "/app/output"
    os.makedirs(output_dir, exist_ok=True)

    # Load hub config
    config = load_hub_config(config_path)
    print(f"Hub config: {len(config['required_quantiles'])} required quantile levels")

    # Load target observations from SQLite
    targets = load_target_data_from_sqlite(os.path.join(data_dir, "observations.db"))
    print(f"Loaded {len(targets)} target observations from SQLite")

    # Load forecasts from mixed formats
    print("Loading forecasts:")
    all_models = load_forecasts(os.path.join(data_dir, "forecasts"))
    locations = load_locations(os.path.join(data_dir, "locations.csv"))

    # Validate models
    models = {}
    for model_id, rows in all_models.items():
        if validate_model(rows, config):
            models[model_id] = rows
            print(f"  {model_id}: VALID")
        else:
            print(f"  {model_id}: EXCLUDED (non-conforming)")

    model_ids = sorted(models.keys())
    print(f"\nValidated {len(model_ids)} models: {model_ids}")

    # Create results database
    results_conn = create_results_db(output_dir)

    # --- Per-forecast WIS scores ---
    wis_rows = []
    wis_by_model = {m: {} for m in model_ids}
    coverage_by_model = {m: {"in_50": 0, "in_95": 0, "total": 0} for m in model_ids}
    all_forecasts = {}

    for model_id, rows in models.items():
        tasks = defaultdict(dict)
        for row in rows:
            key = (row["reference_date"], row["location"], row["horizon"])
            tasks[key][row["output_type_id"]] = row["value"]

        for key, quantile_dict in tasks.items():
            ref_date, loc, horizon = key
            ted = target_end_date_calc(ref_date, horizon)
            target_key = (loc, ted)

            if target_key not in targets:
                continue

            observed = targets[target_key]
            wis, disp, overp, underp = compute_wis(quantile_dict, observed)
            in_50, in_95 = compute_coverage(quantile_dict, observed)

            wis_by_model[model_id][key] = wis
            coverage_by_model[model_id]["in_50"] += in_50
            coverage_by_model[model_id]["in_95"] += in_95
            coverage_by_model[model_id]["total"] += 1

            wis_rows.append({
                "model_id": model_id,
                "reference_date": ref_date,
                "location": loc,
                "horizon": horizon,
                "target_end_date": ted,
                "observed": observed,
                "wis": round(wis, 4),
                "dispersion": round(disp, 4),
                "overprediction": round(overp, 4),
                "underprediction": round(underp, 4),
            })

            if key not in all_forecasts:
                all_forecasts[key] = {}
            all_forecasts[key][model_id] = quantile_dict

    # Write wis_scores.csv and insert into database
    sorted_wis = sorted(wis_rows, key=lambda r: (r["model_id"], r["reference_date"], r["location"], r["horizon"]))
    with open(os.path.join(output_dir, "wis_scores.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "model_id", "reference_date", "location", "horizon",
            "target_end_date", "observed", "wis", "dispersion",
            "overprediction", "underprediction"
        ])
        writer.writeheader()
        for row in sorted_wis:
            writer.writerow(row)
            results_conn.execute(
                "INSERT INTO wis_scores VALUES (?,?,?,?,?,?,?,?,?,?)",
                (row["model_id"], row["reference_date"], row["location"],
                 row["horizon"], row["target_end_date"], row["observed"],
                 row["wis"], row["dispersion"], row["overprediction"],
                 row["underprediction"]))
    results_conn.commit()
    print(f"Wrote {len(wis_rows)} WIS scores")

    # --- Coverage ---
    coverage_rows = []
    for model_id in model_ids:
        total = coverage_by_model[model_id]["total"]
        cov_50 = coverage_by_model[model_id]["in_50"] / total if total > 0 else 0
        cov_95 = coverage_by_model[model_id]["in_95"] / total if total > 0 else 0
        coverage_rows.append({
            "model_id": model_id,
            "coverage_50": round(cov_50, 4),
            "coverage_95": round(cov_95, 4),
            "n_forecasts": total,
        })

    with open(os.path.join(output_dir, "coverage.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["model_id", "coverage_50", "coverage_95", "n_forecasts"])
        writer.writeheader()
        for row in coverage_rows:
            writer.writerow(row)
            results_conn.execute(
                "INSERT INTO coverage VALUES (?,?,?,?)",
                (row["model_id"], row["coverage_50"], row["coverage_95"], row["n_forecasts"]))
    results_conn.commit()
    print("Wrote coverage statistics")

    # --- Relative WIS ---
    rel_wis = compute_relative_wis(wis_by_model)
    mean_wis = {}
    for m in model_ids:
        vals = list(wis_by_model[m].values())
        mean_wis[m] = sum(vals) / len(vals) if vals else 0

    ranking_rows = []
    for rank, (model_id, rwis) in enumerate(sorted(rel_wis.items(), key=lambda x: x[1]), 1):
        ranking_rows.append({
            "rank": rank,
            "model_id": model_id,
            "mean_wis": round(mean_wis[model_id], 4),
            "relative_wis": round(rwis, 4),
        })

    with open(os.path.join(output_dir, "model_rankings.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["rank", "model_id", "mean_wis", "relative_wis"])
        writer.writeheader()
        for row in ranking_rows:
            writer.writerow(row)
            results_conn.execute(
                "INSERT INTO model_rankings VALUES (?,?,?,?)",
                (row["rank"], row["model_id"], row["mean_wis"], row["relative_wis"]))
    results_conn.commit()
    print("Wrote model rankings")

    # --- Ensemble optimization ---
    forecast_target_map = {}
    for key in all_forecasts:
        ref_date, loc, horizon = key
        ted = target_end_date_calc(ref_date, horizon)
        target_key = (loc, ted)
        if target_key in targets:
            forecast_target_map[key] = targets[target_key]

    weights, ensemble_mean_wis = optimize_ensemble_weights(
        all_forecasts, forecast_target_map, model_ids
    )

    with open(os.path.join(output_dir, "ensemble_weights.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["model_id", "weight"])
        writer.writeheader()
        for m in model_ids:
            row = {"model_id": m, "weight": round(weights[m], 4)}
            writer.writerow(row)
            results_conn.execute(
                "INSERT INTO ensemble_weights VALUES (?,?)",
                (m, round(weights[m], 4)))
    results_conn.commit()
    print(f"Wrote ensemble weights (ensemble mean WIS: {ensemble_mean_wis:.4f})")

    # --- Ensemble evaluation ---
    ens_wis_scores = []
    for key, model_quants in all_forecasts.items():
        if key not in forecast_target_map:
            continue
        observed = forecast_target_map[key]
        ens_q = {}
        for q in QUANTILE_LEVELS:
            ens_q[q] = sum(weights[m] * model_quants[m][q]
                          for m in model_ids if m in model_quants)
        wis, _, _, _ = compute_wis(ens_q, observed)
        ens_wis_scores.append(wis)

    ens_mean_wis = sum(ens_wis_scores) / len(ens_wis_scores) if ens_wis_scores else 0

    eval_rows = []
    for m in model_ids:
        eval_rows.append({"model_id": m, "mean_wis": round(mean_wis[m], 4),
                          "relative_wis": round(rel_wis[m], 4)})
    eval_rows.append({
        "model_id": "Ensemble-Trained",
        "mean_wis": round(ens_mean_wis, 4),
        "relative_wis": round(ens_mean_wis / (sum(mean_wis.values()) / len(mean_wis)), 4),
    })

    eval_sorted = sorted(eval_rows, key=lambda r: r["mean_wis"])
    with open(os.path.join(output_dir, "ensemble_evaluation.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["model_id", "mean_wis", "relative_wis"])
        writer.writeheader()
        for row in eval_sorted:
            writer.writerow(row)
            results_conn.execute(
                "INSERT INTO ensemble_evaluation VALUES (?,?,?)",
                (row["model_id"], row["mean_wis"], row["relative_wis"]))
    results_conn.commit()
    results_conn.close()
    print("Wrote ensemble evaluation and results database")
    print("Done! DuckDB Parquet export will follow via solve.sh.")


if __name__ == "__main__":
    main()
