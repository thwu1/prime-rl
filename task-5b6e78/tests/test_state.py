import json
import math
import os
import subprocess
import pytest



class TestResultsStructure:
    """Verify the output file exists and has the correct structure."""

    @pytest.fixture(autouse=True)
    def load_results(self):
        assert os.path.exists("/app/results.json"), "results.json not found at /app/results.json"
        with open("/app/results.json") as f:
            data = json.load(f)
        assert "curves" in data, "results.json missing 'curves' key"
        self.curves = {c["name"]: c for c in data["curves"]}

    def test_all_curves_present(self):
        expected = {"bls12_standard", "bls12_overclaim", "bls12_corrupted", "bn_small", "bn_invalid"}
        assert expected == set(self.curves.keys()), (
            f"Expected curves {expected}, got {set(self.curves.keys())}"
        )

    def test_required_fields(self):
        required = [
            "name", "valid", "validation_errors",
            "g1_security_bits", "gt_security_bits",
            "overall_security_bits", "meets_claimed_level",
        ]
        for name, c in self.curves.items():
            for field in required:
                assert field in c, f"Curve {name} missing field '{field}'"


class TestValidation:
    """Verify parameter validation verdicts."""

    @pytest.fixture(autouse=True)
    def load_results(self):
        with open("/app/results.json") as f:
            data = json.load(f)
        self.curves = {c["name"]: c for c in data["curves"]}

    def test_bls12_standard_valid(self):
        c = self.curves["bls12_standard"]
        assert c["valid"] is True, f"bls12_standard should be valid, errors: {c['validation_errors']}"

    def test_bls12_overclaim_valid(self):
        c = self.curves["bls12_overclaim"]
        assert c["valid"] is True, f"bls12_overclaim should be valid, errors: {c['validation_errors']}"

    def test_bls12_corrupted_invalid(self):
        c = self.curves["bls12_corrupted"]
        assert c["valid"] is False, "bls12_corrupted should be invalid (p modified)"
        assert len(c["validation_errors"]) > 0, "bls12_corrupted should have validation errors"

    def test_bn_small_valid(self):
        c = self.curves["bn_small"]
        assert c["valid"] is True, f"bn_small should be valid, errors: {c['validation_errors']}"

    def test_bn_invalid_invalid(self):
        c = self.curves["bn_invalid"]
        assert c["valid"] is False, "bn_invalid should be invalid (p=107 != BN formula for u=1)"
        assert len(c["validation_errors"]) > 0, "bn_invalid should have validation errors"


class TestSecurity:
    """Verify security estimates and verdicts."""

    @pytest.fixture(autouse=True)
    def load_results(self):
        with open("/app/results.json") as f:
            data = json.load(f)
        self.curves = {c["name"]: c for c in data["curves"]}

    def test_bls12_standard_g1_range(self):
        g1 = self.curves["bls12_standard"]["g1_security_bits"]
        assert isinstance(g1, (int, float)), f"g1 should be numeric, got {type(g1)}"
        assert 125 < g1 < 130, f"BLS12-381 G1 security should be ~127.4, got {g1}"

    def test_bls12_standard_gt_range(self):
        gt = self.curves["bls12_standard"]["gt_security_bits"]
        assert isinstance(gt, (int, float)), f"gt should be numeric, got {type(gt)}"
        assert 100 < gt < 200, f"BLS12-381 GT security out of range, got {gt}"

    def test_bls12_standard_overall_below_128(self):
        overall = self.curves["bls12_standard"]["overall_security_bits"]
        assert math.floor(overall) < 128, (
            f"BLS12-381 overall security floor should be <128, got {overall}"
        )

    def test_bls12_standard_fails_claim(self):
        assert self.curves["bls12_standard"]["meets_claimed_level"] is False, (
            "BLS12-381 should fail 128-bit claim (G1 ~127 bits)"
        )

    def test_bls12_overclaim_fails(self):
        assert self.curves["bls12_overclaim"]["meets_claimed_level"] is False, (
            "BLS12-381 should fail 192-bit claim"
        )

    def test_bls12_corrupted_fails(self):
        assert self.curves["bls12_corrupted"]["meets_claimed_level"] is False

    def test_bn_small_passes(self):
        assert self.curves["bn_small"]["meets_claimed_level"] is True, (
            "BN tiny (u=1) should pass 3-bit claim"
        )

    def test_bn_small_g1_range(self):
        g1 = self.curves["bn_small"]["g1_security_bits"]
        assert 2.5 < g1 < 4.5, f"BN tiny G1 should be ~3.3, got {g1}"

    def test_bn_small_gt_above_g1(self):
        c = self.curves["bn_small"]
        assert c["gt_security_bits"] > c["g1_security_bits"] + 5, (
            f"GT ({c['gt_security_bits']}) should be much higher than G1 ({c['g1_security_bits']}) "
            "for this tiny curve"
        )

    def test_bn_small_overall_is_g1(self):
        c = self.curves["bn_small"]
        assert abs(c["overall_security_bits"] - c["g1_security_bits"]) < 1.0, (
            "Overall should equal G1 for BN tiny (G1 is bottleneck)"
        )

    def test_bn_invalid_fails(self):
        assert self.curves["bn_invalid"]["meets_claimed_level"] is False

    def test_invalid_curves_null_security(self):
        for name in ["bls12_corrupted", "bn_invalid"]:
            c = self.curves[name]
            assert c["g1_security_bits"] is None, f"{name} should have null g1_security_bits"
            assert c["gt_security_bits"] is None, f"{name} should have null gt_security_bits"
            assert c["overall_security_bits"] is None, f"{name} should have null overall_security_bits"

    def test_overall_is_min_of_g1_gt(self):
        for name in ["bls12_standard", "bls12_overclaim", "bn_small"]:
            c = self.curves[name]
            expected_min = min(c["g1_security_bits"], c["gt_security_bits"])
            assert abs(c["overall_security_bits"] - expected_min) < 0.1, (
                f"{name}: overall ({c['overall_security_bits']}) should be "
                f"min(G1={c['g1_security_bits']}, GT={c['gt_security_bits']}) = {expected_min}"
            )


class TestVerifyGP:
    """Verify the PARI/GP verification script exists and produces correct output."""

    @pytest.fixture(autouse=True)
    def run_verify(self):
        assert os.path.exists("/app/verify.gp"), "verify.gp not found at /app/verify.gp"
        result = subprocess.run(
            ["gp", "-q", "/app/verify.gp"],
            capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, f"verify.gp exited with code {result.returncode}: {result.stderr}"
        self.checks = {}
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            parts = line.split(":")
            if len(parts) >= 3:
                curve = parts[0].strip()
                check = parts[1].strip()
                val = parts[2].strip()
                self.checks[(curve, check)] = val

    def test_required_checks_present(self):
        required_checks = ["p_prime", "r_prime", "poly_consistent"]
        for curve in ["bls12_standard", "bls12_overclaim", "bls12_corrupted", "bn_small", "bn_invalid"]:
            for check in required_checks:
                assert (curve, check) in self.checks, (
                    f"Missing check {curve}:{check} in verify.gp output"
                )

    def test_valid_curves_primality(self):
        for name in ["bls12_standard", "bls12_overclaim", "bn_small"]:
            assert self.checks.get((name, "p_prime")) == "1", (
                f"{name} p should be prime"
            )
            assert self.checks.get((name, "r_prime")) == "1", (
                f"{name} r should be prime"
            )

    def test_valid_curves_poly_consistent(self):
        for name in ["bls12_standard", "bls12_overclaim", "bn_small"]:
            assert self.checks.get((name, "poly_consistent")) == "1", (
                f"{name} should be polynomial-consistent"
            )

    def test_corrupted_poly_inconsistent(self):
        assert self.checks.get(("bls12_corrupted", "poly_consistent")) == "0", (
            "bls12_corrupted should have poly_consistent=0"
        )

    def test_bn_invalid_poly_inconsistent(self):
        assert self.checks.get(("bn_invalid", "poly_consistent")) == "0", (
            "bn_invalid should have poly_consistent=0"
        )

    def test_bn_invalid_primes_are_prime(self):
        assert self.checks.get(("bn_invalid", "p_prime")) == "1", (
            "bn_invalid p=107 should be prime"
        )
        assert self.checks.get(("bn_invalid", "r_prime")) == "1", (
            "bn_invalid r=97 should be prime"
        )
