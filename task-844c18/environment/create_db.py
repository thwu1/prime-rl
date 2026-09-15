#!/usr/bin/env python3
"""Build the capsules.db SQLite database from ground truth data.
This script runs at Docker build time and is then removed."""

import sqlite3
import json

GROUND_TRUTH = [
    {
        "capsule_id": "cap-mc-pi",
        "field": "Computer Science",
        "language": "Python",
        "results": [
            {"estimated_pi": 3.1489, "samples_used": 10000},
            {"estimated_pi": 3.1316, "samples_used": 10000},
            {"estimated_pi": 3.1560, "samples_used": 10000}
        ]
    },
    {
        "capsule_id": "cap-cls-eval",
        "field": "Medical Sciences",
        "language": "Python",
        "results": [
            {"accuracy": 94.5, "precision": 92.3, "recall": 96.7, "classifier": "gradient_boosting"},
            {"accuracy": 94.5, "precision": 92.3, "recall": 96.7, "classifier": "gradient_boosting"},
            {"accuracy": 94.5, "precision": 92.3, "recall": 96.7, "classifier": "gradient_boosting"}
        ]
    },
    {
        "capsule_id": "cap-regress",
        "field": "Social Sciences",
        "language": "R",
        "results": [
            {"r_squared": 0.8734, "intercept": 12.456, "slope": -3.289, "method": "OLS", "significant": "yes"},
            {"r_squared": 0.8734, "intercept": 12.456, "slope": -3.289, "method": "OLS", "significant": "yes"},
            {"r_squared": 0.8734, "intercept": 12.456, "slope": -3.289, "method": "OLS", "significant": "yes"}
        ]
    },
    {
        "capsule_id": "cap-bootstrap",
        "field": "Social Sciences",
        "language": "Python",
        "results": [
            {"mean_estimate": 45.23, "ci_lower": 40.1, "ci_upper": 50.4},
            {"mean_estimate": 43.87, "ci_lower": 38.9, "ci_upper": 48.8},
            {"mean_estimate": 46.59, "ci_lower": 41.3, "ci_upper": 51.9}
        ]
    },
    {
        "capsule_id": "cap-nn-train",
        "field": "Computer Science",
        "language": "Python",
        "results": [
            {"test_accuracy": 87.6, "test_loss": 0.3421, "epochs_run": 50, "fig best_architecture": "ResNet-18"},
            {"test_accuracy": 88.2, "test_loss": 0.3312, "epochs_run": 50, "fig best_architecture": "ResNet-18"},
            {"test_accuracy": 87.1, "test_loss": 0.3534, "epochs_run": 50, "fig best_architecture": "ResNet-18"}
        ]
    },
    {
        "capsule_id": "cap-feature-sel",
        "field": "Medical Sciences",
        "language": "Python",
        "results": [
            {"n_selected": 7, "explained_var": 0.923, "top_features": ["glucose", "bmi", "age", "blood_pressure"]},
            {"n_selected": 7, "explained_var": 0.923, "top_features": ["glucose", "bmi", "age", "blood_pressure"]},
            {"n_selected": 7, "explained_var": 0.923, "top_features": ["glucose", "bmi", "age", "blood_pressure"]}
        ]
    },
    {
        "capsule_id": "cap-cluster",
        "field": "Computer Science",
        "language": "Python",
        "results": [
            {"n_clusters": 4, "silhouette": 0.612, "inertia": 1534.2, "fig cluster_labels": [0, 1, 2, 3, 0, 1]},
            {"n_clusters": 4, "silhouette": 0.598, "inertia": 1589.7, "fig cluster_labels": [0, 1, 2, 3, 0, 1]},
            {"n_clusters": 4, "silhouette": 0.625, "inertia": 1478.3, "fig cluster_labels": [0, 1, 2, 3, 0, 1]}
        ]
    },
    {
        "capsule_id": "cap-meta-analysis",
        "field": "Medical Sciences",
        "language": "R",
        "results": [
            {"fig pooled_effect": 0.342, "fig heterogeneity": "moderate"},
            {"fig pooled_effect": 0.358, "fig heterogeneity": "moderate"},
            {"fig pooled_effect": 0.327, "fig heterogeneity": "moderate"}
        ]
    }
]


def main():
    conn = sqlite3.connect('/app/capsules.db')
    c = conn.cursor()

    c.execute('''CREATE TABLE capsules (
        capsule_id TEXT PRIMARY KEY,
        field TEXT NOT NULL,
        language TEXT NOT NULL
    )''')

    c.execute('''CREATE TABLE runs (
        capsule_id TEXT NOT NULL,
        run_number INTEGER NOT NULL,
        PRIMARY KEY (capsule_id, run_number),
        FOREIGN KEY (capsule_id) REFERENCES capsules(capsule_id)
    )''')

    c.execute('''CREATE TABLE numeric_results (
        capsule_id TEXT NOT NULL,
        run_number INTEGER NOT NULL,
        metric TEXT NOT NULL,
        value REAL NOT NULL,
        PRIMARY KEY (capsule_id, run_number, metric),
        FOREIGN KEY (capsule_id, run_number) REFERENCES runs(capsule_id, run_number)
    )''')

    c.execute('''CREATE TABLE string_results (
        capsule_id TEXT NOT NULL,
        run_number INTEGER NOT NULL,
        metric TEXT NOT NULL,
        value TEXT NOT NULL,
        PRIMARY KEY (capsule_id, run_number, metric),
        FOREIGN KEY (capsule_id, run_number) REFERENCES runs(capsule_id, run_number)
    )''')

    c.execute('''CREATE TABLE list_results (
        capsule_id TEXT NOT NULL,
        run_number INTEGER NOT NULL,
        metric TEXT NOT NULL,
        position INTEGER NOT NULL,
        element TEXT NOT NULL,
        PRIMARY KEY (capsule_id, run_number, metric, position),
        FOREIGN KEY (capsule_id, run_number) REFERENCES runs(capsule_id, run_number)
    )''')

    for capsule in GROUND_TRUTH:
        cid = capsule['capsule_id']
        c.execute('INSERT INTO capsules VALUES (?, ?, ?)',
                  (cid, capsule['field'], capsule['language']))

        for run_num, run in enumerate(capsule['results'], 1):
            c.execute('INSERT INTO runs VALUES (?, ?)', (cid, run_num))
            for key, value in run.items():
                if isinstance(value, (int, float)):
                    c.execute('INSERT INTO numeric_results VALUES (?, ?, ?, ?)',
                              (cid, run_num, key, value))
                elif isinstance(value, str):
                    c.execute('INSERT INTO string_results VALUES (?, ?, ?, ?)',
                              (cid, run_num, key, value))
                elif isinstance(value, list):
                    for pos, elem in enumerate(value):
                        c.execute('INSERT INTO list_results VALUES (?, ?, ?, ?, ?)',
                                  (cid, run_num, key, pos, str(elem)))

    conn.commit()
    conn.close()
    print("Database created at /app/capsules.db")


if __name__ == '__main__':
    import os
    os.makedirs('/app', exist_ok=True)
    main()
