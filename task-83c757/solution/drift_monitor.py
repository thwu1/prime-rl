#!/usr/bin/env python3
"""Drift detection and model lifecycle management pipeline."""

import json
import numpy as np
import pandas as pd
from scipy import stats
from scipy.stats import gaussian_kde
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, f1_score
import mlflow
from mlflow.models import infer_signature

MLFLOW_TRACKING_URI = "sqlite:////app/mlflow.db"
FEATURE_NAMES = ["temperature", "pressure", "vibration", "humidity", "speed", "load_factor"]

KS_PVALUE_THRESHOLD = 0.05
PSI_THRESHOLD = 0.25
KDE_OVERLAP_THRESHOLD = 0.85
PSI_N_BINS = 10
KDE_N_POINTS = 1000
LAPLACE_EPSILON = 1e-4


def compute_ks(ref_vals, prod_vals):
    stat, pval = stats.ks_2samp(ref_vals, prod_vals)
    return float(stat), float(pval)


def compute_psi(ref_vals, prod_vals, n_bins=PSI_N_BINS):
    combined = np.concatenate([ref_vals, prod_vals])
    bins = np.linspace(combined.min(), combined.max(), n_bins + 1)

    ref_counts, _ = np.histogram(ref_vals, bins=bins)
    prod_counts, _ = np.histogram(prod_vals, bins=bins)

    ref_props = ref_counts / len(ref_vals)
    prod_props = prod_counts / len(prod_vals)

    # Laplace smoothing for zero-proportion bins
    ref_props = np.where(ref_props == 0, LAPLACE_EPSILON, ref_props)
    prod_props = np.where(prod_props == 0, LAPLACE_EPSILON, prod_props)

    psi = np.sum((prod_props - ref_props) * np.log(prod_props / ref_props))
    return float(psi)


def compute_kde_overlap(ref_vals, prod_vals, n_points=KDE_N_POINTS):
    combined = np.concatenate([ref_vals, prod_vals])
    combined_std = np.std(combined)
    x_min = combined.min() - 3 * combined_std
    x_max = combined.max() + 3 * combined_std
    x_grid = np.linspace(x_min, x_max, n_points)

    kde_ref = gaussian_kde(ref_vals)
    kde_prod = gaussian_kde(prod_vals)

    ref_density = kde_ref(x_grid)
    prod_density = kde_prod(x_grid)

    overlap = np.trapz(np.minimum(ref_density, prod_density), x_grid)
    return float(min(overlap, 1.0))


def is_feature_drifted(ks_pval, psi, kde_overlap):
    conditions = [
        ks_pval < KS_PVALUE_THRESHOLD,
        psi > PSI_THRESHOLD,
        kde_overlap < KDE_OVERLAP_THRESHOLD,
    ]
    return sum(conditions) >= 2


def determine_action(n_drifted, pred_ks_pval):
    if n_drifted >= 4:
        return "urgent"
    elif n_drifted >= 2:
        return "retrain"
    elif n_drifted == 1 or pred_ks_pval < KS_PVALUE_THRESHOLD:
        return "monitor"
    else:
        return "none"


SEVERITY_MAP = {"none": "low", "monitor": "medium", "retrain": "high", "urgent": "critical"}


def main():
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)

    # ---- Load data ----
    ref_df = pd.read_csv("/app/data/reference.csv")
    prod_df = pd.read_csv("/app/data/production.csv")

    # ---- Load registered model ----
    client = mlflow.tracking.MlflowClient()
    model_versions = client.search_model_versions("name='predictive-maintenance-model'")
    latest_version = max(model_versions, key=lambda v: int(v.version))
    model = mlflow.sklearn.load_model(
        f"models:/predictive-maintenance-model/{latest_version.version}")

    # ---- Per-feature drift ----
    features_report = {}
    drifted_features = []

    for feat in FEATURE_NAMES:
        ref_vals = ref_df[feat].values
        prod_vals = prod_df[feat].values

        ks_stat, ks_pval = compute_ks(ref_vals, prod_vals)
        psi = compute_psi(ref_vals, prod_vals)
        kde_overlap = compute_kde_overlap(ref_vals, prod_vals)
        drifted = is_feature_drifted(ks_pval, psi, kde_overlap)

        features_report[feat] = {
            "ks_statistic": ks_stat,
            "ks_pvalue": ks_pval,
            "psi": psi,
            "kde_overlap": kde_overlap,
            "is_drifted": drifted,
        }
        if drifted:
            drifted_features.append(feat)

    # ---- Prediction drift ----
    ref_probs = model.predict_proba(ref_df[FEATURE_NAMES].values)[:, 1]
    prod_probs = model.predict_proba(prod_df[FEATURE_NAMES].values)[:, 1]
    pred_ks_stat, pred_ks_pval = stats.ks_2samp(ref_probs, prod_probs)

    # ---- Decision ----
    n_drifted = len(drifted_features)
    action = determine_action(n_drifted, float(pred_ks_pval))

    report = {
        "features": features_report,
        "prediction_drift": {
            "ks_statistic": float(pred_ks_stat),
            "ks_pvalue": float(pred_ks_pval),
        },
        "n_drifted_features": n_drifted,
        "drifted_feature_names": sorted(drifted_features),
        "severity": SEVERITY_MAP[action],
        "recommended_action": action,
    }

    with open("/app/drift_report.json", "w") as f:
        json.dump(report, f, indent=2)

    # ---- Log to MLflow ----
    experiment = mlflow.set_experiment("predictive-maintenance")

    with mlflow.start_run(run_name="drift-monitoring") as run:
        for feat in FEATURE_NAMES:
            entry = features_report[feat]
            mlflow.log_metric(f"{feat}_ks_statistic", entry["ks_statistic"])
            mlflow.log_metric(f"{feat}_ks_pvalue", entry["ks_pvalue"])
            mlflow.log_metric(f"{feat}_psi", entry["psi"])
            mlflow.log_metric(f"{feat}_kde_overlap", entry["kde_overlap"])

        mlflow.log_metric("prediction_ks_statistic", float(pred_ks_stat))
        mlflow.log_metric("prediction_ks_pvalue", float(pred_ks_pval))
        mlflow.log_metric("n_drifted_features", n_drifted)
        mlflow.log_param("recommended_action", action)
        mlflow.log_param("severity", SEVERITY_MAP[action])
        mlflow.log_param("drifted_features", ",".join(sorted(drifted_features)))
        mlflow.log_artifact("/app/drift_report.json")

    # ---- Retrain if needed ----
    if action in ("retrain", "urgent"):
        X_prod = prod_df[FEATURE_NAMES].values
        y_prod = prod_df["target"].values
        X_train, X_val, y_train, y_val = train_test_split(
            X_prod, y_prod, test_size=0.2, random_state=42)

        with mlflow.start_run(run_name="drift-retrain") as retrain_run:
            new_model = RandomForestClassifier(
                n_estimators=100, max_depth=10, random_state=42)
            new_model.fit(X_train, y_train)

            y_pred = new_model.predict(X_val)
            mlflow.log_params({
                "n_estimators": 100, "max_depth": 10, "random_state": 42,
                "retrain_reason": "drift_detected",
            })
            mlflow.log_metrics({
                "accuracy": accuracy_score(y_val, y_pred),
                "f1_score": f1_score(y_val, y_pred),
            })

            signature = infer_signature(X_train, new_model.predict(X_train))
            mlflow.sklearn.log_model(new_model, "model", signature=signature)

            model_uri = f"runs:/{retrain_run.info.run_id}/model"
            mv = mlflow.register_model(model_uri, "predictive-maintenance-model")
            client.set_model_version_tag(
                "predictive-maintenance-model", mv.version,
                "retrained_reason", "drift_detected")

    print(f"Drift report: /app/drift_report.json")
    print(f"Drifted features ({n_drifted}): {', '.join(sorted(drifted_features))}")
    print(f"Action: {action}")


if __name__ == "__main__":
    main()
