
import json
import math
import os
import subprocess
import tempfile

import pytest

# ---- Paths ----
TOOL_PATH = "/app/odr_eval.py"
XODR_PATH = "/app/network.xodr"
QC_REPORT_PATH = "/app/qc_report.json"
ENTITY_POS_PATH = "/app/entity_positions.json"

# ---- Tolerances ----
COORD_TOL = 0.01
HDG_TOL = 0.001
WIDTH_TOL = 0.001
ELEV_TOL = 0.001

# ---- Road geometry constants ----
HDG0 = math.pi / 6
COS_H0 = math.cos(HDG0)
SIN_H0 = math.sin(HDG0)
X_SEG2_START = 200.0 * COS_H0
Y_SEG2_START = 200.0 * SIN_H0


def _seg2_ref(p):
    """Evaluate curved segment 2 reference point at parameter p."""
    u = p
    v = 2.5e-4 * p * p
    x = X_SEG2_START + u * COS_H0 - v * SIN_H0
    y = Y_SEG2_START + u * SIN_H0 + v * COS_H0
    return x, y


def _seg2_hdg(p):
    """Evaluate heading in curved segment 2 at parameter p."""
    dv = 5e-4 * p
    return HDG0 + math.atan2(dv, 1.0)


X_SEG3_START, Y_SEG3_START = _seg2_ref(200.0)
HDG_SEG3 = _seg2_hdg(200.0)
COS_H3 = math.cos(HDG_SEG3)
SIN_H3 = math.sin(HDG_SEG3)


def _elevation(s):
    """Evaluate elevation at road s-coordinate."""
    if s < 200.0:
        return 0.0 + 0.01 * s + (-1.25e-5) * s ** 2
    else:
        ds = s - 200.0
        return 1.5 + 0.005 * ds


def _lane_m2_width(s):
    """Width of lane -2 at road s-coordinate."""
    if s < 200.0:
        return 3.5 + 1e-3 * s
    else:
        return 3.7 + (-5e-4) * (s - 200.0)


def _ref_point(s):
    """Reference point (x, y) at road s-coordinate."""
    if s <= 200.0:
        return s * COS_H0, s * SIN_H0
    elif s <= 400.0:
        return _seg2_ref(s - 200.0)
    else:
        ds = s - 400.0
        return X_SEG3_START + ds * COS_H3, Y_SEG3_START + ds * SIN_H3


def _heading(s):
    """Heading at road s-coordinate."""
    if s <= 200.0:
        return HDG0
    elif s <= 400.0:
        return _seg2_hdg(s - 200.0)
    else:
        return HDG_SEG3


def _lane_center_position(s, lane_id):
    """Compute (x, y, z) of lane center at road s-coordinate.

    Lane center is at the midpoint between inner and outer lane edges.
    """
    xr, yr = _ref_point(s)
    hdg = _heading(s)
    z = _elevation(s)

    if lane_id == 0:
        return xr, yr, z

    # Compute t-offset to lane center
    if lane_id == 1:
        t = 3.5 / 2.0
    elif lane_id == 2:
        t = 3.5 + 2.0 / 2.0
    elif lane_id == -1:
        t = -(3.75 / 2.0)
    elif lane_id == -2:
        t = -(3.75 + _lane_m2_width(s) / 2.0)
    elif lane_id == -3:
        t = -(3.75 + _lane_m2_width(s) + 1.5 / 2.0)
    else:
        t = 0.0

    x = xr + t * (-math.sin(hdg))
    y = yr + t * math.cos(hdg)
    return x, y, z


# ---- Helpers ----

def run_tool(queries):
    """Run the odr_eval tool with given queries and return parsed results."""
    assert os.path.isfile(TOOL_PATH), f"Tool not found at {TOOL_PATH}"
    assert os.path.isfile(XODR_PATH), f"XODR file not found at {XODR_PATH}"

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, dir="/tmp"
    ) as qf:
        json.dump(queries, qf)
        queries_path = qf.name

    results_path = "/tmp/test_results.json"

    proc = subprocess.run(
        ["python3", TOOL_PATH, XODR_PATH, queries_path, results_path],
        capture_output=True,
        text=True,
        timeout=60,
        cwd="/app",
    )
    assert proc.returncode == 0, (
        f"Tool exited with code {proc.returncode}\n"
        f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    )
    assert os.path.isfile(results_path), f"Results file not written at {results_path}"

    with open(results_path) as f:
        results = json.load(f)

    os.unlink(queries_path)
    os.unlink(results_path)

    assert len(results) == len(queries), (
        f"Expected {len(queries)} results, got {len(results)}"
    )
    return results


def _assert_result(result, expected, idx, query):
    """Assert a single result matches expected within tolerance."""
    for key in expected:
        assert key in result, (
            f"Query {idx} ({query['type']}): missing key '{key}' in result {result}"
        )
        actual = float(result[key])
        exp = float(expected[key])
        if key == "hdg":
            tol = HDG_TOL
        elif key in ("x", "y"):
            tol = COORD_TOL
        elif key == "z":
            tol = ELEV_TOL
        else:
            tol = WIDTH_TOL
        assert abs(actual - exp) < tol, (
            f"Query {idx} ({query['type']}, s={query.get('s')}, "
            f"lane={query.get('lane_id', 'N/A')}): "
            f"{key}={actual}, expected={exp}, diff={abs(actual - exp)}, tol={tol}"
        )


# ===========================================================================
# Test class 1: QC Report
# ===========================================================================

class TestQCReport:
    """Verify ASAM Quality Checker was properly invoked and results captured."""

    def test_qc_report_exists(self):
        assert os.path.isfile(QC_REPORT_PATH), (
            f"QC report not found at {QC_REPORT_PATH}"
        )

    def test_qc_report_structure(self):
        with open(QC_REPORT_PATH) as f:
            report = json.load(f)
        for key in ("checkers_run", "checkers_passed", "issues_found", "checker_details"):
            assert key in report, f"Missing key '{key}' in QC report"
        assert isinstance(report["checkers_run"], int)
        assert isinstance(report["checkers_passed"], int)
        assert isinstance(report["issues_found"], int)
        assert isinstance(report["checker_details"], list)

    def test_qc_checkers_actually_invoked(self):
        with open(QC_REPORT_PATH) as f:
            report = json.load(f)
        assert report["checkers_run"] >= 4, (
            f"Expected at least 4 checkers to have run, got {report['checkers_run']}"
        )

    def test_qc_known_checker_ids(self):
        """At least one known ASAM QC checker ID must appear, proving the real
        asam-qc-opendrive tool was used rather than a stub."""
        with open(QC_REPORT_PATH) as f:
            report = json.load(f)
        known_ids = {
            "check_asam_xodr_xml_valid_xml_document",
            "check_asam_xodr_xml_root_tag_is_opendrive",
            "check_asam_xodr_xml_fileheader_is_present",
            "check_asam_xodr_xml_version_is_defined",
        }
        found_ids = {d["checker_id"] for d in report["checker_details"]}
        overlap = known_ids & found_ids
        assert len(overlap) >= 1, (
            f"No known ASAM QC checker IDs found. Expected at least one of "
            f"{known_ids}, got {found_ids}"
        )

    def test_qc_checker_detail_structure(self):
        with open(QC_REPORT_PATH) as f:
            report = json.load(f)
        for detail in report["checker_details"]:
            assert "checker_id" in detail, f"Missing checker_id in detail: {detail}"
            assert "status" in detail, f"Missing status in detail: {detail}"
            assert "issues" in detail, f"Missing issues in detail: {detail}"
            assert isinstance(detail["issues"], int)


# ===========================================================================
# Test class 2: Entity Position Analysis
# ===========================================================================

class TestEntityPositions:
    """Verify cross-standard entity position resolution."""

    def test_entity_file_exists(self):
        assert os.path.isfile(ENTITY_POS_PATH), (
            f"Entity positions file not found at {ENTITY_POS_PATH}"
        )

    def test_entity_file_structure(self):
        with open(ENTITY_POS_PATH) as f:
            data = json.load(f)
        assert "entities" in data, "Missing 'entities' key"
        assert "cross_ref_errors" in data, "Missing 'cross_ref_errors' key"
        assert len(data["entities"]) == 5, (
            f"Expected 5 entities, got {len(data['entities'])}"
        )

    def test_parameter_resolution_ego(self):
        """Ego's s comes from $EgoS parameter (value=100)."""
        with open(ENTITY_POS_PATH) as f:
            data = json.load(f)
        ego = data["entities"]["Ego"]
        assert ego["s"] == pytest.approx(100.0, abs=0.1), (
            f"Ego s should be 100.0 (from $EgoS), got {ego['s']}"
        )

    def test_parameter_resolution_target(self):
        """Target's s comes from $TargetS parameter (value=300)."""
        with open(ENTITY_POS_PATH) as f:
            data = json.load(f)
        target = data["entities"]["Target"]
        assert target["s"] == pytest.approx(300.0, abs=0.1), (
            f"Target s should be 300.0 (from $TargetS), got {target['s']}"
        )

    def test_ego_position(self):
        """Ego: road 0, lane -1, s=100 — valid position."""
        with open(ENTITY_POS_PATH) as f:
            data = json.load(f)
        ego = data["entities"]["Ego"]
        assert ego["valid"] is True, f"Ego should be valid, got error: {ego.get('error')}"
        assert ego["road_id"] == 0
        assert ego["lane_id"] == -1

        ex, ey, ez = _lane_center_position(100.0, -1)
        assert ego["x"] == pytest.approx(ex, abs=COORD_TOL), (
            f"Ego x: expected {ex}, got {ego['x']}"
        )
        assert ego["y"] == pytest.approx(ey, abs=COORD_TOL), (
            f"Ego y: expected {ey}, got {ego['y']}"
        )
        assert ego["z"] == pytest.approx(ez, abs=ELEV_TOL), (
            f"Ego z: expected {ez}, got {ego['z']}"
        )

    def test_target_position(self):
        """Target: road 0, lane -2, s=300 — valid position in curved segment."""
        with open(ENTITY_POS_PATH) as f:
            data = json.load(f)
        target = data["entities"]["Target"]
        assert target["valid"] is True, (
            f"Target should be valid, got error: {target.get('error')}"
        )

        ex, ey, ez = _lane_center_position(300.0, -2)
        assert target["x"] == pytest.approx(ex, abs=COORD_TOL), (
            f"Target x: expected {ex}, got {target['x']}"
        )
        assert target["y"] == pytest.approx(ey, abs=COORD_TOL), (
            f"Target y: expected {ey}, got {target['y']}"
        )
        assert target["z"] == pytest.approx(ez, abs=ELEV_TOL), (
            f"Target z: expected {ez}, got {target['z']}"
        )

    def test_observer_position(self):
        """Observer: road 0, lane 1, s=50 — valid left-lane position."""
        with open(ENTITY_POS_PATH) as f:
            data = json.load(f)
        obs = data["entities"]["Observer"]
        assert obs["valid"] is True, (
            f"Observer should be valid, got error: {obs.get('error')}"
        )

        ex, ey, ez = _lane_center_position(50.0, 1)
        assert obs["x"] == pytest.approx(ex, abs=COORD_TOL), (
            f"Observer x: expected {ex}, got {obs['x']}"
        )
        assert obs["y"] == pytest.approx(ey, abs=COORD_TOL), (
            f"Observer y: expected {ey}, got {obs['y']}"
        )
        assert obs["z"] == pytest.approx(ez, abs=ELEV_TOL), (
            f"Observer z: expected {ez}, got {obs['z']}"
        )

    def test_ghost_invalid_lane(self):
        """Ghost: road 0, lane -5, s=200 — lane -5 does not exist."""
        with open(ENTITY_POS_PATH) as f:
            data = json.load(f)
        ghost = data["entities"]["Ghost"]
        assert ghost["valid"] is False, "Ghost should be invalid (lane -5 doesn't exist)"
        assert ghost["error"] is not None
        assert "-5" in ghost["error"] or "lane" in ghost["error"].lower()

    def test_phantom_invalid_road(self):
        """Phantom: road 7, lane -1, s=50 — road 7 does not exist."""
        with open(ENTITY_POS_PATH) as f:
            data = json.load(f)
        phantom = data["entities"]["Phantom"]
        assert phantom["valid"] is False, "Phantom should be invalid (road 7 doesn't exist)"
        assert phantom["error"] is not None
        assert "7" in phantom["error"] or "road" in phantom["error"].lower()

    def test_cross_ref_errors_count(self):
        """Should detect exactly 2 cross-reference errors (Ghost + Phantom)."""
        with open(ENTITY_POS_PATH) as f:
            data = json.load(f)
        assert len(data["cross_ref_errors"]) == 2, (
            f"Expected 2 cross-ref errors, got {len(data['cross_ref_errors'])}: "
            f"{data['cross_ref_errors']}"
        )


# ===========================================================================
# Test class 3: Geometry Query Engine
# ===========================================================================

# ---- Primary query set ----
QUERIES_1 = [
    {"type": "ref_point", "road_id": 0, "s": 100.0},
    {"type": "ref_point", "road_id": 0, "s": 300.0},
    {"type": "ref_point", "road_id": 0, "s": 450.0},
    {"type": "heading", "road_id": 0, "s": 100.0},
    {"type": "heading", "road_id": 0, "s": 300.0},
    {"type": "heading", "road_id": 0, "s": 450.0},
    {"type": "elevation", "road_id": 0, "s": 100.0},
    {"type": "elevation", "road_id": 0, "s": 350.0},
    {"type": "lane_width", "road_id": 0, "s": 250.0, "lane_id": -2},
    {"type": "lane_width", "road_id": 0, "s": 100.0, "lane_id": -1},
    {"type": "lane_width", "road_id": 0, "s": 100.0, "lane_id": 1},
    {"type": "lane_edge", "road_id": 0, "s": 100.0, "lane_id": -1},
    {"type": "lane_edge", "road_id": 0, "s": 100.0, "lane_id": -2},
    {"type": "lane_edge", "road_id": 0, "s": 300.0, "lane_id": 1},
]


def _expected_1():
    e = []
    # Q0: ref_point s=100 (segment 1)
    e.append({"x": 100.0 * COS_H0, "y": 100.0 * SIN_H0})
    # Q1: ref_point s=300 (segment 2, p=100)
    x2, y2 = _seg2_ref(100.0)
    e.append({"x": x2, "y": y2})
    # Q2: ref_point s=450 (segment 3, ds=50)
    e.append({
        "x": X_SEG3_START + 50.0 * COS_H3,
        "y": Y_SEG3_START + 50.0 * SIN_H3,
    })
    # Q3: heading s=100
    e.append({"hdg": HDG0})
    # Q4: heading s=300
    e.append({"hdg": _seg2_hdg(100.0)})
    # Q5: heading s=450
    e.append({"hdg": HDG_SEG3})
    # Q6: elevation s=100
    e.append({"z": _elevation(100.0)})
    # Q7: elevation s=350
    e.append({"z": _elevation(350.0)})
    # Q8: lane_width s=250 lane=-2
    e.append({"width": _lane_m2_width(250.0)})
    # Q9: lane_width s=100 lane=-1
    e.append({"width": 3.75})
    # Q10: lane_width s=100 lane=1
    e.append({"width": 3.5})
    # Q11: lane_edge s=100 lane=-1
    xr, yr = 100.0 * COS_H0, 100.0 * SIN_H0
    t = -3.75
    e.append({"x": xr + t * (-SIN_H0), "y": yr + t * COS_H0})
    # Q12: lane_edge s=100 lane=-2
    w2 = _lane_m2_width(100.0)
    t = -(3.75 + w2)
    e.append({"x": xr + t * (-SIN_H0), "y": yr + t * COS_H0})
    # Q13: lane_edge s=300 lane=1
    xr, yr = _seg2_ref(100.0)
    hr = _seg2_hdg(100.0)
    t = 3.5
    e.append({"x": xr + t * (-math.sin(hr)), "y": yr + t * math.cos(hr)})
    return e


EXPECTED_1 = _expected_1()

# ---- Secondary query set ----
QUERIES_2 = [
    {"type": "ref_point", "road_id": 0, "s": 50.0},
    {"type": "ref_point", "road_id": 0, "s": 250.0},
    {"type": "heading", "road_id": 0, "s": 250.0},
    {"type": "elevation", "road_id": 0, "s": 50.0},
    {"type": "elevation", "road_id": 0, "s": 400.0},
    {"type": "lane_width", "road_id": 0, "s": 400.0, "lane_id": -2},
    {"type": "lane_width", "road_id": 0, "s": 150.0, "lane_id": -2},
    {"type": "lane_edge", "road_id": 0, "s": 50.0, "lane_id": 1},
    {"type": "lane_edge", "road_id": 0, "s": 400.0, "lane_id": -3},
    {"type": "ref_point", "road_id": 0, "s": 480.0},
    {"type": "lane_edge", "road_id": 0, "s": 300.0, "lane_id": -2},
]


def _expected_2():
    e = []
    # S0: ref_point s=50
    e.append({"x": 50.0 * COS_H0, "y": 50.0 * SIN_H0})
    # S1: ref_point s=250 (segment 2, p=50)
    x2, y2 = _seg2_ref(50.0)
    e.append({"x": x2, "y": y2})
    # S2: heading s=250
    e.append({"hdg": _seg2_hdg(50.0)})
    # S3: elevation s=50
    e.append({"z": _elevation(50.0)})
    # S4: elevation s=400
    e.append({"z": _elevation(400.0)})
    # S5: lane_width s=400 lane=-2
    e.append({"width": _lane_m2_width(400.0)})
    # S6: lane_width s=150 lane=-2
    e.append({"width": _lane_m2_width(150.0)})
    # S7: lane_edge s=50 lane=1
    xr, yr = 50.0 * COS_H0, 50.0 * SIN_H0
    t = 3.5
    e.append({"x": xr + t * (-SIN_H0), "y": yr + t * COS_H0})
    # S8: lane_edge s=400 lane=-3
    xr, yr = X_SEG3_START, Y_SEG3_START
    w2 = _lane_m2_width(400.0)
    t = -(3.75 + w2 + 1.5)
    e.append({"x": xr + t * (-SIN_H3), "y": yr + t * COS_H3})
    # S9: ref_point s=480 (segment 3, ds=80)
    e.append({
        "x": X_SEG3_START + 80.0 * COS_H3,
        "y": Y_SEG3_START + 80.0 * SIN_H3,
    })
    # S10: lane_edge s=300 lane=-2
    xr, yr = _seg2_ref(100.0)
    hr = _seg2_hdg(100.0)
    w_m1 = 3.75
    w_m2 = _lane_m2_width(300.0)
    t = -(w_m1 + w_m2)
    e.append({"x": xr + t * (-math.sin(hr)), "y": yr + t * math.cos(hr)})
    return e


EXPECTED_2 = _expected_2()


class TestGeometryPrimary:
    """First query set: tests all query types across geometry segments."""

    def test_tool_exists(self):
        assert os.path.isfile(TOOL_PATH), f"odr_eval.py not found at {TOOL_PATH}"

    def test_primary_queries(self):
        results = run_tool(QUERIES_1)
        for i, (q, exp) in enumerate(zip(QUERIES_1, EXPECTED_1)):
            _assert_result(results[i], exp, i, q)


class TestGeometrySecondary:
    """Second query set: different s-values to prevent hardcoded answers."""

    def test_secondary_queries(self):
        results = run_tool(QUERIES_2)
        for i, (q, exp) in enumerate(zip(QUERIES_2, EXPECTED_2)):
            _assert_result(results[i], exp, i, q)


class TestGeometryEdgeCases:
    """Tests for boundary conditions."""

    def test_start_of_road(self):
        queries = [
            {"type": "ref_point", "road_id": 0, "s": 0.0},
            {"type": "heading", "road_id": 0, "s": 0.0},
            {"type": "elevation", "road_id": 0, "s": 0.0},
        ]
        expected = [
            {"x": 0.0, "y": 0.0},
            {"hdg": HDG0},
            {"z": 0.0},
        ]
        results = run_tool(queries)
        for i, (q, exp) in enumerate(zip(queries, expected)):
            _assert_result(results[i], exp, i, q)

    def test_segment_boundary(self):
        """Query exactly at s=200 (transition between geometry segments)."""
        queries = [
            {"type": "ref_point", "road_id": 0, "s": 200.0},
            {"type": "heading", "road_id": 0, "s": 200.0},
        ]
        expected = [
            {"x": X_SEG2_START, "y": Y_SEG2_START},
            {"hdg": HDG0},
        ]
        results = run_tool(queries)
        for i, (q, exp) in enumerate(zip(queries, expected)):
            _assert_result(results[i], exp, i, q)

    def test_end_of_road(self):
        """Query at s=500 (end of road)."""
        queries = [
            {"type": "ref_point", "road_id": 0, "s": 500.0},
            {"type": "elevation", "road_id": 0, "s": 500.0},
        ]
        x_end = X_SEG3_START + 100.0 * COS_H3
        y_end = Y_SEG3_START + 100.0 * SIN_H3
        z_end = _elevation(500.0)
        expected = [
            {"x": x_end, "y": y_end},
            {"z": z_end},
        ]
        results = run_tool(queries)
        for i, (q, exp) in enumerate(zip(queries, expected)):
            _assert_result(results[i], exp, i, q)
