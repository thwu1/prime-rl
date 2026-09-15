"""Tests for the river network hydrological analysis pipeline.

Verifies network cleaning, topological sort, baseflow separation,
recession analysis, hydrological signatures, and flow accumulation
by comparing against independent reference computations.

"""
import json
import math
import os

import networkx as nx
import numpy as np
import pandas as pd
import pytest
from scipy import stats as sp_stats


# ====================================================================
# Reference Implementations (independent ground truth)
# ====================================================================

def ref_forward_pass(q, alpha):
    """Reference forward pass."""
    n = len(q)
    qf = np.zeros(n, dtype=np.float64)
    qf[0] = q[0] - np.min(q)
    for i in range(1, n):
        qf[i] = alpha * qf[i - 1] + 0.5 * (1.0 + alpha) * (q[i] - q[i - 1])
    return np.where(qf > 0, q - qf, q)


def ref_backward_pass(q, alpha):
    """Reference backward pass."""
    n = len(q)
    qf = np.zeros(n, dtype=np.float64)
    qf[-1] = q[-1] - np.min(q)
    for i in range(n - 2, -1, -1):
        qf[i] = alpha * qf[i + 1] + 0.5 * (1.0 + alpha) * (q[i] - q[i + 1])
    return np.where(qf > 0, q - qf, q)


def ref_baseflow(q, alpha=0.925, n_passes=3, pad_width=10):
    """Reference baseflow separation."""
    q = np.asarray(q, dtype=np.float64).copy()
    q = np.pad(q, pad_width, mode='edge')
    qb = ref_forward_pass(q, alpha)
    extra = round(0.5 * (n_passes - 1))
    for _ in range(extra):
        qb = ref_forward_pass(ref_backward_pass(qb, alpha), alpha)
    qb = qb[pad_width:-pad_width]
    qb[qb < 0] = 0.0
    return qb


def ref_bfi(q, alpha=0.925, n_passes=3, pad_width=10):
    """Reference BFI computation."""
    q = np.asarray(q, dtype=np.float64)
    total = np.sum(q)
    if total < 1e-6:
        return 0.0
    qb = ref_baseflow(q, alpha, n_passes, pad_width)
    return float(np.sum(qb) / total)


def ref_flood_moments(q_df):
    """Reference flood moments computation."""
    annual_max = q_df.resample('YE').max()
    maf = float(annual_max.mean().iloc[0])
    n = len(q_df)
    values = q_df.iloc[:, 0].values
    s2 = np.sum((values - maf) ** 2) / (n - 1)
    cv = float(np.sqrt(s2) / maf)
    cs = float(n * np.sum((values - maf) ** 3) / ((n - 1) * (n - 2) * s2 ** 1.5))
    return maf, cv, cs


def ref_seasonality(q_series):
    """Reference Walsh seasonality index."""
    annual = q_series.resample('YE').sum()
    monthly = q_series.resample('ME').sum()
    si_vals = []
    for year_end in annual.index:
        r = annual.loc[year_end]
        if r < 1e-6:
            continue
        ym = monthly[monthly.index.year == year_end.year]
        si_vals.append(float((ym - r / 12.0).abs().sum() / r))
    return float(np.mean(si_vals)) if si_vals else 0.0


def ref_elasticity(q_series, p_series):
    """Reference streamflow elasticity."""
    q_annual = q_series.resample('YE').mean()
    p_annual = p_series.resample('YE').mean()
    dq = q_annual.diff()
    dp = p_annual.diff()
    return float(np.nanmedian(dq / dp * p_annual / q_annual))


def ref_route_flow(q_in, length_km, slope):
    """Reference routing function."""
    if slope <= 0 or length_km <= 0:
        return q_in
    celerity = slope ** 0.3
    travel_time_days = (length_km * 1000.0) / (celerity * 86400.0)
    return q_in * math.exp(-0.5 * travel_time_days)


def ref_find_segments(q, min_length=15):
    """Reference recession segment detection."""
    n = len(q)
    segments = []
    start = None
    for i in range(1, n):
        if q[i] < q[i - 1]:
            if start is None:
                start = i - 1
        else:
            if start is not None:
                end = i - 1
                if (end - start + 1) >= min_length:
                    segments.append((start, end))
                start = None
    if start is not None:
        end = n - 1
        if (end - start + 1) >= min_length:
            segments.append((start, end))
    if segments:
        return np.array(segments, dtype=np.int64)
    return np.empty((0, 2), dtype=np.int64)


def ref_exponential_mrc(q, flow_section):
    """Reference master recession curve via exponential matching strip."""
    start_values = q[flow_section[:, 0]]
    sort_indices = np.argsort(start_values)[::-1]

    first_idx = sort_indices[0]
    s0, e0 = flow_section[first_idx]
    mrc = np.column_stack((
        np.arange(1, e0 - s0 + 2, dtype=np.float64),
        q[s0:e0 + 1]
    ))

    for i in range(1, len(flow_section)):
        seg_idx = sort_indices[i]
        s, e = flow_section[seg_idx]
        log_q = np.log(np.maximum(mrc[:, 1], 1e-10))
        coeffs = np.polyfit(mrc[:, 0], log_q, 1)
        start_val = max(start_values[seg_idx], 1e-10)
        timeshift = (np.log(start_val) - coeffs[1]) / coeffs[0]
        new_seg = np.column_stack((
            timeshift + np.arange(1, e - s + 2, dtype=np.float64),
            q[s:e + 1]
        ))
        mrc = np.vstack((mrc, new_seg))
    return mrc


def ref_recession_constant(q, min_length=15):
    """Reference recession constant computation."""
    segments = ref_find_segments(q, min_length)
    if len(segments) < 2:
        return float('nan')
    mrc = ref_exponential_mrc(q, segments)
    log_q = np.log(np.maximum(mrc[:, 1], 1e-10))
    slope_val, _, _, _, _ = sp_stats.linregress(mrc[:, 0], log_q)
    return float(-slope_val)


# ====================================================================
# Fixture: load results
# ====================================================================

@pytest.fixture(scope="session")
def results():
    """Load pipeline results."""
    path = "/app/results.json"
    assert os.path.exists(path), (
        "results.json not found. The pipeline must write /app/results.json."
    )
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def gauge_data():
    """Load all gauge observation data."""
    gauge_locs = pd.read_csv('/app/data/gauge_locations.csv')
    data = {}
    for _, row in gauge_locs.iterrows():
        gid = row['gauge_id']
        df = pd.read_csv(
            f'/app/data/gauges/{gid}.csv',
            parse_dates=['date'],
            index_col='date'
        )
        data[gid] = {
            'comid': int(row['comid']),
            'df': df,
        }
    return data


# ====================================================================
# Test: Results structure
# ====================================================================

class TestResultsSchema:
    """Verify the output JSON has all required fields."""

    def test_top_level_keys(self, results):
        for key in ['network', 'gauges', 'flow_accumulation']:
            assert key in results, f"Missing top-level key: {key}"

    def test_network_keys(self, results):
        net = results['network']
        for key in ['original_count', 'cleaned_count', 'removed_comids',
                     'topological_order']:
            assert key in net, f"Missing network key: {key}"

    def test_gauge_keys(self, results):
        gauges = results['gauges']
        assert len(gauges) >= 5, f"Expected 5 gauges, got {len(gauges)}"
        for gid, g in gauges.items():
            for key in ['comid', 'bfi', 'recession_k', 'flood_moments',
                         'fdc_slope', 'seasonality_index',
                         'streamflow_elasticity']:
                assert key in g, f"Missing key '{key}' in gauge {gid}"
            fm = g['flood_moments']
            for key in ['MAF', 'CV', 'CS']:
                assert key in fm, (
                    f"Missing '{key}' in flood_moments for {gid}"
                )


# ====================================================================
# Test: Network cleaning
# ====================================================================

class TestNetworkCleaning:
    """Verify correct network cleaning operations."""

    def test_original_count(self, results):
        assert results['network']['original_count'] == 18

    def test_cleaned_count(self, results):
        assert results['network']['cleaned_count'] == 14, (
            f"Expected 14 segments after cleaning, "
            f"got {results['network']['cleaned_count']}"
        )

    def test_coastline_removed(self, results):
        removed = results['network']['removed_comids']
        assert 9001 in removed, "Coastline feature (comid=9001) not removed"

    def test_tiny_network_removed(self, results):
        removed = results['network']['removed_comids']
        assert 8001 in removed and 8002 in removed, (
            "Tiny isolated network (8001, 8002) not removed"
        )

    def test_divergent_isolated_removed(self, results):
        removed = results['network']['removed_comids']
        assert 6001 in removed, (
            "Divergent path (comid=6001) should be isolated and removed"
        )

    def test_main_segments_retained(self, results):
        topo = results['network']['topological_order']
        expected_present = [1001, 1002, 1003, 1004, 1005,
                            2001, 2002, 2003,
                            3001, 3002,
                            4001, 4002, 4003,
                            5001]
        for comid in expected_present:
            assert comid in topo, (
                f"Expected comid {comid} in cleaned network but not found"
            )


# ====================================================================
# Test: Topological sort
# ====================================================================

class TestTopologicalSort:
    """Verify topological ordering is valid."""

    def test_length(self, results):
        topo = results['network']['topological_order']
        assert len(topo) == 14, (
            f"Topological order should have 14 segments, got {len(topo)}"
        )

    def test_valid_ordering(self, results):
        """Each segment must appear before its downstream neighbor."""
        topo = results['network']['topological_order']
        pos = {comid: i for i, comid in enumerate(topo)}

        edges = [
            (1001, 1002), (1002, 1003), (1003, 1004), (1004, 1005),
            (2001, 2002), (2002, 2003), (2003, 1002),
            (3001, 3002), (3002, 1003),
            (4001, 4002), (4002, 4003), (4003, 1004),
            (5001, 4002),
        ]
        for u, v in edges:
            assert pos[u] < pos[v], (
                f"Topological violation: {u} (pos {pos[u]}) should "
                f"come before {v} (pos {pos[v]})"
            )


# ====================================================================
# Test: Baseflow separation
# ====================================================================

class TestBaseflow:
    """Verify baseflow computation against reference."""

    def test_bfi_range_all_gauges(self, results):
        for gid, g in results['gauges'].items():
            bfi = g['bfi']
            assert 0 < bfi < 1, (
                f"BFI for {gid} = {bfi} is outside valid range (0, 1)"
            )

    def test_bfi_reference_gauge_a(self, results, gauge_data):
        """Independently compute BFI for gauge_A and compare."""
        q = gauge_data['gauge_A']['df']['streamflow_mm'].values
        expected_bfi = ref_bfi(q)
        actual_bfi = results['gauges']['gauge_A']['bfi']
        np.testing.assert_allclose(
            actual_bfi, expected_bfi, rtol=0.02,
            err_msg="BFI for gauge_A doesn't match reference computation"
        )

    def test_bfi_reference_gauge_c(self, results, gauge_data):
        """Independently compute BFI for gauge_C and compare."""
        q = gauge_data['gauge_C']['df']['streamflow_mm'].values
        expected_bfi = ref_bfi(q)
        actual_bfi = results['gauges']['gauge_C']['bfi']
        np.testing.assert_allclose(
            actual_bfi, expected_bfi, rtol=0.02,
            err_msg="BFI for gauge_C doesn't match reference computation"
        )

    def test_baseflow_nonnegative_gauge_a(self, results, gauge_data):
        """Baseflow values must be non-negative (physical constraint)."""
        actual_bfi = results['gauges']['gauge_A']['bfi']
        assert actual_bfi <= 1.0, (
            f"BFI for gauge_A = {actual_bfi} > 1.0, indicating "
            f"baseflow computation issue"
        )


# ====================================================================
# Test: Flood moments
# ====================================================================

class TestFloodMoments:
    """Verify flood moment computation against reference."""

    def test_maf_positive_all(self, results):
        for gid, g in results['gauges'].items():
            assert g['flood_moments']['MAF'] > 0, (
                f"MAF for {gid} should be positive"
            )
            assert g['flood_moments']['CV'] > 0, (
                f"CV for {gid} should be positive"
            )

    def test_flood_moments_reference_gauge_b(self, results, gauge_data):
        """Independently compute flood moments for gauge_B and compare."""
        df = gauge_data['gauge_B']['df']
        q_df = df['streamflow_mm'].to_frame('streamflow')
        exp_maf, exp_cv, exp_cs = ref_flood_moments(q_df)

        actual = results['gauges']['gauge_B']['flood_moments']

        np.testing.assert_allclose(
            actual['MAF'], exp_maf, rtol=0.01,
            err_msg="MAF for gauge_B doesn't match reference"
        )
        np.testing.assert_allclose(
            actual['CV'], exp_cv, rtol=0.01,
            err_msg="CV for gauge_B doesn't match reference"
        )
        np.testing.assert_allclose(
            actual['CS'], exp_cs, rtol=0.02,
            err_msg="CS for gauge_B doesn't match reference computation"
        )


# ====================================================================
# Test: Seasonality index
# ====================================================================

class TestSeasonality:
    """Verify Walsh seasonality index against reference."""

    def test_positive_all(self, results):
        for gid, g in results['gauges'].items():
            assert g['seasonality_index'] > 0.01, (
                f"Seasonality index for {gid} = "
                f"{g['seasonality_index']:.6f} is unexpectedly low "
                f"for data with clear seasonal patterns"
            )

    def test_reference_gauge_d(self, results, gauge_data):
        """Independently compute seasonality for gauge_D and compare."""
        q_series = gauge_data['gauge_D']['df']['streamflow_mm']
        expected_si = ref_seasonality(q_series)
        actual_si = results['gauges']['gauge_D']['seasonality_index']
        np.testing.assert_allclose(
            actual_si, expected_si, atol=0.02,
            err_msg="Seasonality index for gauge_D doesn't match reference"
        )


# ====================================================================
# Test: Streamflow elasticity
# ====================================================================

class TestElasticity:
    """Verify streamflow elasticity against reference."""

    def test_reference_gauge_e(self, results, gauge_data):
        """Independently compute elasticity for gauge_E and compare."""
        df = gauge_data['gauge_E']['df']
        q_series = df['streamflow_mm']
        p_series = df['precipitation_mm']
        expected_se = ref_elasticity(q_series, p_series)
        actual_se = results['gauges']['gauge_E']['streamflow_elasticity']
        np.testing.assert_allclose(
            actual_se, expected_se, rtol=0.05,
            err_msg="Streamflow elasticity for gauge_E doesn't match reference"
        )

    def test_finite_all(self, results):
        for gid, g in results['gauges'].items():
            se = g['streamflow_elasticity']
            assert np.isfinite(se), (
                f"Streamflow elasticity for {gid} is not finite: {se}"
            )


# ====================================================================
# Test: Recession analysis
# ====================================================================

class TestRecession:
    """Verify recession constant against reference implementation."""

    def test_k_physical_range(self, results):
        for gid, g in results['gauges'].items():
            k = g['recession_k']
            assert np.isfinite(k), (
                f"Recession K for {gid} is not finite: {k}"
            )
            assert 0.001 < k < 0.5, (
                f"Recession K for {gid} = {k:.6f} is outside "
                f"physical range [0.001, 0.5]"
            )

    def test_k_positive_all(self, results):
        for gid, g in results['gauges'].items():
            assert g['recession_k'] > 0, (
                f"Recession K for {gid} should be positive"
            )

    def test_k_reference_gauge_b(self, results, gauge_data):
        """Independently compute recession K for gauge_B and compare."""
        q = gauge_data['gauge_B']['df']['streamflow_mm'].values
        expected_k = ref_recession_constant(q)
        actual_k = results['gauges']['gauge_B']['recession_k']
        assert np.isfinite(expected_k), "Reference recession K is not finite"
        np.testing.assert_allclose(
            actual_k, expected_k, rtol=0.02,
            err_msg="Recession K for gauge_B doesn't match reference"
        )

    def test_k_reference_gauge_d(self, results, gauge_data):
        """Independently compute recession K for gauge_D and compare."""
        q = gauge_data['gauge_D']['df']['streamflow_mm'].values
        expected_k = ref_recession_constant(q)
        actual_k = results['gauges']['gauge_D']['recession_k']
        assert np.isfinite(expected_k), "Reference recession K is not finite"
        np.testing.assert_allclose(
            actual_k, expected_k, rtol=0.02,
            err_msg="Recession K for gauge_D doesn't match reference"
        )


# ====================================================================
# Test: FDC slope
# ====================================================================

class TestFDCSlope:
    """Verify flow duration curve slope."""

    def test_finite_all(self, results):
        for gid, g in results['gauges'].items():
            assert np.isfinite(g['fdc_slope']), (
                f"FDC slope for {gid} is not finite"
            )

    def test_reference_gauge_a(self, results, gauge_data):
        """Independently compute FDC slope for gauge_A and compare."""
        q = gauge_data['gauge_A']['df']['streamflow_mm'].values
        q_log = np.log(np.clip(q, 1e-3, None))
        p33 = np.percentile(q_log, 33)
        p67 = np.percentile(q_log, 67)
        expected = (p67 - p33) / (34.0 / 100.0)

        actual = results['gauges']['gauge_A']['fdc_slope']
        np.testing.assert_allclose(
            actual, expected, rtol=0.02,
            err_msg="FDC slope for gauge_A doesn't match reference"
        )


# ====================================================================
# Test: Flow accumulation
# ====================================================================

class TestFlowAccumulation:
    """Verify flow accumulation through the network."""

    def test_all_positive(self, results):
        fa = results['flow_accumulation']
        for comid, val in fa.items():
            assert val > 0, (
                f"Accumulated flow at comid {comid} should be positive"
            )

    def test_headwater_exact(self, results):
        """Headwater nodes (no upstream) should have flow = area * 0.001."""
        fa = results['flow_accumulation']
        headwaters = {
            '1001': 12.5 * 0.001,
            '2001': 5.0 * 0.001,
            '3001': 3.5 * 0.001,
            '4001': 6.0 * 0.001,
            '5001': 3.0 * 0.001,
        }
        for comid, expected in headwaters.items():
            assert comid in fa, (
                f"Headwater comid {comid} missing from flow_accumulation"
            )
            np.testing.assert_allclose(
                fa[comid], expected, rtol=1e-6,
                err_msg=(
                    f"Headwater {comid} accumulated flow should be "
                    f"totdasqkm * 0.001 = {expected}"
                )
            )

    def test_downstream_increases_main_stem(self, results):
        """Flow should generally increase along the main stem."""
        fa = results['flow_accumulation']
        main_stem = ['1001', '1002', '1003', '1004', '1005']
        for i in range(len(main_stem) - 1):
            upstream = fa[main_stem[i]]
            downstream = fa[main_stem[i + 1]]
            assert downstream > upstream, (
                f"Main stem flow should increase: "
                f"comid {main_stem[i]} ({upstream:.6f}) -> "
                f"comid {main_stem[i+1]} ({downstream:.6f})"
            )

    def test_confluence_combines_flow(self, results):
        """At confluences, accumulated flow should include both branches."""
        fa = results['flow_accumulation']
        assert fa['1002'] > fa['1001'], (
            "Flow at 1002 should exceed 1001 (receives tributary)"
        )

    def test_confluence_value_1002(self, results):
        """Verify accumulated flow at confluence 1002 against reference."""
        fa = results['flow_accumulation']

        # Trace through upstream segments using reference routing
        acc_1001 = 12.5 * 0.001  # headwater
        acc_2001 = 5.0 * 0.001   # headwater

        # 2002: receives 2001, lengthkm=4.5, slope=0.009, totdasqkm=8.5
        routed = ref_route_flow(acc_2001, 4.5, 0.009)
        acc_2002 = routed + 8.5 * 0.001

        # 2003: receives 2002, lengthkm=7.2, slope=0.007, totdasqkm=15.0
        routed = ref_route_flow(acc_2002, 7.2, 0.007)
        acc_2003 = routed + 15.0 * 0.001

        # 1002: receives 1001 and 2003, lengthkm=8.1, slope=0.005, totdasqkm=45.0
        upstream_total = acc_1001 + acc_2003
        routed = ref_route_flow(upstream_total, 8.1, 0.005)
        expected_1002 = routed + 45.0 * 0.001

        np.testing.assert_allclose(
            fa['1002'], expected_1002, rtol=1e-4,
            err_msg="Accumulated flow at confluence 1002 doesn't match reference"
        )

    def test_outlet_largest(self, results):
        """Outlet should have the largest accumulated flow."""
        fa = results['flow_accumulation']
        outlet_flow = fa['1005']
        for comid, val in fa.items():
            if comid != '1005':
                assert outlet_flow >= val, (
                    f"Outlet (1005) flow {outlet_flow:.6f} should be >= "
                    f"comid {comid} flow {val:.6f}"
                )

    def test_accumulation_count(self, results):
        """Should have accumulated flow for all 14 cleaned segments."""
        fa = results['flow_accumulation']
        assert len(fa) == 14, (
            f"Expected 14 entries in flow_accumulation, got {len(fa)}"
        )
