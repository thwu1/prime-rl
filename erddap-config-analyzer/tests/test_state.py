
import json
import os
import pytest

REPORT_PATH = "/app/output/reconciliation.json"
NCCSV_DIR = "/app/output/datasets_nccsv"


@pytest.fixture(scope="module")
def report():
    assert os.path.isfile(REPORT_PATH), f"{REPORT_PATH} not found — did reconcile.sh run?"
    with open(REPORT_PATH) as f:
        return json.load(f)


def get_dataset(report, dataset_id):
    for ds in report.get("datasets", []):
        if ds["dataset_id"] == dataset_id:
            return ds
    return None


def get_hierarchy(report, dataset_id):
    for h in report.get("hierarchy_audit", []):
        if h["dataset_id"] == dataset_id:
            return h
    return None


# ── Report structure ────────────────────────────────────────────

class TestReportStructure:
    def test_report_has_datasets(self, report):
        assert "datasets" in report
        assert isinstance(report["datasets"], list)
        assert len(report["datasets"]) == 5, (
            f"Expected 5 reconciled datasets, got {len(report['datasets'])}: "
            f"{[d['dataset_id'] for d in report['datasets']]}"
        )

    def test_report_has_hierarchy_audit(self, report):
        assert "hierarchy_audit" in report
        assert isinstance(report["hierarchy_audit"], list)
        assert len(report["hierarchy_audit"]) >= 3

    def test_report_has_netcdf_summary(self, report):
        assert "netcdf_summary" in report
        assert "dimensions" in report["netcdf_summary"]
        assert "variables" in report["netcdf_summary"]
        assert "global_attributes" in report["netcdf_summary"]


# ── erdMBsstd1day: source-only var + attribute conflict ─────────

class TestErdMBsstd:
    def test_source_only_vars_quality_level(self, report):
        ds = get_dataset(report, "erdMBsstd1day")
        assert ds is not None, "erdMBsstd1day not found in datasets"
        assert "quality_level" in ds["discrepancies"]["source_only_vars"]

    def test_no_config_only_vars(self, report):
        ds = get_dataset(report, "erdMBsstd1day")
        assert ds["discrepancies"]["config_only_vars"] == []

    def test_no_type_mismatches(self, report):
        ds = get_dataset(report, "erdMBsstd1day")
        assert ds["discrepancies"]["type_mismatches"] == [], (
            f"MBsstd should be float in both config and source; got {ds['discrepancies']['type_mismatches']}"
        )

    def test_attribute_conflict_units(self, report):
        ds = get_dataset(report, "erdMBsstd1day")
        conflicts = ds["discrepancies"]["attribute_conflicts"]
        units_conflict = [
            c for c in conflicts
            if c["variable"] == "MBsstd" and c["attribute"] == "units"
        ]
        assert len(units_conflict) == 1, f"Expected 1 units conflict for MBsstd, got {units_conflict}"
        assert units_conflict[0]["source_value"] == "deg_C"
        assert units_conflict[0]["config_value"] == "degree_C"

    def test_source_type_opendap(self, report):
        ds = get_dataset(report, "erdMBsstd1day")
        assert ds["source_type"] == "opendap"


# ── erdTAsshl1day: type mismatch ────────────────────────────────

class TestErdTAsshl:
    def test_type_mismatch_float64_vs_float(self, report):
        ds = get_dataset(report, "erdTAsshl1day")
        assert ds is not None, "erdTAsshl1day not found in datasets"
        mismatches = ds["discrepancies"]["type_mismatches"]
        tm = [m for m in mismatches if m["variable"] == "TAsshl"]
        assert len(tm) == 1, f"Expected 1 type mismatch for TAsshl, got {tm}"
        assert tm[0]["config_type"] == "float"
        assert tm[0]["source_type"] == "double"


# ── erdAGchla_part1: CF violation + attribute conflict ──────────

class TestErdAGchla:
    def test_cf_violation_chlorophyll_concentration(self, report):
        ds = get_dataset(report, "erdAGchla_part1")
        assert ds is not None, "erdAGchla_part1 not found in datasets"
        cf_viols = ds["discrepancies"]["cf_violations"]
        chlor = [v for v in cf_viols if v["variable"] == "chlor_a"]
        assert len(chlor) == 1, f"Expected 1 CF violation for chlor_a, got {chlor}"
        assert chlor[0]["standard_name"] == "chlorophyll_concentration"
        assert chlor[0]["reason"] == "not_in_cf_table"

    def test_attribute_conflict_standard_name(self, report):
        ds = get_dataset(report, "erdAGchla_part1")
        conflicts = ds["discrepancies"]["attribute_conflicts"]
        sn = [c for c in conflicts if c["variable"] == "chlor_a" and c["attribute"] == "standard_name"]
        assert len(sn) == 1, f"Expected standard_name conflict for chlor_a, got {sn}"
        assert sn[0]["source_value"] == "chlorophyll_concentration"


# ── erdQSwind_u: clean control case ─────────────────────────────

class TestErdQSwind:
    def test_no_source_only_vars(self, report):
        ds = get_dataset(report, "erdQSwind_u")
        assert ds is not None, "erdQSwind_u not found in datasets"
        assert ds["discrepancies"]["source_only_vars"] == []

    def test_no_config_only_vars(self, report):
        ds = get_dataset(report, "erdQSwind_u")
        assert ds["discrepancies"]["config_only_vars"] == []

    def test_no_type_mismatches(self, report):
        ds = get_dataset(report, "erdQSwind_u")
        assert ds["discrepancies"]["type_mismatches"] == []


# ── localBathyGrid: ncdump-based local file reconciliation ──────

class TestLocalBathy:
    def test_source_type_local_file(self, report):
        ds = get_dataset(report, "localBathyGrid")
        assert ds is not None, "localBathyGrid not found in datasets"
        assert ds["source_type"] == "local_file"

    def test_source_only_vars_land_mask(self, report):
        ds = get_dataset(report, "localBathyGrid")
        assert "land_mask" in ds["discrepancies"]["source_only_vars"]

    def test_attribute_conflict_long_name(self, report):
        ds = get_dataset(report, "localBathyGrid")
        conflicts = ds["discrepancies"]["attribute_conflicts"]
        ln = [c for c in conflicts if c["variable"] == "elevation" and c["attribute"] == "long_name"]
        assert len(ln) == 1, f"Expected long_name conflict for elevation, got {ln}"
        assert ln[0]["source_value"] == "Elevation relative to sea level"
        assert ln[0]["config_value"] == "Topography/Bathymetry"


# ── Hierarchy audit ─────────────────────────────────────────────

class TestHierarchy:
    def test_sidebyside_children(self, report):
        h = get_hierarchy(report, "erdTAssh1day")
        assert h is not None, "erdTAssh1day not in hierarchy_audit"
        assert set(h["children"]) == {"erdTAsshl1day", "erdTAsshd1day"}

    def test_sidebyside_effective_vars(self, report):
        h = get_hierarchy(report, "erdTAssh1day")
        dests = {v["dest"] for v in h["effective_variables"]}
        assert "ssh" in dests
        assert "sshd" in dests

    def test_sidebyside_from_child(self, report):
        h = get_hierarchy(report, "erdTAssh1day")
        by_dest = {v["dest"]: v for v in h["effective_variables"]}
        assert by_dest["ssh"]["from_child"] == "erdTAsshl1day"
        assert by_dest["sshd"]["from_child"] == "erdTAsshd1day"

    def test_sidebyside_axis_compatible(self, report):
        h = get_hierarchy(report, "erdTAssh1day")
        assert h["axis_compatibility"]["compatible"] is True

    def test_aggregate_effective_vars(self, report):
        h = get_hierarchy(report, "erdAGchla_agg")
        assert h is not None, "erdAGchla_agg not in hierarchy_audit"
        dests = {v["dest"] for v in h["effective_variables"]}
        assert "chlorophyll" in dests

    def test_deep_nesting_effective_vars(self, report):
        h = get_hierarchy(report, "erdWindComposite_0360")
        assert h is not None, "erdWindComposite_0360 not in hierarchy_audit"
        dests = {v["dest"] for v in h["effective_variables"]}
        assert "x_wind" in dests
        assert "y_wind" in dests

    def test_deep_nesting_from_child(self, report):
        h = get_hierarchy(report, "erdWindComposite_0360")
        by_dest = {v["dest"]: v for v in h["effective_variables"]}
        assert by_dest["x_wind"]["from_child"] == "erdQSwind_u"
        assert by_dest["y_wind"]["from_child"] == "erdQSwind_v"


# ── NetCDF summary (ncdump) ─────────────────────────────────────

class TestNetCDFSummary:
    def test_dimensions(self, report):
        nc = report["netcdf_summary"]
        assert nc["dimensions"]["latitude"] == 10
        assert nc["dimensions"]["longitude"] == 20

    def test_all_variables_present(self, report):
        nc = report["netcdf_summary"]
        names = {v["name"] for v in nc["variables"]}
        assert {"latitude", "longitude", "elevation", "land_mask"} <= names

    def test_elevation_type_and_dims(self, report):
        nc = report["netcdf_summary"]
        elev = [v for v in nc["variables"] if v["name"] == "elevation"]
        assert len(elev) == 1
        assert elev[0]["type"] == "short"
        assert elev[0]["dimensions"] == ["latitude", "longitude"]

    def test_global_attributes(self, report):
        nc = report["netcdf_summary"]
        assert nc["global_attributes"]["Conventions"] == "CF-1.6"
        assert nc["global_attributes"]["institution"] == "NOAA NGDC"


# ── NCCSV output ────────────────────────────────────────────────

class TestNccsv:
    def test_nccsv_files_exist(self):
        assert os.path.isdir(NCCSV_DIR), f"{NCCSV_DIR} directory not found"
        expected = {"erdMBsstd1day.nccsv", "erdTAsshl1day.nccsv",
                    "erdAGchla_part1.nccsv", "erdQSwind_u.nccsv"}
        actual = set(os.listdir(NCCSV_DIR))
        for f in expected:
            assert f in actual, f"{f} not found in {NCCSV_DIR}"

    def test_nccsv_format_global_and_end(self):
        fp = os.path.join(NCCSV_DIR, "erdMBsstd1day.nccsv")
        assert os.path.isfile(fp), f"{fp} not found"
        with open(fp) as f:
            content = f.read()
        lines = content.strip().split("\n")
        assert lines[0].startswith("*GLOBAL*,"), "First line must be a *GLOBAL* attribute"
        assert lines[-1] == "*END_METADATA*", "Last line must be *END_METADATA*"

    def test_nccsv_data_type_entry(self):
        fp = os.path.join(NCCSV_DIR, "erdMBsstd1day.nccsv")
        with open(fp) as f:
            content = f.read()
        assert "MBsstd,*DATA_TYPE*,float" in content

    def test_nccsv_variable_attribute(self):
        fp = os.path.join(NCCSV_DIR, "erdMBsstd1day.nccsv")
        with open(fp) as f:
            content = f.read()
        assert "MBsstd,long_name,Sea Surface Temperature" in content
