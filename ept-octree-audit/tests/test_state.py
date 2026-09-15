
import json
import os
import subprocess
import shutil

import numpy as np
import laspy
import pytest

DATASET_DIR = "/app/dataset"
FIXED_DIR = "/app/dataset_fixed"
REPORT_PATH = "/app/audit_report.json"
PIPELINE_PATH = "/app/remediation.json"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_las_cache = {}


def load_las_files(base_dir):
    """Return {node_key: laspy.LasData} for every .las in ept-data/."""
    if base_dir in _las_cache:
        return _las_cache[base_dir]
    result = {}
    data_dir = os.path.join(base_dir, "ept-data")
    if not os.path.isdir(data_dir):
        return result
    for fname in sorted(os.listdir(data_dir)):
        if fname.endswith(".las"):
            key = fname[:-4]
            result[key] = laspy.read(os.path.join(data_dir, fname))
    _las_cache[base_dir] = result
    return result


def get_point_ids(las):
    """Extract PointId extra dimension via direct attribute access."""
    return np.array(las.PointId, dtype=np.uint32)


def compute_node_bounds(root_bounds, depth, x, y, z):
    if depth == 0:
        return list(root_bounds)
    cells = 2 ** depth
    cell = [(root_bounds[i + 3] - root_bounds[i]) / cells for i in range(3)]
    return [
        root_bounds[0] + x * cell[0],
        root_bounds[1] + y * cell[1],
        root_bounds[2] + z * cell[2],
        root_bounds[0] + (x + 1) * cell[0],
        root_bounds[1] + (y + 1) * cell[1],
        root_bounds[2] + (z + 1) * cell[2],
    ]


# ===================================================================
# Audit report tests
# ===================================================================
class TestAuditReport:

    def test_report_exists_and_valid(self):
        assert os.path.exists(REPORT_PATH), "audit_report.json not found"
        with open(REPORT_PATH) as f:
            report = json.load(f)
        assert "errors" in report, "Report missing 'errors' key"
        assert isinstance(report["errors"], list)
        for err in report["errors"]:
            assert "type" in err, f"Error entry missing 'type': {err}"
            assert "description" in err, f"Error entry missing 'description': {err}"

    def test_sufficient_errors_detected(self):
        with open(REPORT_PATH) as f:
            report = json.load(f)
        error_types = {e["type"] for e in report["errors"]}
        assert len(error_types) >= 7, (
            f"Expected >=7 distinct error types, found {len(error_types)}: "
            f"{sorted(error_types)}"
        )


# ===================================================================
# PDAL remediation pipeline tests
# ===================================================================
class TestRemediationPipeline:

    def test_pipeline_exists(self):
        assert os.path.exists(PIPELINE_PATH), "remediation.json not found"

    def test_pipeline_structure(self):
        with open(PIPELINE_PATH) as f:
            pipeline = json.load(f)
        if isinstance(pipeline, dict):
            pipeline = pipeline.get("pipeline", pipeline)
        assert isinstance(pipeline, list), "Pipeline must be a JSON array"
        assert len(pipeline) >= 2, "Pipeline needs at least 2 stages"
        stages = [s for s in pipeline if isinstance(s, dict)]
        types = [s.get("type", "") for s in stages]
        assert any("filter" in t for t in types), (
            f"Pipeline must contain filter stages, found types: {types}"
        )


# ===================================================================
# Fixed dataset tests
# ===================================================================
class TestFixedDataset:

    def test_fixed_dataset_structure(self):
        assert os.path.isdir(FIXED_DIR), f"{FIXED_DIR} not found"
        assert os.path.exists(os.path.join(FIXED_DIR, "ept.json")), \
            "Fixed ept.json not found"
        data_dir = os.path.join(FIXED_DIR, "ept-data")
        assert os.path.isdir(data_dir), "Fixed ept-data/ not found"
        las_files = [f for f in os.listdir(data_dir) if f.endswith(".las")]
        assert len(las_files) > 0, "No .las files in fixed ept-data/"

    def test_data_files_are_valid_las(self):
        files = load_las_files(FIXED_DIR)
        assert len(files) > 0, "No LAS files loaded from fixed dataset"
        for key, las in files.items():
            assert len(las.points) > 0, f"Node {key}.las has 0 points"
            assert las.header.version.major == 1 and las.header.version.minor == 4, \
                f"Node {key}: expected LAS 1.4, got {las.header.version}"

    def test_cubic_bounds(self):
        with open(os.path.join(FIXED_DIR, "ept.json")) as f:
            ept = json.load(f)
        bounds = ept["bounds"]
        ranges = [bounds[i + 3] - bounds[i] for i in range(3)]
        assert abs(ranges[0] - ranges[1]) < 0.01, \
            f"X range ({ranges[0]:.4f}) != Y range ({ranges[1]:.4f})"
        assert abs(ranges[0] - ranges[2]) < 0.01, \
            f"X range ({ranges[0]:.4f}) != Z range ({ranges[2]:.4f})"
        assert ranges[0] > 0

    def test_conforming_within_bounds(self):
        with open(os.path.join(FIXED_DIR, "ept.json")) as f:
            ept = json.load(f)
        bounds = ept["bounds"]
        conf = ept["boundsConforming"]
        for i in range(3):
            axis = ["X", "Y", "Z"][i]
            assert conf[i] >= bounds[i] - 0.01, \
                f"Conforming {axis} min ({conf[i]}) < bounds {axis} min ({bounds[i]})"
            assert conf[i + 3] <= bounds[i + 3] + 0.01, \
                f"Conforming {axis} max ({conf[i+3]}) > bounds {axis} max ({bounds[i+3]})"

    def test_hierarchy_counts_match_data(self):
        hier_path = os.path.join(FIXED_DIR, "ept-hierarchy", "0-0-0-0.json")
        assert os.path.exists(hier_path), "Fixed hierarchy file missing"
        with open(hier_path) as f:
            hierarchy = json.load(f)
        files = load_las_files(FIXED_DIR)
        for key, count in hierarchy.items():
            assert key in files, f"Hierarchy node {key} has no data file"
            assert len(files[key].points) == count, \
                f"Node {key}: hierarchy={count}, data={len(files[key].points)}"
        for key in files:
            assert key in hierarchy, f"Data file {key}.las has no hierarchy entry"

    def test_total_point_count(self):
        with open(os.path.join(FIXED_DIR, "ept.json")) as f:
            ept = json.load(f)
        hier_path = os.path.join(FIXED_DIR, "ept-hierarchy", "0-0-0-0.json")
        with open(hier_path) as f:
            hierarchy = json.load(f)
        assert ept["points"] == sum(hierarchy.values()), \
            f"ept.json points ({ept['points']}) != hierarchy sum ({sum(hierarchy.values())})"

    def test_spatial_correctness(self):
        with open(os.path.join(FIXED_DIR, "ept.json")) as f:
            ept = json.load(f)
        bounds = ept["bounds"]
        files = load_las_files(FIXED_DIR)
        EPS = 0.1
        for key, las in files.items():
            parts = key.split("-")
            d, nx, ny, nz = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
            nb = compute_node_bounds(bounds, d, nx, ny, nz)
            pids = get_point_ids(las)
            for i in range(len(las.points)):
                px, py, pz = float(las.x[i]), float(las.y[i]), float(las.z[i])
                pid = int(pids[i])
                assert nb[0] - EPS <= px <= nb[3] + EPS, \
                    f"PointId {pid} X={px} outside node {key} [{nb[0]:.3f},{nb[3]:.3f}]"
                assert nb[1] - EPS <= py <= nb[4] + EPS, \
                    f"PointId {pid} Y={py} outside node {key} [{nb[1]:.3f},{nb[4]:.3f}]"
                assert nb[2] - EPS <= pz <= nb[5] + EPS, \
                    f"PointId {pid} Z={pz} outside node {key} [{nb[2]:.3f},{nb[5]:.3f}]"

    def test_no_invalid_classifications(self):
        files = load_las_files(FIXED_DIR)
        assert len(files) > 0, "No LAS files in fixed dataset"
        INVALID = {0, 12}
        for key, las in files.items():
            pids = get_point_ids(las)
            for i in range(len(las.points)):
                cls = int(las.classification[i])
                assert cls not in INVALID, \
                    f"PointId {int(pids[i])} in {key}: invalid classification {cls}"

    def test_schema_no_phantom_dims(self):
        with open(os.path.join(FIXED_DIR, "ept.json")) as f:
            ept = json.load(f)
        schema_dims = {d["name"] for d in ept["schema"]}
        EXPECTED = {
            "X", "Y", "Z", "Intensity", "Classification",
            "ReturnNumber", "NumberOfReturns", "GPSTime", "PointId",
        }
        phantom = schema_dims - EXPECTED
        assert not phantom, f"Schema lists dimensions not in data: {phantom}"

    def test_point_preservation(self):
        orig_files = load_las_files(DATASET_DIR)
        fixed_files = load_las_files(FIXED_DIR)
        assert len(orig_files) > 0, "No original LAS files"
        assert len(fixed_files) > 0, "No fixed LAS files"
        orig_ids = set()
        for las in orig_files.values():
            orig_ids.update(int(pid) for pid in get_point_ids(las))
        fixed_ids = set()
        for las in fixed_files.values():
            fixed_ids.update(int(pid) for pid in get_point_ids(las))
        assert orig_ids == fixed_ids, \
            f"PointId sets differ: {len(orig_ids)} original vs {len(fixed_ids)} fixed"

    def test_no_duplicate_points(self):
        files = load_las_files(FIXED_DIR)
        assert len(files) > 0, "No LAS files in fixed dataset"
        seen = {}
        for key, las in files.items():
            pids = get_point_ids(las)
            for i in range(len(las.points)):
                pid = int(pids[i])
                assert pid not in seen, \
                    f"PointId {pid} in both {seen[pid]} and {key}"
                seen[pid] = key

    def test_valid_return_numbers(self):
        """ReturnNumber must not exceed NumberOfReturns (LAS 1.4 spec)."""
        files = load_las_files(FIXED_DIR)
        assert len(files) > 0, "No LAS files in fixed dataset"
        for key, las in files.items():
            pids = get_point_ids(las)
            rn = np.array(las.return_number)
            nr = np.array(las.number_of_returns)
            bad = np.where(rn > nr)[0]
            assert len(bad) == 0, (
                f"Node {key}: {len(bad)} points with ReturnNumber > NumberOfReturns, "
                f"e.g. PointId {int(pids[bad[0]])} rn={rn[bad[0]]} nr={nr[bad[0]]}"
            )

    def test_overlap_flag_set(self):
        """Points originally classified as 12 must have overlap bit flag set
        in the corrected data (USGS LBS: overlap via flag, not classification)."""
        orig_files = load_las_files(DATASET_DIR)
        fixed_files = load_las_files(FIXED_DIR)

        # find original class-12 PointIds
        class_12_pids = set()
        for las in orig_files.values():
            mask = np.array(las.classification) == 12
            if np.any(mask):
                class_12_pids.update(
                    int(pid) for pid in get_point_ids(las)[mask]
                )
        assert len(class_12_pids) > 0, "No class 12 points in original (setup error)"

        # verify overlap flag in fixed data
        for key, las in fixed_files.items():
            pids = get_point_ids(las)
            overlaps = np.array(las.overlap)
            for i in range(len(las.points)):
                pid = int(pids[i])
                if pid in class_12_pids:
                    assert bool(overlaps[i]), (
                        f"PointId {pid} in {key}: was class 12, "
                        f"must have overlap flag set"
                    )

    def test_file_source_id_zero(self):
        """Tiled LAS deliverables must have FileSourceID=0 (USGS LBS)."""
        files = load_las_files(FIXED_DIR)
        assert len(files) > 0, "No LAS files in fixed dataset"
        for key, las in files.items():
            fsi = las.header.file_source_id
            assert fsi == 0, \
                f"Node {key}: FileSourceID={fsi}, must be 0 for tiled data"

    def test_pdal_readable(self):
        """At least one corrected LAS tile must be readable by pdal info."""
        if not shutil.which("pdal"):
            pytest.skip("PDAL not installed")
        data_dir = os.path.join(FIXED_DIR, "ept-data")
        las_files = [f for f in os.listdir(data_dir) if f.endswith(".las")]
        sample = os.path.join(data_dir, las_files[0])
        result = subprocess.run(
            ["pdal", "info", "--summary", sample],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, \
            f"pdal info failed on {las_files[0]}: {result.stderr}"
