
"""Tests for netCDF compliance remediation and audit task.

Verifies that the fixed ocean station dataset meets CF-1.6 and ACDD-1.3
compliance thresholds, preserves original scientific data, and that the
compliance audit report is accurate and complete.
"""

import json
import os
import subprocess

import netCDF4 as nc
import numpy as np
import pytest

FIXED_FILE = "/app/ocean_station_fixed.nc"
ORIGINAL_FILE = "/app/ocean_station.nc"
AUDIT_FILE = "/app/compliance_audit.json"

CF_THRESHOLD = 0.92
ACDD_THRESHOLD = 0.87


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def _run_compliance_check(test_name, target_file, output_json):
    """Run compliance-checker and return parsed JSON results."""
    result = subprocess.run(
        [
            "compliance-checker",
            "-t", test_name,
            "-f", "json",
            "-o", output_json,
            target_file,
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert os.path.exists(output_json), (
        f"Compliance check '{test_name}' produced no output. "
        f"stderr: {result.stderr[:500]}"
    )
    with open(output_json) as f:
        data = json.load(f)
    return data


def _get_score_ratio(data):
    """Extract scored/possible ratio from compliance-checker JSON output."""
    first_key = list(data.keys())[0]
    scored = data[first_key]["scored_points"]
    possible = data[first_key]["possible_points"]
    return scored, possible, (scored / possible if possible > 0 else 0)


# ------------------------------------------------------------------ #
# Structural validity
# ------------------------------------------------------------------ #

class TestFileValidity:
    def test_fixed_file_exists(self):
        assert os.path.exists(FIXED_FILE), f"Fixed file not found at {FIXED_FILE}"

    def test_is_valid_netcdf(self):
        ds = nc.Dataset(FIXED_FILE, "r")
        assert len(ds.dimensions) > 0, "File has no dimensions"
        ds.close()

    def test_has_expected_variables(self):
        ds = nc.Dataset(FIXED_FILE, "r")
        expected = {
            "time", "depth", "latitude", "longitude",
            "temperature", "salinity", "pressure",
            "current_speed", "current_direction",
            "dissolved_oxygen", "chlorophyll", "turbidity",
            "temperature_qc",
        }
        actual = set(ds.variables.keys())
        missing = expected - actual
        ds.close()
        assert len(missing) == 0, f"Missing variables: {missing}"


# ------------------------------------------------------------------ #
# Compliance score thresholds (run checker on fixed file)
# ------------------------------------------------------------------ #

class TestComplianceScores:
    def test_cf_compliance_score(self):
        data = _run_compliance_check("cf:1.6", FIXED_FILE, "/tmp/cf_check.json")
        scored, possible, ratio = _get_score_ratio(data)
        assert ratio >= CF_THRESHOLD, (
            f"CF compliance score {scored}/{possible} = {ratio:.3f} "
            f"is below threshold {CF_THRESHOLD}"
        )

    def test_acdd_compliance_score(self):
        data = _run_compliance_check("acdd:1.3", FIXED_FILE, "/tmp/acdd_check.json")
        scored, possible, ratio = _get_score_ratio(data)
        assert ratio >= ACDD_THRESHOLD, (
            f"ACDD compliance score {scored}/{possible} = {ratio:.3f} "
            f"is below threshold {ACDD_THRESHOLD}"
        )


# ------------------------------------------------------------------ #
# Data integrity — measurement arrays must be preserved exactly
# ------------------------------------------------------------------ #

class TestDataIntegrity:
    @pytest.fixture(autouse=True)
    def _open_datasets(self):
        self.orig = nc.Dataset(ORIGINAL_FILE, "r")
        self.fixed = nc.Dataset(FIXED_FILE, "r")
        yield
        self.orig.close()
        self.fixed.close()

    def _compare_variable(self, varname):
        orig_data = np.ma.filled(self.orig.variables[varname][:], fill_value=np.nan)
        fixed_data = np.ma.filled(self.fixed.variables[varname][:], fill_value=np.nan)
        np.testing.assert_array_almost_equal(
            orig_data, fixed_data, decimal=5,
            err_msg=f"Data for '{varname}' was altered during compliance fix",
        )

    def test_temperature_data_preserved(self):
        self._compare_variable("temperature")

    def test_salinity_data_preserved(self):
        self._compare_variable("salinity")

    def test_pressure_data_preserved(self):
        self._compare_variable("pressure")

    def test_current_speed_data_preserved(self):
        self._compare_variable("current_speed")

    def test_current_direction_data_preserved(self):
        self._compare_variable("current_direction")

    def test_dissolved_oxygen_data_preserved(self):
        self._compare_variable("dissolved_oxygen")

    def test_chlorophyll_data_preserved(self):
        self._compare_variable("chlorophyll")

    def test_turbidity_data_preserved(self):
        self._compare_variable("turbidity")

    def test_temperature_qc_data_preserved(self):
        self._compare_variable("temperature_qc")

    def test_depth_data_preserved(self):
        self._compare_variable("depth")

    def test_time_data_preserved(self):
        self._compare_variable("time")


# ------------------------------------------------------------------ #
# CF structural checks on fixed file
# ------------------------------------------------------------------ #

class TestCFStructuralFixes:
    @pytest.fixture(autouse=True)
    def _open_fixed(self):
        self.ds = nc.Dataset(FIXED_FILE, "r")
        yield
        self.ds.close()

    def test_conventions_attribute(self):
        assert hasattr(self.ds, "Conventions"), "Missing Conventions global attribute"
        assert "CF" in self.ds.Conventions, "Conventions must reference CF"

    def test_time_units_valid(self):
        t = self.ds.variables["time"]
        assert hasattr(t, "units"), "time missing units"
        units = t.units
        assert "since" in units, "time units must be 'T since reference_time'"
        prefix = units.split("since")[0].strip().lower()
        valid_prefixes = {"seconds", "minutes", "hours", "days"}
        assert prefix in valid_prefixes, (
            f"time units prefix '{prefix}' not standard CF "
            f"(expected one of {valid_prefixes})"
        )

    def test_time_has_calendar(self):
        assert hasattr(self.ds.variables["time"], "calendar"), "time missing calendar"

    def test_time_bounds_resolved(self):
        """If time has a bounds attribute, the referenced variable must exist."""
        t = self.ds.variables["time"]
        if hasattr(t, "bounds"):
            bounds_name = t.bounds
            assert bounds_name in self.ds.variables, (
                f"time.bounds references '{bounds_name}' which does not exist"
            )
            bnds_var = self.ds.variables[bounds_name]
            assert len(bnds_var.shape) == 2, (
                f"bounds variable '{bounds_name}' should be 2D"
            )
            assert bnds_var.shape[1] == 2, (
                f"bounds variable '{bounds_name}' second dimension must be 2"
            )

    def test_latitude_units(self):
        lat = self.ds.variables["latitude"]
        assert hasattr(lat, "units"), "latitude missing units"
        assert "north" in lat.units.lower() or "degree" in lat.units.lower(), (
            f"latitude units '{lat.units}' not valid"
        )

    def test_longitude_units(self):
        lon = self.ds.variables["longitude"]
        assert hasattr(lon, "units"), "longitude missing units"
        assert "east" in lon.units.lower() or "degree" in lon.units.lower(), (
            f"longitude units '{lon.units}' not valid"
        )

    def test_depth_has_positive(self):
        d = self.ds.variables["depth"]
        assert hasattr(d, "positive"), "depth missing positive attribute"
        assert d.positive in ("up", "down"), (
            f"depth positive='{d.positive}' must be 'up' or 'down'"
        )

    def test_temperature_standard_name_valid(self):
        t = self.ds.variables["temperature"]
        assert hasattr(t, "standard_name"), "temperature missing standard_name"
        assert t.standard_name != "temp", (
            "'temp' is not a valid CF standard name"
        )
        assert "temperature" in t.standard_name.lower() or "temp" in t.standard_name.lower(), (
            f"temperature standard_name '{t.standard_name}' seems unrelated"
        )

    def test_salinity_has_units(self):
        s = self.ds.variables["salinity"]
        assert hasattr(s, "units"), "salinity missing units"
        assert len(s.units.strip()) > 0, "salinity units is empty"

    def test_pressure_valid_range_consistent(self):
        """If valid_range is present, it must encompass actual data."""
        p = self.ds.variables["pressure"]
        pdata = p[:]
        if hasattr(p, "valid_range"):
            vr = p.valid_range
            assert vr[0] <= float(np.nanmin(pdata)), (
                f"valid_range min {vr[0]} > data min {np.nanmin(pdata)}"
            )
            assert vr[1] >= float(np.nanmax(pdata)), (
                f"valid_range max {vr[1]} < data max {np.nanmax(pdata)}"
            )

    def test_flag_meanings_present(self):
        qc = self.ds.variables["temperature_qc"]
        if hasattr(qc, "flag_values"):
            assert hasattr(qc, "flag_meanings"), (
                "flag_values present but flag_meanings missing"
            )
            meanings = qc.flag_meanings.split()
            n_values = len(qc.flag_values)
            assert len(meanings) == n_values, (
                f"flag_meanings has {len(meanings)} entries but "
                f"flag_values has {n_values}"
            )

    def test_cell_methods_syntax(self):
        """cell_methods must contain colons separating dim: method."""
        spd = self.ds.variables["current_speed"]
        if hasattr(spd, "cell_methods"):
            cm = spd.cell_methods
            assert ":" in cm, (
                f"cell_methods '{cm}' is missing colon separator"
            )

    def test_no_dangling_ancillary_variables(self):
        """ancillary_variables must reference existing variables."""
        for vname, var in self.ds.variables.items():
            if hasattr(var, "ancillary_variables"):
                refs = var.ancillary_variables.split()
                for ref in refs:
                    assert ref in self.ds.variables, (
                        f"Variable '{vname}' has ancillary_variables "
                        f"referencing non-existent '{ref}'"
                    )

    def test_dissolved_oxygen_standard_name_valid(self):
        """dissolved_oxygen must have a valid CF standard name, not 'DO_concentration'."""
        do = self.ds.variables["dissolved_oxygen"]
        assert hasattr(do, "standard_name"), "dissolved_oxygen missing standard_name"
        sn = do.standard_name
        assert sn != "DO_concentration", (
            "'DO_concentration' is not a valid CF standard name"
        )
        assert "oxygen" in sn.lower(), (
            f"dissolved_oxygen standard_name '{sn}' seems unrelated to oxygen"
        )


# ------------------------------------------------------------------ #
# ACDD attribute presence
# ------------------------------------------------------------------ #

class TestACDDAttributes:
    @pytest.fixture(autouse=True)
    def _open_fixed(self):
        self.ds = nc.Dataset(FIXED_FILE, "r")
        yield
        self.ds.close()

    def test_title(self):
        assert hasattr(self.ds, "title"), "Missing ACDD title"
        assert len(self.ds.title.strip()) > 0, "title is empty"

    def test_summary(self):
        assert hasattr(self.ds, "summary"), "Missing ACDD summary"
        assert len(self.ds.summary.strip()) > 10, "summary too short"

    def test_source(self):
        assert hasattr(self.ds, "source"), "Missing ACDD source"

    def test_institution(self):
        assert hasattr(self.ds, "institution"), "Missing ACDD institution"

    def test_creator_name(self):
        assert hasattr(self.ds, "creator_name"), "Missing ACDD creator_name"

    def test_creator_email(self):
        assert hasattr(self.ds, "creator_email"), "Missing ACDD creator_email"

    def test_keywords(self):
        assert hasattr(self.ds, "keywords"), "Missing ACDD keywords"

    def test_license(self):
        assert hasattr(self.ds, "license"), "Missing ACDD license"

    def test_standard_name_vocabulary(self):
        assert hasattr(self.ds, "standard_name_vocabulary"), (
            "Missing standard_name_vocabulary"
        )

    def test_project(self):
        assert hasattr(self.ds, "project"), "Missing ACDD project"

    def test_geospatial_bounds(self):
        for attr in ["geospatial_lat_min", "geospatial_lat_max",
                      "geospatial_lon_min", "geospatial_lon_max"]:
            assert hasattr(self.ds, attr), f"Missing {attr}"

    def test_time_coverage(self):
        assert hasattr(self.ds, "time_coverage_start"), (
            "Missing time_coverage_start"
        )
        assert hasattr(self.ds, "time_coverage_end"), (
            "Missing time_coverage_end"
        )

    def test_history_nonempty(self):
        assert hasattr(self.ds, "history"), "Missing history"
        assert len(self.ds.history.strip()) > 0, "history is empty"


# ------------------------------------------------------------------ #
# Compliance audit report
# ------------------------------------------------------------------ #

class TestAuditReport:
    @pytest.fixture(autouse=True)
    def _load_audit(self):
        assert os.path.exists(AUDIT_FILE), (
            f"Audit report not found at {AUDIT_FILE}"
        )
        with open(AUDIT_FILE) as f:
            self.audit = json.load(f)

    def test_audit_has_baseline(self):
        assert "baseline" in self.audit, "Audit missing 'baseline' key"
        baseline = self.audit["baseline"]
        assert "cf_1_6" in baseline, "Audit baseline missing 'cf_1_6'"
        assert "acdd_1_3" in baseline, "Audit baseline missing 'acdd_1_3'"

    def test_audit_has_remediated(self):
        assert "remediated" in self.audit, "Audit missing 'remediated' key"
        remediated = self.audit["remediated"]
        assert "cf_1_6" in remediated, "Audit remediated missing 'cf_1_6'"
        assert "acdd_1_3" in remediated, "Audit remediated missing 'acdd_1_3'"

    def test_audit_baseline_scores_structure(self):
        for key in ("cf_1_6", "acdd_1_3"):
            entry = self.audit["baseline"][key]
            assert "scored_points" in entry, (
                f"baseline.{key} missing scored_points"
            )
            assert "possible_points" in entry, (
                f"baseline.{key} missing possible_points"
            )
            assert isinstance(entry["scored_points"], (int, float))
            assert isinstance(entry["possible_points"], (int, float))
            assert entry["possible_points"] > 0, (
                f"baseline.{key}.possible_points must be positive"
            )

    def test_audit_remediated_scores_structure(self):
        for key in ("cf_1_6", "acdd_1_3"):
            entry = self.audit["remediated"][key]
            assert "scored_points" in entry
            assert "possible_points" in entry
            assert entry["possible_points"] > 0

    def test_audit_baseline_shows_original_failure(self):
        """Baseline scores must show the original file was below threshold."""
        cf = self.audit["baseline"]["cf_1_6"]
        cf_ratio = cf["scored_points"] / cf["possible_points"]
        assert cf_ratio < CF_THRESHOLD, (
            f"Audit baseline CF ratio {cf_ratio:.3f} should be below "
            f"{CF_THRESHOLD} (original file is broken)"
        )

        acdd = self.audit["baseline"]["acdd_1_3"]
        acdd_ratio = acdd["scored_points"] / acdd["possible_points"]
        assert acdd_ratio < ACDD_THRESHOLD, (
            f"Audit baseline ACDD ratio {acdd_ratio:.3f} should be below "
            f"{ACDD_THRESHOLD} (original file is broken)"
        )

    def test_audit_remediated_shows_improvement(self):
        """Remediated scores must show improvement over baseline."""
        for key in ("cf_1_6", "acdd_1_3"):
            base_ratio = (
                self.audit["baseline"][key]["scored_points"]
                / self.audit["baseline"][key]["possible_points"]
            )
            rem_ratio = (
                self.audit["remediated"][key]["scored_points"]
                / self.audit["remediated"][key]["possible_points"]
            )
            assert rem_ratio > base_ratio, (
                f"Remediated {key} ratio {rem_ratio:.3f} must exceed "
                f"baseline {base_ratio:.3f}"
            )

    def test_audit_has_violations(self):
        assert "violations" in self.audit, "Audit missing 'violations' key"
        violations = self.audit["violations"]
        assert isinstance(violations, list), "violations must be a list"
        assert len(violations) >= 10, (
            f"Expected at least 10 violations documented, got {len(violations)}"
        )

    def test_audit_violation_structure(self):
        """Each violation must have required fields."""
        required_keys = {"scope", "standard", "priority", "issue", "resolution"}
        for i, v in enumerate(self.audit["violations"]):
            missing = required_keys - set(v.keys())
            assert len(missing) == 0, (
                f"Violation {i} missing keys: {missing}"
            )
            assert v["standard"] in ("CF-1.6", "ACDD-1.3"), (
                f"Violation {i} standard '{v['standard']}' must be "
                f"'CF-1.6' or 'ACDD-1.3'"
            )
            assert v["priority"] in ("high", "medium", "low"), (
                f"Violation {i} priority '{v['priority']}' must be "
                f"'high', 'medium', or 'low'"
            )

    def test_audit_covers_both_standards(self):
        """Violations must include entries for both CF and ACDD standards."""
        standards_found = {v["standard"] for v in self.audit["violations"]}
        assert "CF-1.6" in standards_found, (
            "No CF-1.6 violations documented in audit"
        )
        assert "ACDD-1.3" in standards_found, (
            "No ACDD-1.3 violations documented in audit"
        )

    def test_audit_baseline_matches_actual_original(self):
        """Baseline scores in audit must approximately match running the
        checker on the original file."""
        cf_data = _run_compliance_check(
            "cf:1.6", ORIGINAL_FILE, "/tmp/audit_verify_cf.json"
        )
        actual_cf_scored, actual_cf_possible, _ = _get_score_ratio(cf_data)

        reported_cf = self.audit["baseline"]["cf_1_6"]
        assert abs(reported_cf["scored_points"] - actual_cf_scored) <= 3, (
            f"Audit baseline CF scored_points {reported_cf['scored_points']} "
            f"doesn't match actual {actual_cf_scored} (tolerance ±3)"
        )
        assert abs(reported_cf["possible_points"] - actual_cf_possible) <= 3, (
            f"Audit baseline CF possible_points {reported_cf['possible_points']} "
            f"doesn't match actual {actual_cf_possible} (tolerance ±3)"
        )

        acdd_data = _run_compliance_check(
            "acdd:1.3", ORIGINAL_FILE, "/tmp/audit_verify_acdd.json"
        )
        actual_acdd_scored, actual_acdd_possible, _ = _get_score_ratio(acdd_data)

        reported_acdd = self.audit["baseline"]["acdd_1_3"]
        assert abs(reported_acdd["scored_points"] - actual_acdd_scored) <= 3, (
            f"Audit baseline ACDD scored_points {reported_acdd['scored_points']} "
            f"doesn't match actual {actual_acdd_scored} (tolerance ±3)"
        )
        assert abs(reported_acdd["possible_points"] - actual_acdd_possible) <= 3, (
            f"Audit baseline ACDD possible_points {reported_acdd['possible_points']} "
            f"doesn't match actual {actual_acdd_possible} (tolerance ±3)"
        )
