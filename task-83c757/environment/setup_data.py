#!/usr/bin/env python3
"""Generate reference/production datasets, train initial MLflow model, and create alert logs."""
import os
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score
import mlflow
from mlflow.models import infer_signature

os.makedirs("/app/data", exist_ok=True)
os.makedirs("/app/config", exist_ok=True)
os.makedirs("/app/logs", exist_ok=True)
mlflow.set_tracking_uri("sqlite:////app/mlflow.db")

FEATURE_NAMES = ["temperature", "pressure", "vibration", "humidity", "speed", "load_factor"]


def generate_target(X, seed):
    rng = np.random.RandomState(seed)
    z = (0.3 * (X[:, 0] - 70) / 5 +
         0.1 * (X[:, 1] - 30) / 3 +
         0.25 * (X[:, 2] - 0.5) / 0.1 +
         0.05 * (X[:, 3] - 45) / 8 +
         0.2 * (X[:, 4] - 1500) / 100 +
         0.1 * (X[:, 5] - 0.6) / 0.17)
    prob = 1 / (1 + np.exp(-z))
    noise = rng.uniform(0, 1, size=len(X))
    return (noise < prob).astype(int)


def generate_data(n, seed, temp_mean=70, temp_std=5, vib_mean=0.5, vib_std=0.1,
                  speed_mean=1500, speed_std=100):
    rng = np.random.RandomState(seed)
    X = np.column_stack([
        rng.normal(temp_mean, temp_std, n),
        rng.normal(30, 3, n),
        rng.normal(vib_mean, vib_std, n),
        rng.normal(45, 8, n),
        rng.normal(speed_mean, speed_std, n),
        rng.uniform(0.3, 0.9, n),
    ])
    target = generate_target(X, seed + 100)
    df = pd.DataFrame(X, columns=FEATURE_NAMES)
    df["target"] = target
    return df


# Reference data (training distribution)
ref_df = generate_data(1000, seed=42)

# Production data (drift in temperature mean +8, vibration std x2.5, speed mean +150)
prod_df = generate_data(1000, seed=43, temp_mean=78, vib_std=0.25, speed_mean=1650)

ref_df.to_csv("/app/data/reference.csv", index=False)
prod_df.to_csv("/app/data/production.csv", index=False)

# -----------------------------------------------------------------
# Red herring: a second experiment for a different use case
# -----------------------------------------------------------------
qa_experiment = mlflow.set_experiment("endpoint-health-metrics")
with mlflow.start_run(run_name="weekly-sla-check",
                      experiment_id=qa_experiment.experiment_id):
    mlflow.log_metrics({
        "latency_p99_ms": 45.2, "throughput_rps": 120.0,
        "error_rate": 0.002, "availability_pct": 99.97
    })
    mlflow.log_params({"evaluation_window": "7d", "endpoint": "prod-v1"})

# -----------------------------------------------------------------
# Red herring: a second registered model (different task)
# -----------------------------------------------------------------
rh_experiment = mlflow.set_experiment("sensor-fault-classification")
with mlflow.start_run(run_name="baseline-gbm",
                      experiment_id=rh_experiment.experiment_id) as rh_run:
    rh_model = GradientBoostingClassifier(n_estimators=50, random_state=99)
    rh_model.fit(ref_df[FEATURE_NAMES[:4]].values, ref_df["target"].values)
    mlflow.sklearn.log_model(rh_model, "model")
    mlflow.register_model(
        f"runs:/{rh_run.info.run_id}/model", "sensor-fault-classifier")

# -----------------------------------------------------------------
# Main experiment: train and register initial predictive-maintenance model
# -----------------------------------------------------------------
experiment = mlflow.set_experiment("predictive-maintenance")
X = ref_df[FEATURE_NAMES].values
y = ref_df["target"].values
X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, random_state=42)

with mlflow.start_run(run_name="initial-training") as run:
    model = RandomForestClassifier(n_estimators=100, max_depth=10, random_state=42)
    model.fit(X_train, y_train)
    y_pred = model.predict(X_val)

    train_acc = accuracy_score(y_val, y_pred)
    train_f1 = f1_score(y_val, y_pred)

    mlflow.log_params({"n_estimators": 100, "max_depth": 10, "random_state": 42})
    mlflow.log_metrics({
        "accuracy": train_acc,
        "f1_score": train_f1,
        "precision": precision_score(y_val, y_pred),
        "recall": recall_score(y_val, y_pred),
    })

    signature = infer_signature(X_train, model.predict(X_train))
    mlflow.sklearn.log_model(model, "model", signature=signature)
    mlflow.register_model(f"runs:/{run.info.run_id}/model", "predictive-maintenance-model")

# Simulate production performance degradation by scoring production data
prod_pred = model.predict(prod_df[FEATURE_NAMES].values)
prod_acc = accuracy_score(prod_df["target"].values, prod_pred)
prod_f1 = f1_score(prod_df["target"].values, prod_pred)

# Generate performance alert logs (ambiguous — don't name root cause)
alert_log = f"""[2026-04-15 10:00:00] INFO  System health check passed: all endpoints nominal
[2026-04-20 10:00:00] INFO  Model endpoint latency p99=42ms — within SLA
[2026-05-01 08:00:00] INFO  Model predictive-maintenance-model v1 deployed to production endpoint
[2026-05-01 08:00:01] INFO  Post-deployment validation: accuracy={train_acc:.2f} f1={train_f1:.2f}
[2026-05-08 12:00:00] INFO  Weekly eval batch 1: accuracy=0.80 f1=0.77 — within tolerance
[2026-05-10 06:30:00] INFO  Upstream sensor firmware updated to v3.2 across plant floor
[2026-05-15 12:00:00] WARN  Weekly eval batch 2: accuracy=0.76 f1=0.72 — below deployment threshold (accuracy >= 0.78)
[2026-05-15 12:00:05] INFO  Ingestion pipeline: 14,200 records/day (normal volume)
[2026-05-22 12:00:00] WARN  Weekly eval batch 3: accuracy=0.73 f1=0.68 — continued decline
[2026-05-22 12:00:05] INFO  No infrastructure incidents or schema changes detected
[2026-05-29 12:00:00] ALERT Production accuracy={prod_acc:.2f} f1={prod_f1:.2f} — significant quality decline
[2026-05-29 12:00:05] ALERT Hypothesis: upstream sensor calibration changes may have affected input characteristics
[2026-05-29 12:00:10] ALERT Action required: investigate root cause per operational monitoring contract in /app/config/
"""

with open("/app/logs/performance_alerts.log", "w") as f:
    f.write(alert_log)

print("Setup complete.")
