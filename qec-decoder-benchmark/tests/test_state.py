
import json
import os

import numpy as np
import pytest
import stim
from tesseract_decoder import common, simplex, tesseract


# ── Output file existence ────────────────────────────────────────────────────

def test_output_processed_dem_exists():
    assert os.path.isfile("/app/output/processed.dem")


def test_output_cross_validation_exists():
    assert os.path.isfile("/app/output/cross_validation.json")


def test_output_error_rates_exists():
    assert os.path.isfile("/app/output/error_rates.json")


def test_output_threshold_exists():
    assert os.path.isfile("/app/output/threshold.json")


# ── Processed DEM validity ───────────────────────────────────────────────────

def test_processed_dem_is_valid_stim_dem():
    with open("/app/output/processed.dem") as f:
        dem_str = f.read()
    dem = stim.DetectorErrorModel(dem_str)
    assert dem.num_detectors > 0
    err_lines = [
        l for l in dem_str.strip().split("\n") if l.strip().startswith("error(")
    ]
    assert len(err_lines) > 0


# ── Cross-validation structure and quality ───────────────────────────────────

def _load_cv():
    with open("/app/output/cross_validation.json") as f:
        return json.load(f)


def test_cross_validation_structure():
    data = _load_cv()
    for key in [
        "total_shots",
        "cost_matches",
        "cost_mismatches",
        "logical_errors_tesseract",
        "logical_errors_simplex",
    ]:
        assert key in data, f"Missing key: {key}"
    assert data["total_shots"] == 500
    assert isinstance(data["cost_matches"], int)
    assert isinstance(data["cost_mismatches"], int)


def test_cross_validation_cost_agreement():
    data = _load_cv()
    total_compared = data["cost_matches"] + data["cost_mismatches"]
    assert total_compared > 0, "No shots were compared"
    match_rate = data["cost_matches"] / total_compared
    assert match_rate >= 0.90, (
        f"Tesseract-Simplex cost match rate {match_rate:.2%} is below 90%"
    )


# ── Error-rate sweep structure and formula ───────────────────────────────────

def _load_er():
    with open("/app/output/error_rates.json") as f:
        return json.load(f)


def test_error_rates_structure():
    data = _load_er()
    assert isinstance(data, list)
    assert len(data) == 9
    required_keys = {
        "distance",
        "physical_error_rate",
        "logical_error_rate_per_shot",
        "logical_error_rate_per_round",
        "num_shots",
        "num_rounds",
        "num_errors",
    }
    for entry in data:
        assert required_keys.issubset(entry.keys()), (
            f"Missing keys: {required_keys - set(entry.keys())}"
        )
        assert entry["num_shots"] == 2000
        assert entry["distance"] in [3, 5, 7]
        assert entry["physical_error_rate"] in [0.05, 0.15, 0.2]


def test_per_round_formula_consistency():
    """Re-derive R_round from R_shot and verify agreement."""
    data = _load_er()
    for entry in data:
        R = entry["logical_error_rate_per_shot"]
        r = entry["num_rounds"]
        actual = entry["logical_error_rate_per_round"]
        if 0 < R < 0.5:
            expected = 0.5 * (1 - (1 - 2 * R) ** (1.0 / r))
            assert abs(expected - actual) < 1e-8, (
                f"d={entry['distance']}, p={entry['physical_error_rate']}: "
                f"expected R_round={expected}, got {actual}"
            )
        elif R == 0:
            assert actual == 0.0
        elif R >= 0.5:
            assert actual == 0.5


def test_error_rates_have_all_combinations():
    data = _load_er()
    seen = {(e["distance"], e["physical_error_rate"]) for e in data}
    for d in [3, 5, 7]:
        for p in [0.05, 0.15, 0.2]:
            assert (d, p) in seen, f"Missing (d={d}, p={p})"


# ── Threshold estimation ─────────────────────────────────────────────────────

def test_threshold_bounds():
    with open("/app/output/threshold.json") as f:
        data = json.load(f)
    t = data["threshold_estimate"]
    assert isinstance(t, float)
    assert 0.1 <= t <= 0.3, f"Threshold {t} out of expected range [0.1, 0.3]"


# ── Independent decoding verification (deterministic) ────────────────────────

_SMALL_DEM = stim.DetectorErrorModel(
    """
    error(0.1) D0 D1 L0
    error(0.2) D1 D2 L1
    detector(0, 0, 0) D0
    detector(1, 0, 0) D1
    detector(2, 0, 0) D2
"""
)


def test_tesseract_decode_small_dem():
    """D0+D1 fired -> error 0 (p=0.1) -> L0 flips, L1 stays."""
    cfg = tesseract.TesseractConfig(dem=_SMALL_DEM, det_beam=20, beam_climbing=True)
    dec = tesseract.TesseractDecoder(cfg)
    obs = dec.decode(np.array([True, True, False], dtype=bool))
    assert bool(obs[0]) is True
    assert bool(obs[1]) is False


def test_simplex_decode_small_dem():
    """Same check using the Simplex (ILP) decoder."""
    cfg = simplex.SimplexConfig(dem=_SMALL_DEM)
    dec = simplex.SimplexDecoder(cfg)
    dec.init_ilp()
    obs = dec.decode(np.array([True, True, False], dtype=bool))
    assert bool(obs[0]) is True
    assert bool(obs[1]) is False


def test_tesseract_decode_d1_d2():
    """D1+D2 fired -> error 1 (p=0.2) -> L1 flips."""
    cfg = tesseract.TesseractConfig(dem=_SMALL_DEM, det_beam=20)
    dec = tesseract.TesseractDecoder(cfg)
    obs = dec.decode(np.array([False, True, True], dtype=bool))
    assert bool(obs[0]) is False
    assert bool(obs[1]) is True


# ── Tesseract-vs-Simplex cost comparison on small DEM ────────────────────────

_CYCLE_DEM = stim.DetectorErrorModel(
    """
    error(0.1) D0 D1 L0
    error(0.1) D1 D2
    error(0.1) D2 D3
    error(0.1) D3 D0
    detector(0, 0, 0) D0
    detector(1, 0, 0) D1
    detector(2, 0, 0) D2
    detector(3, 0, 0) D3
"""
)

# The cycle DEM has 4 errors forming a cycle.  The syndrome matrix has rank 3,
# so only 7 of the 15 non-zero 4-bit syndromes are reachable.
_REACHABLE_BITS = [3, 5, 6, 9, 10, 12, 15]


def test_decoder_cost_agreement_reachable():
    """Compare Tesseract and Simplex costs on reachable syndromes of a small DEM."""
    t_cfg = tesseract.TesseractConfig(
        dem=_CYCLE_DEM, det_beam=20, beam_climbing=True
    )
    t_dec = tesseract.TesseractDecoder(t_cfg)

    s_cfg = simplex.SimplexConfig(dem=_CYCLE_DEM)
    s_dec = simplex.SimplexDecoder(s_cfg)
    s_dec.init_ilp()

    for bits in _REACHABLE_BITS:
        syndrome = np.array([(bits >> i) & 1 for i in range(4)], dtype=bool)

        t_obs = t_dec.decode(syndrome)
        if t_dec.low_confidence_flag:
            continue
        t_cost = t_dec.cost_from_errors(list(t_dec.predicted_errors_buffer))

        s_obs = s_dec.decode(syndrome)
        s_cost = s_dec.cost_from_errors(list(s_dec.predicted_errors_buffer))

        assert abs(t_cost - s_cost) < 1e-6, (
            f"bits={bits}: Tesseract cost={t_cost}, Simplex cost={s_cost}"
        )


# ── Error merging ────────────────────────────────────────────────────────────

def test_merge_indistinguishable_errors():
    dem = stim.DetectorErrorModel(
        """
        error(0.1) D0 D1
        error(0.05) D0 D1
        error(0.2) D2
        detector(0, 0, 0) D0
        detector(1, 0, 0) D1
        detector(2, 0, 0) D2
    """
    )
    merged = common.merge_indistinguishable_errors(dem)
    merged_str = str(merged)
    err_lines = [
        l for l in merged_str.strip().split("\n") if l.strip().startswith("error(")
    ]
    assert len(err_lines) == 2, (
        f"Expected 2 errors after merging, got {len(err_lines)}"
    )
