
"""
Tests for the nekRS pre-flight auditor tool.
Validates mesh analysis (via gmsh API), .par parsing, physics detection,
non-dimensional parameter extraction, consistency checking, and
spectral element resolution diagnostics across 8 test cases.
"""

import subprocess
import json
import math
import os
import pytest

AUDITOR_PATH = "/app/nekrs_auditor.py"
CASES_DIR = "/app/cases"


def run_auditor(case_name):
    """Run the auditor on a case directory and return parsed JSON output."""
    case_dir = os.path.join(CASES_DIR, case_name)
    result = subprocess.run(
        ["python3", AUDITOR_PATH, case_dir],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"Auditor exited with code {result.returncode} on {case_name}.\n"
        f"stderr: {result.stderr[:2000]}"
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        pytest.fail(
            f"Auditor did not output valid JSON for {case_name}.\n"
            f"stdout: {result.stdout[:2000]}"
        )


def approx_eq(a, b, rel_tol=1e-4):
    """Check approximate equality for floating point values."""
    if b == 0:
        return abs(a) < 1e-10
    return abs(a - b) / abs(b) < rel_tol


# ---------------------------------------------------------------------------
# Basic structure validation
# ---------------------------------------------------------------------------

class TestBasic:
    def test_auditor_exists(self):
        assert os.path.isfile(AUDITOR_PATH), f"{AUDITOR_PATH} does not exist"

    def test_produces_json_with_sections(self):
        output = run_auditor("rbc_valid")
        assert isinstance(output, dict)
        for section in ["mesh", "config", "diagnostics"]:
            assert section in output, f"Missing top-level key '{section}'"

    def test_mesh_section_keys(self):
        output = run_auditor("rbc_valid")
        mesh = output["mesh"]
        for key in ["num_elements", "dimension", "bounding_box",
                     "min_element_size", "max_element_size",
                     "mean_quality", "boundary_groups"]:
            assert key in mesh, f"Missing mesh key '{key}'"

    def test_config_section_keys(self):
        output = run_auditor("rbc_valid")
        cfg = output["config"]
        for key in ["physics_type", "polynomial_order", "time_stepper",
                     "nondim_params", "material_props", "boundary_conditions",
                     "errors", "valid"]:
            assert key in cfg, f"Missing config key '{key}'"

    def test_diagnostics_section_keys(self):
        output = run_auditor("rbc_valid")
        diag = output["diagnostics"]
        for key in ["total_dof", "first_gll_spacing"]:
            assert key in diag, f"Missing diagnostics key '{key}'"


# ---------------------------------------------------------------------------
# Mesh statistics — element counts
# ---------------------------------------------------------------------------

class TestMeshElementCounts:
    def test_rbc_valid_elements(self):
        output = run_auditor("rbc_valid")
        assert output["mesh"]["num_elements"] == 240

    def test_rans_valid_elements(self):
        output = run_auditor("rans_valid")
        assert output["mesh"]["num_elements"] == 384

    def test_cht_valid_elements(self):
        output = run_auditor("cht_valid")
        assert output["mesh"]["num_elements"] == 200

    def test_pipe_valid_elements(self):
        output = run_auditor("pipe_valid")
        assert output["mesh"]["num_elements"] == 160

    def test_rbc_broken_elements(self):
        """Broken .par doesn't affect mesh reading."""
        output = run_auditor("rbc_broken")
        assert output["mesh"]["num_elements"] == 240

    def test_dimension_is_2(self):
        output = run_auditor("rbc_valid")
        assert output["mesh"]["dimension"] == 2


# ---------------------------------------------------------------------------
# Mesh statistics — bounding boxes
# ---------------------------------------------------------------------------

class TestMeshBoundingBox:
    def test_rbc_bbox(self):
        output = run_auditor("rbc_valid")
        bb = output["mesh"]["bounding_box"]
        assert approx_eq(bb[0][0], 0.0) and approx_eq(bb[0][1], 0.0)
        assert approx_eq(bb[1][0], 4.0) and approx_eq(bb[1][1], 1.0)

    def test_rans_bbox(self):
        output = run_auditor("rans_valid")
        bb = output["mesh"]["bounding_box"]
        assert approx_eq(bb[1][0], 8.0) and approx_eq(bb[1][1], 1.0)

    def test_cht_bbox(self):
        output = run_auditor("cht_valid")
        bb = output["mesh"]["bounding_box"]
        assert approx_eq(bb[1][0], 2.0) and approx_eq(bb[1][1], 1.0)

    def test_pipe_bbox(self):
        output = run_auditor("pipe_valid")
        bb = output["mesh"]["bounding_box"]
        assert approx_eq(bb[1][0], 2 * math.pi, rel_tol=1e-3)
        assert approx_eq(bb[1][1], 1.0)


# ---------------------------------------------------------------------------
# Mesh statistics — boundary groups
# ---------------------------------------------------------------------------

class TestMeshBoundaryGroups:
    def test_rbc_boundary_groups(self):
        output = run_auditor("rbc_valid")
        bg = output["mesh"]["boundary_groups"]
        assert bg["hot_wall"] == 20
        assert bg["cold_wall"] == 20
        assert bg["periodic_right"] == 12
        assert bg["periodic_left"] == 12

    def test_rans_boundary_groups(self):
        output = run_auditor("rans_valid")
        bg = output["mesh"]["boundary_groups"]
        assert bg["wall"] == 24
        assert bg["symmetry"] == 24
        assert bg["periodic_out"] == 16
        assert bg["periodic_in"] == 16

    def test_cht_boundary_groups(self):
        output = run_auditor("cht_valid")
        bg = output["mesh"]["boundary_groups"]
        assert bg["heated_wall"] == 20
        assert bg["cooled_wall"] == 20
        assert bg["insulated_right"] == 10
        assert bg["insulated_left"] == 10

    def test_pipe_boundary_groups(self):
        output = run_auditor("pipe_valid")
        bg = output["mesh"]["boundary_groups"]
        assert bg["wall"] == 16
        assert bg["symmetry"] == 16


# ---------------------------------------------------------------------------
# Mesh quality
# ---------------------------------------------------------------------------

class TestMeshQuality:
    def test_cht_square_elements_high_quality(self):
        """CHT mesh has square elements (dx=dy=0.1), quality should be ~1.0."""
        output = run_auditor("cht_valid")
        q = output["mesh"]["mean_quality"]
        assert q > 0.95, f"Square-element quality={q}, expected ~1.0"

    def test_quality_positive(self):
        output = run_auditor("rbc_valid")
        q = output["mesh"]["mean_quality"]
        assert 0.0 < q <= 1.0, f"Quality={q}, expected in (0, 1]"


# ---------------------------------------------------------------------------
# Mesh element sizes
# ---------------------------------------------------------------------------

class TestMeshElementSizes:
    def test_cht_uniform_square_size(self):
        """CHT mesh: 20x10 on [0,2]x[0,1], dx=0.1, dy=0.1, area=0.01."""
        output = run_auditor("cht_valid")
        assert approx_eq(output["mesh"]["min_element_size"], 0.01, rel_tol=0.02)
        assert approx_eq(output["mesh"]["max_element_size"], 0.01, rel_tol=0.02)

    def test_rbc_element_size(self):
        """RBC mesh: 20x12 on [0,4]x[0,1], area = 0.2 * (1/12) = 0.01667."""
        output = run_auditor("rbc_valid")
        expected_area = (4.0 / 20) * (1.0 / 12)
        assert approx_eq(output["mesh"]["min_element_size"], expected_area, rel_tol=0.02)

    def test_pipe_element_size(self):
        """Pipe mesh: 16x10 on [0,2pi]x[0,1], area = (2pi/16)*(1/10)."""
        output = run_auditor("pipe_valid")
        expected_area = (2 * math.pi / 16) * (1.0 / 10)
        assert approx_eq(output["mesh"]["min_element_size"], expected_area, rel_tol=0.02)


# ---------------------------------------------------------------------------
# Physics type detection
# ---------------------------------------------------------------------------

class TestPhysicsDetection:
    def test_rbc_valid(self):
        output = run_auditor("rbc_valid")
        assert output["config"]["physics_type"] == "rbc"

    def test_rans_valid(self):
        output = run_auditor("rans_valid")
        assert output["config"]["physics_type"] == "rans_ktau"

    def test_cht_valid(self):
        output = run_auditor("cht_valid")
        assert output["config"]["physics_type"] == "cht"

    def test_pipe_valid(self):
        output = run_auditor("pipe_valid")
        assert output["config"]["physics_type"] == "pipe_flow"

    def test_rbc_broken_still_detected(self):
        output = run_auditor("rbc_broken")
        assert output["config"]["physics_type"] == "rbc"

    def test_rans_broken_still_detected(self):
        output = run_auditor("rans_broken")
        assert output["config"]["physics_type"] == "rans_ktau"

    def test_cht_broken_still_detected(self):
        output = run_auditor("cht_broken")
        assert output["config"]["physics_type"] == "cht"

    def test_pipe_broken_still_detected(self):
        output = run_auditor("pipe_broken")
        assert output["config"]["physics_type"] == "pipe_flow"


# ---------------------------------------------------------------------------
# Polynomial order and time stepper
# ---------------------------------------------------------------------------

class TestGeneralParams:
    def test_rbc_poly_order(self):
        output = run_auditor("rbc_valid")
        assert output["config"]["polynomial_order"] == 7

    def test_rans_poly_order(self):
        output = run_auditor("rans_valid")
        assert output["config"]["polynomial_order"] == 5

    def test_pipe_poly_order(self):
        output = run_auditor("pipe_valid")
        assert output["config"]["polynomial_order"] == 7

    def test_rbc_timestepper(self):
        output = run_auditor("rbc_valid")
        assert output["config"]["time_stepper"] == "tombo2"


# ---------------------------------------------------------------------------
# Expression evaluation and material properties
# ---------------------------------------------------------------------------

class TestExpressionEvaluation:
    def test_sqrt_expression(self):
        """viscosity = sqrt(7/1e8) must evaluate correctly."""
        output = run_auditor("rbc_valid")
        visc = output["config"]["material_props"]["viscosity"]
        expected = math.sqrt(7.0 / 1e8)
        assert approx_eq(visc, expected), f"viscosity={visc}, expected={expected}"

    def test_reciprocal_sqrt_expression(self):
        """diffusionCoeff = 1/sqrt(7*1e8) must evaluate correctly."""
        output = run_auditor("rbc_valid")
        diff = output["config"]["material_props"]["diffusionCoeff"]
        expected = 1.0 / math.sqrt(7.0 * 1e8)
        assert approx_eq(diff, expected), f"diffusionCoeff={diff}, expected={expected}"

    def test_simple_division(self):
        """viscosity = 1/10595 must evaluate correctly."""
        output = run_auditor("rans_valid")
        visc = output["config"]["material_props"]["viscosity"]
        expected = 1.0 / 10595.0
        assert approx_eq(visc, expected), f"viscosity={visc}, expected={expected}"

    def test_integer_division(self):
        """viscosity = 1/1000 must evaluate correctly."""
        output = run_auditor("cht_valid")
        visc = output["config"]["material_props"]["viscosity"]
        expected = 1.0 / 1000.0
        assert approx_eq(visc, expected), f"viscosity={visc}, expected={expected}"

    def test_fraction_expression(self):
        """diffusionCoeffSolid = 5/7000 must evaluate correctly."""
        output = run_auditor("cht_valid")
        val = output["config"]["material_props"]["diffusionCoeffSolid"]
        expected = 5.0 / 7000.0
        assert approx_eq(val, expected), f"diffusionCoeffSolid={val}, expected={expected}"

    def test_reciprocal_expression(self):
        """viscosity = 1/19000 must evaluate correctly."""
        output = run_auditor("pipe_valid")
        visc = output["config"]["material_props"]["viscosity"]
        expected = 1.0 / 19000.0
        assert approx_eq(visc, expected), f"viscosity={visc}, expected={expected}"


# ---------------------------------------------------------------------------
# Non-dimensional parameter extraction
# ---------------------------------------------------------------------------

class TestNondimParams:
    def test_rbc_rayleigh(self):
        output = run_auditor("rbc_valid")
        ra = output["config"]["nondim_params"]["Ra"]
        assert approx_eq(ra, 1e8), f"Ra={ra}, expected=1e8"

    def test_rbc_prandtl(self):
        output = run_auditor("rbc_valid")
        pr = output["config"]["nondim_params"]["Pr"]
        assert approx_eq(pr, 7.0), f"Pr={pr}, expected=7.0"

    def test_rans_reynolds(self):
        output = run_auditor("rans_valid")
        re = output["config"]["nondim_params"]["Re"]
        assert approx_eq(re, 10595.0), f"Re={re}, expected=10595.0"

    def test_cht_reynolds(self):
        output = run_auditor("cht_valid")
        re = output["config"]["nondim_params"]["Re"]
        assert approx_eq(re, 1000.0), f"Re={re}, expected=1000.0"

    def test_cht_prandtl(self):
        output = run_auditor("cht_valid")
        pr = output["config"]["nondim_params"]["Pr"]
        assert approx_eq(pr, 7.0), f"Pr={pr}, expected=7.0"

    def test_cht_conductivity_ratio(self):
        output = run_auditor("cht_valid")
        kr = output["config"]["nondim_params"]["conductivity_ratio"]
        assert approx_eq(kr, 5.0), f"conductivity_ratio={kr}, expected=5.0"

    def test_pipe_reynolds(self):
        output = run_auditor("pipe_valid")
        re = output["config"]["nondim_params"]["Re"]
        assert approx_eq(re, 19000.0), f"Re={re}, expected=19000.0"

    def test_pipe_flow_direction(self):
        output = run_auditor("pipe_valid")
        direction = output["config"]["nondim_params"]["flow_direction"]
        assert direction == "Z", f"flow_direction={direction}, expected=Z"


# ---------------------------------------------------------------------------
# Boundary condition extraction
# ---------------------------------------------------------------------------

class TestBoundaryConditions:
    def test_rbc_velocity_bcs(self):
        output = run_auditor("rbc_valid")
        bcs = output["config"]["boundary_conditions"]
        assert "velocity" in bcs
        assert bcs["velocity"] == ["zeroDirichlet", "zeroDirichlet"]

    def test_rbc_temperature_bcs(self):
        output = run_auditor("rbc_valid")
        bcs = output["config"]["boundary_conditions"]
        assert "temperature" in bcs
        assert bcs["temperature"] == ["udfDirichlet", "zeroNeumann"]

    def test_rans_velocity_bcs(self):
        output = run_auditor("rans_valid")
        bcs = output["config"]["boundary_conditions"]
        assert "velocity" in bcs
        assert bcs["velocity"] == ["zeroDirichlet"]

    def test_rans_k_bcs(self):
        output = run_auditor("rans_valid")
        bcs = output["config"]["boundary_conditions"]
        assert "k" in bcs
        assert bcs["k"] == ["udfDirichlet"]

    def test_rans_tau_bcs(self):
        output = run_auditor("rans_valid")
        bcs = output["config"]["boundary_conditions"]
        assert "tau" in bcs
        assert bcs["tau"] == ["udfDirichlet"]


# ---------------------------------------------------------------------------
# Valid files must pass all config checks
# ---------------------------------------------------------------------------

class TestValidFiles:
    def test_rbc_valid_no_errors(self):
        output = run_auditor("rbc_valid")
        assert output["config"]["valid"] is True, (
            f"rbc_valid reported errors: {output['config']['errors']}"
        )
        assert len(output["config"]["errors"]) == 0

    def test_rans_valid_no_errors(self):
        output = run_auditor("rans_valid")
        assert output["config"]["valid"] is True, (
            f"rans_valid reported errors: {output['config']['errors']}"
        )

    def test_cht_valid_no_errors(self):
        output = run_auditor("cht_valid")
        assert output["config"]["valid"] is True, (
            f"cht_valid reported errors: {output['config']['errors']}"
        )

    def test_pipe_valid_no_errors(self):
        output = run_auditor("pipe_valid")
        assert output["config"]["valid"] is True, (
            f"pipe_valid reported errors: {output['config']['errors']}"
        )


# ---------------------------------------------------------------------------
# Broken RBC: MISSING_SCALAR_SECTION, EXPRESSION_ERROR, INVALID_TIMESTEPPER
# ---------------------------------------------------------------------------

class TestBrokenRBC:
    def test_is_invalid(self):
        output = run_auditor("rbc_broken")
        assert output["config"]["valid"] is False

    def test_has_at_least_three_errors(self):
        output = run_auditor("rbc_broken")
        assert len(output["config"]["errors"]) >= 3

    def test_missing_scalar_section(self):
        output = run_auditor("rbc_broken")
        codes = [e["code"] for e in output["config"]["errors"]]
        assert "MISSING_SCALAR_SECTION" in codes

    def test_expression_error(self):
        output = run_auditor("rbc_broken")
        codes = [e["code"] for e in output["config"]["errors"]]
        assert "EXPRESSION_ERROR" in codes

    def test_invalid_timestepper(self):
        output = run_auditor("rbc_broken")
        codes = [e["code"] for e in output["config"]["errors"]]
        assert "INVALID_TIMESTEPPER" in codes


# ---------------------------------------------------------------------------
# Broken RANS: MISSING_VARIABLE_VISCOSITY, MISSING_SCALAR_SECTION, NEGATIVE_PROPERTY
# ---------------------------------------------------------------------------

class TestBrokenRANS:
    def test_is_invalid(self):
        output = run_auditor("rans_broken")
        assert output["config"]["valid"] is False

    def test_has_at_least_three_errors(self):
        output = run_auditor("rans_broken")
        assert len(output["config"]["errors"]) >= 3

    def test_missing_variable_viscosity(self):
        output = run_auditor("rans_broken")
        codes = [e["code"] for e in output["config"]["errors"]]
        assert "MISSING_VARIABLE_VISCOSITY" in codes

    def test_missing_scalar_section(self):
        output = run_auditor("rans_broken")
        codes = [e["code"] for e in output["config"]["errors"]]
        assert "MISSING_SCALAR_SECTION" in codes

    def test_negative_property(self):
        output = run_auditor("rans_broken")
        codes = [e["code"] for e in output["config"]["errors"]]
        assert "NEGATIVE_PROPERTY" in codes


# ---------------------------------------------------------------------------
# Broken CHT: MISSING_SOLID_DIFFUSION, MISSING_SOLID_TRANSPORT, INVALID_POLYNOMIAL_ORDER
# ---------------------------------------------------------------------------

class TestBrokenCHT:
    def test_is_invalid(self):
        output = run_auditor("cht_broken")
        assert output["config"]["valid"] is False

    def test_has_at_least_three_errors(self):
        output = run_auditor("cht_broken")
        assert len(output["config"]["errors"]) >= 3

    def test_missing_solid_diffusion(self):
        output = run_auditor("cht_broken")
        codes = [e["code"] for e in output["config"]["errors"]]
        assert "MISSING_SOLID_DIFFUSION" in codes

    def test_missing_solid_transport(self):
        output = run_auditor("cht_broken")
        codes = [e["code"] for e in output["config"]["errors"]]
        assert "MISSING_SOLID_TRANSPORT" in codes

    def test_invalid_polynomial_order(self):
        output = run_auditor("cht_broken")
        codes = [e["code"] for e in output["config"]["errors"]]
        assert "INVALID_POLYNOMIAL_ORDER" in codes


# ---------------------------------------------------------------------------
# Broken Pipe: INVALID_FLOW_DIRECTION, SCALING_COEFF_OUT_OF_RANGE, EXPRESSION_ERROR
# ---------------------------------------------------------------------------

class TestBrokenPipe:
    def test_is_invalid(self):
        output = run_auditor("pipe_broken")
        assert output["config"]["valid"] is False

    def test_has_at_least_three_errors(self):
        output = run_auditor("pipe_broken")
        assert len(output["config"]["errors"]) >= 3

    def test_invalid_flow_direction(self):
        output = run_auditor("pipe_broken")
        codes = [e["code"] for e in output["config"]["errors"]]
        assert "INVALID_FLOW_DIRECTION" in codes

    def test_scaling_coeff_out_of_range(self):
        output = run_auditor("pipe_broken")
        codes = [e["code"] for e in output["config"]["errors"]]
        assert "SCALING_COEFF_OUT_OF_RANGE" in codes

    def test_expression_error(self):
        output = run_auditor("pipe_broken")
        codes = [e["code"] for e in output["config"]["errors"]]
        assert "EXPRESSION_ERROR" in codes


# ---------------------------------------------------------------------------
# Diagnostics — total DOF
# ---------------------------------------------------------------------------

class TestDOF:
    def test_rbc_dof(self):
        """RBC: 240 elements, N=7, dim=2 → 240 × 8² = 15360."""
        output = run_auditor("rbc_valid")
        assert output["diagnostics"]["total_dof"] == 240 * 64

    def test_rans_dof(self):
        """RANS: 384 elements, N=5, dim=2 → 384 × 6² = 13824."""
        output = run_auditor("rans_valid")
        assert output["diagnostics"]["total_dof"] == 384 * 36

    def test_cht_dof(self):
        """CHT: 200 elements, N=7, dim=2 → 200 × 8² = 12800."""
        output = run_auditor("cht_valid")
        assert output["diagnostics"]["total_dof"] == 200 * 64

    def test_pipe_dof(self):
        """Pipe: 160 elements, N=7, dim=2 → 160 × 8² = 10240."""
        output = run_auditor("pipe_valid")
        assert output["diagnostics"]["total_dof"] == 160 * 64


# ---------------------------------------------------------------------------
# Diagnostics — GLL spacing
# ---------------------------------------------------------------------------

class TestGLLSpacing:
    def test_rbc_gll_spacing(self):
        """RBC: N=7, min edge = 1/12 ≈ 0.0833.
        GLL first fraction for N=7 ≈ 0.06413.
        first_gll_spacing ≈ 0.0833 × 0.06413 ≈ 0.00534.
        """
        output = run_auditor("rbc_valid")
        gll = output["diagnostics"]["first_gll_spacing"]
        expected = (1.0 / 12.0) * 0.06413
        assert approx_eq(gll, expected, rel_tol=0.05), (
            f"first_gll_spacing={gll}, expected≈{expected}"
        )

    def test_rans_gll_spacing(self):
        """RANS: N=5, min edge = 1/16 = 0.0625.
        GLL first fraction for N=5 ≈ 0.11745.
        first_gll_spacing ≈ 0.0625 × 0.11745 ≈ 0.00734.
        """
        output = run_auditor("rans_valid")
        gll = output["diagnostics"]["first_gll_spacing"]
        expected = 0.0625 * 0.11745
        assert approx_eq(gll, expected, rel_tol=0.05), (
            f"first_gll_spacing={gll}, expected≈{expected}"
        )

    def test_cht_gll_spacing(self):
        """CHT: N=7, min edge = 0.1 (square elements).
        first_gll_spacing ≈ 0.1 × 0.06413 ≈ 0.006413.
        """
        output = run_auditor("cht_valid")
        gll = output["diagnostics"]["first_gll_spacing"]
        expected = 0.1 * 0.06413
        assert approx_eq(gll, expected, rel_tol=0.05), (
            f"first_gll_spacing={gll}, expected≈{expected}"
        )


# ---------------------------------------------------------------------------
# Diagnostics — y+ estimation
# ---------------------------------------------------------------------------

class TestYPlus:
    def test_rans_y_plus_is_number(self):
        """RANS pipe flow should have a y+ estimate."""
        output = run_auditor("rans_valid")
        yp = output["diagnostics"]["estimated_y_plus"]
        assert yp is not None, "y+ should be computed for RANS"
        assert isinstance(yp, (int, float)), f"y+ should be numeric, got {type(yp)}"
        assert yp > 0, f"y+ should be positive, got {yp}"

    def test_pipe_y_plus_is_number(self):
        """Pipe flow should have a y+ estimate."""
        output = run_auditor("pipe_valid")
        yp = output["diagnostics"]["estimated_y_plus"]
        assert yp is not None
        assert yp > 0

    def test_cht_y_plus_is_number(self):
        """CHT (has Re) should have a y+ estimate."""
        output = run_auditor("cht_valid")
        yp = output["diagnostics"]["estimated_y_plus"]
        assert yp is not None
        assert yp > 0

    def test_rbc_y_plus_null(self):
        """RBC (buoyancy-driven, no bulk Re) may have null y+."""
        output = run_auditor("rbc_valid")
        yp = output["diagnostics"]["estimated_y_plus"]
        # RBC doesn't have a direct bulk Reynolds number, y+ is either
        # null or computed from an equivalent Re — both are acceptable.
        # We just verify the field exists.
        assert "estimated_y_plus" in output["diagnostics"]
