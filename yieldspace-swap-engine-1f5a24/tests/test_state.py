
import json
import pytest
import os

VERIFY_OUTPUT = "/tmp/verify_output.json"


@pytest.fixture(scope="session")
def results():
    """Load verification results from the TypeScript runner."""
    if not os.path.exists(VERIFY_OUTPUT):
        pytest.fail("verify_output.json not found — run test.sh first")
    with open(VERIFY_OUTPUT) as f:
        data = json.load(f)
    if "error" in data:
        pytest.fail(f"verify.ts failed: {data['error']}")
    return data


def _check_no_error(results, key):
    err_key = key + "_error"
    if err_key in results:
        pytest.fail(f"{key} raised error: {results[err_key]}")


class TestFyTokenOutForSharesIn:
    """Golden value tests for fyTokenOutForSharesIn."""

    EXPECTED = [55113, 110185, 220202, 549235, 985292]

    def test_values_present(self, results):
        _check_no_error(results, "fyTokenOutForSharesIn")
        assert "fyTokenOutForSharesIn" in results

    @pytest.mark.parametrize("idx,expected", list(enumerate(EXPECTED)))
    def test_golden(self, results, idx, expected):
        _check_no_error(results, "fyTokenOutForSharesIn")
        actual = int(results["fyTokenOutForSharesIn"][idx])
        assert abs(actual - expected) <= 2, (
            f"fyTokenOutForSharesIn[{idx}]: got {actual}, expected {expected}"
        )


class TestSharesInForFYTokenOut:
    """Golden value tests for sharesInForFYTokenOut."""

    EXPECTED = [45359, 90749, 181625, 821505]

    def test_values_present(self, results):
        _check_no_error(results, "sharesInForFYTokenOut")
        assert "sharesInForFYTokenOut" in results

    @pytest.mark.parametrize("idx,expected", list(enumerate(EXPECTED)))
    def test_golden(self, results, idx, expected):
        _check_no_error(results, "sharesInForFYTokenOut")
        actual = int(results["sharesInForFYTokenOut"][idx])
        assert abs(actual - expected) <= 2, (
            f"sharesInForFYTokenOut[{idx}]: got {actual}, expected {expected}"
        )


class TestSharesOutForFYTokenIn:
    """Golden value tests for sharesOutForFYTokenIn (uses g2)."""

    EXPECTED = [22661, 45313, 90592, 181041, 451473]

    def test_values_present(self, results):
        _check_no_error(results, "sharesOutForFYTokenIn")
        assert "sharesOutForFYTokenIn" in results

    @pytest.mark.parametrize("idx,expected", list(enumerate(EXPECTED)))
    def test_golden(self, results, idx, expected):
        _check_no_error(results, "sharesOutForFYTokenIn")
        actual = int(results["sharesOutForFYTokenIn"][idx])
        assert abs(actual - expected) <= 2, (
            f"sharesOutForFYTokenIn[{idx}]: got {actual}, expected {expected}"
        )


class TestFyTokenInForSharesOut:
    """Golden value tests for fyTokenInForSharesOut (uses g2)."""

    EXPECTED = [55173, 110393, 220981, 331770, 554008, 1058525]

    def test_values_present(self, results):
        _check_no_error(results, "fyTokenInForSharesOut")
        assert "fyTokenInForSharesOut" in results

    @pytest.mark.parametrize("idx,expected", list(enumerate(EXPECTED)))
    def test_golden(self, results, idx, expected):
        _check_no_error(results, "fyTokenInForSharesOut")
        actual = int(results["fyTokenInForSharesOut"][idx])
        assert abs(actual - expected) <= 2, (
            f"fyTokenInForSharesOut[{idx}]: got {actual}, expected {expected}"
        )


class TestMirror:
    """Mirror property: fyTokenOutForSharesIn -> sharesInForFYTokenOut recovers input."""

    def test_mirror(self, results):
        _check_no_error(results, "mirror")
        inp = int(results["mirror_input"])
        out = int(results["mirror_result"])
        assert abs(out - inp) <= 1, f"Mirror: input={inp}, recovered={out}"


class TestMirror2:
    """Mirror property: sharesOutForFYTokenIn -> fyTokenInForSharesOut recovers input."""

    def test_mirror2(self, results):
        _check_no_error(results, "mirror2")
        inp = int(results["mirror2_input"])
        out = int(results["mirror2_result"])
        assert abs(out - inp) <= 1, f"Mirror2: input={inp}, recovered={out}"


class TestMaturityConvergence:
    """At maturity (t=0) with no fees, fyTokenOut = c * sharesIn."""

    def test_convergence(self, results):
        _check_no_error(results, "maturity")
        actual = int(results["maturity_result"])
        expected = int(results["maturity_expected"])
        assert abs(actual - expected) <= 2, (
            f"Maturity convergence: got {actual}, expected {expected}"
        )


class TestMaxFunctions:
    """Test max boundary functions against reference values."""

    def test_maxFYTokenIn(self, results):
        _check_no_error(results, "maxFYTokenIn")
        val = int(results["maxFYTokenIn"])
        # Expected: ~1230211.59495e18, tolerance 1e13
        expected = 1230211594950000000000000
        assert abs(val - expected) <= 10**13, (
            f"maxFYTokenIn: got {val}, expected ~{expected}"
        )

    def test_maxFYTokenOut(self, results):
        _check_no_error(results, "maxFYTokenOut")
        val = int(results["maxFYTokenOut"])
        # Expected: ~176616.991033e18, tolerance 1e12
        expected = 176616991033000000000000
        assert abs(val - expected) <= 10**12, (
            f"maxFYTokenOut: got {val}, expected ~{expected}"
        )

    def test_maxSharesIn(self, results):
        _check_no_error(results, "maxSharesIn")
        val = int(results["maxSharesIn"])
        # Expected: ~160364.770445e18, tolerance 1e12
        expected = 160364770445000000000000
        assert abs(val - expected) <= 10**12, (
            f"maxSharesIn: got {val}, expected ~{expected}"
        )


class TestInvariant:
    """Test pool invariant calculation."""

    def test_invariant(self, results):
        _check_no_error(results, "invariant")
        val = int(results["invariant"])
        # Expected: ~1.1553244e18, tolerance 1e12
        expected = 1155324400000000000
        assert abs(val - expected) <= 10**12, (
            f"invariant: got {val}, expected ~{expected}"
        )


class TestNormalizedPow:
    """Test normalizedPow identity: normalizedPow(x, ONE, ONE) ~= x."""

    def test_identity(self, results):
        _check_no_error(results, "normPow_identity")
        actual = int(results["normPow_identity"])
        expected = int(results["normPow_identity_expected"])
        # Allow small rounding error (< 0.001% of value)
        tolerance = max(expected // 100000, 2)
        assert abs(actual - expected) <= tolerance, (
            f"normalizedPow identity: got {actual}, expected {expected}"
        )
