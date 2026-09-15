
import json
import math
import os

import numpy as np
import pytest
import scipy.linalg

from simulator import AnalogCore, CrossSimParameters


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DFT_SIZE = 64
WEIGHT_BITS = 8
INPUT_BITS = 8
NUM_INPUTS = 10
SEED_INPUTS = 42
SEED_CORE = 123

REF_NSLICES = 2
REF_ADC_BITS = 6
REF_WEIGHT_MAPPING = "OFFSET"
REF_INPUT_SLICE_SIZE = 8
REF_PROG_ALPHA = 0.05
REF_NOISE_ALPHA = 0.03
REF_RMIN = 1000
REF_RMAX = 100000

NSLICES_OPTIONS = [1, 2, 4]
ADC_BITS_OPTIONS = [6, 8, 10]
WEIGHT_MAPPING_OPTIONS = ["BALANCED", "OFFSET"]
INPUT_SLICE_OPTIONS = [1, 2, 4, 8]

TOTAL_CONFIGS = (
    len(NSLICES_OPTIONS) * len(ADC_BITS_OPTIONS)
    * len(WEIGHT_MAPPING_OPTIONS) * len(INPUT_SLICE_OPTIONS)
)

SNR_TOL = 1.5  # dB tolerance for re-simulation comparison


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _generate_test_data():
    W = scipy.linalg.dft(DFT_SIZE)
    np.random.seed(SEED_INPUTS)
    ti = (np.random.randn(NUM_INPUTS, DFT_SIZE)
          + 1j * np.random.randn(NUM_INPUTS, DFT_SIZE))
    ti /= np.max(np.abs(ti))
    ideal = np.array([W @ x for x in ti])
    return W, ti, ideal


def _compute_snr(y_analog, y_ideal):
    sp = np.sum(np.abs(y_ideal) ** 2)
    ep = np.sum(np.abs(y_analog - y_ideal) ** 2)
    if ep < 1e-30:
        return 100.0
    return 10.0 * np.log10(sp / ep)


def _compute_cost(ns, ab, wm, isl):
    M = 2 if wm == "BALANCED" else 1
    return ns * M * (2 ** ab) * int(math.ceil(INPUT_BITS / isl))


def _create_params(ns, ab, wm, isl,
                   prog_en=True, noise_en=True):
    p = CrossSimParameters()
    p.core.complex_matrix = True
    p.core.complex_input = True
    p.core.weight_bits = WEIGHT_BITS
    p.core.rows_max = 128
    p.core.cols_max = 128
    p.core.mapping.weights.percentile = 1.0
    p.core.mapping.inputs.mvm.min = -1.0
    p.core.mapping.inputs.mvm.max = 1.0

    if ns == 1:
        p.core.style = wm
    else:
        p.core.style = "BITSLICED"
        p.core.bit_sliced.style = wm
        p.core.bit_sliced.num_slices = ns

    if wm == "BALANCED":
        cb = WEIGHT_BITS - 1 if ns == 1 else int(math.ceil((WEIGHT_BITS - 1) / ns))
    else:
        cb = WEIGHT_BITS if ns == 1 else int(math.ceil(WEIGHT_BITS / ns))
    p.xbar.device.cell_bits = cb

    p.xbar.device.Rmin = REF_RMIN
    p.xbar.device.Rmax = REF_RMAX

    p.xbar.device.programming_error.enable = prog_en
    if prog_en:
        p.xbar.device.programming_error.model = "NormalProportionalDevice"
        p.xbar.device.programming_error.magnitude = REF_PROG_ALPHA

    p.xbar.device.read_noise.enable = noise_en
    if noise_en:
        p.xbar.device.read_noise.model = "NormalIndependentDevice"
        p.xbar.device.read_noise.magnitude = REF_NOISE_ALPHA

    p.xbar.adc.mvm.bits = ab
    p.xbar.adc.mvm.model = "SignMagnitudeADC"
    p.xbar.adc.mvm.signed = True
    p.xbar.adc.mvm.adc_range_option = "MAX"

    p.xbar.dac.mvm.bits = INPUT_BITS
    p.xbar.dac.mvm.model = "SignMagnitudeDAC"
    p.xbar.dac.mvm.signed = True
    if isl < INPUT_BITS:
        p.xbar.dac.mvm.input_bitslicing = True
        p.xbar.dac.mvm.slice_size = isl
    else:
        p.xbar.dac.mvm.input_bitslicing = False

    p.core.balanced.style = "ONE_SIDED"
    p.core.balanced.subtract_current_in_xbar = True
    p.core.offset.style = "DIGITAL_OFFSET"

    p.validate()
    return p


def _simulate(cfg, W, ti, ideal, prog_en=True, noise_en=True):
    np.random.seed(SEED_CORE)
    params = _create_params(
        cfg["Nslices"], cfg["adc_bits"], cfg["weight_mapping"],
        cfg["input_slice_size"], prog_en=prog_en, noise_en=noise_en,
    )
    core = AnalogCore(W, params=params)
    snrs = [_compute_snr(core @ ti[i], ideal[i]) for i in range(NUM_INPUTS)]
    return float(np.mean(snrs))


def _is_dominated(c, by, configs):
    """Return True if c is dominated by any config in configs."""
    for d in configs:
        if d is c:
            continue
        if (d["cost"] <= c["cost"] and d["snr_db"] >= c["snr_db"]
                and (d["cost"] < c["cost"] or d["snr_db"] > c["snr_db"])):
            return True
    return False


# ---------------------------------------------------------------------------
# Fixtures (module-scoped: computed once, shared across all tests)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def results():
    path = "/app/analysis.json"
    assert os.path.isfile(path), "analysis.json not found at /app/analysis.json"
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def test_data():
    return _generate_test_data()


@pytest.fixture(scope="module")
def ref_cfg():
    return {
        "Nslices": REF_NSLICES, "adc_bits": REF_ADC_BITS,
        "weight_mapping": REF_WEIGHT_MAPPING,
        "input_slice_size": REF_INPUT_SLICE_SIZE,
    }


@pytest.fixture(scope="module")
def gt_attribution(test_data, ref_cfg):
    """Ground-truth error attribution for the reference config."""
    W, ti, ideal = test_data
    baseline = _simulate(ref_cfg, W, ti, ideal, prog_en=False, noise_en=False)
    prog_only = _simulate(ref_cfg, W, ti, ideal, prog_en=True, noise_en=False)
    noise_only = _simulate(ref_cfg, W, ti, ideal, prog_en=False, noise_en=True)
    all_err = _simulate(ref_cfg, W, ti, ideal, prog_en=True, noise_en=True)

    dp = baseline - prog_only
    dn = baseline - noise_only
    dc = baseline - all_err
    interaction = dc - dp - dn
    dominant = "programming_error" if dp > dn else "read_noise"

    return {
        "baseline_snr": baseline,
        "prog_error_only_snr": prog_only,
        "read_noise_only_snr": noise_only,
        "all_errors_snr": all_err,
        "dominant_source": dominant,
        "interaction_delta_db": interaction,
    }


@pytest.fixture(scope="module")
def gt_design_space(test_data):
    """Re-simulate all 72 configurations."""
    W, ti, ideal = test_data
    out = []
    for ns in NSLICES_OPTIONS:
        for ab in ADC_BITS_OPTIONS:
            for wm in WEIGHT_MAPPING_OPTIONS:
                for isl in INPUT_SLICE_OPTIONS:
                    cfg = {"Nslices": ns, "adc_bits": ab,
                           "weight_mapping": wm, "input_slice_size": isl}
                    snr = _simulate(cfg, W, ti, ideal)
                    cost = _compute_cost(ns, ab, wm, isl)
                    out.append({**cfg, "snr_db": snr, "cost": cost})
    return out


@pytest.fixture(scope="module")
def gt_pareto(gt_design_space):
    """Ground-truth Pareto frontier."""
    frontier = [c for c in gt_design_space
                if not _is_dominated(c, None, gt_design_space)]
    frontier.sort(key=lambda x: x["cost"])
    return frontier


# ---------------------------------------------------------------------------
# Tests: JSON Format
# ---------------------------------------------------------------------------
class TestFormat:
    def test_top_level_keys(self, results):
        for k in ("reference_analysis", "pareto_frontier",
                   "dominated_count", "recommended_config"):
            assert k in results, f"Missing key: {k}"

    def test_reference_analysis_keys(self, results):
        ra = results["reference_analysis"]
        for k in ("baseline_snr", "prog_error_only_snr", "read_noise_only_snr",
                   "all_errors_snr", "dominant_source", "interaction_delta_db"):
            assert k in ra, f"Missing reference_analysis key: {k}"

    def test_pareto_is_nonempty_list(self, results):
        pf = results["pareto_frontier"]
        assert isinstance(pf, list) and len(pf) > 0

    def test_pareto_entry_keys(self, results):
        for e in results["pareto_frontier"]:
            for k in ("Nslices", "adc_bits", "weight_mapping",
                       "input_slice_size", "snr_db", "cost"):
                assert k in e, f"Missing pareto entry key: {k}"

    def test_recommended_keys(self, results):
        rc = results["recommended_config"]
        for k in ("Nslices", "adc_bits", "weight_mapping",
                   "input_slice_size", "snr_db", "cost", "efficiency"):
            assert k in rc, f"Missing recommended_config key: {k}"

    def test_dominant_source_value(self, results):
        assert results["reference_analysis"]["dominant_source"] in (
            "programming_error", "read_noise")

    def test_config_values_in_range(self, results):
        for e in results["pareto_frontier"]:
            assert e["Nslices"] in (1, 2, 4)
            assert e["adc_bits"] in (6, 8, 10)
            assert e["weight_mapping"] in ("BALANCED", "OFFSET")
            assert e["input_slice_size"] in (1, 2, 4, 8)


# ---------------------------------------------------------------------------
# Tests: Error Attribution
# ---------------------------------------------------------------------------
class TestErrorAttribution:
    def test_baseline_snr(self, results, gt_attribution):
        r = results["reference_analysis"]["baseline_snr"]
        e = gt_attribution["baseline_snr"]
        assert abs(r - e) < SNR_TOL, f"baseline_snr: {r:.2f} vs {e:.2f}"

    def test_prog_error_only_snr(self, results, gt_attribution):
        r = results["reference_analysis"]["prog_error_only_snr"]
        e = gt_attribution["prog_error_only_snr"]
        assert abs(r - e) < SNR_TOL, f"prog_error_only_snr: {r:.2f} vs {e:.2f}"

    def test_read_noise_only_snr(self, results, gt_attribution):
        r = results["reference_analysis"]["read_noise_only_snr"]
        e = gt_attribution["read_noise_only_snr"]
        assert abs(r - e) < SNR_TOL, f"read_noise_only_snr: {r:.2f} vs {e:.2f}"

    def test_all_errors_snr(self, results, gt_attribution):
        r = results["reference_analysis"]["all_errors_snr"]
        e = gt_attribution["all_errors_snr"]
        assert abs(r - e) < SNR_TOL, f"all_errors_snr: {r:.2f} vs {e:.2f}"

    def test_dominant_source(self, results, gt_attribution):
        assert (results["reference_analysis"]["dominant_source"]
                == gt_attribution["dominant_source"]), (
            f"dominant: {results['reference_analysis']['dominant_source']} "
            f"vs {gt_attribution['dominant_source']}")

    def test_interaction_delta(self, results, gt_attribution):
        r = results["reference_analysis"]["interaction_delta_db"]
        e = gt_attribution["interaction_delta_db"]
        assert abs(r - e) < SNR_TOL, (
            f"interaction_delta_db: {r:.4f} vs {e:.4f}")

    def test_snr_ordering(self, results):
        ra = results["reference_analysis"]
        assert ra["baseline_snr"] >= ra["prog_error_only_snr"] - 0.5
        assert ra["baseline_snr"] >= ra["read_noise_only_snr"] - 0.5
        assert ra["baseline_snr"] >= ra["all_errors_snr"] - 0.5


# ---------------------------------------------------------------------------
# Tests: Pareto Frontier
# ---------------------------------------------------------------------------
class TestParetoFrontier:
    def test_no_internal_domination(self, results):
        """No frontier config should dominate another frontier config."""
        pf = results["pareto_frontier"]
        for i, c in enumerate(pf):
            for j, d in enumerate(pf):
                if i == j:
                    continue
                assert not (
                    d["cost"] <= c["cost"] and d["snr_db"] >= c["snr_db"]
                    and (d["cost"] < c["cost"] or d["snr_db"] > c["snr_db"])
                ), f"Frontier config {c} dominated by {d}"

    def test_sorted_by_cost(self, results):
        costs = [c["cost"] for c in results["pareto_frontier"]]
        assert costs == sorted(costs), "Pareto frontier not sorted by cost"

    def test_snr_monotonic_on_frontier(self, results):
        """On a cost-sorted Pareto frontier, SNR must be non-decreasing."""
        pf = results["pareto_frontier"]
        for i in range(len(pf) - 1):
            assert pf[i]["snr_db"] <= pf[i + 1]["snr_db"] + 0.5, (
                f"SNR not monotonic: {pf[i]} then {pf[i+1]}")

    def test_cost_formula(self, results):
        for e in results["pareto_frontier"]:
            exp = _compute_cost(e["Nslices"], e["adc_bits"],
                                e["weight_mapping"], e["input_slice_size"])
            assert e["cost"] == exp, (
                f"Cost mismatch: {e['cost']} vs {exp} for {e}")

    def test_frontier_size(self, results, gt_pareto):
        r = len(results["pareto_frontier"])
        e = len(gt_pareto)
        assert r == e, f"Pareto frontier size: {r} vs expected {e}"

    def test_dominated_count(self, results, gt_pareto):
        expected = TOTAL_CONFIGS - len(gt_pareto)
        assert results["dominated_count"] == expected, (
            f"dominated_count: {results['dominated_count']} vs {expected}")

    def test_spot_check_snr(self, results, test_data):
        """Re-simulate a few Pareto configs to verify SNR."""
        W, ti, ideal = test_data
        pf = results["pareto_frontier"]
        indices = [0, len(pf) - 1]
        if len(pf) > 2:
            indices.append(len(pf) // 2)
        for idx in indices:
            e = pf[idx]
            snr = _simulate(e, W, ti, ideal)
            assert abs(snr - e["snr_db"]) < SNR_TOL, (
                f"Spot-check SNR: simulated {snr:.2f} vs reported "
                f"{e['snr_db']:.2f} for {e}")

    def test_frontier_configs_match_ground_truth(self, results, gt_pareto):
        """Check that every ground-truth Pareto config appears in reported frontier."""
        reported_keys = set()
        for c in results["pareto_frontier"]:
            reported_keys.add(
                (c["Nslices"], c["adc_bits"], c["weight_mapping"],
                 c["input_slice_size"]))
        for gt in gt_pareto:
            key = (gt["Nslices"], gt["adc_bits"], gt["weight_mapping"],
                   gt["input_slice_size"])
            assert key in reported_keys, (
                f"Missing Pareto config: {gt}")


# ---------------------------------------------------------------------------
# Tests: Recommended Config
# ---------------------------------------------------------------------------
class TestRecommendedConfig:
    def test_on_frontier(self, results):
        rec = results["recommended_config"]
        rk = (rec["Nslices"], rec["adc_bits"],
              rec["weight_mapping"], rec["input_slice_size"])
        fks = [(c["Nslices"], c["adc_bits"],
                c["weight_mapping"], c["input_slice_size"])
               for c in results["pareto_frontier"]]
        assert rk in fks, "Recommended config not on Pareto frontier"

    def test_efficiency_value(self, results):
        rc = results["recommended_config"]
        exp = rc["snr_db"] / rc["cost"]
        assert abs(rc["efficiency"] - exp) < 1e-6, (
            f"efficiency: {rc['efficiency']} vs {exp}")

    def test_max_efficiency(self, results):
        rc = results["recommended_config"]
        for e in results["pareto_frontier"]:
            eff = e["snr_db"] / e["cost"]
            assert rc["efficiency"] >= eff - 1e-9, (
                f"Recommended eff {rc['efficiency']:.8f} < "
                f"frontier eff {eff:.8f} for {e}")

    def test_cost_formula(self, results):
        rc = results["recommended_config"]
        exp = _compute_cost(rc["Nslices"], rc["adc_bits"],
                            rc["weight_mapping"], rc["input_slice_size"])
        assert rc["cost"] == exp
