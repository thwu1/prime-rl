#!/usr/bin/env python3
"""
Solution: WSPL evaluator and hierarchical quantile forecast reconciliation.


Strategy:
1. Implement WSPL metric from the specification in /app/data/spec.md
2. Evaluate base forecasts
3. Perform bottom-up reconciliation: keep bottom-level (Store_Category) quantile
   forecasts, aggregate them to produce upper-level quantile forecasts
4. This guarantees coherence by construction and preserves monotonicity
   (sum of monotonic sequences is monotonic)
5. Evaluate reconciled forecasts and output results
"""
import json
import csv
import os

DATA_DIR = "/app/data"
OUTPUT_DIR = "/app/output"
N_FORECAST = 28
QUANTILES = [0.005, 0.025, 0.165, 0.25, 0.5, 0.75, 0.835, 0.975, 0.995]


def load_json(filename):
    with open(os.path.join(DATA_DIR, filename)) as f:
        return json.load(f)


def load_csv_series(filename):
    """Load CSV where first column is series_name, rest are numeric values.
    Returns {series_name: [float, ...]}"""
    data = {}
    with open(os.path.join(DATA_DIR, filename), newline="") as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        for row in reader:
            data[row[0]] = [float(x) for x in row[1:]]
    return data


def load_forecasts(filename):
    """Load forecast CSV with columns: series_name, quantile, h_1, ..., h_28.
    Returns {series_name: {quantile_str: [float, ...]}}"""
    data = {}
    with open(os.path.join(DATA_DIR, filename), newline="") as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        for row in reader:
            sn = row[0]
            q_str = row[1]
            vals = [float(x) for x in row[2:]]
            if sn not in data:
                data[sn] = {}
            data[sn][q_str] = vals
    return data


def compute_scale_factor(history_vals):
    """Compute scale factor: mean absolute first difference of history."""
    n = len(history_vals)
    if n < 2:
        return 1.0
    diffs_sum = sum(abs(history_vals[t] - history_vals[t - 1]) for t in range(1, n))
    s = diffs_sum / (n - 1)
    return max(s, 1.0)


def pinball_loss(q, y, y_hat):
    """Compute pinball loss for a single observation."""
    diff = y - y_hat
    if diff >= 0:
        return q * diff
    else:
        return (1 - q) * (-diff)


def compute_wspl(forecasts, actuals, history_data, weights, hierarchy):
    """Compute WSPL metric as per specification.

    Args:
        forecasts: {series_name: {quantile_str: [h1, ..., h28]}}
        actuals: {series_name: [h1, ..., h28]}
        history_data: {series_name: [d1, ..., d365]}
        weights: {level_name: {series_name: weight}}
        hierarchy: parsed hierarchy.json

    Returns:
        (overall_wspl, {level_name: level_wspl})
    """
    level_order = hierarchy["level_order"]
    levels = hierarchy["levels"]
    n_quantiles = len(QUANTILES)

    # Pre-compute scale factors
    scale_factors = {}
    for sn in actuals:
        if sn in history_data:
            scale_factors[sn] = compute_scale_factor(history_data[sn])
        else:
            scale_factors[sn] = 1.0

    level_wspls = {}
    for level_name in level_order:
        level_wspl = 0.0
        for q in QUANTILES:
            q_str = f"{q:.3f}"
            weighted_spl = 0.0
            for series_name in levels[level_name]:
                w = weights[level_name][series_name]
                s = scale_factors[series_name]
                y_vals = actuals[series_name]
                y_hat_vals = forecasts[series_name][q_str]

                # Average SPL across horizons
                pl_sum = sum(
                    pinball_loss(q, y_vals[h], y_hat_vals[h])
                    for h in range(N_FORECAST)
                )
                avg_spl = (pl_sum / N_FORECAST) / s
                weighted_spl += w * avg_spl
            level_wspl += weighted_spl
        level_wspl /= n_quantiles
        level_wspls[level_name] = level_wspl

    overall_wspl = sum(level_wspls.values()) / len(level_wspls)
    return overall_wspl, level_wspls


def bottom_up_reconcile(base_forecasts, hierarchy):
    """Perform bottom-up quantile forecast reconciliation.

    Keep bottom-level (Store_Category) quantile forecasts intact.
    For each upper level, compute quantile forecasts as the sum of
    constituent bottom-level quantile forecasts.

    This guarantees:
    - Hierarchical coherence (upper = sum of bottom by construction)
    - Quantile monotonicity (sum of monotonic sequences is monotonic)
    """
    levels = hierarchy["levels"]
    bottom_series = hierarchy["bottom_series"]
    reconciled = {}

    # Copy bottom-level forecasts
    for sn in bottom_series:
        reconciled[sn] = {}
        for q_str in base_forecasts[sn]:
            reconciled[sn][q_str] = list(base_forecasts[sn][q_str])

    # Aggregate for upper levels
    for level_name in ["Total", "Region", "Store", "Category", "Region_Category"]:
        for series_name, indices in levels[level_name].items():
            reconciled[series_name] = {}
            for q in QUANTILES:
                q_str = f"{q:.3f}"
                agg = [0.0] * N_FORECAST
                for bi in indices:
                    bname = bottom_series[bi]
                    for h in range(N_FORECAST):
                        agg[h] += base_forecasts[bname][q_str][h]
                reconciled[series_name][q_str] = agg

    return reconciled


def save_forecasts_csv(forecasts, hierarchy, output_path):
    """Save forecasts to CSV in the same format as base_forecasts.csv."""
    level_order = hierarchy["level_order"]
    levels = hierarchy["levels"]

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        header = ["series_name", "quantile"] + [f"h_{h + 1}" for h in range(N_FORECAST)]
        writer.writerow(header)

        for level_name in level_order:
            for series_name in levels[level_name]:
                for q in QUANTILES:
                    q_str = f"{q:.3f}"
                    vals = forecasts[series_name][q_str]
                    row = [series_name, q_str] + [f"{x:.4f}" for x in vals]
                    writer.writerow(row)


def main():
    # Load data
    hierarchy = load_json("hierarchy.json")
    weights = load_json("weights.json")
    actuals = load_csv_series("actuals.csv")
    history = load_csv_series("history.csv")
    base_forecasts = load_forecasts("base_forecasts.csv")

    # Compute base WSPL
    base_wspl, base_level_wspls = compute_wspl(
        base_forecasts, actuals, history, weights, hierarchy
    )
    print(f"Base WSPL: {base_wspl:.6f}")
    for level, val in base_level_wspls.items():
        print(f"  {level}: {val:.6f}")

    # Perform bottom-up reconciliation
    reconciled = bottom_up_reconcile(base_forecasts, hierarchy)

    # Compute reconciled WSPL
    recon_wspl, recon_level_wspls = compute_wspl(
        reconciled, actuals, history, weights, hierarchy
    )
    print(f"\nReconciled WSPL: {recon_wspl:.6f}")
    for level, val in recon_level_wspls.items():
        print(f"  {level}: {val:.6f}")
    print(f"\nImprovement: {base_wspl - recon_wspl:.6f}")

    # Save outputs
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    scores = {
        "base_wspl": base_wspl,
        "reconciled_wspl": recon_wspl,
        "level_wspls": recon_level_wspls,
    }
    with open(os.path.join(OUTPUT_DIR, "scores.json"), "w") as f:
        json.dump(scores, f, indent=2)

    save_forecasts_csv(
        reconciled, hierarchy,
        os.path.join(OUTPUT_DIR, "reconciled_forecasts.csv")
    )

    print(f"\nOutputs saved to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
