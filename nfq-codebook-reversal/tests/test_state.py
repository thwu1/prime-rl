"""

Property-based verification — no stored ground truth.
All tests verify mathematical consistency and optimality conditions.
"""
import pytest
import json
import numpy as np
import struct
import os
from scipy.stats import norm

OUTPUT_DIR = '/app/output'
WEIGHTS_PATH = '/app/original_weights.bin'
QUANT_PATH = '/app/quantized_data.bin'
META_PATH = '/app/metadata.json'


def _parse_quantized():
    """Parse quantized binary to extract header, scales, and indices."""
    with open(QUANT_PATH, 'rb') as f:
        raw = f.read()
    n_w, bs = struct.unpack_from('<II', raw, 0)
    nb = n_w // bs
    off = 8
    sc = np.frombuffer(raw, dtype=np.float32, count=nb, offset=off).copy()
    off += nb * 4
    pk = np.frombuffer(raw, dtype=np.uint8, count=n_w // 2, offset=off).copy()
    idx = np.zeros(n_w, dtype=np.uint8)
    for i in range(len(pk)):
        idx[2 * i] = pk[i] & 0x0F
        idx[2 * i + 1] = (pk[i] >> 4) & 0x0F
    return n_w, bs, nb, sc, idx


def _cb_from_alpha(a):
    """QLoRA NF4 codebook construction from alpha parameter."""
    Q = norm.ppf
    Z = Q(a)
    if not np.isfinite(Z) or Z <= 0:
        return None
    d1 = (a - 0.5) / 7
    d2 = (a - 0.5) / 8
    cb = np.zeros(16, dtype=np.float64)
    for i in range(7):
        v = a - i * d1
        if v <= 0 or v >= 1:
            return None
        cb[i] = -Q(v) / Z
    for i in range(8):
        v = 0.5 + (i + 1) * d2
        if v <= 0 or v >= 1:
            return None
        cb[i + 8] = Q(v) / Z
    return cb


def _requant_mse(cb_f32, weights, n_blocks, block_size, n_weights):
    """Compute MSE when quantizing weights with a codebook + per-block scaling."""
    cb_f64 = cb_f32.astype(np.float64)
    total_se = 0.0
    for b in range(n_blocks):
        s, e = b * block_size, (b + 1) * block_size
        block = weights[s:e].astype(np.float64)
        sc = np.max(np.abs(block))
        if sc == 0:
            continue
        normed = block / sc
        d = np.abs(normed[:, None] - cb_f64[None, :])
        idx = np.argmin(d, axis=1)
        deq = cb_f64[idx] * sc
        total_se += np.sum((block - deq) ** 2)
    return float(total_se / n_weights)


@pytest.fixture(scope='session')
def task_data():
    n_w, bs, nb, sc, idx = _parse_quantized()
    w = np.fromfile(WEIGHTS_PATH, dtype=np.float32)
    return dict(n_weights=n_w, block_size=bs, n_blocks=nb,
                scales=sc, indices=idx, weights=w)


# ===================================================================
# NF4 Codebook
# ===================================================================
class TestCodebook:
    def test_exists(self):
        assert os.path.exists(f'{OUTPUT_DIR}/codebook.json')

    def test_shape(self):
        with open(f'{OUTPUT_DIR}/codebook.json') as f:
            cb = json.load(f)
        assert isinstance(cb, list) and len(cb) == 16

    def test_range(self):
        with open(f'{OUTPUT_DIR}/codebook.json') as f:
            cb = json.load(f)
        assert min(cb) >= -1.01 and max(cb) <= 1.01

    def test_contains_zero(self):
        with open(f'{OUTPUT_DIR}/codebook.json') as f:
            cb = json.load(f)
        assert any(abs(v) < 1e-3 for v in cb)

    def test_consistent_with_alpha(self):
        """Codebook must match QLoRA NF4 formula for the claimed alpha."""
        with open(f'{OUTPUT_DIR}/alpha.txt') as f:
            alpha = float(f.read().strip())
        with open(f'{OUTPUT_DIR}/codebook.json') as f:
            cb = sorted(json.load(f))
        expected = sorted(_cb_from_alpha(alpha).astype(np.float32).tolist())
        for i in range(16):
            assert abs(cb[i] - expected[i]) < 1e-4, \
                f"Codebook[{i}] inconsistent with alpha: {cb[i]:.6f} vs {expected[i]:.6f}"


# ===================================================================
# Alpha Recovery
# ===================================================================
class TestAlpha:
    def test_exists(self):
        assert os.path.exists(f'{OUTPUT_DIR}/alpha.txt')

    def test_in_range(self):
        with open(f'{OUTPUT_DIR}/alpha.txt') as f:
            a = float(f.read().strip())
        assert 0.5 < a < 1.0

    def test_precision(self):
        with open(f'{OUTPUT_DIR}/alpha.txt') as f:
            t = f.read().strip()
        if '.' in t:
            assert len(t.split('.')[1]) >= 6

    def test_nearest_neighbor_consistency(self, task_data):
        """Stored indices must equal nearest-codebook assignment for claimed alpha."""
        with open(f'{OUTPUT_DIR}/alpha.txt') as f:
            alpha = float(f.read().strip())
        cb = _cb_from_alpha(alpha)
        assert cb is not None, "Invalid alpha value"
        cb32 = cb.astype(np.float32)
        d = task_data
        se = np.repeat(d['scales'], d['block_size'])
        nz = se != 0
        normed = np.zeros(d['n_weights'], dtype=np.float32)
        normed[nz] = d['weights'][nz] / se[nz]
        dists = np.abs(normed[:, None] - cb32[None, :])
        nearest = np.argmin(dists, axis=1).astype(np.uint8)
        matches = int(np.sum((nearest == d['indices']) & nz))
        total = int(np.sum(nz))
        assert matches >= total * 0.999, \
            f"Only {matches}/{total} indices match nearest neighbor — alpha likely wrong"


# ===================================================================
# NF4 Dequantized Output
# ===================================================================
class TestDequantized:
    def test_exists(self):
        assert os.path.exists(f'{OUTPUT_DIR}/dequantized.bin')

    def test_size(self):
        data = np.fromfile(f'{OUTPUT_DIR}/dequantized.bin', dtype=np.float32)
        assert len(data) == 16384

    def test_no_nans(self):
        data = np.fromfile(f'{OUTPUT_DIR}/dequantized.bin', dtype=np.float32)
        assert not np.any(np.isnan(data))

    def test_consistent_with_codebook(self, task_data):
        """Dequantized must equal codebook[indices] * scale for claimed alpha."""
        with open(f'{OUTPUT_DIR}/alpha.txt') as f:
            alpha = float(f.read().strip())
        cb_orig = _cb_from_alpha(alpha).astype(np.float32)
        d = task_data
        se = np.repeat(d['scales'], d['block_size'])
        expected_deq = cb_orig[d['indices']] * se
        actual_deq = np.fromfile(f'{OUTPUT_DIR}/dequantized.bin', dtype=np.float32)
        mse = float(np.mean((actual_deq - expected_deq) ** 2))
        assert mse < 1e-8, \
            f"Dequantized inconsistent with codebook*scale: MSE={mse:.2e}"


# ===================================================================
# NF4 Error Metrics
# ===================================================================
class TestErrorMetrics:
    def test_exists(self):
        assert os.path.exists(f'{OUTPUT_DIR}/error_metrics.json')

    def test_required_keys(self):
        with open(f'{OUTPUT_DIR}/error_metrics.json') as f:
            m = json.load(f)
        for k in ['mse', 'max_abs_error', 'sqnr_db']:
            assert k in m

    def test_mse_recomputed(self, task_data):
        """MSE must match recomputation from weights and dequantized."""
        w = task_data['weights']
        deq = np.fromfile(f'{OUTPUT_DIR}/dequantized.bin', dtype=np.float32)
        mse_r = float(np.mean((w - deq) ** 2))
        with open(f'{OUTPUT_DIR}/error_metrics.json') as f:
            m = json.load(f)
        assert abs(m['mse'] - mse_r) / max(mse_r, 1e-15) < 0.01, \
            f"MSE mismatch: reported {m['mse']:.6e}, recomputed {mse_r:.6e}"

    def test_max_abs_error_recomputed(self, task_data):
        w = task_data['weights']
        deq = np.fromfile(f'{OUTPUT_DIR}/dequantized.bin', dtype=np.float32)
        mae_r = float(np.max(np.abs(w - deq)))
        with open(f'{OUTPUT_DIR}/error_metrics.json') as f:
            m = json.load(f)
        assert abs(m['max_abs_error'] - mae_r) / max(mae_r, 1e-15) < 0.01

    def test_sqnr_recomputed(self, task_data):
        w = task_data['weights']
        deq = np.fromfile(f'{OUTPUT_DIR}/dequantized.bin', dtype=np.float32)
        mse_val = float(np.mean((w - deq) ** 2))
        sig = float(np.mean(w ** 2))
        sqnr = 10 * np.log10(sig / mse_val) if mse_val > 0 else float('inf')
        with open(f'{OUTPUT_DIR}/error_metrics.json') as f:
            m = json.load(f)
        assert abs(m['sqnr_db'] - sqnr) / max(abs(sqnr), 1e-15) < 0.01

    def test_mse_positive(self):
        with open(f'{OUTPUT_DIR}/error_metrics.json') as f:
            m = json.load(f)
        assert m['mse'] > 0

    def test_sqnr_positive(self):
        with open(f'{OUTPUT_DIR}/error_metrics.json') as f:
            m = json.load(f)
        assert m['sqnr_db'] > 0


# ===================================================================
# Lloyd-Max Codebook — Optimality Conditions
# ===================================================================
class TestLloydMaxCodebook:
    def test_exists(self):
        assert os.path.exists(f'{OUTPUT_DIR}/lloyd_max_codebook.json')

    def test_shape(self):
        with open(f'{OUTPUT_DIR}/lloyd_max_codebook.json') as f:
            cb = json.load(f)
        assert isinstance(cb, list) and len(cb) == 16

    def test_sorted(self):
        with open(f'{OUTPUT_DIR}/lloyd_max_codebook.json') as f:
            cb = json.load(f)
        assert cb == sorted(cb), "Lloyd-Max codebook must be sorted ascending"

    def test_distinct(self):
        with open(f'{OUTPUT_DIR}/lloyd_max_codebook.json') as f:
            cb = json.load(f)
        assert len(set(round(v, 6) for v in cb)) == 16, \
            "Lloyd-Max codebook must have 16 distinct levels"

    def test_centroid_condition(self, task_data):
        """Each level must be the centroid of its Voronoi cell (Lloyd-Max optimality)."""
        with open(f'{OUTPUT_DIR}/lloyd_max_codebook.json') as f:
            cb = np.array(json.load(f), dtype=np.float64)
        d = task_data
        se = np.repeat(d['scales'], d['block_size'])
        nz = se != 0
        normed = np.zeros(d['n_weights'], dtype=np.float64)
        normed[nz] = d['weights'][nz].astype(np.float64) / se[nz].astype(np.float64)
        normed_nz = normed[nz]
        dists = np.abs(normed_nz[:, None] - cb[None, :])
        assign = np.argmin(dists, axis=1)
        max_viol = 0.0
        for j in range(16):
            mask = assign == j
            cnt = int(np.sum(mask))
            if cnt > 5:
                cent = float(np.mean(normed_nz[mask]))
                max_viol = max(max_viol, abs(float(cb[j]) - cent))
        assert max_viol < 0.005, \
            f"Centroid condition violated: max deviation = {max_viol:.6f}"


# ===================================================================
# Lloyd-Max Dequantized + Metrics
# ===================================================================
class TestLloydMaxOutput:
    def test_deq_exists(self):
        assert os.path.exists(f'{OUTPUT_DIR}/lloyd_max_dequantized.bin')

    def test_deq_size(self):
        data = np.fromfile(f'{OUTPUT_DIR}/lloyd_max_dequantized.bin', dtype=np.float32)
        assert len(data) == 16384

    def test_deq_no_nans(self):
        data = np.fromfile(f'{OUTPUT_DIR}/lloyd_max_dequantized.bin', dtype=np.float32)
        assert not np.any(np.isnan(data))

    def test_metrics_exists(self):
        assert os.path.exists(f'{OUTPUT_DIR}/lloyd_max_metrics.json')

    def test_metrics_keys(self):
        with open(f'{OUTPUT_DIR}/lloyd_max_metrics.json') as f:
            m = json.load(f)
        for k in ['mse', 'max_abs_error', 'sqnr_db']:
            assert k in m

    def test_metrics_recomputed(self, task_data):
        """Lloyd-Max metrics must match recomputation from raw data."""
        w = task_data['weights']
        deq = np.fromfile(f'{OUTPUT_DIR}/lloyd_max_dequantized.bin', dtype=np.float32)
        mse = float(np.mean((w - deq) ** 2))
        mae = float(np.max(np.abs(w - deq)))
        sig = float(np.mean(w ** 2))
        sqnr = 10 * np.log10(sig / mse) if mse > 0 else float('inf')
        with open(f'{OUTPUT_DIR}/lloyd_max_metrics.json') as f:
            m = json.load(f)
        assert abs(m['mse'] - mse) / max(mse, 1e-15) < 0.01
        assert abs(m['max_abs_error'] - mae) / max(mae, 1e-15) < 0.01
        assert abs(m['sqnr_db'] - sqnr) / max(abs(sqnr), 1e-15) < 0.01

    def test_mse_better_than_nf4(self, task_data):
        """Lloyd-Max MSE must be <= NF4 MSE (optimal quantizer guarantee)."""
        with open(f'{OUTPUT_DIR}/lloyd_max_codebook.json') as f:
            lm_cb = np.array(json.load(f), dtype=np.float32)
        with open(f'{OUTPUT_DIR}/codebook.json') as f:
            nf4_cb = np.array(sorted(json.load(f)), dtype=np.float32)
        d = task_data
        nf4_mse = _requant_mse(nf4_cb, d['weights'], d['n_blocks'],
                                d['block_size'], d['n_weights'])
        lm_mse = _requant_mse(lm_cb, d['weights'], d['n_blocks'],
                               d['block_size'], d['n_weights'])
        assert lm_mse <= nf4_mse * 1.001, \
            f"Lloyd-Max MSE ({lm_mse:.6e}) should be <= NF4 ({nf4_mse:.6e})"

    def test_deq_consistent_with_codebook(self, task_data):
        """Dequantized values must match codebook nearest-neighbor with per-block scaling."""
        with open(f'{OUTPUT_DIR}/lloyd_max_codebook.json') as f:
            cb = np.array(json.load(f), dtype=np.float32)
        d = task_data
        expected = np.zeros(d['n_weights'], dtype=np.float32)
        for b in range(d['n_blocks']):
            s = b * d['block_size']
            e = s + d['block_size']
            block = d['weights'][s:e]
            sc = d['scales'][b]
            if sc == 0:
                continue
            normed = block / sc
            dd = np.abs(normed[:, None] - cb[None, :])
            idx = np.argmin(dd, axis=1)
            expected[s:e] = cb[idx] * sc
        actual = np.fromfile(f'{OUTPUT_DIR}/lloyd_max_dequantized.bin', dtype=np.float32)
        mse = float(np.mean((actual - expected) ** 2))
        assert mse < 1e-8, \
            f"LM dequantized inconsistent with codebook: MSE={mse:.2e}"


# ===================================================================
# Comparison — Internal Consistency
# ===================================================================
class TestComparison:
    def test_exists(self):
        assert os.path.exists(f'{OUTPUT_DIR}/comparison.json')

    def test_required_keys(self):
        with open(f'{OUTPUT_DIR}/comparison.json') as f:
            c = json.load(f)
        for k in ['nf4_mse', 'lloyd_max_mse', 'nf4_sqnr_db',
                   'lloyd_max_sqnr_db', 'mse_winner',
                   'mse_improvement_pct', 'sqnr_winner']:
            assert k in c, f"Missing key '{k}'"

    def test_mse_winner_consistent(self):
        """mse_winner must name the scheme with lower MSE."""
        with open(f'{OUTPUT_DIR}/comparison.json') as f:
            c = json.load(f)
        if c['nf4_mse'] < c['lloyd_max_mse']:
            assert c['mse_winner'] == 'nf4'
        else:
            assert c['mse_winner'] == 'lloyd_max'

    def test_sqnr_winner_consistent(self):
        """sqnr_winner must name the scheme with higher SQNR."""
        with open(f'{OUTPUT_DIR}/comparison.json') as f:
            c = json.load(f)
        if c['nf4_sqnr_db'] > c['lloyd_max_sqnr_db']:
            assert c['sqnr_winner'] == 'nf4'
        else:
            assert c['sqnr_winner'] == 'lloyd_max'

    def test_improvement_pct_consistent(self):
        """mse_improvement_pct must equal (loser - winner) / loser * 100."""
        with open(f'{OUTPUT_DIR}/comparison.json') as f:
            c = json.load(f)
        loser_mse = max(c['nf4_mse'], c['lloyd_max_mse'])
        winner_mse = min(c['nf4_mse'], c['lloyd_max_mse'])
        expected_pct = (loser_mse - winner_mse) / loser_mse * 100
        assert abs(c['mse_improvement_pct'] - expected_pct) < 0.5, \
            f"Improvement % inconsistent: {c['mse_improvement_pct']:.2f} vs {expected_pct:.2f}"

    def test_metrics_match_individual(self):
        """Comparison metrics must agree with individual metric files."""
        with open(f'{OUTPUT_DIR}/comparison.json') as f:
            c = json.load(f)
        with open(f'{OUTPUT_DIR}/error_metrics.json') as f:
            nf4 = json.load(f)
        with open(f'{OUTPUT_DIR}/lloyd_max_metrics.json') as f:
            lm = json.load(f)
        assert abs(c['nf4_mse'] - nf4['mse']) / max(nf4['mse'], 1e-15) < 0.01
        assert abs(c['lloyd_max_mse'] - lm['mse']) / max(lm['mse'], 1e-15) < 0.01
        assert abs(c['nf4_sqnr_db'] - nf4['sqnr_db']) / max(abs(nf4['sqnr_db']), 1e-15) < 0.01
        assert abs(c['lloyd_max_sqnr_db'] - lm['sqnr_db']) / max(abs(lm['sqnr_db']), 1e-15) < 0.01


# ===================================================================
# Optimal Alpha — Local Optimality Check
# ===================================================================
class TestOptimalAlpha:
    def test_exists(self):
        assert os.path.exists(f'{OUTPUT_DIR}/optimal_alpha.txt')

    def test_in_range(self):
        with open(f'{OUTPUT_DIR}/optimal_alpha.txt') as f:
            a = float(f.read().strip())
        assert 0.9 < a < 0.999

    def test_precision(self):
        with open(f'{OUTPUT_DIR}/optimal_alpha.txt') as f:
            t = f.read().strip()
        if '.' in t:
            assert len(t.split('.')[1]) >= 4

    def test_better_than_recovered(self, task_data):
        """Optimal alpha MSE must be <= recovered alpha MSE."""
        with open(f'{OUTPUT_DIR}/alpha.txt') as f:
            a_rec = float(f.read().strip())
        with open(f'{OUTPUT_DIR}/optimal_alpha.txt') as f:
            a_opt = float(f.read().strip())
        cb_rec = _cb_from_alpha(a_rec).astype(np.float32)
        cb_opt = _cb_from_alpha(a_opt).astype(np.float32)
        d = task_data
        mse_rec = _requant_mse(cb_rec, d['weights'], d['n_blocks'],
                                d['block_size'], d['n_weights'])
        mse_opt = _requant_mse(cb_opt, d['weights'], d['n_blocks'],
                                d['block_size'], d['n_weights'])
        assert mse_opt <= mse_rec * 1.001, \
            f"Optimal alpha MSE ({mse_opt:.6e}) should be <= recovered ({mse_rec:.6e})"

    def test_local_optimality(self, task_data):
        """No nearby alpha should yield significantly lower MSE."""
        with open(f'{OUTPUT_DIR}/optimal_alpha.txt') as f:
            a_opt = float(f.read().strip())
        cb_opt = _cb_from_alpha(a_opt).astype(np.float32)
        d = task_data
        mse_opt = _requant_mse(cb_opt, d['weights'], d['n_blocks'],
                                d['block_size'], d['n_weights'])
        for delta in [-0.02, -0.01, 0.01, 0.02]:
            a = a_opt + delta
            if 0.9 < a < 0.999:
                cb = _cb_from_alpha(a)
                if cb is not None:
                    mse = _requant_mse(cb.astype(np.float32), d['weights'],
                                       d['n_blocks'], d['block_size'],
                                       d['n_weights'])
                    assert mse_opt <= mse * 1.005, \
                        f"alpha={a:.4f} gives lower MSE: {mse:.6e} vs {mse_opt:.6e}"
