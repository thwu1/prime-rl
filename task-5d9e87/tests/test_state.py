"""
Tests for CadQuery Assembly Feature Extraction & Conformance Audit.

"""

import json
import math
import os
import pytest

RESULTS_PATH = "/app/analysis.json"
SPEC_PATH = "/app/assembly_spec.json"
CORRECTED_DIR = "/app/parts_corrected"
PART_NAMES = ["base_plate", "bracket", "bushing", "flange", "housing", "shaft"]
CONFORMING = {"base_plate", "bracket", "shaft"}
NON_CONFORMING = {"bushing", "flange", "housing"}


@pytest.fixture(scope="module")
def results():
    assert os.path.isfile(RESULTS_PATH), f"{RESULTS_PATH} does not exist"
    with open(RESULTS_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def spec():
    with open(SPEC_PATH) as f:
        return json.load(f)


# ── JSON structure ──────────────────────────────────────────────────

class TestJsonStructure:
    def test_top_level_keys(self, results):
        required = {"features", "conformance", "assembly_mates"}
        assert required.issubset(set(results.keys())), \
            f"Missing top-level keys: {required - set(results.keys())}"

    def test_all_parts_in_features(self, results):
        for name in PART_NAMES:
            assert name in results["features"], f"'{name}' missing from features"

    def test_all_parts_in_conformance(self, results):
        for name in PART_NAMES:
            assert name in results["conformance"], f"'{name}' missing from conformance"

    def test_feature_subkeys(self, results):
        for name in PART_NAMES:
            feat = results["features"][name]
            assert "volume_mm3" in feat, f"'{name}' features missing volume_mm3"
            assert "cylindrical_surfaces" in feat, \
                f"'{name}' features missing cylindrical_surfaces"
            assert isinstance(feat["cylindrical_surfaces"], list)

    def test_conformance_subkeys(self, results):
        for name in PART_NAMES:
            conf = results["conformance"][name]
            assert "passes" in conf, f"'{name}' conformance missing 'passes'"
            assert "issues" in conf, f"'{name}' conformance missing 'issues'"
            assert "corrected_code" in conf, \
                f"'{name}' conformance missing 'corrected_code'"

    def test_cylindrical_surface_format(self, results):
        for name in PART_NAMES:
            for cs in results["features"][name]["cylindrical_surfaces"]:
                assert "radius_mm" in cs, f"cylindrical_surface missing radius_mm"
                assert "axis" in cs, f"cylindrical_surface missing axis"
                assert isinstance(cs["axis"], list) and len(cs["axis"]) == 3

    def test_all_mate_ids_present(self, results):
        expected = {"shaft_step1_in_bushing", "shaft_step2_in_housing",
                    "flange_base_bore_match", "housing_bore_axis"}
        actual = set(results["assembly_mates"].keys())
        assert expected.issubset(actual), \
            f"Missing mate IDs: {expected - actual}"

    def test_mate_subkeys(self, results):
        for mate_id, mate in results["assembly_mates"].items():
            assert "feasible" in mate, f"Mate '{mate_id}' missing 'feasible'"
            assert "details" in mate, f"Mate '{mate_id}' missing 'details'"


# ── Feature extraction for conforming parts ─────────────────────────

class TestFeatureExtraction:
    def test_base_plate_central_bore(self, results):
        """base_plate must have a cylindrical surface with radius ~20mm (bore diam 40)."""
        surfs = results["features"]["base_plate"]["cylindrical_surfaces"]
        radii = [s["radius_mm"] for s in surfs]
        assert any(abs(r - 20.0) < 0.5 for r in radii), \
            f"Expected bore r~20 in base_plate, got radii: {radii}"

    def test_base_plate_bolt_holes(self, results):
        """base_plate must have 4 cylindrical surfaces with radius ~4mm (Ø8 holes)."""
        surfs = results["features"]["base_plate"]["cylindrical_surfaces"]
        bolts = [s for s in surfs if abs(s["radius_mm"] - 4.0) < 0.5]
        assert len(bolts) == 4, \
            f"Expected 4 bolt holes r~4 in base_plate, got {len(bolts)}"

    def test_base_plate_all_axes_vertical(self, results):
        """All base_plate bores/holes should have Z-aligned axes."""
        surfs = results["features"]["base_plate"]["cylindrical_surfaces"]
        for s in surfs:
            ax = s["axis"]
            assert abs(ax[2]) > 0.95, \
                f"base_plate cylindrical axis {ax} not Z-aligned"

    def test_shaft_step1_radius(self, results):
        """shaft must have a cylindrical surface with radius ~19mm (Ø38)."""
        surfs = results["features"]["shaft"]["cylindrical_surfaces"]
        radii = [s["radius_mm"] for s in surfs]
        assert any(abs(r - 19.0) < 0.5 for r in radii), \
            f"Expected step1 r~19 in shaft, got radii: {radii}"

    def test_shaft_step2_radius(self, results):
        """shaft must have a cylindrical surface with radius ~12mm (Ø24)."""
        surfs = results["features"]["shaft"]["cylindrical_surfaces"]
        radii = [s["radius_mm"] for s in surfs]
        assert any(abs(r - 12.0) < 0.5 for r in radii), \
            f"Expected step2 r~12 in shaft, got radii: {radii}"

    def test_bracket_no_cylinders(self, results):
        """bracket (prismatic L-shape) must have zero cylindrical surfaces."""
        surfs = results["features"]["bracket"]["cylindrical_surfaces"]
        assert len(surfs) == 0, \
            f"bracket should have no cylindrical faces, got {len(surfs)}"

    def test_base_plate_volume(self, results):
        """base_plate volume ~ 122135 mm³."""
        vol = results["features"]["base_plate"]["volume_mm3"]
        expected = 144000 - 6960 * math.pi  # ~122135
        assert abs(vol - expected) / expected < 0.02, \
            f"base_plate volume {vol:.0f} vs expected {expected:.0f}"

    def test_shaft_volume(self, results):
        """shaft volume ~ 52120 mm³."""
        vol = results["features"]["shaft"]["volume_mm3"]
        expected = 16590 * math.pi  # ~52120
        assert abs(vol - expected) / expected < 0.02, \
            f"shaft volume {vol:.0f} vs expected {expected:.0f}"

    def test_bracket_volume(self, results):
        """bracket volume = 24000 mm³ exactly."""
        vol = results["features"]["bracket"]["volume_mm3"]
        assert abs(vol - 24000.0) / 24000.0 < 0.02, \
            f"bracket volume {vol:.0f} vs expected 24000"


# ── Defective part features (anti-cheat) ────────────────────────────

class TestDefectiveFeatures:
    def test_housing_bore_axis_is_Y(self, results):
        """Housing bore axis should be Y-aligned (defective), proving actual measurement."""
        surfs = results["features"]["housing"]["cylindrical_surfaces"]
        bore = [s for s in surfs if abs(s["radius_mm"] - 20.0) < 0.5]
        assert len(bore) > 0, "Housing should have bore r~20"
        ax = bore[0]["axis"]
        assert abs(ax[1]) > 0.9, \
            f"Defective housing bore axis should be Y-aligned, got {ax}"

    def test_housing_volume_reflects_defect(self, results):
        """Housing defective volume (~379469) must differ from correct (~404602)."""
        vol = results["features"]["housing"]["volume_mm3"]
        defective_expected = 480000 - 32000 * math.pi  # ~379469
        correct_expected = 480000 - 24000 * math.pi    # ~404602
        # Volume should be close to defective, not correct
        assert abs(vol - defective_expected) / defective_expected < 0.02, \
            f"Housing volume {vol:.0f} should be ~{defective_expected:.0f} (defective)"
        assert abs(vol - correct_expected) / correct_expected > 0.03, \
            f"Housing volume {vol:.0f} should NOT match correct {correct_expected:.0f}"

    def test_bushing_bore_radius_19(self, results):
        """Bushing inner bore should show r~19 (defective), not r~20 (correct)."""
        surfs = results["features"]["bushing"]["cylindrical_surfaces"]
        # Exclude outer cylinder r~25
        inner = [s for s in surfs if s["radius_mm"] < 22]
        assert len(inner) > 0, "Bushing should have inner bore"
        assert any(abs(s["radius_mm"] - 19.0) < 0.5 for s in inner), \
            f"Defective bushing bore should be r~19, got {[s['radius_mm'] for s in inner]}"

    def test_flange_bore_radius_7_5(self, results):
        """Flange central bore should show r~7.5 (defective), not r~20."""
        surfs = results["features"]["flange"]["cylindrical_surfaces"]
        # Central bore: not bolt holes (r~4) and not outer (r~50)
        bore = [s for s in surfs if 5.0 < s["radius_mm"] < 15.0]
        assert len(bore) > 0, "Flange should have central bore"
        assert any(abs(s["radius_mm"] - 7.5) < 0.5 for s in bore), \
            f"Defective flange bore should be r~7.5, got {[s['radius_mm'] for s in bore]}"


# ── Conformance classification ──────────────────────────────────────

class TestConformance:
    @pytest.mark.parametrize("name", sorted(CONFORMING))
    def test_conforming_parts(self, results, name):
        assert results["conformance"][name]["passes"] is True, \
            f"{name} should be conforming"

    @pytest.mark.parametrize("name", sorted(NON_CONFORMING))
    def test_non_conforming_parts(self, results, name):
        assert results["conformance"][name]["passes"] is False, \
            f"{name} should be non-conforming"

    @pytest.mark.parametrize("name", sorted(NON_CONFORMING))
    def test_issues_non_empty(self, results, name):
        issues = results["conformance"][name]["issues"]
        assert isinstance(issues, list) and len(issues) > 0, \
            f"{name} should have non-empty issues list"

    @pytest.mark.parametrize("name", sorted(NON_CONFORMING))
    def test_corrected_code_is_cadquery(self, results, name):
        code = results["conformance"][name]["corrected_code"]
        assert isinstance(code, str) and "cadquery" in code, \
            f"{name} corrected_code must contain valid CadQuery code"

    @pytest.mark.parametrize("name", sorted(CONFORMING))
    def test_conforming_no_correction(self, results, name):
        assert results["conformance"][name]["corrected_code"] == "", \
            f"{name} is conforming — corrected_code should be empty"


# ── Corrected files ─────────────────────────────────────────────────

class TestCorrectedFiles:
    @pytest.mark.parametrize("name", sorted(NON_CONFORMING))
    def test_file_exists(self, name):
        path = os.path.join(CORRECTED_DIR, f"{name}.py")
        assert os.path.isfile(path), f"{path} does not exist"

    @pytest.mark.parametrize("name", sorted(NON_CONFORMING))
    def test_file_executes(self, name):
        path = os.path.join(CORRECTED_DIR, f"{name}.py")
        with open(path) as f:
            code = f.read()
        ns = {}
        exec(code, ns)
        assert "r" in ns, f"Corrected {name}.py must define variable 'r'"

    def test_corrected_housing_volume(self):
        """Corrected housing: bore through Z (60mm), volume ~404602."""
        path = os.path.join(CORRECTED_DIR, "housing.py")
        with open(path) as f:
            code = f.read()
        ns = {}
        exec(code, ns)
        vol = ns["r"].val().Volume()
        expected = 480000 - 24000 * math.pi
        assert abs(vol - expected) / expected < 0.02, \
            f"Corrected housing volume {vol:.0f} vs expected {expected:.0f}"

    def test_corrected_housing_bore_axis_Z(self):
        """Corrected housing bore axis must be Z-aligned."""
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.GeomAbs import GeomAbs_Cylinder

        path = os.path.join(CORRECTED_DIR, "housing.py")
        with open(path) as f:
            code = f.read()
        ns = {}
        exec(code, ns)
        shape = ns["r"].val()

        found = False
        for face in shape.Faces():
            adaptor = BRepAdaptor_Surface(face.wrapped)
            if adaptor.GetType() == GeomAbs_Cylinder:
                cyl = adaptor.Cylinder()
                if abs(cyl.Radius() - 20.0) < 0.5:
                    ax = cyl.Axis().Direction()
                    assert abs(ax.Z()) > 0.95, \
                        f"Corrected housing bore axis Z={ax.Z():.4f}, expected ~1"
                    found = True
                    break
        assert found, "No bore r~20 found in corrected housing"

    def test_corrected_flange_volume(self):
        """Corrected flange: bore Ø40, volume ~76745."""
        path = os.path.join(CORRECTED_DIR, "flange.py")
        with open(path) as f:
            code = f.read()
        ns = {}
        exec(code, ns)
        vol = ns["r"].val().Volume()
        expected = 12 * math.pi * (2500 - 64 - 400)
        assert abs(vol - expected) / expected < 0.02, \
            f"Corrected flange volume {vol:.0f} vs expected {expected:.0f}"

    def test_corrected_flange_bore_radius(self):
        """Corrected flange must have bore r~20 (diam 40)."""
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.GeomAbs import GeomAbs_Cylinder

        path = os.path.join(CORRECTED_DIR, "flange.py")
        with open(path) as f:
            code = f.read()
        ns = {}
        exec(code, ns)
        shape = ns["r"].val()

        radii = []
        for face in shape.Faces():
            adaptor = BRepAdaptor_Surface(face.wrapped)
            if adaptor.GetType() == GeomAbs_Cylinder:
                radii.append(adaptor.Cylinder().Radius())
        assert any(abs(r - 20.0) < 0.5 for r in radii), \
            f"Corrected flange should have bore r~20, got {radii}"

    def test_corrected_bushing_volume(self):
        """Corrected bushing: bore Ø40, volume ~24740."""
        path = os.path.join(CORRECTED_DIR, "bushing.py")
        with open(path) as f:
            code = f.read()
        ns = {}
        exec(code, ns)
        vol = ns["r"].val().Volume()
        expected = math.pi * (625 - 400) * 35
        assert abs(vol - expected) / expected < 0.02, \
            f"Corrected bushing volume {vol:.0f} vs expected {expected:.0f}"

    def test_corrected_bushing_bore_radius(self):
        """Corrected bushing must have bore r~20 (diam 40)."""
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.GeomAbs import GeomAbs_Cylinder

        path = os.path.join(CORRECTED_DIR, "bushing.py")
        with open(path) as f:
            code = f.read()
        ns = {}
        exec(code, ns)
        shape = ns["r"].val()

        radii = []
        for face in shape.Faces():
            adaptor = BRepAdaptor_Surface(face.wrapped)
            if adaptor.GetType() == GeomAbs_Cylinder:
                radii.append(adaptor.Cylinder().Radius())
        inner_radii = [r for r in radii if r < 22]
        assert any(abs(r - 20.0) < 0.5 for r in inner_radii), \
            f"Corrected bushing bore should be r~20, got {inner_radii}"

    @pytest.mark.parametrize("name", sorted(NON_CONFORMING))
    def test_corrected_code_valid_python(self, results, name):
        code = results["conformance"][name]["corrected_code"]
        try:
            compile(code, f"<{name}_corrected>", "exec")
        except SyntaxError as e:
            pytest.fail(f"corrected_code for {name} has syntax error: {e}")


# ── Assembly mate analysis ──────────────────────────────────────────

class TestMateAnalysis:
    def test_shaft_bushing_infeasible(self, results):
        """Bushing bore Ø38 for shaft Ø38 → 0mm clearance → infeasible."""
        mate = results["assembly_mates"]["shaft_step1_in_bushing"]
        assert mate["feasible"] is False, \
            "shaft_step1_in_bushing should be infeasible (zero clearance)"

    def test_shaft_bushing_clearance_near_zero(self, results):
        """Radial clearance should be ~0mm (bore r=19 == shaft r=19)."""
        mate = results["assembly_mates"]["shaft_step1_in_bushing"]
        if mate.get("radial_clearance_mm") is not None:
            assert mate["radial_clearance_mm"] < 0.5, \
                f"Expected ~0mm clearance, got {mate['radial_clearance_mm']}"

    def test_housing_bore_axis_infeasible(self, results):
        """Housing bore axis is Y not Z → axis alignment check fails."""
        mate = results["assembly_mates"]["housing_bore_axis"]
        assert mate["feasible"] is False, \
            "housing_bore_axis should be infeasible (axis deviation ~90°)"

    def test_flange_base_bore_infeasible(self, results):
        """Flange bore Ø15 vs base_plate bore Ø40 → bore match fails."""
        mate = results["assembly_mates"]["flange_base_bore_match"]
        assert mate["feasible"] is False, \
            "flange_base_bore_match should be infeasible (Ø15 ≠ Ø40)"

    def test_shaft_housing_clearance_value(self, results):
        """Housing bore is Ø40 for shaft step2 Ø24 → radial clearance ~8mm."""
        mate = results["assembly_mates"]["shaft_step2_in_housing"]
        if mate.get("radial_clearance_mm") is not None:
            assert 5.0 < mate["radial_clearance_mm"] < 12.0, \
                f"Expected clearance ~8mm, got {mate['radial_clearance_mm']}"

    def test_mate_details_non_empty(self, results):
        for mate_id, mate in results["assembly_mates"].items():
            assert isinstance(mate["details"], str) and len(mate["details"]) > 5, \
                f"Mate '{mate_id}' should have a meaningful details string"
