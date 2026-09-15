
import sys
sys.path.insert(0, '/app')
import pytest
from fractions import Fraction
from models import CompType, LinearExpr, Constraint, Certificate


def C(coeffs_dict, comp):
    """Helper to build a Constraint from {var_index: coeff_int, ...}."""
    return Constraint(
        LinearExpr({k: Fraction(v) for k, v in coeffs_dict.items()}),
        comp
    )


def make_cert(d):
    """Helper to build a Certificate from {index: coeff, ...}."""
    return Certificate({k: Fraction(v) for k, v in d.items()})


# ---------------------------------------------------------------------------
# Problem bank
# ---------------------------------------------------------------------------

# P1: Trivial contradiction: 1 < 0
P1 = [C({-1: 1}, CompType.LT)]

# P2: x0 < 0 AND -x0 < 0
P2 = [C({0: 1}, CompType.LT), C({0: -1}, CompType.LT)]

# P3: x0 - 1 < 0 AND -x0 + 2 < 0  (x0 < 1 and x0 > 2)
P3 = [
    C({0: 1, -1: -1}, CompType.LT),
    C({0: -1, -1: 2}, CompType.LT),
]

# P4: The linarith textbook example (3 vars, all strict)
# 2*x0 - 3*x1 < 0, -4*x0 + 2*x2 < 0, 12*x1 - 4*x2 < 0
P4 = [
    C({0: 2, 1: -3}, CompType.LT),
    C({0: -4, 2: 2}, CompType.LT),
    C({1: 12, 2: -4}, CompType.LT),
]

# P5: Satisfiable: x0+x1 <= 10, x0 >= 1, x1 >= 1  (e.g. x0=1, x1=1)
P5 = [
    C({0: 1, 1: 1, -1: -10}, CompType.LE),
    C({0: -1, -1: 1}, CompType.LE),
    C({1: -1, -1: 1}, CompType.LE),
]

# P6: Mixed strict/non-strict: x0 <= 5, x0 > 6
P6 = [
    C({0: 1, -1: -5}, CompType.LE),
    C({0: -1, -1: 6}, CompType.LT),
]

# P7: With equality: x0+x1 = 0 AND -x0-x1+3 < 0  (implies 3 < 0)
P7 = [
    C({0: 1, 1: 1}, CompType.EQ),
    C({0: -1, 1: -1, -1: 3}, CompType.LT),
]

# P8: 4-variable cyclic chain (all cancel, constant=1, one strict)
# x0-x1+2<=0, x1-x2+3<=0, x2-x3+1<=0, x3-x0-5<0
P8 = [
    C({0: 1, 1: -1, -1: 2}, CompType.LE),
    C({1: 1, 2: -1, -1: 3}, CompType.LE),
    C({2: 1, 3: -1, -1: 1}, CompType.LE),
    C({3: 1, 0: -1, -1: -5}, CompType.LT),
]

# P9: Satisfiable 1-var: x0 < 3 AND x0 > 0
P9 = [
    C({0: 1, -1: -3}, CompType.LT),
    C({0: -1}, CompType.LT),
]

# P10: 6-variable cyclic chain with 6 constraints
P10 = [
    C({0: 1, 1: -1, -1: 1}, CompType.LE),
    C({1: 1, 2: -1, -1: 1}, CompType.LE),
    C({2: 1, 3: -1, -1: 1}, CompType.LE),
    C({3: 1, 4: -1, -1: 1}, CompType.LE),
    C({4: 1, 5: -1, -1: 1}, CompType.LE),
    C({5: 1, 0: -1, -1: 1}, CompType.LT),
]

# P11: Non-strict-only contradiction: x0 <= 0, -x0 + 1 <= 0  (x0<=0, x0>=1)
P11 = [
    C({0: 1}, CompType.LE),
    C({0: -1, -1: 1}, CompType.LE),
]

# P12: Equality system: x0 = 3, x0 = 5 (unsatisfiable)
P12 = [
    C({0: 1, -1: -3}, CompType.EQ),
    C({0: 1, -1: -5}, CompType.EQ),
]

# P13: Fractional coefficients: (1/2)*x0 - 1 < 0, -(1/3)*x0 + 1 < 0
# => x0 < 2 and x0 > 3, contradiction
P13 = [
    C({0: Fraction(1, 2), -1: -1}, CompType.LT),
    C({0: Fraction(-1, 3), -1: 1}, CompType.LT),
]


# ---------------------------------------------------------------------------
# Tests: verify_certificate
# ---------------------------------------------------------------------------

class TestVerifyCertificate:
    def test_valid_simple(self):
        from engine import verify_certificate
        # P2: x0<0, -x0<0 -> cert {0:1, 1:1}, sum=0, LT, 0>=0 -> contradiction
        assert verify_certificate(P2, make_cert({0: 1, 1: 1})) is True

    def test_valid_with_constants(self):
        from engine import verify_certificate
        # P3: sum = (x0-1)+(-x0+2) = 1, LT, 1>=0 -> contradiction
        assert verify_certificate(P3, make_cert({0: 1, 1: 1})) is True

    def test_valid_linarith(self):
        from engine import verify_certificate
        # P4: k={0:4, 1:2, 2:1}, sum = 0, LT -> contradiction
        assert verify_certificate(P4, make_cert({0: 4, 1: 2, 2: 1})) is True

    def test_invalid_nonzero_vars(self):
        from engine import verify_certificate
        # Wrong certificate: variables don't cancel
        assert verify_certificate(P4, make_cert({0: 1, 1: 1, 2: 1})) is False

    def test_invalid_negative_coeff_for_lt(self):
        from engine import verify_certificate
        # Negative coefficient for a LT constraint
        assert verify_certificate(P2, make_cert({0: 1, 1: -1})) is False

    def test_invalid_no_strict(self):
        from engine import verify_certificate
        # All LE, sum = 0. 0<=0 is TRUE, not a contradiction
        system = [C({0: 1}, CompType.LE), C({0: -1}, CompType.LE)]
        assert verify_certificate(system, make_cert({0: 1, 1: 1})) is False

    def test_valid_le_only_positive_constant(self):
        from engine import verify_certificate
        # P11: x0<=0, -x0+1<=0, cert {0:1,1:1}, sum=1, LE, 1>0 -> contradiction
        assert verify_certificate(P11, make_cert({0: 1, 1: 1})) is True

    def test_valid_equality(self):
        from engine import verify_certificate
        # P12: x0-3=0, x0-5=0, cert {0:1, 1:-1}, sum = -3-(-5)=2, EQ, 2!=0 -> contradiction
        assert verify_certificate(P12, make_cert({0: 1, 1: -1})) is True

    def test_empty_cert(self):
        from engine import verify_certificate
        assert verify_certificate(P2, Certificate()) is False

    def test_out_of_range_index(self):
        from engine import verify_certificate
        assert verify_certificate(P2, make_cert({5: 1})) is False


# ---------------------------------------------------------------------------
# Tests: fourier_motzkin_oracle
# ---------------------------------------------------------------------------

class TestFourierMotzkin:
    def _check_unsat(self, constraints):
        from engine import fourier_motzkin_oracle, verify_certificate
        cert = fourier_motzkin_oracle(constraints)
        assert cert is not None, "FM oracle returned None for unsatisfiable system"
        assert verify_certificate(constraints, cert), \
            f"FM certificate failed verification: {cert}"

    def _check_sat(self, constraints):
        from engine import fourier_motzkin_oracle
        cert = fourier_motzkin_oracle(constraints)
        assert cert is None, f"FM oracle returned certificate for satisfiable system: {cert}"

    def test_trivial(self):
        self._check_unsat(P1)

    def test_simple_1var(self):
        self._check_unsat(P2)

    def test_constants(self):
        self._check_unsat(P3)

    def test_linarith_example(self):
        self._check_unsat(P4)

    def test_satisfiable_2var(self):
        self._check_sat(P5)

    def test_mixed_strict(self):
        self._check_unsat(P6)

    def test_equality(self):
        self._check_unsat(P7)

    def test_cyclic_4var(self):
        self._check_unsat(P8)

    def test_satisfiable_1var(self):
        self._check_sat(P9)

    def test_cyclic_6var(self):
        self._check_unsat(P10)

    def test_le_only_contradiction(self):
        self._check_unsat(P11)

    def test_equality_contradiction(self):
        self._check_unsat(P12)

    def test_fractional_coefficients(self):
        self._check_unsat(P13)

    def test_empty_system(self):
        from engine import fourier_motzkin_oracle
        assert fourier_motzkin_oracle([]) is None


# ---------------------------------------------------------------------------
# Tests: simplex_oracle
# ---------------------------------------------------------------------------

class TestSimplexOracle:
    def _check_unsat(self, constraints):
        from engine import simplex_oracle, verify_certificate
        cert = simplex_oracle(constraints)
        assert cert is not None, "Simplex oracle returned None for unsatisfiable system"
        assert verify_certificate(constraints, cert), \
            f"Simplex certificate failed verification: {cert}"

    def _check_sat(self, constraints):
        from engine import simplex_oracle
        cert = simplex_oracle(constraints)
        assert cert is None, f"Simplex oracle returned certificate for satisfiable system: {cert}"

    def test_trivial(self):
        self._check_unsat(P1)

    def test_simple_1var(self):
        self._check_unsat(P2)

    def test_constants(self):
        self._check_unsat(P3)

    def test_linarith_example(self):
        self._check_unsat(P4)

    def test_satisfiable_2var(self):
        self._check_sat(P5)

    def test_mixed_strict(self):
        self._check_unsat(P6)

    def test_equality(self):
        self._check_unsat(P7)

    def test_cyclic_4var(self):
        self._check_unsat(P8)

    def test_satisfiable_1var(self):
        self._check_sat(P9)

    def test_cyclic_6var(self):
        self._check_unsat(P10)

    def test_le_only_contradiction(self):
        self._check_unsat(P11)

    def test_fractional_coefficients(self):
        self._check_unsat(P13)


# ---------------------------------------------------------------------------
# Tests: is_unsatisfiable
# ---------------------------------------------------------------------------

class TestIsUnsatisfiable:
    def test_fm_dispatch(self):
        from engine import is_unsatisfiable, verify_certificate
        unsat, cert = is_unsatisfiable(P4, oracle="fm")
        assert unsat is True
        assert verify_certificate(P4, cert) is True

    def test_simplex_dispatch(self):
        from engine import is_unsatisfiable, verify_certificate
        unsat, cert = is_unsatisfiable(P4, oracle="simplex")
        assert unsat is True
        assert verify_certificate(P4, cert) is True

    def test_satisfiable_fm(self):
        from engine import is_unsatisfiable
        unsat, cert = is_unsatisfiable(P5, oracle="fm")
        assert unsat is False
        assert cert is None

    def test_satisfiable_simplex(self):
        from engine import is_unsatisfiable
        unsat, cert = is_unsatisfiable(P5, oracle="simplex")
        assert unsat is False
        assert cert is None


# ---------------------------------------------------------------------------
# Tests: parse_constraint
# ---------------------------------------------------------------------------

class TestParseConstraint:
    def test_basic(self):
        from engine import parse_constraint
        c = parse_constraint("2*x0 + -3*x1 + 1 < 0")
        assert c.comp == CompType.LT
        assert c.expr.get(0) == Fraction(2)
        assert c.expr.get(1) == Fraction(-3)
        assert c.expr.get(-1) == Fraction(1)

    def test_implicit_coeff(self):
        from engine import parse_constraint
        c = parse_constraint("x0 + x1 <= 0")
        assert c.comp == CompType.LE
        assert c.expr.get(0) == Fraction(1)
        assert c.expr.get(1) == Fraction(1)

    def test_negative_var(self):
        from engine import parse_constraint
        c = parse_constraint("-x0 + 3 <= 0")
        assert c.expr.get(0) == Fraction(-1)
        assert c.expr.get(-1) == Fraction(3)

    def test_equality(self):
        from engine import parse_constraint
        c = parse_constraint("x0 + x1 = 0")
        assert c.comp == CompType.EQ

    def test_fraction_coeff(self):
        from engine import parse_constraint
        c = parse_constraint("1/2*x0 + -1*x1 = 0")
        assert c.expr.get(0) == Fraction(1, 2)
        assert c.expr.get(1) == Fraction(-1)

    def test_roundtrip_verify(self):
        """Parse constraints, build system, verify with FM oracle."""
        from engine import parse_constraint, fourier_motzkin_oracle, verify_certificate
        system = [
            parse_constraint("x0 + -1 < 0"),
            parse_constraint("-x0 + 2 < 0"),
        ]
        cert = fourier_motzkin_oracle(system)
        assert cert is not None
        assert verify_certificate(system, cert) is True


# ---------------------------------------------------------------------------
# Tests: GLPK integration (export_lp + validate_with_glpsol)
# ---------------------------------------------------------------------------

class TestGlpsolIntegration:
    """Tests for LP format export and glpsol cross-validation."""

    def _export_and_validate(self, constraints, path):
        from engine import export_lp, validate_with_glpsol
        import os
        try:
            export_lp(constraints, path)
            return validate_with_glpsol(path)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_unsat_le_only(self):
        """LE-only infeasible system: glpsol confirms INFEASIBLE."""
        result = self._export_and_validate(P11, "/tmp/glpk_p11.lp")
        assert result == "INFEASIBLE"

    def test_sat_le_only(self):
        """Satisfiable LE system: glpsol confirms FEASIBLE."""
        result = self._export_and_validate(P5, "/tmp/glpk_p5.lp")
        assert result == "FEASIBLE"

    def test_unsat_eq_only(self):
        """EQ-only infeasible system: glpsol confirms INFEASIBLE."""
        result = self._export_and_validate(P12, "/tmp/glpk_p12.lp")
        assert result == "INFEASIBLE"

    def test_unsat_relaxed_strict(self):
        """System that stays infeasible after strict-to-non-strict relaxation."""
        result = self._export_and_validate(P3, "/tmp/glpk_p3.lp")
        assert result == "INFEASIBLE"

    def test_unsat_cyclic_relaxed(self):
        """Cyclic 4-var system remains infeasible after relaxation."""
        result = self._export_and_validate(P8, "/tmp/glpk_p8.lp")
        assert result == "INFEASIBLE"

    def test_lp_format_accepted(self):
        """glpsol accepts exported LP files for systems with various features."""
        from engine import export_lp, validate_with_glpsol
        import os
        # P4: 3-var all-strict, P13: fractional coefficients
        for idx, sys_constraints in enumerate([P4, P13]):
            path = f"/tmp/glpk_fmt_{idx}.lp"
            try:
                export_lp(sys_constraints, path)
                result = validate_with_glpsol(path)
                assert result in ("FEASIBLE", "INFEASIBLE"), \
                    f"Unexpected result for system {idx}: {result}"
            finally:
                if os.path.exists(path):
                    os.unlink(path)

    def test_cross_validate_oracle_vs_glpsol(self):
        """Oracle and glpsol agree on systems where relaxation preserves the answer."""
        from engine import export_lp, validate_with_glpsol, is_unsatisfiable
        import os
        # (constraints, expected_unsat, label)
        cases = [
            (P5, False, "P5_sat"),
            (P9, False, "P9_sat"),
            (P11, True, "P11_unsat_le"),
            (P12, True, "P12_unsat_eq"),
            (P3, True, "P3_unsat_relaxed"),
            (P8, True, "P8_unsat_cyclic"),
        ]
        for constraints, expect_unsat, label in cases:
            path = f"/tmp/glpk_xval_{label}.lp"
            try:
                export_lp(constraints, path)
                glp_result = validate_with_glpsol(path)
                oracle_unsat, _ = is_unsatisfiable(constraints, oracle="fm")
                if expect_unsat:
                    assert glp_result == "INFEASIBLE", \
                        f"{label}: glpsol expected INFEASIBLE, got {glp_result}"
                    assert oracle_unsat is True, \
                        f"{label}: oracle expected unsatisfiable"
                else:
                    assert glp_result == "FEASIBLE", \
                        f"{label}: glpsol expected FEASIBLE, got {glp_result}"
                    assert oracle_unsat is False, \
                        f"{label}: oracle expected satisfiable"
            finally:
                if os.path.exists(path):
                    os.unlink(path)
