#!/usr/bin/env python3

import pytest
import json
import subprocess
import os
import tempfile
import sqlite3


def run_tool(scenario):
    """Write scenario JSON to a temp file, run geosettle.py, return parsed output."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(scenario, f)
        tmp_path = f.name
    try:
        result = subprocess.run(
            ['python3', '/app/geosettle.py', tmp_path],
            capture_output=True, text=True, timeout=120
        )
    finally:
        os.unlink(tmp_path)
    assert result.returncode == 0, \
        f"Tool exited with code {result.returncode}.\nstderr: {result.stderr}\nstdout: {result.stdout}"
    return json.loads(result.stdout)


# ---------------------------------------------------------------------------
# Settlement engine tests (direct JSON input)
# ---------------------------------------------------------------------------

class TestSettlementTwoLayerOC:
    """Two-layer profile: NC clay over heavily OC clay, rectangular foundation.

    Reference values derived from Budhu (2011) soil mechanics methodology.
    Expected total settlement ~0.741 m.
    """

    SCENARIO = {
        "soil_profile": {
            "layers": [
                {"depth_from": 0, "depth_to": 4.2,
                 "total_unit_weight": 15, "Cc": 0.7, "Cr": 0.07, "OCR": 1},
                {"depth_from": 4.2, "depth_to": 20,
                 "total_unit_weight": 17, "Cc": 0.45, "Cr": 0.045, "OCR": 4}
                ]
        },
        "water_table_depth": 0.8,
        "foundation": {
            "shape": "rectangular", "width": 5, "length": 8,
            "applied_stress": 100
        },
        "grid_spacing": 0.5
    }

    def test_total_settlement(self):
        result = run_tool(self.SCENARIO)
        assert "total_settlement" in result
        assert abs(result["total_settlement"] - 0.741) < 0.02, \
            f"Expected ~0.741 m, got {result['total_settlement']}"

    def test_layer_settlements_sum(self):
        result = run_tool(self.SCENARIO)
        assert "layer_settlements" in result
        total_from_layers = sum(e["delta_z"] for e in result["layer_settlements"])
        assert abs(total_from_layers - result["total_settlement"]) < 1e-6, \
            "Sum of layer settlements must equal total_settlement"

    def test_layer_settlements_have_keys(self):
        result = run_tool(self.SCENARIO)
        for entry in result["layer_settlements"]:
            assert "depth_from" in entry
            assert "depth_to" in entry
            assert "delta_z" in entry

    def test_shallow_settles_more(self):
        result = run_tool(self.SCENARIO)
        settlements = result["layer_settlements"]
        shallow = sum(e["delta_z"] for e in settlements if e["depth_to"] <= 5)
        deep = sum(e["delta_z"] for e in settlements if e["depth_from"] >= 10)
        assert shallow > deep, \
            f"Shallow settlement ({shallow}) should exceed deep ({deep})"


class TestSettlementZeroCcLayers:
    """Profile with sand (Cc=0) and clay layers. Only clay should settle.

    Reference: Budhu (2011) example with Gs=2.7, gamma_w=9.8.
    Expected total settlement ~0.086 m.
    """

    SCENARIO = {
        "soil_profile": {
            "layers": [
                {"depth_from": 0, "depth_to": 3,
                 "total_unit_weight": 19.3, "Cc": 0, "Cr": 0, "OCR": 1},
                {"depth_from": 3, "depth_to": 10.4,
                 "total_unit_weight": 19.5, "Cc": 0, "Cr": 0, "OCR": 1},
                {"depth_from": 10.4, "depth_to": 12.4,
                 "total_unit_weight": 17.5, "Cc": 0.3, "Cr": 0.03, "OCR": 1},
                {"depth_from": 12.4, "depth_to": 15,
                 "total_unit_weight": 19.5, "Cc": 0, "Cr": 0, "OCR": 1}
            ]
        },
        "water_table_depth": 3,
        "specific_gravity": 2.7,
        "unit_weight_water": 9.8,
        "foundation": {
            "shape": "rectangular", "width": 5, "length": 8,
            "applied_stress": 1100
        },
        "grid_spacing": 0.5
    }

    def test_sand_layers_zero_settlement(self):
        result = run_tool(self.SCENARIO)
        for entry in result["layer_settlements"]:
            center = (entry["depth_from"] + entry["depth_to"]) / 2
            if center < 10.4 or center > 12.4:
                assert abs(entry["delta_z"]) < 1e-10, \
                    f"Sand layer element at depth {center:.2f} m should have zero settlement"

    def test_total_settlement_budhu(self):
        result = run_tool(self.SCENARIO)
        assert abs(result["total_settlement"] - 0.086) < 0.01, \
            f"Expected ~0.086 m, got {result['total_settlement']}"


class TestCircularFoundation:
    """Circular foundation on single NC layer."""

    SCENARIO = {
        "soil_profile": {
            "layers": [
                {"depth_from": 0, "depth_to": 10,
                 "total_unit_weight": 17, "Cc": 0.3, "Cr": 0.03, "OCR": 1}
            ]
        },
        "water_table_depth": 0,
        "foundation": {
            "shape": "circular", "width": 4, "applied_stress": 100
        },
        "grid_spacing": 0.5
    }

    def test_positive_settlement(self):
        result = run_tool(self.SCENARIO)
        assert result["total_settlement"] > 0

    def test_settlement_distribution(self):
        result = run_tool(self.SCENARIO)
        settlements = result["layer_settlements"]
        top_half = sum(s["delta_z"] for s in settlements if s["depth_to"] <= 5)
        bot_half = sum(s["delta_z"] for s in settlements if s["depth_from"] >= 5)
        assert top_half > bot_half, \
            "Top half should settle more than bottom half for circular footing"


class TestStripFoundation:
    """Strip foundation on single NC layer."""

    SCENARIO = {
        "soil_profile": {
            "layers": [
                {"depth_from": 0, "depth_to": 10,
                 "total_unit_weight": 17, "Cc": 0.3, "Cr": 0.03, "OCR": 1}
            ]
        },
        "water_table_depth": 0,
        "foundation": {
            "shape": "strip", "width": 4, "applied_stress": 100
        },
        "grid_spacing": 0.5
    }

    def test_positive_settlement(self):
        result = run_tool(self.SCENARIO)
        assert result["total_settlement"] > 0

    def test_strip_larger_than_rect(self):
        """Strip footing produces more settlement than equal-width rectangular."""
        strip_result = run_tool(self.SCENARIO)
        rect_scenario = dict(self.SCENARIO)
        rect_scenario["foundation"] = {
            "shape": "rectangular", "width": 4, "length": 4,
            "applied_stress": 100
        }
        rect_result = run_tool(rect_scenario)
        assert strip_result["total_settlement"] > rect_result["total_settlement"], \
            "Strip (plane strain) should produce more settlement than square footing"


class TestOCRecompressionRatio:
    """Highly overconsolidated soil (OCR=10) should settle much less than NC.

    Uses circular foundation to isolate the OC/NC settlement logic from
    rectangular stress computation. Water table at surface so saturation
    assignment is unambiguous.
    """

    BASE = {
        "soil_profile": {
            "layers": [
                {"depth_from": 0, "depth_to": 10,
                 "total_unit_weight": 20, "Cc": 0.5, "Cr": 0.05, "OCR": 1}
            ]
        },
        "water_table_depth": 0,
        "foundation": {
            "shape": "circular", "width": 4, "applied_stress": 20
        },
        "grid_spacing": 0.5
    }

    def _make_scenario(self, ocr):
        import copy
        s = copy.deepcopy(self.BASE)
        s["soil_profile"]["layers"][0]["OCR"] = ocr
        return s

    def test_ocr10_much_less_than_nc(self):
        """With OCR=10 and small load, recompression index (Cr=Cc/10) governs.
        Settlement should be roughly 1/10th of NC case."""
        nc_result = run_tool(self._make_scenario(1))
        oc_result = run_tool(self._make_scenario(10))
        assert oc_result["total_settlement"] > 0, \
            "OC soil should still produce some settlement"
        assert oc_result["total_settlement"] < nc_result["total_settlement"] / 5, \
            f"OCR=10 settlement ({oc_result['total_settlement']:.4f}) should be " \
            f"much less than NC ({nc_result['total_settlement']:.4f})"

    def test_ocr2_intermediate(self):
        """OCR=2 should produce settlement between NC and OCR=10."""
        nc_result = run_tool(self._make_scenario(1))
        oc2_result = run_tool(self._make_scenario(2))
        oc10_result = run_tool(self._make_scenario(10))
        assert oc10_result["total_settlement"] < oc2_result["total_settlement"] < \
            nc_result["total_settlement"], \
            "Settlement should decrease with increasing OCR"


class TestRectangularStressMagnitude:
    """Rectangular foundation settlement must reflect correct stress superposition.

    A single NC layer with WT at surface avoids saturation and OC complications.
    Compares rectangular vs circular with matched area to verify the rectangle
    stress computation gives reasonable magnitude.
    """

    def test_rect_vs_circle_area_matched(self):
        """A 4x4 rectangular footing and a circle with same area should give
        similar (but not identical) settlement. The rectangle produces slightly
        more settlement due to 4-corner superposition geometry."""
        import math
        base = {
            "soil_profile": {
                "layers": [
                    {"depth_from": 0, "depth_to": 10,
                     "total_unit_weight": 18, "Cc": 0.3, "Cr": 0.03, "OCR": 1}
                ]
            },
            "water_table_depth": 0,
            "grid_spacing": 0.5
        }
        rect_scenario = dict(base)
        rect_scenario["foundation"] = {
            "shape": "rectangular", "width": 4, "length": 4, "applied_stress": 100
        }
        diameter = 2 * math.sqrt(16 / math.pi)
        circ_scenario = dict(base)
        circ_scenario["foundation"] = {
            "shape": "circular", "width": diameter, "applied_stress": 100
        }
        rect_result = run_tool(rect_scenario)
        circ_result = run_tool(circ_scenario)
        assert rect_result["total_settlement"] > 0
        assert circ_result["total_settlement"] > 0
        ratio = rect_result["total_settlement"] / circ_result["total_settlement"]
        assert 0.5 < ratio < 2.0, \
            f"Rectangular/circular settlement ratio ({ratio:.2f}) should be near 1"


class TestCombinedScenario:
    """Both settlement and consolidation in one input must both appear in output."""

    SCENARIO = {
        "soil_profile": {
            "layers": [
                {"depth_from": 0, "depth_to": 5,
                 "total_unit_weight": 17, "Cc": 0.3, "Cr": 0.03, "OCR": 1}
            ]
        },
        "water_table_depth": 0,
        "foundation": {
            "shape": "circular", "width": 4, "applied_stress": 100
        },
        "grid_spacing": 0.5,
        "consolidation": {
            "height": 1.0,
            "total_time": 5000,
            "no_nodes": 11,
            "cv": 100,
            "top_drainage": True,
            "bottom_drainage": True,
            "initial_excess_pore_pressure": 50,
            "output_times_seconds": [5000]
        }
    }

    def test_both_outputs_present(self):
        result = run_tool(self.SCENARIO)
        assert "total_settlement" in result, "Settlement output missing"
        assert "layer_settlements" in result, "Layer settlements missing"
        assert "pore_pressures" in result, "Pore pressures missing"
        assert result["total_settlement"] > 0
        assert len(result["pore_pressures"]) == 1
        assert len(result["pore_pressures"][0]["values"]) == 11


# ---------------------------------------------------------------------------
# 1D finite-difference consolidation tests
# ---------------------------------------------------------------------------

class TestConsolidationDoubleDrainage:
    """Double-drainage FD consolidation: uniform initial u=50, cv=100 m2/yr.

    Reference: midpoint pore pressure at t=10000 s ~ 45.23 kPa.
    """

    SCENARIO = {
        "consolidation": {
            "height": 1.0,
            "total_time": 10000,
            "no_nodes": 21,
            "cv": 100,
            "top_drainage": True,
            "bottom_drainage": True,
            "initial_excess_pore_pressure": 50,
            "output_times_seconds": [10000]
        }
    }

    def test_midpoint_pore_pressure(self):
        result = run_tool(self.SCENARIO)
        assert "pore_pressures" in result
        pp = result["pore_pressures"]
        assert len(pp) == 1
        values = pp[0]["values"]
        assert len(values) == 21
        midpoint_u = values[10]
        assert abs(midpoint_u - 45.23) < 0.5, \
            f"Expected ~45.23 kPa at midpoint, got {midpoint_u}"

    def test_boundary_values_zero(self):
        result = run_tool(self.SCENARIO)
        values = result["pore_pressures"][0]["values"]
        assert abs(values[0]) < 1e-6, f"Top boundary should be 0, got {values[0]}"
        assert abs(values[-1]) < 1e-6, f"Bottom boundary should be 0, got {values[-1]}"

    def test_symmetric_profile(self):
        """Double-drainage with uniform initial u should produce symmetric result."""
        result = run_tool(self.SCENARIO)
        values = result["pore_pressures"][0]["values"]
        n = len(values)
        for i in range(n // 2):
            assert abs(values[i] - values[n - 1 - i]) < 0.01, \
                f"Profile should be symmetric: u[{i}]={values[i]}, u[{n-1-i}]={values[n-1-i]}"


class TestConsolidationTopDrainageOnly:
    """Top-drainage only: linear initial u from 0 (top) to 50 (bottom).

    Reference: pore pressure at impermeable bottom at t=10000 s ~ 39.98 kPa.
    """

    SCENARIO = {
        "consolidation": {
            "height": 1.0,
            "total_time": 10000,
            "no_nodes": 21,
            "cv": 100,
            "top_drainage": True,
            "bottom_drainage": False,
            "initial_excess_pore_pressure": [0, 50],
            "output_times_seconds": [10000]
        }
    }

    def test_top_boundary_zero(self):
        result = run_tool(self.SCENARIO)
        values = result["pore_pressures"][0]["values"]
        assert abs(values[0]) < 1e-6

    def test_bottom_pore_pressure(self):
        result = run_tool(self.SCENARIO)
        values = result["pore_pressures"][0]["values"]
        assert abs(values[-1] - 39.98) < 0.5, \
            f"Expected ~39.98 kPa at impermeable bottom, got {values[-1]}"


class TestConsolidationBottomDrainageOnly:
    """Bottom-drainage only: linear initial u from 50 (top) to 0 (bottom).

    Reference: pore pressure at impermeable top at t=10000 s ~ 39.98 kPa.
    """

    SCENARIO = {
        "consolidation": {
            "height": 1.0,
            "total_time": 10000,
            "no_nodes": 21,
            "cv": 100,
            "top_drainage": False,
            "bottom_drainage": True,
            "initial_excess_pore_pressure": [50, 0],
            "output_times_seconds": [10000]
        }
    }

    def test_bottom_boundary_zero(self):
        result = run_tool(self.SCENARIO)
        values = result["pore_pressures"][0]["values"]
        assert abs(values[-1]) < 1e-6

    def test_top_pore_pressure(self):
        result = run_tool(self.SCENARIO)
        values = result["pore_pressures"][0]["values"]
        assert abs(values[0] - 39.98) < 0.5, \
            f"Expected ~39.98 kPa at impermeable top, got {values[0]}"


class TestConsolidationMultipleOutputTimes:
    """Multiple output times: pore pressure should decrease monotonically at midpoint."""

    SCENARIO = {
        "consolidation": {
            "height": 1.0,
            "total_time": 10000,
            "no_nodes": 21,
            "cv": 100,
            "top_drainage": True,
            "bottom_drainage": True,
            "initial_excess_pore_pressure": 50,
            "output_times_seconds": [1000, 5000, 10000]
        }
    }

    def test_correct_number_of_outputs(self):
        result = run_tool(self.SCENARIO)
        assert len(result["pore_pressures"]) == 3

    def test_times_match(self):
        result = run_tool(self.SCENARIO)
        times = [entry["time"] for entry in result["pore_pressures"]]
        assert times == [1000, 5000, 10000]

    def test_midpoint_decreases(self):
        result = run_tool(self.SCENARIO)
        midpoints = [entry["values"][10] for entry in result["pore_pressures"]]
        assert midpoints[0] > midpoints[1] > midpoints[2], \
            f"Midpoint pore pressure should decrease monotonically: {midpoints}"


class TestConsolidationNoSettlement:
    """Consolidation-only scenario (no foundation) should not produce settlement keys."""

    SCENARIO = {
        "consolidation": {
            "height": 1.0,
            "total_time": 5000,
            "no_nodes": 11,
            "cv": 100,
            "top_drainage": True,
            "bottom_drainage": True,
            "initial_excess_pore_pressure": 50,
            "output_times_seconds": [5000]
        }
    }

    def test_no_settlement_keys(self):
        result = run_tool(self.SCENARIO)
        assert "total_settlement" not in result
        assert "layer_settlements" not in result
        assert "pore_pressures" in result


# ---------------------------------------------------------------------------
# Pipeline tests (Makefile + preprocessing + database)
# ---------------------------------------------------------------------------

class TestMakePipeline:
    """Tests the full Makefile pipeline: preprocessing -> analysis -> database."""

    @classmethod
    def setup_class(cls):
        subprocess.run(['make', 'clean'], cwd='/app', capture_output=True, timeout=30)
        cls.make_result = subprocess.run(
            ['make', 'all'], cwd='/app', capture_output=True, text=True, timeout=180
        )

    def test_make_succeeds(self):
        assert self.make_result.returncode == 0, \
            f"make all failed:\nstdout: {self.make_result.stdout}\nstderr: {self.make_result.stderr}"

    def test_scenario_files_created(self):
        for site in ['site_a', 'site_b', 'site_c']:
            assert os.path.exists(f'/app/sites/{site}/scenario.json'), \
                f"Scenario file for {site} not created"

    def test_results_files_created(self):
        for site in ['site_a', 'site_b', 'site_c']:
            assert os.path.exists(f'/app/sites/{site}/results.json'), \
                f"Results file for {site} not created"

    def test_results_db_exists(self):
        assert os.path.exists('/app/results.db'), "results.db not created"

    def test_site_a_settlement_in_db(self):
        conn = sqlite3.connect('/app/results.db')
        row = conn.execute(
            "SELECT total_settlement FROM analysis_results WHERE site_name = 'site_a'"
        ).fetchone()
        conn.close()
        assert row is not None, "site_a not found in results.db"
        assert isinstance(row[0], (int, float)), \
            f"total_settlement should be numeric, got {type(row[0]).__name__}: {row[0]}"
        assert abs(row[0] - 0.741) < 0.02, \
            f"Expected ~0.741, got {row[0]}"

    def test_site_b_settlement_in_db(self):
        conn = sqlite3.connect('/app/results.db')
        row = conn.execute(
            "SELECT total_settlement FROM analysis_results WHERE site_name = 'site_b'"
        ).fetchone()
        conn.close()
        assert row is not None, "site_b not found in results.db"
        assert isinstance(row[0], (int, float)), \
            f"total_settlement should be numeric, got {type(row[0]).__name__}: {row[0]}"
        assert abs(row[0] - 0.086) < 0.01, \
            f"Expected ~0.086, got {row[0]}"

    def test_site_c_consolidation_in_db(self):
        conn = sqlite3.connect('/app/results.db')
        row = conn.execute(
            "SELECT raw_json, has_consolidation FROM analysis_results WHERE site_name = 'site_c'"
        ).fetchone()
        conn.close()
        assert row is not None, "site_c not found in results.db"
        assert row[1] == 1, "site_c should have has_consolidation=1"
        data = json.loads(row[0])
        assert "pore_pressures" in data
        midpoint_u = data["pore_pressures"][0]["values"][10]
        assert abs(midpoint_u - 45.23) < 0.5, \
            f"Expected midpoint ~45.23, got {midpoint_u}"

    def test_site_b_specific_gravity_in_scenario(self):
        """Site B scenario must use site-specific Gs=2.7 and gamma_w=9.8."""
        path = '/app/sites/site_b/scenario.json'
        assert os.path.exists(path), "site_b scenario.json not found"
        with open(path) as f:
            scenario = json.load(f)
        assert abs(scenario.get("specific_gravity", 2.65) - 2.7) < 0.01, \
            f"Site B must use Gs=2.7, got {scenario.get('specific_gravity')}"
        assert abs(scenario.get("unit_weight_water", 10.0) - 9.8) < 0.01, \
            f"Site B must use gamma_w=9.8, got {scenario.get('unit_weight_water')}"

    def test_site_c_output_times_format(self):
        """Consolidation output_times_seconds must be a list, not a scalar."""
        path = '/app/sites/site_c/scenario.json'
        assert os.path.exists(path), "site_c scenario.json not found"
        with open(path) as f:
            scenario = json.load(f)
        ot = scenario["consolidation"]["output_times_seconds"]
        assert isinstance(ot, list), \
            f"output_times_seconds must be a list, got {type(ot).__name__}: {ot}"
