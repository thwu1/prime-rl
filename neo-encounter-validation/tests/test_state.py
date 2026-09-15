
import json
import math
import os

import requests

AU_KM = 149597870.700
GM_EARTH = 398600.4418
CAD_URL = "https://ssd-api.jpl.nasa.gov/cad.api"


def load_results():
    with open("/app/results.json") as f:
        return json.load(f)


def get_cad_reference():
    """Query CAD API for reference data."""
    params = {
        "date-min": "2024-01-01",
        "date-max": "2024-12-31",
        "dist-max": "0.01",
        "sort": "dist",
    }
    resp = requests.get(CAD_URL, params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    fields = data["fields"]
    des_idx = fields.index("des")
    seen = set()
    unique_des = []
    for row in data["data"]:
        des = row[des_idx]
        if des not in seen:
            seen.add(des)
            unique_des.append(des)
    return unique_des


class TestResultsExist:
    def test_results_file_exists(self):
        assert os.path.exists("/app/results.json"), "results.json not found at /app/"

    def test_results_is_valid_json(self):
        data = load_results()
        assert isinstance(data, dict)

    def test_preliminary_not_copied(self):
        """Ensure the solver did not simply copy the flawed preliminary analysis."""
        data = load_results()
        for enc in data["neo_encounters"]:
            dist = enc.get("computed_dist_au", enc.get("dist_au", 999))
            assert dist < 0.05, (
                f"{enc.get('designation', '?')}: computed_dist_au={dist} is too large — "
                "appears to be a heliocentric distance, not a geocentric close approach distance"
            )


class TestResultsStructure:
    def test_has_neo_encounters_key(self):
        data = load_results()
        assert "neo_encounters" in data, "Missing top-level 'neo_encounters' key"

    def test_encounters_is_list(self):
        data = load_results()
        assert isinstance(data["neo_encounters"], list)

    def test_required_keys_present(self):
        data = load_results()
        required = [
            "designation", "close_approach_jd", "cad_dist_au", "computed_dist_au",
            "cad_v_rel_kms", "computed_v_rel_kms", "cad_v_inf_kms",
            "computed_v_inf_kms", "vis_viva_residual", "tisserand_jupiter",
            "deflection_angle_deg",
        ]
        for enc in data["neo_encounters"]:
            for key in required:
                assert key in enc, f"Missing key '{key}' in encounter for {enc.get('designation', '?')}"

    def test_values_are_numeric(self):
        data = load_results()
        numeric_keys = [
            "close_approach_jd", "cad_dist_au", "computed_dist_au",
            "cad_v_rel_kms", "computed_v_rel_kms", "cad_v_inf_kms",
            "computed_v_inf_kms", "vis_viva_residual", "tisserand_jupiter",
            "deflection_angle_deg",
        ]
        for enc in data["neo_encounters"]:
            for key in numeric_keys:
                val = enc[key]
                assert isinstance(val, (int, float)), (
                    f"{enc['designation']}: '{key}' is {type(val).__name__}, expected numeric"
                )


class TestEncounterCount:
    def test_five_encounters(self):
        data = load_results()
        assert len(data["neo_encounters"]) == 5, (
            f"Expected 5 encounters, got {len(data['neo_encounters'])}"
        )


class TestDesignationsMatchCAD:
    def test_designations_in_cad_top_results(self):
        """At least 4 of 5 designations should appear in CAD top-12 closest."""
        data = load_results()
        result_des = set(enc["designation"] for enc in data["neo_encounters"])
        cad_des = get_cad_reference()
        cad_top12 = set(cad_des[:12])
        matches = result_des & cad_top12
        assert len(matches) >= 4, (
            f"Only {len(matches)} of 5 designations match CAD top-12. "
            f"Result: {result_des}, CAD top-12: {cad_top12}"
        )


class TestDistanceCrossValidation:
    def test_computed_dist_matches_cad(self):
        """Computed distance should be within 10% of CAD-reported distance."""
        data = load_results()
        for enc in data["neo_encounters"]:
            cad = enc["cad_dist_au"]
            comp = enc["computed_dist_au"]
            assert cad > 0, f"{enc['designation']}: cad_dist_au must be positive"
            assert comp > 0, f"{enc['designation']}: computed_dist_au must be positive"
            rel_err = abs(comp - cad) / cad
            assert rel_err < 0.10, (
                f"{enc['designation']}: distance error {rel_err:.2%} exceeds 10% "
                f"(cad={cad:.6e}, computed={comp:.6e})"
            )


class TestVrelCrossValidation:
    def test_computed_v_rel_matches_cad(self):
        """Computed relative velocity should be within 10% of CAD v_rel."""
        data = load_results()
        for enc in data["neo_encounters"]:
            cad = enc["cad_v_rel_kms"]
            comp = enc["computed_v_rel_kms"]
            assert cad > 0
            assert comp > 0
            rel_err = abs(comp - cad) / cad
            assert rel_err < 0.10, (
                f"{enc['designation']}: v_rel error {rel_err:.2%} exceeds 10% "
                f"(cad={cad:.4f}, computed={comp:.4f})"
            )


class TestVinfConsistency:
    def test_v_inf_energy_equation(self):
        """v_inf should satisfy v_inf^2 = v_rel^2 - 2*GM_Earth/r_ca."""
        data = load_results()
        for enc in data["neo_encounters"]:
            v_rel = enc["computed_v_rel_kms"]
            v_inf = enc["computed_v_inf_kms"]
            dist_km = enc["computed_dist_au"] * AU_KM
            assert dist_km > 0
            v_inf_check = math.sqrt(max(0.0, v_rel ** 2 - 2.0 * GM_EARTH / dist_km))
            if v_inf > 0.5:
                rel_err = abs(v_inf_check - v_inf) / v_inf
                assert rel_err < 0.05, (
                    f"{enc['designation']}: v_inf consistency error {rel_err:.2%} "
                    f"(formula={v_inf_check:.4f}, reported={v_inf:.4f})"
                )


class TestVinfCadCrossCheck:
    def test_computed_v_inf_matches_cad(self):
        """Computed v_inf should be within 15% of CAD v_inf."""
        data = load_results()
        for enc in data["neo_encounters"]:
            cad = enc["cad_v_inf_kms"]
            comp = enc["computed_v_inf_kms"]
            if cad > 0.5:
                rel_err = abs(comp - cad) / cad
                assert rel_err < 0.15, (
                    f"{enc['designation']}: v_inf cross-check error {rel_err:.2%} "
                    f"(cad={cad:.4f}, computed={comp:.4f})"
                )


class TestVisVivaResidual:
    def test_vis_viva_small_residual(self):
        """Vis-viva residual should be under 1%."""
        data = load_results()
        for enc in data["neo_encounters"]:
            residual = enc["vis_viva_residual"]
            assert 0.0 <= residual < 0.01, (
                f"{enc['designation']}: vis-viva residual {residual:.4e} exceeds 0.01"
            )


class TestTisserandRange:
    def test_tisserand_physical_range(self):
        """Tisserand parameter should be in (1, 12) for NEOs."""
        data = load_results()
        for enc in data["neo_encounters"]:
            t_j = enc["tisserand_jupiter"]
            assert 1.0 < t_j < 12.0, (
                f"{enc['designation']}: T_J={t_j:.3f} outside physical range (1, 12)"
            )


class TestDeflectionAngle:
    def test_deflection_angle_range(self):
        """Deflection angle should be in (0, 180) degrees."""
        data = load_results()
        for enc in data["neo_encounters"]:
            delta = enc["deflection_angle_deg"]
            assert 0.0 < delta < 180.0, (
                f"{enc['designation']}: deflection={delta:.3f} deg outside (0, 180)"
            )

    def test_deflection_consistent_with_v_inf(self):
        """Deflection must be consistent with encounter geometry to within 5%."""
        data = load_results()
        encounters = data["neo_encounters"]
        for enc in encounters:
            v_inf = enc["computed_v_inf_kms"]
            dist_km = enc["computed_dist_au"] * AU_KM
            delta = enc["deflection_angle_deg"]
            if v_inf > 0.5 and dist_km > 0:
                e_hyp = 1.0 + dist_km * v_inf ** 2 / GM_EARTH
                expected_delta = math.degrees(2.0 * math.asin(1.0 / e_hyp))
                rel_err = abs(expected_delta - delta) / expected_delta
                assert rel_err < 0.05, (
                    f"{enc['designation']}: deflection inconsistency {rel_err:.2%} "
                    f"(expected={expected_delta:.3f} deg, reported={delta:.3f} deg)"
                )
