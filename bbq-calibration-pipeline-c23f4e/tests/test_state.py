"""
Tests for calibration pipeline: correctness, SQLite storage, report, validation.

Reference values are computed at test time from the same deterministic seed —
no pre-computed expected values are stored anywhere.

"""
import json
import os
import sqlite3
import subprocess

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Reference implementation — independent of the pipeline under test
# ---------------------------------------------------------------------------

def _generate_ref():
    """Reproduce data from generate_data.py using same seed."""
    rng = np.random.RandomState(2024)

    def _mk(rng, n, nc):
        tp = rng.dirichlet(np.ones(nc) * 0.8, size=n)
        lb = np.array([rng.choice(nc, p=p) for p in tp])
        rl = np.log(np.clip(tp, 1e-10, None))
        ns = rng.normal(0, 0.3, size=rl.shape)
        return (rl + ns) * 2.0, lb

    lt, lbt = _mk(rng, 1500, 5)
    le, lbe = _mk(rng, 600, 5)
    return lt, lbt, le, lbe, 5


def _sm(logits):
    s = logits - np.max(logits, axis=1, keepdims=True)
    e = np.exp(s)
    return e / np.sum(e, axis=1, keepdims=True)


def _bindata(c, r, nb):
    edges = np.linspace(0, 1, nb + 1)
    a, co, cn = [], [], []
    for b in range(nb):
        m = ((c >= edges[b]) & (c < edges[b + 1])) if b < nb - 1 \
            else ((c >= edges[b]) & (c <= edges[b + 1]))
        n = int(np.sum(m))
        if n > 0:
            a.append(float(np.mean(r[m])))
            co.append(float(np.mean(c[m])))
            cn.append(n)
    return a, co, cn, len(c)


def _ece(c, r, nb=10):
    a, co, cn, t = _bindata(c, r, nb)
    return sum((n / t) * abs(ac - cc) for ac, cc, n in zip(a, co, cn)) if t else 0.0


def _mce(c, r, nb=10):
    a, co, _, _ = _bindata(c, r, nb)
    return max(abs(ac - cc) for ac, cc in zip(a, co)) if a else 0.0


def _ace(c, r, nb=10):
    a, co, _, _ = _bindata(c, r, nb)
    return float(np.mean([abs(ac - cc) for ac, cc in zip(a, co)])) if a else 0.0


def _brier(c, r):
    return float(np.mean(
        (np.asarray(c, dtype=np.float64) - np.asarray(r, dtype=np.float64)) ** 2
    ))


def _hb_transform(ct, rt, ce, nb):
    edges = np.linspace(0, 1, nb + 1)
    ix = np.clip(np.digitize(ct, edges, right=False) - 1, 0, nb - 1)
    vals = np.full(nb, np.nan)
    for b in range(nb):
        m = ix == b
        vals[b] = np.mean(rt[m]) if np.sum(m) > 0 else (edges[b] + edges[b + 1]) / 2
    tix = np.clip(np.digitize(ce, edges, right=False) - 1, 0, nb - 1)
    return np.clip(vals[tix], 0, 1)


def _temp_opt(logits, labels):
    from scipy.optimize import minimize_scalar

    def nll(T):
        sp = np.clip(_sm(logits / T), 1e-15, 1 - 1e-15)
        return -np.mean(np.log(sp[np.arange(len(labels)), labels]))

    return minimize_scalar(nll, bounds=(0.1, 10.0), method='bounded').x


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

RESULTS_PATH = '/app/results.json'
CONFIG_PATH = '/app/config.json'
DB_PATH = '/app/calibration.db'
REPORT_PATH = '/app/report.txt'
NB = 10
TOL = 1e-4
TTOL = 1e-3


@pytest.fixture(scope='module')
def results():
    assert os.path.exists(RESULTS_PATH), f"Pipeline output not found at {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        return json.load(f)


@pytest.fixture(scope='module')
def ref():
    """Compute reference values from scratch using same seed."""
    lt, lbt, le, lbe, nc = _generate_ref()
    pt, pe = _sm(lt), _sm(le)
    ct, ce = np.max(pt, axis=1), np.max(pe, axis=1)
    rt = (np.argmax(pt, axis=1) == lbt).astype(np.float64)
    re = (np.argmax(pe, axis=1) == lbe).astype(np.float64)

    rv = {'n_test': len(lbe)}

    rv['uncalibrated'] = {
        'ece': _ece(ce, re, NB), 'mce': _mce(ce, re, NB),
        'ace': _ace(ce, re, NB), 'brier': _brier(ce, re),
    }

    hb = _hb_transform(ct, rt, ce, NB)
    rv['histogram_binning'] = {
        'ece': _ece(hb, re, NB), 'mce': _mce(hb, re, NB),
        'ace': _ace(hb, re, NB), 'brier': _brier(hb, re),
    }

    ot = _temp_opt(lt, lbt)
    ts = np.max(_sm(le / ot), axis=1)
    rv['temperature_scaling'] = {
        'ece': _ece(ts, re, NB), 'mce': _mce(ts, re, NB),
        'ace': _ace(ts, re, NB), 'brier': _brier(ts, re),
        'optimal_temperature': ot,
    }

    return rv


# ---------------------------------------------------------------------------
# Uncalibrated metrics
# ---------------------------------------------------------------------------

class TestUncalibratedMetrics:
    @pytest.mark.parametrize('metric', ['ece', 'mce', 'ace', 'brier'])
    def test_metric(self, results, ref, metric):
        actual = results['uncalibrated'][metric]
        expected = ref['uncalibrated'][metric]
        assert abs(actual - expected) < TOL, \
            f"uncalibrated.{metric}: {actual} != {expected} (tol={TOL})"


# ---------------------------------------------------------------------------
# Histogram binning
# ---------------------------------------------------------------------------

class TestHistogramBinning:
    @pytest.mark.parametrize('metric', ['ece', 'mce', 'ace', 'brier'])
    def test_metric(self, results, ref, metric):
        actual = results['histogram_binning'][metric]
        expected = ref['histogram_binning'][metric]
        assert abs(actual - expected) < TOL, \
            f"histogram_binning.{metric}: {actual} != {expected}"

    def test_calibrated_confidences_valid(self, results, ref):
        preds = results['histogram_binning']['calibrated_confidences']
        assert isinstance(preds, list)
        assert len(preds) == ref['n_test']
        for p in preds:
            assert 0.0 <= p <= 1.0


# ---------------------------------------------------------------------------
# Temperature scaling
# ---------------------------------------------------------------------------

class TestTemperatureScaling:
    @pytest.mark.parametrize('metric', ['ece', 'mce', 'ace', 'brier'])
    def test_metric(self, results, ref, metric):
        actual = results['temperature_scaling'][metric]
        expected = ref['temperature_scaling'][metric]
        assert abs(actual - expected) < TOL, \
            f"temperature_scaling.{metric}: {actual} != {expected}"

    def test_optimal_temperature(self, results, ref):
        actual = results['temperature_scaling']['optimal_temperature']
        expected = ref['temperature_scaling']['optimal_temperature']
        assert abs(actual - expected) < TTOL, \
            f"optimal_temperature: {actual} != {expected} (tol={TTOL})"

    def test_calibrated_confidences_valid(self, results, ref):
        preds = results['temperature_scaling']['calibrated_confidences']
        assert isinstance(preds, list)
        assert len(preds) == ref['n_test']
        for p in preds:
            assert 0.0 <= p <= 1.0


# ---------------------------------------------------------------------------
# BBQ method: property-based tests
# ---------------------------------------------------------------------------

class TestBBQ:
    def test_present(self, results):
        assert 'bbq' in results, "Missing 'bbq' key in results"

    def test_required_keys(self, results):
        for k in ['ece', 'mce', 'ace', 'brier', 'calibrated_confidences',
                   'num_models_selected', 'model_weights']:
            assert k in results['bbq'], f"Missing key '{k}' in bbq"

    def test_predictions_valid(self, results, ref):
        preds = results['bbq']['calibrated_confidences']
        assert isinstance(preds, list)
        assert len(preds) == ref['n_test'], \
            f"Expected {ref['n_test']} predictions, got {len(preds)}"
        for p in preds:
            assert 0.0 <= p <= 1.0, f"BBQ prediction {p} out of [0,1]"
        assert not any(np.isnan(p) for p in preds), "NaN in BBQ predictions"

    def test_improves_ece(self, results):
        assert results['bbq']['ece'] < results['uncalibrated']['ece'], \
            f"BBQ ECE ({results['bbq']['ece']}) should be < " \
            f"uncalibrated ECE ({results['uncalibrated']['ece']})"

    def test_weights_sum(self, results):
        w = results['bbq']['model_weights']
        assert isinstance(w, list) and len(w) > 0
        assert abs(sum(w) - 1.0) < 1e-6, \
            f"model_weights sum to {sum(w)}, expected 1.0"

    def test_model_count(self, results):
        n = results['bbq']['num_models_selected']
        assert isinstance(n, int) and n >= 1

    def test_weights_length(self, results):
        assert len(results['bbq']['model_weights']) == \
               results['bbq']['num_models_selected']

    def test_metrics_valid_range(self, results):
        for m in ['ece', 'mce', 'ace']:
            v = results['bbq'][m]
            assert isinstance(v, float) and 0 <= v <= 1, \
                f"bbq.{m}={v} invalid"

    def test_brier_valid(self, results):
        v = results['bbq']['brier']
        assert isinstance(v, float) and 0 <= v <= 2


# ---------------------------------------------------------------------------
# Brier score
# ---------------------------------------------------------------------------

class TestBrierScore:
    def test_present_all_methods(self, results):
        for method in ['uncalibrated', 'histogram_binning',
                       'temperature_scaling', 'bbq']:
            assert 'brier' in results[method], f"Missing 'brier' in {method}"

    def test_valid_range(self, results):
        for method in ['uncalibrated', 'histogram_binning',
                       'temperature_scaling', 'bbq']:
            v = results[method]['brier']
            assert isinstance(v, float) and 0 <= v <= 2, \
                f"{method}.brier={v} invalid"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

class TestConfig:
    def test_bbq_method(self):
        with open(CONFIG_PATH) as f:
            c = json.load(f)
        assert 'bbq' in c['methods'], "config.json must include 'bbq' in methods"

    def test_brier_metric(self):
        with open(CONFIG_PATH) as f:
            c = json.load(f)
        assert 'brier' in c['metrics'], "config.json must include 'brier' in metrics"


# ---------------------------------------------------------------------------
# SQLite results table
# ---------------------------------------------------------------------------

class TestSQLite:
    def test_results_table_exists(self):
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='results'")
        row = cur.fetchone()
        conn.close()
        assert row is not None, "results table not found in calibration.db"

    def test_results_populated(self):
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM results")
        count = cur.fetchone()[0]
        conn.close()
        assert count >= 16, f"Expected >=16 rows in results, got {count}"

    def test_results_match_json(self, results):
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        for method in ['uncalibrated', 'histogram_binning',
                       'temperature_scaling', 'bbq']:
            for metric in ['ece', 'mce', 'ace', 'brier']:
                cur.execute(
                    "SELECT value FROM results WHERE method=? AND metric=?",
                    (method, metric))
                row = cur.fetchone()
                assert row is not None, \
                    f"Missing ({method}, {metric}) in results table"
                assert abs(row[0] - results[method][metric]) < 1e-8, \
                    f"({method}, {metric}): db={row[0]} != json={results[method][metric]}"
        conn.close()


# ---------------------------------------------------------------------------
# Report file
# ---------------------------------------------------------------------------

class TestReport:
    def test_exists(self):
        assert os.path.exists(REPORT_PATH), "report.txt not found"

    def test_format(self):
        with open(REPORT_PATH) as f:
            lines = f.readlines()
        assert len(lines) > 1, "report.txt should have header + data lines"
        header = lines[0].strip().split('\t')
        assert 'method' in header and 'metric' in header and 'value' in header, \
            f"Bad header: {lines[0].strip()}"
        for line in lines[1:]:
            parts = line.strip().split('\t')
            assert len(parts) == 3, f"Expected 3 tab-separated fields: {line.strip()}"
            float(parts[2])  # value should be numeric


# ---------------------------------------------------------------------------
# Validation script
# ---------------------------------------------------------------------------

class TestValidation:
    def test_validate_sh_passes(self):
        r = subprocess.run(
            ['bash', '/app/validate.sh', '/app/results.json'],
            capture_output=True, text=True)
        assert r.returncode == 0, f"validate.sh failed: {r.stderr}"


# ---------------------------------------------------------------------------
# Cross-method consistency
# ---------------------------------------------------------------------------

class TestConsistency:
    def test_ece_ne_ace_uncalibrated(self, results):
        """ECE and ACE should differ for unequally populated bins."""
        ece = results['uncalibrated']['ece']
        ace = results['uncalibrated']['ace']
        assert abs(ece - ace) > 1e-6, \
            f"ECE ({ece}) should differ from ACE ({ace})"

    def test_calibration_improves_ece(self, results):
        u = results['uncalibrated']['ece']
        for m in ['histogram_binning', 'temperature_scaling']:
            assert results[m]['ece'] < u, \
                f"{m} ECE ({results[m]['ece']}) should be < uncalibrated ({u})"

    def test_temperature_reasonable(self, results):
        t = results['temperature_scaling']['optimal_temperature']
        assert 1.0 < t < 10.0, f"Optimal temperature {t} outside (1, 10)"
