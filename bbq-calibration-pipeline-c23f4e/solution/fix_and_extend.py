#!/usr/bin/env python3
"""
Fix all bugs across Python, SQL, Makefile, shell/jq, and extend the
calibration pipeline with BBQ and Brier score.

"""
import json

# ============================================================
# Fix 1: lib/metrics.py
# Bug: compute_ece uses unweighted average (ACE formula) instead
# of sample-count-weighted average. Also add compute_brier.
# ============================================================
METRICS_CODE = '''\
"""Calibration metrics: ECE, MCE, ACE, Brier."""
import numpy as np


def _bin_data(confidences, correctness, n_bins):
    confidences = np.asarray(confidences, dtype=np.float64).ravel()
    correctness = np.asarray(correctness, dtype=np.float64).ravel()
    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    bin_accs, bin_confs, bin_counts = [], [], []
    n_total = len(confidences)
    for b in range(n_bins):
        if b < n_bins - 1:
            mask = (confidences >= bin_edges[b]) & (confidences < bin_edges[b + 1])
        else:
            mask = (confidences >= bin_edges[b]) & (confidences <= bin_edges[b + 1])
        n_b = int(np.sum(mask))
        if n_b > 0:
            bin_accs.append(float(np.mean(correctness[mask])))
            bin_confs.append(float(np.mean(confidences[mask])))
            bin_counts.append(n_b)
    return bin_accs, bin_confs, bin_counts, n_total


def compute_ece(confidences, correctness, n_bins=10):
    """Expected Calibration Error: sample-weighted average of per-bin gaps."""
    bin_accs, bin_confs, bin_counts, n_total = _bin_data(
        confidences, correctness, n_bins
    )
    if n_total == 0:
        return 0.0
    ece = sum(
        (count / n_total) * abs(acc - conf)
        for acc, conf, count in zip(bin_accs, bin_confs, bin_counts)
    )
    return float(ece)


def compute_mce(confidences, correctness, n_bins=10):
    """Maximum Calibration Error."""
    bin_accs, bin_confs, _, _ = _bin_data(confidences, correctness, n_bins)
    if not bin_accs:
        return 0.0
    return float(max(abs(a - c) for a, c in zip(bin_accs, bin_confs)))


def compute_ace(confidences, correctness, n_bins=10):
    """Average Calibration Error: unweighted average of per-bin gaps."""
    bin_accs, bin_confs, _, _ = _bin_data(confidences, correctness, n_bins)
    if not bin_accs:
        return 0.0
    gaps = [abs(a - c) for a, c in zip(bin_accs, bin_confs)]
    return float(np.mean(gaps))


def compute_brier(confidences, correctness, n_bins=10):
    """Top-class Brier score: mean squared error of confidence vs correctness."""
    confidences = np.asarray(confidences, dtype=np.float64).ravel()
    correctness = np.asarray(correctness, dtype=np.float64).ravel()
    return float(np.mean((confidences - correctness) ** 2))
'''

# ============================================================
# Fix 2: lib/binning.py
# Bug: transform() missing "- 1" after np.digitize
# ============================================================
BINNING_CODE = '''\
"""Histogram Binning calibration method."""
import numpy as np


class HistogramBinning:
    def __init__(self, n_bins=10):
        self.n_bins = n_bins
        self.bin_edges = None
        self.bin_values = None

    def fit(self, confidences, correctness):
        confidences = np.asarray(confidences, dtype=np.float64).ravel()
        correctness = np.asarray(correctness, dtype=np.float64).ravel()
        self.bin_edges = np.linspace(0.0, 1.0, self.n_bins + 1)
        indices = np.digitize(confidences, self.bin_edges, right=False) - 1
        indices = np.clip(indices, 0, self.n_bins - 1)
        self.bin_values = np.full(self.n_bins, np.nan)
        for b in range(self.n_bins):
            mask = indices == b
            if np.sum(mask) > 0:
                self.bin_values[b] = np.mean(correctness[mask])
            else:
                self.bin_values[b] = (self.bin_edges[b] + self.bin_edges[b + 1]) / 2.0
        return self

    def transform(self, confidences):
        confidences = np.asarray(confidences, dtype=np.float64).ravel()
        indices = np.digitize(confidences, self.bin_edges, right=False) - 1
        indices = np.clip(indices, 0, self.n_bins - 1)
        return np.clip(self.bin_values[indices], 0.0, 1.0)
'''

# ============================================================
# Fix 3: lib/scaling.py
# Bug: minimize_scalar called with -nll(T), double-negating
# ============================================================
SCALING_CODE = '''\
"""Temperature Scaling calibration method."""
import numpy as np
from scipy.optimize import minimize_scalar


class TemperatureScaling:
    def __init__(self):
        self.temperature = 1.0

    @staticmethod
    def _softmax(logits):
        shifted = logits - np.max(logits, axis=1, keepdims=True)
        exp_vals = np.exp(shifted)
        return exp_vals / np.sum(exp_vals, axis=1, keepdims=True)

    def fit(self, logits, labels, n_classes):
        def nll(T):
            scaled_probs = self._softmax(logits / T)
            scaled_probs = np.clip(scaled_probs, 1e-15, 1 - 1e-15)
            log_probs = np.log(scaled_probs[np.arange(len(labels)), labels])
            return float(-np.mean(log_probs))

        result = minimize_scalar(
            nll,
            bounds=(0.1, 10.0),
            method='bounded',
        )
        self.temperature = float(result.x)
        return self

    def transform(self, logits, n_classes):
        return self._softmax(logits / self.temperature)
'''

# ============================================================
# Extension: lib/bbq.py - Bayesian Binning into Quantiles
# ============================================================
BBQ_CODE = '''\
"""Bayesian Binning into Quantiles (BBQ) calibration."""
import numpy as np
from lib.binning import HistogramBinning


class BBQ:
    def __init__(self, score_function='bic'):
        self.score_function = score_function.lower()
        self._models = []
        self._weights = []

    def fit(self, confidences, correctness):
        confidences = np.asarray(confidences, dtype=np.float64).ravel()
        correctness = np.asarray(correctness, dtype=np.float64).ravel()
        n = len(confidences)

        n_root = n ** (1.0 / 3.0)
        min_bins = int(max(1, np.floor(n_root / 10.0)))
        max_bins = int(min(np.ceil(n / 5.0), np.ceil(n_root * 10.0)))
        if max_bins < min_bins:
            max_bins = min_bins

        models = []
        for b in range(min_bins, max_bins + 1):
            hb = HistogramBinning(n_bins=b)
            hb.fit(confidences, correctness)
            models.append(hb)

        ic_scores = self._compute_scores(confidences, correctness, models)
        posteriors = np.exp((np.min(ic_scores) - ic_scores) / 2.0)
        self._weights, self._models = self._select_models(models, posteriors)
        return self

    def _compute_scores(self, confidences, correctness, models):
        n = len(confidences)
        scores = np.zeros(len(models))
        for i, model in enumerate(models):
            preds = model.transform(confidences)
            eps = np.finfo(np.float64).eps
            preds = np.clip(preds, eps, 1.0 - eps)
            ll = np.sum(
                correctness * np.log(preds)
                + (1.0 - correctness) * np.log(1.0 - preds)
            )
            k = model.n_bins
            if self.score_function == 'bic':
                scores[i] = -2.0 * ll + k * np.log(n)
            else:
                scores[i] = -2.0 * ll + 2.0 * k
        return scores

    def _select_models(self, models, posteriors, alpha=0.001):
        n = len(posteriors)
        variance = np.var(posteriors)
        sorted_idx = np.argsort(posteriors)[::-1]
        sorted_scores = posteriors[sorted_idx]

        k = 0
        while k < n - 1 and sorted_scores[k] == sorted_scores[k + 1]:
            k += 1
        if variance > 0:
            while (
                k < n - 1
                and (sorted_scores[k] - sorted_scores[k + 1]) / variance > alpha
            ):
                k += 1
        k += 1

        kept = [models[sorted_idx[i]] for i in range(k)]
        weights = np.array([posteriors[sorted_idx[i]] for i in range(k)])
        weights = weights / np.sum(weights)
        return weights.tolist(), kept

    def transform(self, confidences):
        confidences = np.asarray(confidences, dtype=np.float64).ravel()
        result = np.zeros_like(confidences)
        for w, m in zip(self._weights, self._models):
            result += w * m.transform(confidences)
        return np.clip(result, 0.0, 1.0)

    @property
    def num_models_selected(self):
        return len(self._models)

    @property
    def model_weights(self):
        return list(self._weights)
'''

# ============================================================
# Fix 4+5: pipeline.py
# Bugs: SQL query uses 'logit_value' instead of 'logit',
#        missing BBQ and Brier handlers
# ============================================================
PIPELINE_CODE = '''\
#!/usr/bin/env python3
"""Calibration evaluation pipeline. Reads data from SQLite."""
import json
import os
import sys
import sqlite3
import subprocess
import numpy as np


def softmax(logits):
    shifted = logits - np.max(logits, axis=1, keepdims=True)
    exp_vals = np.exp(shifted)
    return exp_vals / np.sum(exp_vals, axis=1, keepdims=True)


def load_from_sqlite(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("SELECT value FROM metadata WHERE key = 'n_classes'")
    n_classes = int(cur.fetchone()[0])
    cur.execute("SELECT value FROM metadata WHERE key = 'n_train'")
    n_train = int(cur.fetchone()[0])
    cur.execute("SELECT value FROM metadata WHERE key = 'n_test'")
    n_test = int(cur.fetchone()[0])

    cur.execute("""
        SELECT sample_id, class_id, logit
        FROM train_logits
        ORDER BY sample_id, class_id
    """)
    rows = cur.fetchall()
    logits_train = np.zeros((n_train, n_classes))
    for sid, cid, val in rows:
        logits_train[sid, cid] = val

    cur.execute("SELECT sample_id, label FROM train_labels ORDER BY sample_id")
    labels_train = np.array([r[1] for r in cur.fetchall()], dtype=np.int64)

    cur.execute("""
        SELECT sample_id, class_id, logit
        FROM test_logits
        ORDER BY sample_id, class_id
    """)
    rows = cur.fetchall()
    logits_test = np.zeros((n_test, n_classes))
    for sid, cid, val in rows:
        logits_test[sid, cid] = val

    cur.execute("SELECT sample_id, label FROM test_labels ORDER BY sample_id")
    labels_test = np.array([r[1] for r in cur.fetchall()], dtype=np.int64)

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

    logits_train, labels_train, logits_test, labels_test, n_classes = \\
        load_from_sqlite(db_path)

    probs_train = softmax(logits_train)
    probs_test = softmax(logits_test)

    conf_train = np.max(probs_train, axis=1)
    conf_test = np.max(probs_test, axis=1)
    correct_train = (np.argmax(probs_train, axis=1) == labels_train).astype(np.float64)
    correct_test = (np.argmax(probs_test, axis=1) == labels_test).astype(np.float64)

    from lib.metrics import compute_ece, compute_mce, compute_ace, compute_brier

    metric_fns = {
        'ece': lambda c, r: compute_ece(c, r, n_bins),
        'mce': lambda c, r: compute_mce(c, r, n_bins),
        'ace': lambda c, r: compute_ace(c, r, n_bins),
        'brier': lambda c, r: compute_brier(c, r, n_bins),
    }

    def eval_metrics(confidences, correctness):
        return {m: metric_fns[m](confidences, correctness)
                for m in metrics_list if m in metric_fns}

    results = {}
    results['uncalibrated'] = eval_metrics(conf_test, correct_test)

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

        elif method == 'bbq':
            from lib.bbq import BBQ
            bbq = BBQ(score_function='bic')
            bbq.fit(conf_train, correct_train)
            cal_conf = bbq.transform(conf_test)
            entry = eval_metrics(cal_conf, correct_test)
            entry['calibrated_confidences'] = cal_conf.tolist()
            entry['num_models_selected'] = bbq.num_models_selected
            entry['model_weights'] = bbq.model_weights
            results['bbq'] = entry

    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"Results written to {output_path}")


if __name__ == '__main__':
    main()
'''

# ============================================================
# Fix 6: Makefile - calibrate target missing 'data' dependency
# ============================================================
MAKEFILE_CODE = """\
.PHONY: all data calibrate validate report clean

all: validate report

data:
\tpython3 /app/generate_data.py

calibrate: data
\tpython3 /app/pipeline.py

validate: calibrate
\tbash /app/validate.sh /app/results.json

report: validate
\tpython3 /app/report.py

clean:
\trm -f /app/data/predictions.npz /app/calibration.db /app/results.json /app/report.txt
"""

# ============================================================
# Fix 7: validate.sh - 'temp_scaling' should be 'temperature_scaling'
# ============================================================
VALIDATE_CODE = '''\
#!/bin/bash
# Validate results.json schema using jq
set -u

RESULTS="${1:-/app/results.json}"

if [ ! -f "$RESULTS" ]; then
    echo "FAIL: results.json not found" >&2
    exit 1
fi

for method in uncalibrated histogram_binning temperature_scaling bbq; do
    if ! jq -e ".\\"$method\\"" "$RESULTS" > /dev/null 2>&1; then
        echo "FAIL: missing method '$method'" >&2
        exit 1
    fi
done

for method in $(jq -r 'keys[]' "$RESULTS"); do
    for metric in ece mce ace brier; do
        VAL=$(jq -r ".\\"$method\\".\\"$metric\\"" "$RESULTS" 2>/dev/null)
        if [ "$VAL" = "null" ] || [ -z "$VAL" ]; then
            echo "FAIL: ${method}.${metric} missing or null" >&2
            exit 1
        fi
    done
done

for method in histogram_binning temperature_scaling bbq; do
    LEN=$(jq ".\\"$method\\".calibrated_confidences | length" "$RESULTS" 2>/dev/null)
    if [ -z "$LEN" ] || [ "$LEN" = "null" ] || [ "$LEN" -le 0 ] 2>/dev/null; then
        echo "FAIL: ${method}.calibrated_confidences empty or missing" >&2
        exit 1
    fi
    BAD=$(jq "[.\\"$method\\".calibrated_confidences[] | select(. < 0 or . > 1)] | length" "$RESULTS" 2>/dev/null)
    if [ -n "$BAD" ] && [ "$BAD" -gt 0 ] 2>/dev/null; then
        echo "FAIL: ${method} has confidences outside [0,1]" >&2
        exit 1
    fi
done

N_MODELS=$(jq '.bbq.num_models_selected' "$RESULTS" 2>/dev/null)
if [ "$N_MODELS" = "null" ] || [ -z "$N_MODELS" ]; then
    echo "FAIL: bbq.num_models_selected missing" >&2
    exit 1
fi

WSUM=$(jq '.bbq.model_weights | add' "$RESULTS" 2>/dev/null)
VALID=$(jq -n "$WSUM > 0.999 and $WSUM < 1.001")
if [ "$VALID" != "true" ]; then
    echo "FAIL: bbq.model_weights sum=$WSUM, expected ~1.0" >&2
    exit 1
fi

N_WEIGHTS=$(jq '.bbq.model_weights | length' "$RESULTS" 2>/dev/null)
if [ "$N_WEIGHTS" != "$N_MODELS" ]; then
    echo "FAIL: model_weights length != num_models_selected" >&2
    exit 1
fi

OT=$(jq '.temperature_scaling.optimal_temperature' "$RESULTS" 2>/dev/null)
if [ "$OT" = "null" ] || [ -z "$OT" ]; then
    echo "FAIL: temperature_scaling.optimal_temperature missing" >&2
    exit 1
fi

echo "PASS: schema validation complete"
exit 0
'''

# ============================================================
# Fix 8: report.py - column name mismatch (metric_name vs metric)
# ============================================================
REPORT_CODE = '''\
#!/usr/bin/env python3
"""Insert results into SQLite and generate report."""
import json
import sqlite3


def main():
    with open('/app/results.json') as f:
        results = json.load(f)

    conn = sqlite3.connect('/app/calibration.db')
    cur = conn.cursor()

    cur.execute(\'\'\'CREATE TABLE IF NOT EXISTS results (
        method TEXT,
        metric TEXT,
        value REAL,
        PRIMARY KEY (method, metric)
    )\'\'\')

    for method, metrics in results.items():
        for key, val in metrics.items():
            if isinstance(val, (int, float)):
                cur.execute(
                    'INSERT OR REPLACE INTO results (method, metric, value) '
                    'VALUES (?, ?, ?)',
                    (method, key, float(val))
                )

    conn.commit()

    cur.execute('SELECT method, metric, value FROM results ORDER BY method, metric')
    rows = cur.fetchall()

    with open('/app/report.txt', 'w') as f:
        f.write("method\\tmetric\\tvalue\\n")
        for row in rows:
            f.write(f"{row[0]}\\t{row[1]}\\t{row[2]:.8f}\\n")

    conn.close()
    print(f"Report: {len(rows)} rows written to /app/report.txt")


if __name__ == '__main__':
    main()
'''

# ============================================================
# Updated config.json
# ============================================================
CONFIG = {
    "db_path": "/app/calibration.db",
    "output_path": "/app/results.json",
    "n_bins": 10,
    "methods": ["histogram_binning", "temperature_scaling", "bbq"],
    "metrics": ["ece", "mce", "ace", "brier"],
}


def main():
    # Write fixed Python files
    with open('/app/lib/metrics.py', 'w') as f:
        f.write(METRICS_CODE)

    with open('/app/lib/binning.py', 'w') as f:
        f.write(BINNING_CODE)

    with open('/app/lib/scaling.py', 'w') as f:
        f.write(SCALING_CODE)

    with open('/app/lib/bbq.py', 'w') as f:
        f.write(BBQ_CODE)

    with open('/app/pipeline.py', 'w') as f:
        f.write(PIPELINE_CODE)

    # Fix Makefile
    with open('/app/Makefile', 'w') as f:
        f.write(MAKEFILE_CODE)

    # Fix validate.sh
    with open('/app/validate.sh', 'w') as f:
        f.write(VALIDATE_CODE)

    # Fix report.py
    with open('/app/report.py', 'w') as f:
        f.write(REPORT_CODE)

    # Update config
    with open('/app/config.json', 'w') as f:
        json.dump(CONFIG, f, indent=2)

    print("Pipeline fixed and extended.")


if __name__ == '__main__':
    main()
