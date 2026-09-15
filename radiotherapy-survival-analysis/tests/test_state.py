"""
Test suite for the Radiotherapy Clinical Analytics Engine.

Verifies output structure, exact integer counts (independently computed
from raw CSV), and floating-point values within defined tolerances.

"""

import json
import csv
import os
import math
import pytest

RESULTS_PATH = '/app/results.json'
DATA_PATH = '/app/data/hnscc.csv'

# Reference values computed directly from the dataset
REF_N_PATIENTS = 215
REF_PRE_DEPLETED = 76
REF_POST_DEPLETED = 139
REF_TRANSITION_DD = 71
REF_TRANSITION_DN = 5
REF_TRANSITION_ND = 68
REF_TRANSITION_NN = 71
REF_N_INCONSISTENT = 4
REF_N_EXTENDED = 1
REF_STAGE_III_N = 31
REF_STAGE_IVA_N = 156
REF_STAGE_IVB_N = 19

# Reference floating-point values with tolerances
REF_BED_TUMOR_MEAN = 82.6811
REF_EQD2_TUMOR_MEAN = 68.9009
REF_EQD2_LATE_MEAN = 69.7482
REF_KM_12M = 0.957677
REF_KM_24M = 0.853737
REF_KM_36M = 0.791343
REF_KM_60M = 0.707414
REF_MEDIAN_OS = 105.8667
REF_MEAN_SMI_PRE = 53.9884
REF_MEAN_SMI_POST = 47.6730
REF_MEAN_SMI_CHANGE = -6.3155
REF_LOG_RANK_CHI = 0.1804


def load_results():
    """Load the results JSON file."""
    with open(RESULTS_PATH) as f:
        return json.load(f)


def load_raw_data():
    """Load CSV with BOM handling."""
    with open(DATA_PATH, encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope='module')
def results():
    assert os.path.exists(RESULTS_PATH), \
        f"Results file not found at {RESULTS_PATH}. Did you run analyze.py?"
    return load_results()


@pytest.fixture(scope='module')
def raw_data():
    return load_raw_data()


# ============================================================
# 1. STRUCTURAL TESTS
# ============================================================

class TestStructure:
    def test_results_file_exists(self):
        assert os.path.exists(RESULTS_PATH), "results.json not found"

    def test_valid_json(self):
        with open(RESULTS_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_required_top_keys(self, results):
        required = ['n_patients', 'radiobiology', 'overall_survival',
                     'stage_stratified', 'log_rank', 'sarcopenia']
        for key in required:
            assert key in results, f"Missing top-level key: {key}"

    def test_radiobiology_keys(self, results):
        rb = results['radiobiology']
        for key in ['bed_tumor_mean', 'bed_tumor_std', 'eqd2_tumor_mean',
                     'eqd2_late_mean', 'n_inconsistent_dose', 'n_extended_treatment']:
            assert key in rb, f"Missing radiobiology key: {key}"

    def test_overall_survival_keys(self, results):
        os_data = results['overall_survival']
        for key in ['km_12m', 'km_24m', 'km_36m', 'km_60m',
                     'median_os_months', 'ci_95_lower_12m', 'ci_95_upper_12m']:
            assert key in os_data, f"Missing overall_survival key: {key}"

    def test_stage_stratified_keys(self, results):
        ss = results['stage_stratified']
        for stage in ['III', 'IVA', 'IVB']:
            assert stage in ss, f"Missing stage: {stage}"
            assert 'km_24m' in ss[stage], f"Missing km_24m for stage {stage}"
            assert 'n_patients' in ss[stage], f"Missing n_patients for stage {stage}"

    def test_log_rank_keys(self, results):
        lr = results['log_rank']
        assert 'chi_square' in lr, "Missing log_rank chi_square"
        assert 'p_value' in lr, "Missing log_rank p_value"

    def test_sarcopenia_keys(self, results):
        sc = results['sarcopenia']
        required = ['pre_rt_depleted_count', 'post_rt_depleted_count',
                     'pre_rt_prevalence', 'post_rt_prevalence',
                     'mean_smi_pre_rt', 'mean_smi_post_rt', 'mean_smi_change',
                     'transition_dd', 'transition_dn', 'transition_nd', 'transition_nn']
        for key in required:
            assert key in sc, f"Missing sarcopenia key: {key}"


# ============================================================
# 2. PATIENT COUNT
# ============================================================

class TestPatientCount:
    def test_n_patients_exact(self, results):
        assert results['n_patients'] == REF_N_PATIENTS, \
            f"Expected {REF_N_PATIENTS} patients, got {results['n_patients']}"


# ============================================================
# 3. RADIOBIOLOGY
# ============================================================

class TestRadiobiology:
    def test_bed_tumor_mean(self, results):
        val = results['radiobiology']['bed_tumor_mean']
        assert abs(val - REF_BED_TUMOR_MEAN) < 1.0, \
            f"BED tumor mean {val} not within tolerance of {REF_BED_TUMOR_MEAN}"

    def test_eqd2_tumor_mean(self, results):
        val = results['radiobiology']['eqd2_tumor_mean']
        assert abs(val - REF_EQD2_TUMOR_MEAN) < 1.0, \
            f"EQD2 tumor mean {val} not within tolerance of {REF_EQD2_TUMOR_MEAN}"

    def test_eqd2_late_mean(self, results):
        val = results['radiobiology']['eqd2_late_mean']
        assert abs(val - REF_EQD2_LATE_MEAN) < 1.0, \
            f"EQD2 late mean {val} not within tolerance of {REF_EQD2_LATE_MEAN}"

    def test_bed_std_positive(self, results):
        assert results['radiobiology']['bed_tumor_std'] > 0, \
            "BED tumor std should be positive"

    def test_n_inconsistent_dose(self, results):
        assert results['radiobiology']['n_inconsistent_dose'] == REF_N_INCONSISTENT, \
            f"Expected {REF_N_INCONSISTENT} inconsistent, got {results['radiobiology']['n_inconsistent_dose']}"

    def test_n_extended_treatment(self, results):
        assert results['radiobiology']['n_extended_treatment'] == REF_N_EXTENDED, \
            f"Expected {REF_N_EXTENDED} extended, got {results['radiobiology']['n_extended_treatment']}"

    def test_bed_formula_spot_check(self, raw_data):
        """Verify BED formula on a known patient (first row)."""
        row = raw_data[0]
        td = float(row['RT Total Dose (Gy)'])
        dpf = float(row['Dose/Fraction (Gy/fx)'])
        # BED = D * (1 + d/(α/β)) with α/β=10
        expected_bed = td * (1.0 + dpf / 10.0)
        # For 69.96 Gy at 2.12 Gy/fx: BED ≈ 84.83
        assert abs(expected_bed - 84.83) < 0.5, \
            f"BED formula check failed: expected ~84.83, got {expected_bed}"


# ============================================================
# 4. KAPLAN-MEIER SURVIVAL
# ============================================================

class TestKaplanMeier:
    def test_km_non_increasing(self, results):
        os_data = results['overall_survival']
        vals = [os_data['km_12m'], os_data['km_24m'],
                os_data['km_36m'], os_data['km_60m']]
        for i in range(len(vals) - 1):
            assert vals[i] >= vals[i + 1] - 1e-9, \
                f"KM not non-increasing: S({[12,24,36,60][i]})={vals[i]} > S({[12,24,36,60][i+1]})={vals[i+1]}"

    def test_km_range(self, results):
        os_data = results['overall_survival']
        for key in ['km_12m', 'km_24m', 'km_36m', 'km_60m']:
            val = os_data[key]
            assert 0 <= val <= 1, f"KM {key}={val} out of [0,1]"

    def test_km_12m_value(self, results):
        val = results['overall_survival']['km_12m']
        assert abs(val - REF_KM_12M) < 0.02, \
            f"KM 12m: {val} vs reference {REF_KM_12M}"

    def test_km_24m_value(self, results):
        val = results['overall_survival']['km_24m']
        assert abs(val - REF_KM_24M) < 0.02, \
            f"KM 24m: {val} vs reference {REF_KM_24M}"

    def test_km_36m_value(self, results):
        val = results['overall_survival']['km_36m']
        assert abs(val - REF_KM_36M) < 0.02, \
            f"KM 36m: {val} vs reference {REF_KM_36M}"

    def test_km_60m_value(self, results):
        val = results['overall_survival']['km_60m']
        assert abs(val - REF_KM_60M) < 0.02, \
            f"KM 60m: {val} vs reference {REF_KM_60M}"

    def test_median_os(self, results):
        med = results['overall_survival']['median_os_months']
        assert med is not None, "Median OS should not be None for this dataset"
        assert abs(med - REF_MEDIAN_OS) < 5.0, \
            f"Median OS: {med} vs reference {REF_MEDIAN_OS}"

    def test_ci_bounds(self, results):
        os_data = results['overall_survival']
        km12 = os_data['km_12m']
        lo = os_data['ci_95_lower_12m']
        hi = os_data['ci_95_upper_12m']
        assert lo <= km12 + 1e-9, f"CI lower {lo} > KM12 {km12}"
        assert hi >= km12 - 1e-9, f"CI upper {hi} < KM12 {km12}"
        assert 0 <= lo, f"CI lower bound {lo} < 0"
        assert hi <= 1, f"CI upper bound {hi} > 1"
        # CI width should be reasonable (not too wide)
        assert (hi - lo) < 0.2, f"CI width {hi - lo} seems too wide"


# ============================================================
# 5. STAGE-STRATIFIED ANALYSIS
# ============================================================

class TestStageStratified:
    def test_stage_iii_count(self, results):
        assert results['stage_stratified']['III']['n_patients'] == REF_STAGE_III_N, \
            f"Stage III: expected {REF_STAGE_III_N}, got {results['stage_stratified']['III']['n_patients']}"

    def test_stage_iva_count(self, results):
        assert results['stage_stratified']['IVA']['n_patients'] == REF_STAGE_IVA_N, \
            f"Stage IVA: expected {REF_STAGE_IVA_N}, got {results['stage_stratified']['IVA']['n_patients']}"

    def test_stage_ivb_count(self, results):
        assert results['stage_stratified']['IVB']['n_patients'] == REF_STAGE_IVB_N, \
            f"Stage IVB: expected {REF_STAGE_IVB_N}, got {results['stage_stratified']['IVB']['n_patients']}"

    def test_stage_km24m_range(self, results):
        ss = results['stage_stratified']
        for stage in ['III', 'IVA', 'IVB']:
            val = ss[stage]['km_24m']
            assert 0 <= val <= 1, f"Stage {stage} km_24m={val} out of [0,1]"

    def test_stage_ivb_worst_24m(self, results):
        """Stage IVB should generally have worst 24-month survival."""
        ss = results['stage_stratified']
        assert ss['IVB']['km_24m'] <= ss['IVA']['km_24m'] + 0.05, \
            f"IVB km_24m={ss['IVB']['km_24m']} unexpectedly higher than IVA={ss['IVA']['km_24m']}"


# ============================================================
# 6. LOG-RANK TEST
# ============================================================

class TestLogRank:
    def test_chi_square_non_negative(self, results):
        assert results['log_rank']['chi_square'] >= 0, \
            "Chi-square must be non-negative"

    def test_p_value_range(self, results):
        p = results['log_rank']['p_value']
        assert 0 <= p <= 1, f"p-value {p} out of [0,1]"

    def test_chi_square_value(self, results):
        val = results['log_rank']['chi_square']
        assert abs(val - REF_LOG_RANK_CHI) < 0.5, \
            f"Log-rank chi-sq: {val} vs reference {REF_LOG_RANK_CHI}"

    def test_p_value_not_significant(self, results):
        """For this dataset, Stage III vs IV difference is not significant."""
        p = results['log_rank']['p_value']
        assert p > 0.05, \
            f"Expected non-significant p-value (>0.05), got {p}"


# ============================================================
# 7. SARCOPENIA
# ============================================================

class TestSarcopenia:
    def test_pre_rt_depleted_count(self, results):
        assert results['sarcopenia']['pre_rt_depleted_count'] == REF_PRE_DEPLETED, \
            f"Pre-RT depleted: expected {REF_PRE_DEPLETED}, got {results['sarcopenia']['pre_rt_depleted_count']}"

    def test_post_rt_depleted_count(self, results):
        assert results['sarcopenia']['post_rt_depleted_count'] == REF_POST_DEPLETED, \
            f"Post-RT depleted: expected {REF_POST_DEPLETED}, got {results['sarcopenia']['post_rt_depleted_count']}"

    def test_prevalence_consistent_pre(self, results):
        sc = results['sarcopenia']
        expected = REF_PRE_DEPLETED / REF_N_PATIENTS
        assert abs(sc['pre_rt_prevalence'] - expected) < 0.01, \
            f"Pre-RT prevalence {sc['pre_rt_prevalence']} inconsistent with count"

    def test_prevalence_consistent_post(self, results):
        sc = results['sarcopenia']
        expected = REF_POST_DEPLETED / REF_N_PATIENTS
        assert abs(sc['post_rt_prevalence'] - expected) < 0.01, \
            f"Post-RT prevalence {sc['post_rt_prevalence']} inconsistent with count"

    def test_transitions_exact(self, results):
        sc = results['sarcopenia']
        assert sc['transition_dd'] == REF_TRANSITION_DD, \
            f"DD: expected {REF_TRANSITION_DD}, got {sc['transition_dd']}"
        assert sc['transition_dn'] == REF_TRANSITION_DN, \
            f"DN: expected {REF_TRANSITION_DN}, got {sc['transition_dn']}"
        assert sc['transition_nd'] == REF_TRANSITION_ND, \
            f"ND: expected {REF_TRANSITION_ND}, got {sc['transition_nd']}"
        assert sc['transition_nn'] == REF_TRANSITION_NN, \
            f"NN: expected {REF_TRANSITION_NN}, got {sc['transition_nn']}"

    def test_transitions_sum(self, results):
        sc = results['sarcopenia']
        total = sc['transition_dd'] + sc['transition_dn'] + \
                sc['transition_nd'] + sc['transition_nn']
        assert total == REF_N_PATIENTS, \
            f"Transitions sum {total} should equal n_patients {REF_N_PATIENTS}"

    def test_smi_pre_value(self, results):
        val = results['sarcopenia']['mean_smi_pre_rt']
        assert abs(val - REF_MEAN_SMI_PRE) < 1.0, \
            f"Mean SMI pre: {val} vs reference {REF_MEAN_SMI_PRE}"

    def test_smi_post_value(self, results):
        val = results['sarcopenia']['mean_smi_post_rt']
        assert abs(val - REF_MEAN_SMI_POST) < 1.0, \
            f"Mean SMI post: {val} vs reference {REF_MEAN_SMI_POST}"

    def test_smi_change_negative(self, results):
        """SMI should decrease during treatment (muscle wasting)."""
        assert results['sarcopenia']['mean_smi_change'] < 0, \
            "Mean SMI change should be negative (muscle loss during RT)"

    def test_smi_change_value(self, results):
        val = results['sarcopenia']['mean_smi_change']
        assert abs(val - REF_MEAN_SMI_CHANGE) < 1.0, \
            f"Mean SMI change: {val} vs reference {REF_MEAN_SMI_CHANGE}"

    def test_post_rt_prevalence_higher(self, results):
        """Post-RT sarcopenia prevalence should exceed pre-RT."""
        sc = results['sarcopenia']
        assert sc['post_rt_prevalence'] > sc['pre_rt_prevalence'], \
            "Post-RT sarcopenia prevalence should be higher than pre-RT"
