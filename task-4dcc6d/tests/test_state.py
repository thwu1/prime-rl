"""
Verify backward-facing step simulation convergence and validation pipeline.

"""
import os
import re
import json

CASE_DIR = "/app/backwardStep"
LOG_FILE = os.path.join(CASE_DIR, "log.solver")
REPORT_PATH = os.path.join(CASE_DIR, "validation_report.json")
VALIDATE_SCRIPT = os.path.join(CASE_DIR, "validate.py")


# ==================== CONVERGENCE TESTS ====================


def test_solver_log_exists():
    """Solver log must exist at the expected path."""
    assert os.path.exists(LOG_FILE), f"Solver log not found at {LOG_FILE}"


def test_solver_completed_successfully():
    """Solver must run to completion without fatal errors."""
    with open(LOG_FILE) as f:
        content = f.read()
    assert "FOAM FATAL ERROR" not in content, "Solver encountered FOAM FATAL ERROR"
    assert "FOAM FATAL IO ERROR" not in content, "Solver encountered FOAM FATAL IO ERROR"
    assert "End" in content, "Solver did not reach completion (missing 'End' marker)"


def test_no_floating_point_exception():
    """No floating point exceptions during the simulation."""
    with open(LOG_FILE) as f:
        lines = f.readlines()
    # Filter out benign FPE trapping startup messages
    crash_lines = [l for l in lines if "trapping" not in l.lower()]
    filtered = "".join(crash_lines).lower()
    assert "floating point exception" not in filtered, "Simulation crashed with FPE"
    handler_lines = [
        l for l in lines if "enabling" not in l.lower() and "trapping" not in l.lower()
    ]
    assert "sigfpe" not in "".join(handler_lines).lower(), "Simulation encountered SIGFPE"


def test_velocity_residuals_converged():
    """Ux initial residual in the last iteration must be below 5e-4."""
    with open(LOG_FILE) as f:
        content = f.read()
    matches = re.findall(
        r"Solving for Ux,\s*Initial residual = ([0-9.eE\-+]+)", content
    )
    assert len(matches) > 0, "No Ux residuals found in solver log"
    assert float(matches[-1]) < 5e-4, (
        f"Ux not converged: last initial residual = {float(matches[-1]):.6e}"
    )


def test_pressure_residuals_converged():
    """Pressure initial residual in the last iteration must be below 5e-4."""
    with open(LOG_FILE) as f:
        content = f.read()
    matches = re.findall(
        r"Solving for p,\s*Initial residual = ([0-9.eE\-+]+)", content
    )
    assert len(matches) > 0, "No pressure residuals found"
    assert float(matches[-1]) < 5e-4, (
        f"p not converged: last initial residual = {float(matches[-1]):.6e}"
    )


def test_turbulence_residuals_converged():
    """k initial residual in the last iteration must be below 5e-4."""
    with open(LOG_FILE) as f:
        content = f.read()
    matches = re.findall(
        r"Solving for k,\s*Initial residual = ([0-9.eE\-+]+)", content
    )
    assert len(matches) > 0, "No k residuals found"
    assert float(matches[-1]) < 5e-4, (
        f"k not converged: last initial residual = {float(matches[-1]):.6e}"
    )


def test_final_time_directory_exists():
    """At least one result time directory beyond 0/ must exist."""
    time_dirs = [
        d
        for d in os.listdir(CASE_DIR)
        if os.path.isdir(os.path.join(CASE_DIR, d)) and d != "0"
        and _is_float(d)
    ]
    assert len(time_dirs) > 0, "No time directories found beyond 0/"


def test_velocity_field_valid():
    """Velocity field in the latest time directory must not contain NaN."""
    time_dirs = []
    for d in os.listdir(CASE_DIR):
        if os.path.isdir(os.path.join(CASE_DIR, d)) and d != "0" and _is_float(d):
            time_dirs.append((float(d), d))
    assert len(time_dirs) > 0, "No time directories found"
    time_dirs.sort()
    latest = time_dirs[-1][1]
    u_file = os.path.join(CASE_DIR, latest, "U")
    assert os.path.exists(u_file), f"U field not found in {latest}/"
    with open(u_file) as f:
        content = f.read()
    parts = content.split("internalField")
    data_section = parts[-1] if len(parts) > 1 else content
    assert "nan" not in data_section.lower(), "U field contains NaN values"


def test_sufficient_iterations():
    """Solver must run for at least 20 iterations."""
    with open(LOG_FILE) as f:
        content = f.read()
    time_matches = re.findall(r"^Time = (\d+)", content, re.MULTILINE)
    assert len(time_matches) >= 20, (
        f"Only {len(time_matches)} iterations — may indicate immediate failure"
    )


# ==================== VALIDATION PIPELINE TESTS ====================


def test_validate_script_exists():
    """validate.py must exist and contain substantial computation logic."""
    assert os.path.exists(VALIDATE_SCRIPT), (
        "validate.py not found at /app/backwardStep/validate.py"
    )
    with open(VALIDATE_SCRIPT) as f:
        content = f.read()
    code_lines = [
        l for l in content.split("\n") if l.strip() and not l.strip().startswith("#")
    ]
    assert len(code_lines) >= 20, (
        f"validate.py has only {len(code_lines)} code lines — appears to hardcode values"
    )
    assert "json" in content, "validate.py does not import/use json"
    content_lower = content.lower()
    reads_data = (
        "log" in content_lower
        or "solver" in content_lower
        or "polymesh" in content_lower
        or "polym" in content_lower
        or "postprocess" in content_lower
    )
    assert reads_data, "validate.py does not appear to read simulation data"


def test_validation_report_exists():
    """validation_report.json must exist and be valid JSON."""
    assert os.path.exists(REPORT_PATH), "validation_report.json not found"
    with open(REPORT_PATH) as f:
        report = json.load(f)
    assert isinstance(report, dict), "Report is not a JSON object"


def test_report_required_fields():
    """Report must contain all 12 required fields."""
    with open(REPORT_PATH) as f:
        report = json.load(f)
    required = [
        "reattachment_length_m",
        "step_height_m",
        "xr_over_h",
        "experimental_xr_over_h",
        "accuracy_percent_error",
        "inlet_mass_flow_m3s",
        "continuity_error_final",
        "mass_conservation_ok",
        "final_residuals",
        "converged",
        "total_iterations",
        "validation_verdict",
    ]
    for field in required:
        assert field in report, f"Missing required field: {field}"


def test_report_field_types():
    """Report fields must have correct types."""
    with open(REPORT_PATH) as f:
        report = json.load(f)
    assert isinstance(report["reattachment_length_m"], (int, float))
    assert isinstance(report["step_height_m"], (int, float))
    assert isinstance(report["xr_over_h"], (int, float))
    assert isinstance(report["experimental_xr_over_h"], (int, float))
    assert isinstance(report["accuracy_percent_error"], (int, float))
    assert isinstance(report["converged"], bool)
    assert isinstance(report["total_iterations"], int)
    assert isinstance(report["validation_verdict"], str)
    assert isinstance(report["final_residuals"], dict)
    assert isinstance(report["mass_conservation_ok"], bool)
    assert isinstance(report["inlet_mass_flow_m3s"], (int, float))


def test_reattachment_physically_reasonable():
    """Reattachment length must be within physical bounds for backward-facing step."""
    with open(REPORT_PATH) as f:
        report = json.load(f)
    xr = report["reattachment_length_m"]
    assert 0.1 < xr < 1.5, (
        f"Reattachment length {xr} m is outside reasonable physical range [0.1, 1.5]"
    )
    xrh = report["xr_over_h"]
    assert 2.0 < xrh < 15.0, (
        f"x_r/h = {xrh} is outside expected range [2, 15] for backward-facing step"
    )


def test_report_internal_consistency():
    """Derived quantities in the report must be self-consistent."""
    with open(REPORT_PATH) as f:
        report = json.load(f)
    # xr_over_h == reattachment_length_m / step_height_m
    expected_ratio = report["reattachment_length_m"] / report["step_height_m"]
    assert abs(report["xr_over_h"] - expected_ratio) < 0.01, (
        f"xr_over_h={report['xr_over_h']} != length/height={expected_ratio:.4f}"
    )
    # accuracy_percent_error == |xr_over_h - 7.0| / 7.0 * 100
    expected_err = abs(report["xr_over_h"] - 7.0) / 7.0 * 100.0
    assert abs(report["accuracy_percent_error"] - expected_err) < 0.5, (
        f"accuracy_percent_error={report['accuracy_percent_error']:.2f} "
        f"!= expected {expected_err:.2f}"
    )


def test_mass_conservation():
    """Continuity error must be very small for a converged solution."""
    with open(REPORT_PATH) as f:
        report = json.load(f)
    ce = report["continuity_error_final"]
    assert ce is not None, "Continuity error not reported"
    assert abs(ce) < 1e-4, f"Continuity error |{ce}| exceeds 1e-4"
    assert report["mass_conservation_ok"] is True, (
        "mass_conservation_ok is False despite small continuity error"
    )


def test_convergence_verdict_consistent():
    """converged flag must match whether all residuals are below 1e-4."""
    with open(REPORT_PATH) as f:
        report = json.load(f)
    residuals = report["final_residuals"]
    all_below = all(v < 1e-4 for v in residuals.values())
    assert report["converged"] == all_below, (
        f"converged={report['converged']} inconsistent with residuals {residuals}"
    )


def test_validation_verdict_consistent():
    """validation_verdict must follow the defined pass/fail criteria."""
    with open(REPORT_PATH) as f:
        report = json.load(f)
    should_pass = (
        report["converged"]
        and report["xr_over_h"] is not None
        and 3.0 <= report["xr_over_h"] <= 12.0
        and report["mass_conservation_ok"]
    )
    expected = "pass" if should_pass else "fail"
    assert report["validation_verdict"] == expected, (
        f"verdict='{report['validation_verdict']}' but expected '{expected}'"
    )


def test_report_residuals_match_log():
    """Reported residuals must match independently parsed solver log values."""
    with open(REPORT_PATH) as f:
        report = json.load(f)
    with open(LOG_FILE) as f:
        log_content = f.read()
    # Cross-check Ux residual
    matches = re.findall(
        r"Solving for Ux,\s*Initial residual = ([0-9.eE+\-]+)", log_content
    )
    if matches:
        log_val = float(matches[-1])
        rpt_val = report["final_residuals"].get("Ux")
        assert rpt_val is not None, "Ux not in report final_residuals"
        rel = abs(log_val - rpt_val) / max(log_val, 1e-15)
        assert rel < 0.05, (
            f"Ux residual mismatch: log={log_val:.2e} report={rpt_val:.2e}"
        )
    # Cross-check p residual
    matches = re.findall(
        r"Solving for p,\s*Initial residual = ([0-9.eE+\-]+)", log_content
    )
    if matches:
        log_val = float(matches[-1])
        rpt_val = report["final_residuals"].get("p")
        assert rpt_val is not None, "p not in report final_residuals"
        rel = abs(log_val - rpt_val) / max(log_val, 1e-15)
        assert rel < 0.05, (
            f"p residual mismatch: log={log_val:.2e} report={rpt_val:.2e}"
        )


# ==================== HELPERS ====================


def _is_float(s):
    try:
        float(s)
        return True
    except ValueError:
        return False
