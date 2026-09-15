#!/usr/bin/env python3
"""Set up the task environment: generate datasets and create baseline model."""
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import f1_score, precision_score, recall_score
import mlflow
import mlflow.sklearn
import os

# Generate reference data
np.random.seed(42)
n = 1000

ref_data = pd.DataFrame({
    'temperature': np.random.normal(70, 5, n),
    'pressure': np.random.normal(30, 3, n),
    'vibration': np.random.normal(0.5, 0.1, n),
    'humidity': np.random.normal(45, 8, n),
    'speed': np.random.normal(1500, 200, n),
    'group': np.random.choice(['A', 'B'], n),
})

logits = (
    0.05 * (ref_data['temperature'] - 70) +
    0.03 * (ref_data['pressure'] - 30) +
    2.0 * (ref_data['vibration'] - 0.5) +
    0.01 * (ref_data['humidity'] - 45) +
    0.001 * (ref_data['speed'] - 1500) +
    np.random.normal(0, 0.5, n)
)
ref_data['failure'] = (logits > 0).astype(int)

# Generate production data (with drift in temperature and vibration)
np.random.seed(123)
prod_data = pd.DataFrame({
    'temperature': np.random.normal(80, 7, n),
    'pressure': np.random.normal(30, 3, n),
    'vibration': np.random.normal(0.7, 0.15, n),
    'humidity': np.random.normal(45, 8, n),
    'speed': np.random.normal(1510, 200, n),
    'group': np.random.choice(['A', 'B'], n),
})

logits_prod = (
    0.05 * (prod_data['temperature'] - 70) +
    0.03 * (prod_data['pressure'] - 30) +
    2.0 * (prod_data['vibration'] - 0.5) +
    0.01 * (prod_data['humidity'] - 45) +
    0.001 * (prod_data['speed'] - 1500) +
    np.random.normal(0, 0.5, n)
)
prod_data['failure'] = (logits_prod > 0).astype(int)

os.makedirs('/app/data', exist_ok=True)
ref_data.to_csv('/app/data/reference.csv', index=False)
prod_data.to_csv('/app/data/production.csv', index=False)

# Train and log baseline model
feature_cols = ['temperature', 'pressure', 'vibration', 'humidity', 'speed']
X = ref_data[feature_cols]
y = ref_data['failure']

mlflow.set_tracking_uri('file:///app/mlruns')
mlflow.set_experiment('predictive_maintenance')

with mlflow.start_run(run_name='baseline_model') as run:
    model = RandomForestClassifier(n_estimators=50, max_depth=5, random_state=42)
    model.fit(X, y)

    mlflow.log_param('n_estimators', 50)
    mlflow.log_param('max_depth', 5)
    mlflow.log_param('model_type', 'RandomForestClassifier')

    y_pred = model.predict(X)
    mlflow.log_metric('f1_score', float(f1_score(y, y_pred)))
    mlflow.log_metric('precision', float(precision_score(y, y_pred)))
    mlflow.log_metric('recall', float(recall_score(y, y_pred)))

    mlflow.sklearn.log_model(model, 'model')
    model_uri = f'runs:/{run.info.run_id}/model'
    mlflow.register_model(model_uri, 'predictive_maintenance_model')

with open('/app/baseline_run_id.txt', 'w') as f:
    f.write(run.info.run_id)

print(f"Setup complete. Baseline run ID: {run.info.run_id}")
