
"""
Tests for the Bolted Joint Integrity Analyzer (/app/bjoint).

Verifies correctness of build system, torque-tension, stiffness, embedding,
thermal expansion, design margin, compatibility checks, probability calculations,
gnuplot diagram generation, batch processing, and SQLite logging/analytics.
"""

import json
import math
import os
import sqlite3
import subprocess
import tempfile
import textwrap

import pytest


DB_PATH = "/app/analysis.db"


def run_bjoint(toml_content: str) -> dict:
    """Write a TOML spec to a temp file, run bjoint, return parsed JSON."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write(toml_content)
        f.flush()
        tmp = f.name
    try:
        result = subprocess.run(
            ["/app/bjoint", tmp],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, (
            f"bjoint failed (rc={result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        return json.loads(result.stdout)
    finally:
        os.unlink(tmp)


def make_spec(
    size="M12", prop_class="10.9", grip=40.0,
    nut_std="ISO", nut_class=10,
    num_if=3, if_friction=0.15, roughness="normal", E_joint=210.0,
    joint_cte=12.0,
    washer_present=True, washer_hv=300,
    axial=0.0, shear=5.0,
    torque=100.0, mu_t_min=0.10, mu_t_max=0.18,
    mu_b_min=0.10, mu_b_max=0.18,
    temp=25, bolt_mat="ISO898",
    shim_present=False, shim_mu=0.7,
):
    wp = "true" if washer_present else "false"
    sp = "true" if shim_present else "false"
    return textwrap.dedent(f"""\
        [bolt]
        size = "{size}"
        property_class = "{prop_class}"
        grip_length_mm = {grip}

        [nut]
        standard = "{nut_std}"
        property_class = {nut_class}

        [joint]
        num_interfaces = {num_if}
        interface_friction = {if_friction}
        surface_roughness_class = "{roughness}"
        material_elastic_modulus_GPa = {E_joint}
        cte_ppm_per_K = {joint_cte}

        [washer]
        present = {wp}
        hardness_HV = {washer_hv}

        [loading]
        axial_kN = {axial}
        shear_kN = {shear}

        [tightening]
        torque_Nm = {torque}
        thread_friction_min = {mu_t_min}
        thread_friction_max = {mu_t_max}
        bearing_friction_min = {mu_b_min}
        bearing_friction_max = {mu_b_max}

        [environment]
        temperature_C = {temp}
        bolt_material = "{bolt_mat}"

        [friction_shim]
        present = {sp}
        friction_coefficient = {shim_mu}
    """)


# ── Helper assertions ──

def approx_kN(expected, tol=0.3):
    return pytest.approx(expected, abs=tol)


def approx_rel(expected, rel=0.03):
    return pytest.approx(expected, rel=rel)


def cleanup_db():
    """Remove database to start fresh."""
    if os.path.exists(DB_PATH):
        os.unlink(DB_PATH)


# ── Test: Makefile build system ──

class TestMakefileBuild:
    def test_makefile_exists(self):
        assert os.path.isfile("/app/Makefile"), "Makefile not found at /app/Makefile"

    def test_make_succeeds(self):
        result = subprocess.run(
            ["make"], cwd="/app", capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, f"make failed:\n{result.stderr}"

    def test_executable_after_make(self):
        subprocess.run(["make"], cwd="/app", capture_output=True, timeout=60)
        assert os.path.isfile("/app/bjoint"), "bjoint not found after make"
        assert os.access("/app/bjoint", os.X_OK), "bjoint not executable after make"

    def test_make_is_idempotent(self):
        r1 = subprocess.run(["make"], cwd="/app", capture_output=True, text=True, timeout=60)
        r2 = subprocess.run(["make"], cwd="/app", capture_output=True, text=True, timeout=60)
        assert r1.returncode == 0
        assert r2.returncode == 0

    def test_rebuild_after_removal(self):
        """Removing bjoint and running make should recreate it."""
        if os.path.isfile("/app/bjoint"):
            os.unlink("/app/bjoint")
        result = subprocess.run(
            ["make"], cwd="/app", capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, f"make rebuild failed:\n{result.stderr}"
        assert os.path.isfile("/app/bjoint"), "bjoint not recreated by make"
        assert os.access("/app/bjoint", os.X_OK), "bjoint not executable after rebuild"


# ── Test: executable exists and produces valid JSON ──

class TestBasicInfrastructure:
    def test_executable_exists(self):
        assert os.path.isfile("/app/bjoint"), "bjoint executable not found at /app/bjoint"
        assert os.access("/app/bjoint", os.X_OK), "bjoint is not executable"

    def test_produces_valid_json(self):
        spec = make_spec()
        out = run_bjoint(spec)
        required_keys = [
            "stress_area_mm2", "max_preload_kN", "min_preload_kN",
            "bolt_stiffness_kN_per_mm", "joint_stiffness_kN_per_mm",
            "load_factor_phi", "embedding_loss_kN",
            "differential_thermal_load_kN",
            "shear_grip_requirement_kN", "axial_clamp_reduction_kN",
            "total_preload_requirement_kN", "design_margin",
            "nut_compatible", "washer_suitable", "temperature_suitable",
            "thread_root_radius_range_mm", "probability_of_failure",
            "diagram_path",
        ]
        for k in required_keys:
            assert k in out, f"Missing key: {k}"

    def test_output_types(self):
        out = run_bjoint(make_spec())
        assert isinstance(out["stress_area_mm2"], (int, float))
        assert isinstance(out["differential_thermal_load_kN"], (int, float))
        assert isinstance(out["nut_compatible"], bool)
        assert isinstance(out["washer_suitable"], bool)
        assert isinstance(out["temperature_suitable"], bool)
        assert isinstance(out["thread_root_radius_range_mm"], list)
        assert len(out["thread_root_radius_range_mm"]) == 2
        assert isinstance(out["diagram_path"], str)


# ── Test: M12 10.9 pure shear friction-grip joint ──

class TestBasicFrictionGrip:
    """
    M12 property class 10.9, 40mm grip, 3 interfaces, normal roughness.
    Pure shear 5 kN, no axial load, torque 100 Nm.
    Thread/bearing friction: 0.10-0.18. CTE matched (steel-on-steel at 25C).

    Hand-computed reference values:
    - Stress area: 84.27 mm2
    - Max preload (min friction): ~59.51 kN
    - Min preload (max friction): ~35.68 kN
    - Bolt stiffness ~365.8 kN/mm
    - Joint stiffness ~2117 kN/mm
    - phi ~0.147
    - Embedding ~2.81 kN
    - Thermal load ~0 kN (CTE matched)
    - Shear grip: 5/0.15 = 33.33 kN
    - Total req ~36.14 kN
    - Design margin ~0.987
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        spec = make_spec()
        self.out = run_bjoint(spec)

    def test_stress_area(self):
        assert self.out["stress_area_mm2"] == approx_rel(84.27, rel=0.001)

    def test_max_preload(self):
        assert self.out["max_preload_kN"] == approx_kN(59.51, tol=0.5)

    def test_min_preload(self):
        assert self.out["min_preload_kN"] == approx_kN(35.68, tol=0.5)

    def test_bolt_stiffness(self):
        assert self.out["bolt_stiffness_kN_per_mm"] == approx_rel(365.8, rel=0.03)

    def test_joint_stiffness(self):
        assert self.out["joint_stiffness_kN_per_mm"] == approx_rel(2117.3, rel=0.03)

    def test_load_factor(self):
        assert self.out["load_factor_phi"] == approx_rel(0.1473, rel=0.05)

    def test_embedding_loss(self):
        assert self.out["embedding_loss_kN"] == approx_kN(2.81, tol=0.3)

    def test_thermal_load_zero(self):
        assert abs(self.out["differential_thermal_load_kN"]) < 0.01

    def test_shear_grip(self):
        assert self.out["shear_grip_requirement_kN"] == approx_kN(33.33, tol=0.1)

    def test_axial_clamp(self):
        assert self.out["axial_clamp_reduction_kN"] == approx_kN(0.0, tol=0.01)

    def test_total_preload_requirement(self):
        assert self.out["total_preload_requirement_kN"] == approx_kN(36.14, tol=0.5)

    def test_design_margin_below_one(self):
        dm = self.out["design_margin"]
        assert 0.85 < dm < 1.10, f"Design margin {dm} not in expected range"

    def test_nut_compatible(self):
        assert self.out["nut_compatible"] is True

    def test_washer_suitable(self):
        assert self.out["washer_suitable"] is True

    def test_temperature_suitable(self):
        assert self.out["temperature_suitable"] is True

    def test_thread_root_radius(self):
        rr = self.out["thread_root_radius_range_mm"]
        assert rr[0] == approx_rel(0.21875, rel=0.01)
        assert rr[1] == approx_rel(0.252, rel=0.01)

    def test_probability_of_failure(self):
        pof = self.out["probability_of_failure"]
        assert 0.001 < pof < 0.10, f"P(failure) = {pof} not in expected range"


# ── Test: friction shim dramatically improves design margin ──

class TestFrictionShimEffect:
    """With friction shim (mu=0.7), shear grip drops from 33.33 to 7.14 kN."""

    @pytest.fixture(autouse=True)
    def setup(self):
        spec = make_spec(shim_present=True, shim_mu=0.7)
        self.out = run_bjoint(spec)

    def test_shear_grip_with_shim(self):
        assert self.out["shear_grip_requirement_kN"] == approx_kN(7.14, tol=0.1)

    def test_design_margin_much_improved(self):
        dm = self.out["design_margin"]
        assert dm > 2.5, f"Design margin {dm} should be > 2.5 with friction shim"

    def test_total_req_reduced(self):
        assert self.out["total_preload_requirement_kN"] == approx_kN(9.95, tol=0.5)

    def test_probability_near_zero(self):
        assert self.out["probability_of_failure"] < 0.001


# ── Test: DIN nut compatibility (should fail for M12 8.8) ──

class TestDINNutIncompatible:
    """
    M12 bolt property class 8.8:
      bolt UTS load = 84.27 x 800 = 67416 N
    DIN class 8 nut proof load = 67000 N < 67416 N => NOT compatible.
    """

    def test_din_nut_fails(self):
        spec = make_spec(
            prop_class="8.8", nut_std="DIN", nut_class=8,
            torque=80.0,
        )
        out = run_bjoint(spec)
        assert out["nut_compatible"] is False

    def test_iso_nut_passes(self):
        spec = make_spec(
            prop_class="8.8", nut_std="ISO", nut_class=8,
            torque=80.0,
        )
        out = run_bjoint(spec)
        assert out["nut_compatible"] is True


# ── Test: temperature suitability ──

class TestTemperature:
    def test_iso898_at_200c_fails(self):
        spec = make_spec(temp=200, bolt_mat="ISO898")
        out = run_bjoint(spec)
        assert out["temperature_suitable"] is False

    def test_iso898_at_100c_passes(self):
        spec = make_spec(temp=100, bolt_mat="ISO898")
        out = run_bjoint(spec)
        assert out["temperature_suitable"] is True

    def test_a193_b7_at_350c_passes(self):
        spec = make_spec(temp=350, bolt_mat="A193_B7")
        out = run_bjoint(spec)
        assert out["temperature_suitable"] is True

    def test_a193_b7_at_450c_fails(self):
        spec = make_spec(temp=450, bolt_mat="A193_B7")
        out = run_bjoint(spec)
        assert out["temperature_suitable"] is False

    def test_inconel718_at_750c_passes(self):
        spec = make_spec(temp=750, bolt_mat="Inconel718")
        out = run_bjoint(spec)
        assert out["temperature_suitable"] is True


# ── Test: washer suitability ──

class TestWasher:
    def test_12_9_with_200hv_fails(self):
        spec = make_spec(prop_class="12.9", washer_hv=200, nut_class=12)
        out = run_bjoint(spec)
        assert out["washer_suitable"] is False

    def test_12_9_with_380hv_passes(self):
        spec = make_spec(prop_class="12.9", washer_hv=380, nut_class=12)
        out = run_bjoint(spec)
        assert out["washer_suitable"] is True

    def test_8_8_no_washer_fails(self):
        spec = make_spec(prop_class="8.8", washer_present=False, nut_class=8)
        out = run_bjoint(spec)
        assert out["washer_suitable"] is False

    def test_low_grade_no_washer_ok(self):
        spec = make_spec(
            prop_class="4.6", washer_present=False,
            nut_class=5, torque=20.0,
        )
        out = run_bjoint(spec)
        assert out["washer_suitable"] is True


# ── Test: thread root radius for different sizes ──

class TestThreadRootRadius:
    def test_m6_root_radius(self):
        spec = make_spec(size="M6", prop_class="8.8", nut_class=8, torque=15.0)
        out = run_bjoint(spec)
        rr = out["thread_root_radius_range_mm"]
        assert rr[0] == approx_rel(0.125, rel=0.01)
        assert rr[1] == approx_rel(0.144, rel=0.01)

    def test_m24_root_radius(self):
        spec = make_spec(
            size="M24", prop_class="8.8", nut_class=8,
            grip=80.0, torque=400.0,
        )
        out = run_bjoint(spec)
        rr = out["thread_root_radius_range_mm"]
        assert rr[0] == approx_rel(0.375, rel=0.01)
        assert rr[1] == approx_rel(0.432, rel=0.01)


# ── Test: combined axial + shear loading (M16 10.9) ──

class TestCombinedLoading:
    """
    M16 10.9, grip=50mm, axial=20kN, shear=8kN, mu_interface=0.20.
    Hand-computed references:
    - As=156.67, max preload ~91.24 kN, min ~54.19 kN
    - phi ~0.154, shear grip = 40 kN, axial clamp ~16.92 kN
    - Total req ~61.0 kN, design margin ~0.889
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        spec = make_spec(
            size="M16", prop_class="10.9", grip=50.0,
            nut_std="ISO", nut_class=10,
            num_if=3, if_friction=0.20, roughness="normal",
            axial=20.0, shear=8.0,
            torque=200.0,
        )
        self.out = run_bjoint(spec)

    def test_stress_area_m16(self):
        assert self.out["stress_area_mm2"] == approx_rel(156.67, rel=0.001)

    def test_max_preload(self):
        assert self.out["max_preload_kN"] == approx_kN(91.24, tol=1.0)

    def test_min_preload(self):
        assert self.out["min_preload_kN"] == approx_kN(54.19, tol=1.0)

    def test_load_factor(self):
        phi = self.out["load_factor_phi"]
        assert 0.10 < phi < 0.25, f"phi={phi} outside expected range"

    def test_shear_grip(self):
        assert self.out["shear_grip_requirement_kN"] == approx_kN(40.0, tol=0.1)

    def test_axial_clamp_reduction(self):
        acr = self.out["axial_clamp_reduction_kN"]
        assert 15.0 < acr < 19.0, f"Axial clamp reduction {acr} not in range"

    def test_total_requirement(self):
        assert self.out["total_preload_requirement_kN"] == approx_kN(61.0, tol=2.0)

    def test_design_margin_below_one(self):
        dm = self.out["design_margin"]
        assert 0.70 < dm < 1.05, f"Design margin {dm} not in expected range"

    def test_embedding_loss_nonzero(self):
        assert self.out["embedding_loss_kN"] > 2.0


# ── Test: stiffness calculations are physically reasonable ──

class TestStiffnessPhysics:
    def test_joint_stiffer_than_bolt(self):
        out = run_bjoint(make_spec())
        assert out["joint_stiffness_kN_per_mm"] > out["bolt_stiffness_kN_per_mm"]

    def test_phi_in_range(self):
        out = run_bjoint(make_spec())
        assert 0.05 < out["load_factor_phi"] < 0.25

    def test_longer_grip_lower_bolt_stiffness(self):
        out_short = run_bjoint(make_spec(grip=20.0))
        out_long = run_bjoint(make_spec(grip=60.0))
        assert out_long["bolt_stiffness_kN_per_mm"] < out_short["bolt_stiffness_kN_per_mm"]

    def test_longer_grip_different_phi(self):
        out_short = run_bjoint(make_spec(grip=20.0))
        out_long = run_bjoint(make_spec(grip=60.0))
        assert out_long["load_factor_phi"] < out_short["load_factor_phi"]


# ── Test: embedding loss scales with interfaces and roughness ──

class TestEmbedding:
    def test_more_interfaces_more_loss(self):
        out_3 = run_bjoint(make_spec(num_if=3))
        out_5 = run_bjoint(make_spec(num_if=5))
        assert out_5["embedding_loss_kN"] > out_3["embedding_loss_kN"]

    def test_rougher_surface_more_loss(self):
        out_fine = run_bjoint(make_spec(roughness="fine"))
        out_rough = run_bjoint(make_spec(roughness="rough"))
        assert out_rough["embedding_loss_kN"] > out_fine["embedding_loss_kN"]

    def test_rough_to_fine_ratio(self):
        """Rough (5um) should cause ~2.5x the embedding of fine (2um)."""
        out_fine = run_bjoint(make_spec(roughness="fine"))
        out_rough = run_bjoint(make_spec(roughness="rough"))
        ratio = out_rough["embedding_loss_kN"] / out_fine["embedding_loss_kN"]
        assert 2.0 < ratio < 3.0, f"Rough/fine ratio {ratio} not ~2.5"


# ── Test: preload changes with friction range ──

class TestPreloadFriction:
    def test_wider_friction_wider_preload_range(self):
        out_narrow = run_bjoint(make_spec(
            mu_t_min=0.12, mu_t_max=0.14,
            mu_b_min=0.12, mu_b_max=0.14,
        ))
        out_wide = run_bjoint(make_spec(
            mu_t_min=0.08, mu_t_max=0.22,
            mu_b_min=0.08, mu_b_max=0.22,
        ))
        narrow_range = out_narrow["max_preload_kN"] - out_narrow["min_preload_kN"]
        wide_range = out_wide["max_preload_kN"] - out_wide["min_preload_kN"]
        assert wide_range > narrow_range

    def test_max_preload_greater_than_min(self):
        out = run_bjoint(make_spec())
        assert out["max_preload_kN"] > out["min_preload_kN"]


# ── Test: probability of failure consistency ──

class TestProbability:
    def test_high_margin_low_probability(self):
        spec = make_spec(
            size="M20", prop_class="10.9", grip=60.0,
            nut_class=10, shear=2.0, axial=0.0,
            torque=400.0,
        )
        out = run_bjoint(spec)
        assert out["design_margin"] > 2.0
        assert out["probability_of_failure"] < 0.001

    def test_probability_between_zero_and_one(self):
        out = run_bjoint(make_spec())
        pof = out["probability_of_failure"]
        assert 0.0 <= pof <= 1.0

    def test_marginal_joint_higher_probability(self):
        out_marginal = run_bjoint(make_spec())
        out_safe = run_bjoint(make_spec(shim_present=True))
        assert out_marginal["probability_of_failure"] > out_safe["probability_of_failure"]


# ── Test: different bolt sizes produce correct lookups ──

class TestMultipleSizes:
    def test_m8_stress_area(self):
        spec = make_spec(size="M8", prop_class="8.8", nut_class=8, torque=25.0)
        out = run_bjoint(spec)
        assert out["stress_area_mm2"] == approx_rel(36.61, rel=0.001)

    def test_m20_stress_area(self):
        spec = make_spec(
            size="M20", prop_class="10.9", nut_class=10,
            grip=60.0, torque=400.0,
        )
        out = run_bjoint(spec)
        assert out["stress_area_mm2"] == approx_rel(244.79, rel=0.001)


# ── Test: differential thermal expansion ──

class TestThermalExpansion:
    def test_zero_at_assembly_temperature(self):
        """At 20C (assembly temp), thermal load is zero regardless of CTEs."""
        spec = make_spec(temp=20, joint_cte=23.0)
        out = run_bjoint(spec)
        assert abs(out["differential_thermal_load_kN"]) < 0.01

    def test_zero_when_cte_match(self):
        """When CTEs match, thermal load is zero even at elevated temp."""
        spec = make_spec(temp=150, joint_cte=12.0, bolt_mat="ISO898")
        out = run_bjoint(spec)
        assert abs(out["differential_thermal_load_kN"]) < 0.01

    def test_positive_when_joint_cte_higher(self):
        """Joint CTE > bolt CTE at elevated temp -> preload gain (positive)."""
        spec = make_spec(temp=100, joint_cte=23.0, bolt_mat="ISO898")
        out = run_bjoint(spec)
        assert out["differential_thermal_load_kN"] > 5.0

    def test_negative_when_bolt_cte_higher(self):
        """Bolt CTE > joint CTE at elevated temp -> preload loss (negative)."""
        spec = make_spec(temp=200, joint_cte=10.0, bolt_mat="Inconel718")
        out = run_bjoint(spec)
        assert out["differential_thermal_load_kN"] < -3.0

    def test_thermal_loss_increases_total_requirement(self):
        """Negative thermal load should increase total preload requirement."""
        spec_ref = make_spec(temp=20, joint_cte=10.0, bolt_mat="Inconel718")
        spec_hot = make_spec(temp=200, joint_cte=10.0, bolt_mat="Inconel718")
        out_ref = run_bjoint(spec_ref)
        out_hot = run_bjoint(spec_hot)
        assert out_hot["total_preload_requirement_kN"] > out_ref["total_preload_requirement_kN"]

    def test_thermal_gain_does_not_reduce_requirement(self):
        """Positive thermal load (gain) should not reduce total requirement."""
        spec_ref = make_spec(temp=20, joint_cte=23.0, bolt_mat="ISO898")
        spec_hot = make_spec(temp=100, joint_cte=23.0, bolt_mat="ISO898")
        out_ref = run_bjoint(spec_ref)
        out_hot = run_bjoint(spec_hot)
        assert abs(
            out_hot["total_preload_requirement_kN"]
            - out_ref["total_preload_requirement_kN"]
        ) < 0.1


# ── Test: gnuplot SVG diagram generation ──

class TestDiagramGeneration:
    def test_diagram_path_in_output(self):
        out = run_bjoint(make_spec())
        assert "diagram_path" in out
        assert out["diagram_path"], "diagram_path is empty"

    def test_diagram_file_exists(self):
        out = run_bjoint(make_spec())
        assert os.path.isfile(out["diagram_path"]), (
            f"SVG not found at {out['diagram_path']}"
        )

    def test_diagram_is_valid_svg(self):
        out = run_bjoint(make_spec())
        with open(out["diagram_path"]) as f:
            content = f.read()
        assert "<svg" in content.lower(), "File does not contain SVG content"

    def test_diagram_in_correct_directory(self):
        out = run_bjoint(make_spec())
        assert out["diagram_path"].startswith("/app/diagrams/"), (
            f"Diagram path {out['diagram_path']} not in /app/diagrams/"
        )

    def test_diagram_filename_contains_bolt_size(self):
        out = run_bjoint(make_spec(size="M16", torque=200.0, grip=50.0))
        basename = os.path.basename(out["diagram_path"])
        assert basename.startswith("M16_"), (
            f"Diagram filename '{basename}' doesn't start with M16_"
        )

    def test_diagram_id_matches_db(self):
        cleanup_db()
        out = run_bjoint(make_spec())
        basename = os.path.basename(out["diagram_path"])
        name_part = basename.replace(".svg", "")
        parts = name_part.split("_", 1)
        row_id = int(parts[1])
        conn = sqlite3.connect(DB_PATH)
        db_id = conn.execute(
            "SELECT id FROM analyses ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
        conn.close()
        assert row_id == db_id, f"Diagram ID {row_id} != DB ID {db_id}"


# ── Test: batch processing mode ──

class TestBatchMode:
    def test_batch_processes_all_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for i, size in enumerate(["M8", "M12", "M16"]):
                spec = make_spec(
                    size=size, torque=[25.0, 100.0, 200.0][i],
                    prop_class="8.8", nut_class=8,
                )
                with open(os.path.join(tmpdir, f"spec_{i:02d}.toml"), "w") as f:
                    f.write(spec)
            result = subprocess.run(
                ["/app/bjoint", "--batch", tmpdir],
                capture_output=True, text=True, timeout=60,
            )
            assert result.returncode == 0, f"Batch failed: {result.stderr}"
            lines = result.stdout.strip().split("\n")
            assert len(lines) == 3, f"Expected 3 JSONL lines, got {len(lines)}"
            for line in lines:
                obj = json.loads(line)
                assert "source_file" in obj
                assert "stress_area_mm2" in obj

    def test_batch_alphabetical_order(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for name in ["zebra.toml", "alpha.toml", "middle.toml"]:
                with open(os.path.join(tmpdir, name), "w") as f:
                    f.write(make_spec())
            result = subprocess.run(
                ["/app/bjoint", "--batch", tmpdir],
                capture_output=True, text=True, timeout=60,
            )
            lines = result.stdout.strip().split("\n")
            sources = [json.loads(line)["source_file"] for line in lines]
            assert sources == ["alpha.toml", "middle.toml", "zebra.toml"]

    def test_batch_logs_each_to_db(self):
        cleanup_db()
        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(3):
                with open(os.path.join(tmpdir, f"spec_{i}.toml"), "w") as f:
                    f.write(make_spec())
            subprocess.run(
                ["/app/bjoint", "--batch", tmpdir],
                capture_output=True, text=True, timeout=60,
            )
        conn = sqlite3.connect(DB_PATH)
        count = conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]
        conn.close()
        assert count == 3, f"Expected 3 rows after batch, found {count}"

    def test_batch_generates_diagrams(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(2):
                with open(os.path.join(tmpdir, f"spec_{i}.toml"), "w") as f:
                    f.write(make_spec())
            result = subprocess.run(
                ["/app/bjoint", "--batch", tmpdir],
                capture_output=True, text=True, timeout=60,
            )
            lines = result.stdout.strip().split("\n")
            for line in lines:
                obj = json.loads(line)
                assert os.path.isfile(obj["diagram_path"]), (
                    f"Batch diagram not found: {obj['diagram_path']}"
                )


# ── Test: SQLite database logging ──

class TestSQLiteLogging:
    """Verify that every analysis is persisted to /app/analysis.db."""

    def test_database_created(self):
        cleanup_db()
        run_bjoint(make_spec())
        assert os.path.isfile(DB_PATH), "analysis.db not created at /app/analysis.db"

    def test_table_exists_with_correct_name(self):
        cleanup_db()
        run_bjoint(make_spec())
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='analyses'"
        )
        tables = cursor.fetchall()
        conn.close()
        assert len(tables) == 1, "analyses table not found in database"

    def test_schema_has_required_columns(self):
        cleanup_db()
        run_bjoint(make_spec())
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute("PRAGMA table_info(analyses)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()
        required = {
            "id", "timestamp", "bolt_size", "property_class",
            "grip_length_mm", "design_margin", "probability_of_failure",
            "nut_compatible", "washer_suitable", "temperature_suitable",
            "risk_category", "full_result",
        }
        missing = required - columns
        assert not missing, f"Missing columns in analyses table: {missing}"

    def test_single_run_inserts_one_row(self):
        cleanup_db()
        run_bjoint(make_spec())
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute("SELECT COUNT(*) FROM analyses")
        count = cursor.fetchone()[0]
        conn.close()
        assert count == 1, f"Expected 1 row after single run, found {count}"

    def test_multiple_runs_accumulate_rows(self):
        cleanup_db()
        run_bjoint(make_spec())
        run_bjoint(make_spec(size="M16", torque=200.0, grip=50.0))
        run_bjoint(make_spec(size="M8", torque=25.0, prop_class="8.8", nut_class=8))
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute("SELECT COUNT(*) FROM analyses")
        count = cursor.fetchone()[0]
        conn.close()
        assert count == 3, f"Expected 3 rows after 3 runs, found {count}"

    def test_logged_bolt_size_matches(self):
        cleanup_db()
        run_bjoint(make_spec(size="M16", torque=200.0, grip=50.0))
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute("SELECT bolt_size FROM analyses LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        assert row[0] == "M16", f"bolt_size should be M16, got {row[0]}"

    def test_logged_design_margin_matches_output(self):
        cleanup_db()
        result = run_bjoint(make_spec())
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute(
            "SELECT design_margin FROM analyses ORDER BY id DESC LIMIT 1"
        )
        row = cursor.fetchone()
        conn.close()
        assert abs(row[0] - result["design_margin"]) < 0.001, (
            f"DB design_margin {row[0]} != output {result['design_margin']}"
        )

    def test_full_result_is_valid_json(self):
        cleanup_db()
        result = run_bjoint(make_spec())
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute(
            "SELECT full_result FROM analyses ORDER BY id DESC LIMIT 1"
        )
        row = cursor.fetchone()
        conn.close()
        logged = json.loads(row[0])
        assert logged["stress_area_mm2"] == result["stress_area_mm2"]
        assert logged["max_preload_kN"] == result["max_preload_kN"]

    def test_timestamp_is_iso8601(self):
        cleanup_db()
        run_bjoint(make_spec())
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute("SELECT timestamp FROM analyses LIMIT 1")
        ts = cursor.fetchone()[0]
        conn.close()
        from datetime import datetime
        try:
            datetime.fromisoformat(ts)
        except ValueError:
            pytest.fail(f"Timestamp '{ts}' is not valid ISO 8601 format")

    def test_boolean_fields_stored_as_integers(self):
        cleanup_db()
        run_bjoint(make_spec())
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute(
            "SELECT nut_compatible, washer_suitable, temperature_suitable "
            "FROM analyses LIMIT 1"
        )
        row = cursor.fetchone()
        conn.close()
        for i, name in enumerate(
            ["nut_compatible", "washer_suitable", "temperature_suitable"]
        ):
            assert row[i] in (0, 1), f"{name} should be 0 or 1, got {row[i]}"

    def test_grip_length_logged(self):
        cleanup_db()
        run_bjoint(make_spec(grip=55.5))
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute("SELECT grip_length_mm FROM analyses LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        assert abs(row[0] - 55.5) < 0.01, (
            f"grip_length_mm should be 55.5, got {row[0]}"
        )


# ── Test: SQLite views and triggers ──

class TestSQLiteViewsAndTriggers:
    def test_risk_category_critical(self):
        cleanup_db()
        spec = make_spec(shear=15.0)
        out = run_bjoint(spec)
        assert out["design_margin"] < 0.8, (
            f"Test setup: DM={out['design_margin']} should be < 0.8"
        )
        conn = sqlite3.connect(DB_PATH)
        cat = conn.execute(
            "SELECT risk_category FROM analyses ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
        conn.close()
        assert cat == "critical", f"Expected 'critical', got '{cat}'"

    def test_risk_category_marginal(self):
        cleanup_db()
        out = run_bjoint(make_spec())
        assert 0.8 <= out["design_margin"] < 1.0, (
            f"Test setup: DM={out['design_margin']} should be in [0.8, 1.0)"
        )
        conn = sqlite3.connect(DB_PATH)
        cat = conn.execute(
            "SELECT risk_category FROM analyses ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
        conn.close()
        assert cat == "marginal", f"Expected 'marginal', got '{cat}'"

    def test_risk_category_acceptable(self):
        cleanup_db()
        spec = make_spec(shear=3.0)
        out = run_bjoint(spec)
        assert 1.0 <= out["design_margin"] < 2.0, (
            f"Test setup: DM={out['design_margin']} should be in [1.0, 2.0)"
        )
        conn = sqlite3.connect(DB_PATH)
        cat = conn.execute(
            "SELECT risk_category FROM analyses ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
        conn.close()
        assert cat == "acceptable", f"Expected 'acceptable', got '{cat}'"

    def test_risk_category_over_designed(self):
        cleanup_db()
        spec = make_spec(shim_present=True, shim_mu=0.7)
        out = run_bjoint(spec)
        assert out["design_margin"] >= 2.0, (
            f"Test setup: DM={out['design_margin']} should be >= 2.0"
        )
        conn = sqlite3.connect(DB_PATH)
        cat = conn.execute(
            "SELECT risk_category FROM analyses ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
        conn.close()
        assert cat == "over_designed", f"Expected 'over_designed', got '{cat}'"

    def test_risk_summary_view_exists(self):
        cleanup_db()
        run_bjoint(make_spec())
        conn = sqlite3.connect(DB_PATH)
        views = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view' AND name='risk_summary'"
        ).fetchall()
        conn.close()
        assert len(views) == 1, "risk_summary view not found"

    def test_risk_summary_aggregation(self):
        cleanup_db()
        run_bjoint(make_spec(size="M12"))
        run_bjoint(make_spec(size="M12", shear=3.0))
        run_bjoint(make_spec(size="M16", torque=200.0, grip=50.0))
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT bolt_size, analysis_count, avg_design_margin, "
            "min_design_margin, max_pof "
            "FROM risk_summary ORDER BY bolt_size"
        ).fetchall()
        conn.close()
        assert len(rows) == 2, f"Expected 2 groups (M12, M16), got {len(rows)}"
        m12_row = [r for r in rows if r[0] == "M12"][0]
        assert m12_row[1] == 2, f"M12 should have 2 analyses, got {m12_row[1]}"
        assert m12_row[3] is not None, "min_design_margin should not be None"

    def test_trigger_exists(self):
        cleanup_db()
        run_bjoint(make_spec())
        conn = sqlite3.connect(DB_PATH)
        triggers = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        ).fetchall()
        conn.close()
        trigger_names = [t[0] for t in triggers]
        assert "classify_risk" in trigger_names, (
            f"classify_risk trigger not found; triggers: {trigger_names}"
        )
