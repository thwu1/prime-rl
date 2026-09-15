
import subprocess
import pytest


def run(expr):
    r = subprocess.run(
        ['node', '/app/src/index.js', expr],
        capture_output=True, text=True, timeout=10,
        cwd='/app'
    )
    assert r.returncode == 0, f"CLI error for '{expr}': {r.stderr}"
    return r.stdout.strip()


# ── Same-unit UCUM arithmetic ──

class TestSameUcumArithmetic:
    def test_add_kg(self):
        assert run("3 'kg' + 2 'kg'") == "5 'kg'"

    def test_sub_m(self):
        assert run("10 'm' - 3 'm'") == "7 'm'"

    def test_mul_qty_num(self):
        assert run("5 'kg' * 3") == "15 'kg'"

    def test_div_qty_num(self):
        assert run("10 'kg' / 2") == "5 'kg'"


# ── Calendar arithmetic ──

class TestCalendarArithmetic:
    def test_add_same(self):
        assert run("3 months + 5 months") == "8 months"

    def test_sub_same(self):
        assert run("10 days - 3 days") == "7 days"

    def test_year_plus_months(self):
        assert run("1 year + 6 months") == "18 months"

    def test_months_plus_year(self):
        assert run("6 months + 1 year") == "18 months"

    def test_years_minus_months(self):
        assert run("2 years - 6 months") == "18 months"

    def test_hour_plus_minutes(self):
        assert run("1 hour + 30 minutes") == "90 minutes"

    def test_day_plus_hours(self):
        assert run("1 day + 12 hours") == "36 hours"

    def test_singular_plural_mix(self):
        assert run("1 year + 1 months") == "13 months"

    def test_large_calendar_conversion(self):
        assert run("2 years + 6 months") == "30 months"

    def test_years_minus_years(self):
        assert run("3 years - 1 year") == "2 years"


# ── UCUM cross-unit arithmetic ──

class TestUcumCrossArithmetic:
    def test_kg_plus_g(self):
        assert run("1 'kg' + 500 'g'") == "1.5 'kg'"

    def test_incompatible(self):
        assert run("1 'kg' + 1 'm'") == "{}"


# ── Compound units ──

class TestCompoundUnits:
    def test_mul_two_ucum(self):
        assert run("2 'kg' * 5 'm'") == "10 'kg.m'"

    def test_div_two_ucum(self):
        assert run("10 'kg' / 5 'm'") == "2 'kg/m'"

    def test_num_div_qty(self):
        assert run("20 / 5 'kg'") == "4 '1/kg'"


# ── Comparison ──

class TestComparison:
    def test_lt_same(self):
        assert run("3 'kg' < 5 'kg'") == "true"

    def test_eq_same(self):
        assert run("5 'kg' = 5 'kg'") == "true"

    def test_cross_ucum(self):
        assert run("999 'g' < 1 'kg'") == "true"

    def test_year_month_cmp(self):
        assert run("1 year = 12 months") == "true"


# ── Calendar vs UCUM comparison (cross-system) ──

class TestMixedComparison:
    def test_cal_sec_vs_ucum_s(self):
        assert run("10 seconds > 1 's'") == "true"

    def test_ucum_min_vs_cal_min(self):
        assert run("1 'min' < 2 minutes") == "true"

    def test_60sec_eq_1min(self):
        assert run("60 seconds = 1 'min'") == "true"

    def test_week_vs_ucum_s(self):
        assert run("1 week > 604799 's'") == "true"

    def test_week_eq_ucum_s(self):
        assert run("1 week = 604800 's'") == "true"

    def test_year_vs_ucum_s_incomparable(self):
        assert run("1 year > 1 's'") == "{}"

    def test_month_vs_ucum_min_incomparable(self):
        assert run("1 month > 1 'min'") == "{}"

    def test_kg_vs_m_incomparable(self):
        assert run("1 'kg' < 2 'm'") == "{}"


# ── Extended UCUM time units ──

class TestExtendedUcumUnits:
    def test_d_plus_h(self):
        assert run("1 'd' + 12 'h'") == "1.5 'd'"

    def test_d_minus_h(self):
        assert run("1 'd' - 12 'h'") == "0.5 'd'"

    def test_wk_eq_168h(self):
        assert run("1 'wk' = 168 'h'") == "true"

    def test_1000ms_eq_1s(self):
        assert run("1000 'ms' = 1 's'") == "true"

    def test_2d_gt_47h(self):
        assert run("2 'd' > 47 'h'") == "true"


# ── Mixed calendar/UCUM arithmetic ──

class TestMixedArithmetic:
    def test_cal_min_plus_ucum_s(self):
        assert run("1 minute + 30 's'") == "1.5 minutes"

    def test_ucum_min_plus_cal_sec(self):
        assert run("1 'min' + 30 seconds") == "1.5 'min'"

    def test_ucum_h_plus_cal_min(self):
        assert run("1 'h' + 30 minutes") == "1.5 'h'"

    def test_cal_day_minus_ucum_h(self):
        assert run("1 day - 12 'h'") == "0.5 days"

    def test_year_plus_ucum_s_empty(self):
        assert run("1 year + 1 's'") == "{}"

    def test_ucum_s_plus_month_empty(self):
        assert run("1 's' + 1 month") == "{}"

    def test_ucum_kg_plus_cal_hour_empty(self):
        assert run("1 'kg' + 1 hour") == "{}"


# ── Cross-system comparison with extended UCUM units ──

class TestMixedComparisonExtended:
    def test_week_eq_7d(self):
        assert run("1 week = 7 'd'") == "true"

    def test_day_lt_25h(self):
        assert run("1 day < 25 'h'") == "true"

    def test_week_gt_6d(self):
        assert run("1 week > 6 'd'") == "true"


# ── Edge cases ──

class TestEdgeCases:
    def test_unit_one(self):
        assert run("5 '1' * 3") == "15 '1'"

    def test_div_by_zero(self):
        assert run("5 'kg' / 0") == "{}"

    def test_parens(self):
        assert run("(2 + 3) * 4") == "20"

    def test_negative_result(self):
        assert run("3 'kg' - 5 'kg'") == "-2 'kg'"

    def test_nested_calendar(self):
        assert run("((1 year + 6 months) - 6 months) = 12 months") == "true"

    def test_chained_calendar(self):
        assert run("1 year - 6 months - 1 year + 18 months = 1 year") == "true"

    def test_day_vs_ucum_h(self):
        assert run("1 day > 23 'h'") == "true"

    def test_mixed_arith_eq(self):
        assert run("(1 'h' + 30 minutes) = 1.5 'h'") == "true"

    def test_mixed_arith_zero(self):
        assert run("60 seconds - 1 'min' = 0 seconds") == "true"
