
import json
import math
import copy
import os
import subprocess
import tempfile
import pytest


def run_solver(config_dict, output_suffix=""):
    """Run the VLM solver with a given config and return parsed results."""
    tmp_config = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, dir="/tmp"
    )
    json.dump(config_dict, tmp_config)
    tmp_config.close()

    out_path = f"/tmp/results{output_suffix}.json"
    result = subprocess.run(
        ["python3", "/app/vlm_solver.py", tmp_config.name, out_path],
        capture_output=True,
        text=True,
        timeout=120,
    )
    os.unlink(tmp_config.name)
    assert result.returncode == 0, (
        f"Solver exited with code {result.returncode}.\n"
        f"STDOUT: {result.stdout[-2000:]}\nSTDERR: {result.stderr[-2000:]}"
    )
    with open(out_path) as f:
        return json.load(f)


def load_original_config():
    for path in ["/app/config.json", "/data/config.json"]:
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    raise FileNotFoundError("config.json not found at /app or /data")


def make_config_at_alpha(original, alpha_deg):
    """Return a copy of the config with all cases set to a given alpha."""
    cfg = copy.deepcopy(original)
    for case in cfg["cases"]:
        case["alpha_deg"] = alpha_deg
    return cfg


# ---------------------------------------------------------------
# 1. Output format and basic sanity
# ---------------------------------------------------------------

class TestOutputFormat:
    @pytest.fixture(autouse=True, scope="class")
    def results(self, request):
        cfg = load_original_config()
        request.cls.cfg = cfg
        request.cls.res = run_solver(cfg, "_format")

    def test_cases_present(self):
        assert "cases" in self.res
        assert len(self.res["cases"]) == len(self.cfg["cases"])

    def test_required_keys(self):
        required = [
            "CL", "CDi", "CM", "CL_alpha", "CM_alpha",
            "static_margin", "oswald_efficiency", "circulations",
        ]
        for case in self.res["cases"]:
            for key in required:
                assert key in case, f"Missing key '{key}' in case '{case.get('name')}'"

    def test_values_are_finite(self):
        for case in self.res["cases"]:
            for key in ["CL", "CDi", "CM", "CL_alpha", "CM_alpha",
                        "static_margin", "oswald_efficiency"]:
                v = case[key]
                assert isinstance(v, (int, float)), f"{key} is not numeric"
                assert math.isfinite(v), f"{key} is not finite"

    def test_circulations_count(self):
        """Number of circulations must equal (nx-1)*(ny-1) panels."""
        for i, case in enumerate(self.res["cases"]):
            mesh = self.cfg["cases"][i]["mesh"]
            nx = len(mesh)
            ny = len(mesh[0])
            expected = (nx - 1) * (ny - 1)
            assert len(case["circulations"]) == expected, (
                f"Expected {expected} circulations, got {len(case['circulations'])}"
            )


# ---------------------------------------------------------------
# 2. Physics checks at alpha = 5 deg for both wing types
# ---------------------------------------------------------------

class TestPhysicsAtAlpha5:
    @pytest.fixture(autouse=True, scope="class")
    def results(self, request):
        cfg = load_original_config()
        request.cls.cfg = cfg
        request.cls.res = run_solver(cfg, "_phys5")

    def _case(self, name):
        for c in self.res["cases"]:
            if c.get("name") == name:
                return c
        raise KeyError(name)

    # --- Rectangular wing ---
    def test_rect_CL_positive(self):
        assert self._case("rectangular_wing")["CL"] > 0

    def test_rect_CDi_positive(self):
        assert self._case("rectangular_wing")["CDi"] > 0

    def test_rect_CL_magnitude(self):
        """CL at 5 deg for AR=10 rectangular wing should be in [0.3, 0.65]."""
        cl = self._case("rectangular_wing")["CL"]
        assert 0.3 < cl < 0.65, f"CL = {cl}"

    def test_rect_CDi_magnitude(self):
        """CDi should be physically reasonable for moderate alpha."""
        cdi = self._case("rectangular_wing")["CDi"]
        assert 0.002 < cdi < 0.03, f"CDi = {cdi}"

    def test_rect_CL_alpha_range(self):
        """For AR=10, CL_alpha should be in ~[4.0, 6.5] per radian."""
        cla = self._case("rectangular_wing")["CL_alpha"]
        assert 4.0 < cla < 6.5, f"CL_alpha = {cla}"

    def test_rect_oswald_range(self):
        """Oswald factor for a rectangular wing should be in [0.7, 1.1]."""
        e = self._case("rectangular_wing")["oswald_efficiency"]
        assert 0.7 < e < 1.1, f"oswald = {e}"

    def test_rect_circulations_positive(self):
        for g in self._case("rectangular_wing")["circulations"]:
            assert g > 0

    def test_rect_static_margin_near_zero(self):
        """Moment ref at quarter-chord root: SM should be near zero for unswept."""
        sm = self._case("rectangular_wing")["static_margin"]
        assert abs(sm) < 0.2, f"static_margin = {sm}"

    # --- Swept wing ---
    def test_swept_CL_positive(self):
        assert self._case("swept_wing")["CL"] > 0

    def test_swept_CDi_positive(self):
        assert self._case("swept_wing")["CDi"] > 0

    def test_swept_CM_alpha_negative(self):
        """30-deg swept wing with ref at root quarter-chord: CM_alpha < 0."""
        cma = self._case("swept_wing")["CM_alpha"]
        assert cma < -1.0, f"CM_alpha = {cma}"

    def test_swept_static_margin_positive_and_large(self):
        sm = self._case("swept_wing")["static_margin"]
        assert sm > 0.3, f"static_margin = {sm}"

    def test_swept_more_stable_than_rect(self):
        cma_rect = self._case("rectangular_wing")["CM_alpha"]
        cma_swept = self._case("swept_wing")["CM_alpha"]
        assert cma_swept < cma_rect, (
            f"swept CM_alpha={cma_swept} should be < rect CM_alpha={cma_rect}"
        )


# ---------------------------------------------------------------
# 3. Zero angle of attack: CL, CDi, CM should all vanish
# ---------------------------------------------------------------

class TestZeroAlpha:
    @pytest.fixture(autouse=True, scope="class")
    def results(self, request):
        cfg = load_original_config()
        request.cls.res = run_solver(
            make_config_at_alpha(cfg, 0.0), "_zero"
        )

    def test_CL_vanishes(self):
        for case in self.res["cases"]:
            assert abs(case["CL"]) < 1e-10, (
                f"CL={case['CL']} at alpha=0 for {case.get('name')}"
            )

    def test_CDi_vanishes(self):
        for case in self.res["cases"]:
            assert abs(case["CDi"]) < 1e-10, (
                f"CDi={case['CDi']} at alpha=0 for {case.get('name')}"
            )

    def test_CM_vanishes(self):
        for case in self.res["cases"]:
            assert abs(case["CM"]) < 1e-10, (
                f"CM={case['CM']} at alpha=0 for {case.get('name')}"
            )


# ---------------------------------------------------------------
# 4. Linearity: CL is linear in alpha, CDi is quadratic
# ---------------------------------------------------------------

class TestLinearity:
    @pytest.fixture(autouse=True, scope="class")
    def results(self, request):
        cfg = load_original_config()
        request.cls.res5 = run_solver(
            make_config_at_alpha(cfg, 5.0), "_lin5"
        )
        request.cls.res2 = run_solver(
            make_config_at_alpha(cfg, 2.5), "_lin2"
        )
        request.cls.res10 = run_solver(
            make_config_at_alpha(cfg, 10.0), "_lin10"
        )

    def test_CL_linear(self):
        """CL(10) / CL(5) ~ 2 and CL(2.5) / CL(5) ~ 0.5."""
        for i in range(len(self.res5["cases"])):
            cl5 = self.res5["cases"][i]["CL"]
            cl2 = self.res2["cases"][i]["CL"]
            cl10 = self.res10["cases"][i]["CL"]
            ratio_double = cl10 / cl5
            ratio_half = cl2 / cl5
            assert abs(ratio_double - 2.0) < 0.02, (
                f"CL(10)/CL(5)={ratio_double}"
            )
            assert abs(ratio_half - 0.5) < 0.02, (
                f"CL(2.5)/CL(5)={ratio_half}"
            )

    def test_CDi_quadratic(self):
        """CDi(10)/CDi(5) ~ 4 and CDi(2.5)/CDi(5) ~ 0.25."""
        for i in range(len(self.res5["cases"])):
            cd5 = self.res5["cases"][i]["CDi"]
            cd2 = self.res2["cases"][i]["CDi"]
            cd10 = self.res10["cases"][i]["CDi"]
            ratio4 = cd10 / cd5
            ratio025 = cd2 / cd5
            assert abs(ratio4 - 4.0) < 0.15, f"CDi(10)/CDi(5)={ratio4}"
            assert abs(ratio025 - 0.25) < 0.02, f"CDi(2.5)/CDi(5)={ratio025}"


# ---------------------------------------------------------------
# 5. Self-consistency: reported derivatives match finite-difference
# ---------------------------------------------------------------

class TestDerivativeConsistency:
    @pytest.fixture(autouse=True, scope="class")
    def results(self, request):
        cfg = load_original_config()
        request.cls.res_nom = run_solver(
            make_config_at_alpha(cfg, 5.0), "_dnom"
        )
        delta = 0.01
        request.cls.delta_rad = math.radians(delta)
        request.cls.res_plus = run_solver(
            make_config_at_alpha(cfg, 5.0 + delta), "_dp"
        )
        request.cls.res_minus = run_solver(
            make_config_at_alpha(cfg, 5.0 - delta), "_dm"
        )

    def test_CL_alpha_fd(self):
        for i in range(len(self.res_nom["cases"])):
            cl_p = self.res_plus["cases"][i]["CL"]
            cl_m = self.res_minus["cases"][i]["CL"]
            cla_fd = (cl_p - cl_m) / (2 * self.delta_rad)
            cla_rep = self.res_nom["cases"][i]["CL_alpha"]
            rel = abs(cla_fd - cla_rep) / abs(cla_rep)
            assert rel < 0.01, (
                f"CL_alpha FD={cla_fd:.6f} vs reported={cla_rep:.6f} "
                f"(rel={rel:.4f})"
            )

    def test_CM_alpha_fd(self):
        for i in range(len(self.res_nom["cases"])):
            cm_p = self.res_plus["cases"][i]["CM"]
            cm_m = self.res_minus["cases"][i]["CM"]
            cma_fd = (cm_p - cm_m) / (2 * self.delta_rad)
            cma_rep = self.res_nom["cases"][i]["CM_alpha"]
            if abs(cma_rep) < 1e-6:
                assert abs(cma_fd) < 0.01
            else:
                rel = abs(cma_fd - cma_rep) / abs(cma_rep)
                assert rel < 0.01, (
                    f"CM_alpha FD={cma_fd:.6f} vs reported={cma_rep:.6f} "
                    f"(rel={rel:.4f})"
                )


# ---------------------------------------------------------------
# 6. Static margin consistency
# ---------------------------------------------------------------

class TestStaticMarginConsistency:
    @pytest.fixture(autouse=True, scope="class")
    def results(self, request):
        cfg = load_original_config()
        request.cls.res = run_solver(cfg, "_sm")

    def test_sm_equals_minus_cma_over_cla(self):
        for case in self.res["cases"]:
            expected = -case["CM_alpha"] / case["CL_alpha"]
            actual = case["static_margin"]
            assert abs(actual - expected) < 1e-6, (
                f"SM={actual}, expected -CM_a/CL_a={expected} "
                f"for {case.get('name')}"
            )


# ---------------------------------------------------------------
# 7. Oswald efficiency self-consistency
# ---------------------------------------------------------------

class TestOswaldConsistency:
    @pytest.fixture(autouse=True, scope="class")
    def results(self, request):
        cfg = load_original_config()
        request.cls.cfg = cfg
        request.cls.res = run_solver(cfg, "_osw")

    def test_oswald_formula(self):
        for i, case in enumerate(self.res["cases"]):
            AR = self.cfg["cases"][i]["AR"]
            CL = case["CL"]
            CDi = case["CDi"]
            expected = CL ** 2 / (math.pi * AR * CDi)
            actual = case["oswald_efficiency"]
            assert abs(actual - expected) < 1e-6, (
                f"oswald={actual}, expected CL^2/(pi*AR*CDi)={expected}"
            )


# ---------------------------------------------------------------
# 8. Anti-symmetry of lift: CL(alpha) = -CL(-alpha)
# ---------------------------------------------------------------

class TestAntiSymmetry:
    @pytest.fixture(autouse=True, scope="class")
    def results(self, request):
        cfg = load_original_config()
        request.cls.res_pos = run_solver(
            make_config_at_alpha(cfg, 5.0), "_asymp"
        )
        request.cls.res_neg = run_solver(
            make_config_at_alpha(cfg, -5.0), "_asymn"
        )

    def test_CL_antisymmetric(self):
        for i in range(len(self.res_pos["cases"])):
            cl_p = self.res_pos["cases"][i]["CL"]
            cl_n = self.res_neg["cases"][i]["CL"]
            assert abs(cl_p + cl_n) < 1e-8, (
                f"CL(5)={cl_p}, CL(-5)={cl_n}, sum={cl_p+cl_n}"
            )

    def test_CDi_symmetric(self):
        """Induced drag is the same for +alpha and -alpha."""
        for i in range(len(self.res_pos["cases"])):
            cd_p = self.res_pos["cases"][i]["CDi"]
            cd_n = self.res_neg["cases"][i]["CDi"]
            assert abs(cd_p - cd_n) / cd_p < 1e-8, (
                f"CDi(5)={cd_p}, CDi(-5)={cd_n}"
            )
