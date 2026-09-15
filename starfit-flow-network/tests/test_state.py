"""Tests for STARFIT Reservoir Network Simulation (NetCDF output).

"""

import math
import os
import subprocess

import numpy as np
import pytest
from netCDF4 import Dataset

OMEGA = 1.0 / 52.0

# ---- Reservoir parameters (hardcoded for independent verification) --------
PARAMS = {
    "A": {
        "GRanD_CAP_MCM": 1200.0, "Obs_MEANFLOW_CUMECS": 85.0,
        "NORhi_min": 60.0, "NORhi_max": 95.0,
        "NORhi_alpha": 5.0, "NORhi_beta": 3.0, "NORhi_mu": 78.0,
        "NORlo_min": 20.0, "NORlo_max": 55.0,
        "NORlo_alpha": -3.0, "NORlo_beta": 2.0, "NORlo_mu": 35.0,
        "Release_min": -0.4, "Release_max": 1.8,
        "Release_alpha1": 0.12, "Release_alpha2": -0.04,
        "Release_beta1": 0.09, "Release_beta2": -0.025,
        "Release_p1": 0.18, "Release_p2": 0.08, "Release_c": -0.02,
    },
    "C": {
        "GRanD_CAP_MCM": 350.0, "Obs_MEANFLOW_CUMECS": 30.0,
        "NORhi_min": 58.0, "NORhi_max": 90.0,
        "NORhi_alpha": 6.0, "NORhi_beta": -4.0, "NORhi_mu": 72.0,
        "NORlo_min": 15.0, "NORlo_max": 48.0,
        "NORlo_alpha": -4.0, "NORlo_beta": 3.0, "NORlo_mu": 30.0,
        "Release_min": -0.6, "Release_max": 1.5,
        "Release_alpha1": 0.15, "Release_alpha2": -0.03,
        "Release_beta1": 0.06, "Release_beta2": -0.02,
        "Release_p1": 0.20, "Release_p2": 0.05, "Release_c": -0.03,
    },
}

CAPACITIES = {0: 1200.0, 2: 800.0, 4: 350.0}


# ---- Reference implementation (independent of agent code) ----------------

def get_epiweek(day):
    return min(1 + (day - 1) // 7, 52)


def ref_max_nor(params, ew):
    v = (params["NORhi_mu"]
         + params["NORhi_alpha"] * np.sin(2 * np.pi * OMEGA * ew)
         + params["NORhi_beta"] * np.cos(2 * np.pi * OMEGA * ew))
    return float(np.minimum(params["NORhi_max"],
                            np.maximum(params["NORhi_min"], v)))


def ref_min_nor(params, ew):
    v = (params["NORlo_mu"]
         + params["NORlo_alpha"] * np.sin(2 * np.pi * OMEGA * ew)
         + params["NORlo_beta"] * np.cos(2 * np.pi * OMEGA * ew))
    return float(np.minimum(params["NORlo_max"],
                            np.maximum(params["NORlo_min"], v)))


def ref_calc_release(ew, cap, stor, inflow, obs, params):
    s3 = stor * 1e6
    c3 = cap * 1e6
    mn = ref_max_nor(params, ew)
    ln = ref_min_nor(params, ew)
    fwv = 7.0 * inflow * 86400.0
    mwv = 7.0 * obs * 86400.0
    si = fwv / mwv - 1.0
    swr = (params["Release_alpha1"] * np.sin(2 * np.pi * OMEGA * ew)
           + params["Release_alpha2"] * np.sin(4 * np.pi * OMEGA * ew)
           + params["Release_beta1"] * np.cos(2 * np.pi * OMEGA * ew)
           + params["Release_beta2"] * np.cos(4 * np.pi * OMEGA * ew))
    r_lo = mwv * (1.0 + params["Release_min"]) / 7.0
    r_hi = mwv * (1.0 + params["Release_max"]) / 7.0
    avail = (100.0 * s3 / c3 - ln) / (mn - ln)
    rel = mwv * (1.0 + (swr + params["Release_c"]
                        + params["Release_p1"] * avail
                        + params["Release_p2"] * si)) / 7.0
    ra = (s3 - c3 * mn / 100.0 + fwv) / 7.0
    rb = (s3 - c3 * ln / 100.0 + fwv) / 7.0
    if avail > 1.0:
        rel = ra
    if avail < 0.0:
        rel = rb
    rel = max(r_lo, min(r_hi, rel))
    return float(rel), float(avail)


def get_lateral_inflow(day, node_id):
    d = day
    if node_id == 0:
        return (50.0 + 30.0 * math.sin(2 * math.pi * d / 365.0)
                + 10.0 * math.sin(4 * math.pi * d / 365.0))
    elif node_id == 1:
        return 5.0
    elif node_id == 2:
        return 8.0
    elif node_id == 3:
        return 3.0
    elif node_id == 4:
        return (20.0 + 15.0 * math.sin(2 * math.pi * d / 365.0
                                        + math.pi / 4.0))
    return 0.0


def ref_simulate_headwater(params, laterals, n_days=365, n_sub=24):
    cap = params["GRanD_CAP_MCM"]
    obs = params["Obs_MEANFLOW_CUMECS"]
    m2m = 3600.0 / 1e6
    m2f = 1e6 / 3600.0
    hi = ref_max_nor(params, 1)
    lo = ref_min_nor(params, 1)
    stor = cap * (hi + lo) / 2.0 / 100.0
    results = []
    for day in range(1, n_days + 1):
        ew = get_epiweek(day)
        lat = laterals[day - 1]
        oa, ra, sa = 0.0, 0.0, 0.0
        for _ in range(n_sub):
            rel_m3pd, _ = ref_calc_release(ew, cap, stor, lat, obs, params)
            rs = rel_m3pd / 86400.0
            sc = (lat - rs) * m2m
            if stor + sc < 0.0:
                rs = max(rs + (stor + sc) * m2f, 0.0)
                sc = (lat - rs) * m2m
            stor = max(stor + sc, 0.0)
            sp = 0.0
            if stor > cap:
                sp = (stor - cap) * m2f
                stor = cap
            oa += rs + sp
            ra += rs
            sa += sp
        results.append({
            "outflow_cms": oa / n_sub,
            "storage_MCM": stor,
            "release_cms": ra / n_sub,
            "spill_cms": sa / n_sub,
        })
    return results


def initial_storage(params):
    hi = ref_max_nor(params, 1)
    lo = ref_min_nor(params, 1)
    return params["GRanD_CAP_MCM"] * (hi + lo) / 2.0 / 100.0


# ---- Fixtures -------------------------------------------------------------

@pytest.fixture(scope="module")
def run_simulation():
    """Run the agent's simulation and parse the output NetCDF."""
    assert os.path.isfile("/app/simulate.py"), \
        "/app/simulate.py does not exist"

    result = subprocess.run(
        ["python3", "/app/simulate.py"],
        capture_output=True, text=True, timeout=300, cwd="/app",
    )
    assert result.returncode == 0, (
        f"Simulation failed (exit {result.returncode}):\n"
        f"--- stdout ---\n{result.stdout[-2000:]}\n"
        f"--- stderr ---\n{result.stderr[-2000:]}"
    )

    nc_path = "/app/output/simulation.nc"
    assert os.path.isfile(nc_path), \
        f"{nc_path} not produced by simulate.py"

    ds = Dataset(nc_path, "r")
    assert "day" in ds.dimensions, "Missing dimension 'day'"
    assert "node" in ds.dimensions, "Missing dimension 'node'"
    n_days = len(ds.dimensions["day"])
    n_nodes = len(ds.dimensions["node"])

    for var in ("day", "node_id", "outflow_cms", "storage_MCM",
                "release_cms", "spill_cms"):
        assert var in ds.variables, f"Missing variable '{var}'"

    day_vals = ds.variables["day"][:].data
    node_vals = ds.variables["node_id"][:].data

    data = {}
    for di in range(n_days):
        d = int(day_vals[di])
        data[d] = {}
        for ni in range(n_nodes):
            nid = int(node_vals[ni])
            data[d][nid] = {
                "outflow_cms": float(ds.variables["outflow_cms"][di, ni]),
                "storage_MCM": float(ds.variables["storage_MCM"][di, ni]),
                "release_cms": float(ds.variables["release_cms"][di, ni]),
                "spill_cms": float(ds.variables["spill_cms"][di, ni]),
            }
    ds.close()
    return data


# ---- Tests -----------------------------------------------------------------

class TestOutputFormat:
    """Verify the output NetCDF structure."""

    def test_output_completeness(self, run_simulation):
        assert len(run_simulation) == 365, \
            f"Expected 365 days, got {len(run_simulation)}"
        for day in range(1, 366):
            assert day in run_simulation, f"Missing day {day}"
            assert len(run_simulation[day]) == 5, \
                f"Day {day}: expected 5 nodes, got {len(run_simulation[day])}"
            for nid in range(5):
                assert nid in run_simulation[day], \
                    f"Day {day}: missing node {nid}"


class TestPhysicalConstraints:
    """Verify physical constraints on the simulation output."""

    def test_storage_non_negative(self, run_simulation):
        for day in range(1, 366):
            for nid in [0, 2, 4]:
                s = run_simulation[day][nid]["storage_MCM"]
                assert s >= -1e-10, \
                    f"Day {day} node {nid}: negative storage {s:.8e}"

    def test_storage_within_capacity(self, run_simulation):
        for day in range(1, 366):
            for nid, cap in CAPACITIES.items():
                s = run_simulation[day][nid]["storage_MCM"]
                assert s <= cap + 1e-6, \
                    f"Day {day} node {nid}: storage {s:.6f} > capacity {cap}"

    def test_outflow_non_negative(self, run_simulation):
        for day in range(1, 366):
            for nid in range(5):
                o = run_simulation[day][nid]["outflow_cms"]
                assert o >= -1e-10, \
                    f"Day {day} node {nid}: negative outflow {o:.8e}"

    def test_passthrough_zero_storage(self, run_simulation):
        for day in range(1, 366):
            for nid in [1, 3]:
                s = run_simulation[day][nid]["storage_MCM"]
                assert abs(s) < 1e-10, \
                    f"Day {day} node {nid}: non-zero storage {s:.8e}"

    def test_passthrough_zero_spill(self, run_simulation):
        for day in range(1, 366):
            for nid in [1, 3]:
                sp = run_simulation[day][nid]["spill_cms"]
                assert abs(sp) < 1e-10, \
                    f"Day {day} node {nid}: non-zero spill {sp:.8e}"


class TestMassBalance:
    """Verify conservation of mass."""

    def test_daily_mass_balance(self, run_simulation):
        prev_storage = {
            0: initial_storage(PARAMS["A"]),
            2: initial_storage({"GRanD_CAP_MCM": 800.0,
                                "Obs_MEANFLOW_CUMECS": 120.0,
                                "NORhi_min": 55.0, "NORhi_max": 92.0,
                                "NORhi_alpha": 4.0, "NORhi_beta": -2.5,
                                "NORhi_mu": 75.0,
                                "NORlo_min": 18.0, "NORlo_max": 50.0,
                                "NORlo_alpha": -2.5, "NORlo_beta": 1.5,
                                "NORlo_mu": 32.0,
                                "Release_min": -0.3, "Release_max": 2.0,
                                "Release_alpha1": 0.08,
                                "Release_alpha2": -0.06,
                                "Release_beta1": 0.11,
                                "Release_beta2": -0.04,
                                "Release_p1": 0.12, "Release_p2": 0.15,
                                "Release_c": 0.01}),
            4: initial_storage(PARAMS["C"]),
        }

        max_imb = 0.0
        for day in range(1, 366):
            total_lat = sum(get_lateral_inflow(day, n) for n in range(5))
            boundary_out = run_simulation[day][3]["outflow_cms"]
            dsr = 0.0
            for nid in [0, 2, 4]:
                cur = run_simulation[day][nid]["storage_MCM"]
                dsr += (cur - prev_storage[nid]) * 1e6 / 86400.0
                prev_storage[nid] = cur
            imb = abs(total_lat - boundary_out - dsr)
            max_imb = max(max_imb, imb)
            assert imb < 0.1, f"Day {day}: mass imbalance {imb:.6f} m³/s"

        assert max_imb < 0.01, \
            f"Max daily mass imbalance {max_imb:.8f} m³/s exceeds 0.01"

    def test_cumulative_mass_balance(self, run_simulation):
        init_stor = {
            0: initial_storage(PARAMS["A"]),
            2: initial_storage({"GRanD_CAP_MCM": 800.0,
                                "Obs_MEANFLOW_CUMECS": 120.0,
                                "NORhi_min": 55.0, "NORhi_max": 92.0,
                                "NORhi_alpha": 4.0, "NORhi_beta": -2.5,
                                "NORhi_mu": 75.0,
                                "NORlo_min": 18.0, "NORlo_max": 50.0,
                                "NORlo_alpha": -2.5, "NORlo_beta": 1.5,
                                "NORlo_mu": 32.0,
                                "Release_min": -0.3, "Release_max": 2.0,
                                "Release_alpha1": 0.08,
                                "Release_alpha2": -0.06,
                                "Release_beta1": 0.11,
                                "Release_beta2": -0.04,
                                "Release_p1": 0.12, "Release_p2": 0.15,
                                "Release_c": 0.01}),
            4: initial_storage(PARAMS["C"]),
        }

        total_lat_vol = 0.0
        for day in range(1, 366):
            for n in range(5):
                total_lat_vol += get_lateral_inflow(day, n) * 86400.0

        total_out_vol = 0.0
        for day in range(1, 366):
            total_out_vol += run_simulation[day][3]["outflow_cms"] * 86400.0

        delta_stor_vol = 0.0
        for nid in [0, 2, 4]:
            delta_stor_vol += (run_simulation[365][nid]["storage_MCM"]
                               - init_stor[nid]) * 1e6

        rel_err = abs(total_lat_vol - total_out_vol
                      - delta_stor_vol) / total_lat_vol
        assert rel_err < 1e-4, \
            f"Cumulative mass balance relative error: {rel_err:.8e}"


class TestDAGRouting:
    """Verify that network routing is consistent."""

    def test_passthrough_node1(self, run_simulation):
        """Node 1 outflow = Node 0 outflow + 5.0 m³/s lateral."""
        for day in range(1, 366):
            out_0 = run_simulation[day][0]["outflow_cms"]
            out_1 = run_simulation[day][1]["outflow_cms"]
            expected = out_0 + 5.0
            assert abs(out_1 - expected) < 1e-4, (
                f"Day {day}: Node 1 outflow {out_1:.8f} != "
                f"expected {expected:.8f}")

    def test_boundary_node3(self, run_simulation):
        """Node 3 outflow = Node 2 + Node 4 outflow + 3.0 lateral."""
        for day in range(1, 366):
            out_2 = run_simulation[day][2]["outflow_cms"]
            out_4 = run_simulation[day][4]["outflow_cms"]
            out_3 = run_simulation[day][3]["outflow_cms"]
            expected = out_2 + out_4 + 3.0
            assert abs(out_3 - expected) < 1e-4, (
                f"Day {day}: Node 3 outflow {out_3:.8f} != "
                f"expected {expected:.8f}")

    def test_boundary_exceeds_lateral(self, run_simulation):
        for day in range(1, 366):
            assert run_simulation[day][3]["outflow_cms"] >= 3.0 - 1e-6, \
                f"Day {day}: boundary outflow below lateral"


class TestHeadwaterReference:
    """Compare headwater reservoir outputs against independent reference."""

    def test_reservoir_A(self, run_simulation):
        laterals = [get_lateral_inflow(d, 0) for d in range(1, 366)]
        ref = ref_simulate_headwater(PARAMS["A"], laterals)
        for day in range(1, 366):
            r = ref[day - 1]
            s = run_simulation[day][0]
            assert abs(s["outflow_cms"] - r["outflow_cms"]) < 1e-4, \
                f"Day {day} Node 0 outflow mismatch"
            assert abs(s["storage_MCM"] - r["storage_MCM"]) < 1e-3, \
                f"Day {day} Node 0 storage mismatch"
            assert abs(s["release_cms"] - r["release_cms"]) < 1e-4, \
                f"Day {day} Node 0 release mismatch"
            assert abs(s["spill_cms"] - r["spill_cms"]) < 1e-4, \
                f"Day {day} Node 0 spill mismatch"

    def test_reservoir_C(self, run_simulation):
        laterals = [get_lateral_inflow(d, 4) for d in range(1, 366)]
        ref = ref_simulate_headwater(PARAMS["C"], laterals)
        for day in range(1, 366):
            r = ref[day - 1]
            s = run_simulation[day][4]
            assert abs(s["outflow_cms"] - r["outflow_cms"]) < 1e-4, \
                f"Day {day} Node 4 outflow mismatch"
            assert abs(s["storage_MCM"] - r["storage_MCM"]) < 1e-3, \
                f"Day {day} Node 4 storage mismatch"


class TestNORBounds:
    """Spot-check Normal Operating Range."""

    def test_nor_seasonal_variation(self):
        p = PARAMS["A"]
        hi_1 = ref_max_nor(p, 1)
        lo_1 = ref_min_nor(p, 1)
        hi_26 = ref_max_nor(p, 26)
        lo_26 = ref_min_nor(p, 26)
        assert 60.0 <= hi_1 <= 95.0
        assert 20.0 <= lo_1 <= 55.0
        assert abs(hi_1 - hi_26) > 1.0
        assert abs(lo_1 - lo_26) > 0.5

    def test_nor_hi_exceeds_lo(self):
        for key in ["A", "C"]:
            p = PARAMS[key]
            for w in range(1, 53):
                assert ref_max_nor(p, w) > ref_min_nor(p, w), \
                    f"Reservoir {key} w{w}: NOR_hi <= NOR_lo"


class TestNetCDFMetadata:
    """Verify that the output file is proper NetCDF4."""

    def test_output_is_netcdf(self):
        nc_path = "/app/output/simulation.nc"
        assert os.path.isfile(nc_path), "Output file missing"
        ds = Dataset(nc_path, "r")
        assert ds.file_format in ("NETCDF4", "NETCDF4_CLASSIC",
                                   "NETCDF3_CLASSIC", "NETCDF3_64BIT_OFFSET",
                                   "NETCDF3_64BIT_DATA")
        dims = list(ds.dimensions.keys())
        assert "day" in dims, "Missing 'day' dimension"
        assert "node" in dims, "Missing 'node' dimension"
        assert len(ds.dimensions["day"]) == 365
        assert len(ds.dimensions["node"]) == 5
        ds.close()
