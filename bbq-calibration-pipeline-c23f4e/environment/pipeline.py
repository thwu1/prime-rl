#!/usr/bin/env python3
"""
Calibration evaluation pipeline.

Reads prediction data from SQLite, applies calibration methods,
computes calibration metrics, and writes results to JSON.

"""
import json
import os
import sys
import sqlite3
import subprocess
import numpy as np


def softmax(logits):
    """Numerically stable softmax along class dimension."""
    shifted = logits - np.max(logits, axis=1, keepdims=True)
    exp_vals = np.exp(shifted)
    return exp_vals / np.sum(exp_vals, axis=1, keepdims=True)


def load_from_sqlite(db_path):
    """Load prediction data from SQLite database."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("SELECT value FROM metadata WHERE key = 'n_classes'")
    n_classes = int(cur.fetchone()[0])
    cur.execute("SELECT value FROM metadata WHERE key = 'n_train'")
    n_train = int(cur.fetchone()[0])
    cur.execute("SELECT value FROM metadata WHERE key = 'n_test'")
    n_test = int(cur.fetchone()[0])

    # Load train logits
    cur.execute("""
        SELECT sample_id, class_id, logit_value
        FROM train_logits
        ORDER BY sample_id, class_id
    """)
    rows = cur.fetchall()
    logits_train = np.zeros((n_train, n_classes))
    for sid, cid, val in rows:
        logits_train[sid, cid] = val

    # Load train labels
    cur.execute("SELECT sample_id, label FROM train_labels ORDER BY sample_id")
    rows = cur.fetchall()
    labels_train = np.array([r[1] for r in rows], dtype=np.int64)

    # Load test logits
    cur.execute("""
        SELECT sample_id, class_id, logit_value
        FROM test_logits
        ORDER BY sample_id, class_id
    """)
    rows = cur.fetchall()
    logits_test = np.zeros((n_test, n_classes))
    for sid, cid, val in rows:
        logits_test[sid, cid] = val

    # Load test labels
    cur.execute("SELECT sample_id, label FROM test_labels ORDER BY sample_id")
    rows = cur.fetchall()
    labels_test = np.array([r[1] for r in rows], dtype=np.int64)

    conn.close()
    return logits_train, labels_train, logits_test, labels_test, n_classes


def main():
    with open('/app/config.json') as f:
        config = json.load(f)

    db_path = config['db_path']
    output_path = config['output_path']
    n_bins = config['n_bins']
    methods = config['methods']
    metrics_list = config['metrics']

    logits_train, labels_train, logits_test, labels_test, n_classes = \
        load_from_sqlite(db_path)

    # Compute probability estimates via softmax
    probs_train = softmax(logits_train)
    probs_test = softmax(logits_test)

    # Extract top-class confidence and correctness
    conf_train = np.max(probs_train, axis=1)
    conf_test = np.max(probs_test, axis=1)
    correct_train = (np.argmax(probs_train, axis=1) == labels_train).astype(np.float64)
    correct_test = (np.argmax(probs_test, axis=1) == labels_test).astype(np.float64)

    # Build metric function map from available functions in lib.metrics
    from lib.metrics import compute_ece, compute_mce, compute_ace

    metric_fns = {
        'ece': lambda c, r: compute_ece(c, r, n_bins),
        'mce': lambda c, r: compute_mce(c, r, n_bins),
        'ace': lambda c, r: compute_ace(c, r, n_bins),
    }

    def eval_metrics(confidences, correctness):
        return {m: metric_fns[m](confidences, correctness)
                for m in metrics_list if m in metric_fns}

    results = {}

    # Uncalibrated metrics
    results['uncalibrated'] = eval_metrics(conf_test, correct_test)

    # Calibration methods
    for method in methods:
        if method == 'histogram_binning':
            from lib.binning import HistogramBinning
            hb = HistogramBinning(n_bins=n_bins)
            hb.fit(conf_train, correct_train)
            cal_conf = hb.transform(conf_test)
            entry = eval_metrics(cal_conf, correct_test)
            entry['calibrated_confidences'] = cal_conf.tolist()
            results['histogram_binning'] = entry

        elif method == 'temperature_scaling':
            from lib.scaling import TemperatureScaling
            ts = TemperatureScaling()
            ts.fit(logits_train, labels_train, n_classes)
            cal_probs = ts.transform(logits_test, n_classes)
            cal_conf = np.max(cal_probs, axis=1)
            entry = eval_metrics(cal_conf, correct_test)
            entry['optimal_temperature'] = float(ts.temperature)
            entry['calibrated_confidences'] = cal_conf.tolist()
            results['temperature_scaling'] = entry

    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"Results written to {output_path}")


if __name__ == '__main__':
    main()
