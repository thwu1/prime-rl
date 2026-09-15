
"""
Tests for UBPR formula computation engine.

Golden values are derived from the following computation chain:

System: UBPRC752=41 (Form 041), UBPR9999='2024-09-30', ANN=4/3

Layer 1 - CC Lookups (form 041 -> RCON prefix from JSON, RIAD/RCONA from XBRL):
  UBPR3368=1700000, UBPR2170=1720000, UBPR3360=900000, UBPR3484=5000,
  UBPR3365=20000, UBPR3381=50000, UBPRB558=100000, UBPRB559=300000,
  UBPRB560=150000, UBPR3200=17000, UBPR3123=10000, UBPRB528=890000,
  UBPRB529=880000, UBPR5369=5000, UBPR2200=1400000, UBPR8274=145000,
  UBPR7204=8.53, UBPR7205=13.50

Layer 2 - Arithmetic:
  UBPRE878=1700000, UBPRD142=900000, UBPRD429=550000,
  UBPRD398=9400 (3500+5000+900), UBPRD309=-150 (0+(-150)),
  UBPRE037=18800 (11000+2200+5500+0+100), UBPR4635=2850 (2800+50),
  UBPR1795=2250 (2850-600), UBPR4107=63500 (52000+300+1200+9400+500+100),
  UBPR4074=39500 (63500-24000), UBPRE036=47000 (39500+7500),
  UBPRPG64=28200 (47000-18800), UBPRD483=2500, UBPRE038=25700 (25550+150),
  UBPRE119=885000 (880000+5000), UBPRD663=1400000, UBPRE625=6000,
  UBPRE644=145000

Layer 3 - Averaging (CAVG04X for Q3 = avg of Q1,Q2,Q3 within 2024):
  UBPRD659 = avg(1660000,1680000,1700000) = 1680000
  UBPRD151 = avg(860000,880000,900000) = 880000
  UBPRD272 = avg(4600,4800,5000) = 4800
  UBPRD337 = avg(46000,48000,50000) = 48000
  UBPRD498 = avg(560000,555000,550000) = 555000
  UBPRD377 = avg(16000,18000,20000) = 18000
  UBPRD506 (CAVG05X) = avg(15000,16000,16000,17000) = 16000

Layer 4 - Higher:
  UBPRE386 = 880000+4800 = 884800
  UBPRD362 = 48000+555000+18000+880000+4800 = 1505800
  UBPRD088 = UBPR2170 at 2023-09-30 = 1640000
  UBPRD087 = 1720000-1640000 = 80000
  UBPRD251 = UBPRE119 at 2023-09-30 = 810000+3000 = 813000
  UBPRD250 = 885000-813000 = 72000
  UBPRD349 = UBPRE644 at 2023-09-30 = 133000
  UBPRD347 = 145000-133000 = 12000

Layer 5 - Summary Ratios (all using ANN=4/3):
  See EXPECTED_VALUES below.
"""

import json
import os
import math
import sqlite3
import pytest


EXPECTED_VALUES = {
    # Earnings ratios (PCTOFANN with denominator UBPRD659=1680000, ANN=4/3)
    "UBPRE001": 63500 / 1680000 * (4/3) * 100,     # ~5.0397
    "UBPRE002": 24000 / 1680000 * (4/3) * 100,      # ~1.9048
    "UBPRE003": 39500 / 1680000 * (4/3) * 100,      # ~3.1349
    "UBPRE004": 7500 / 1680000 * (4/3) * 100,       # ~0.5952
    "UBPRE005": 18800 / 1680000 * (4/3) * 100,      # ~1.4921
    "UBPRPG69": 28200 / 1680000 * (4/3) * 100,      # ~2.2381
    "UBPRE006": 2500 / 1680000 * (4/3) * 100,       # ~0.1984
    "UBPRE007": 25700 / 1680000 * (4/3) * 100,      # ~2.0397
    "UBPRE008": -150 / 1680000 * (4/3) * 100,       # ~-0.0119
    "UBPRE010": 20440 / 1680000 * (4/3) * 100,      # ~1.6222
    "UBPRE013": 20440 / 1680000 * (4/3) * 100,      # ~1.6222

    # Earning asset ratios
    "UBPRE014": 1505800 / 1680000 * 100,             # ~89.6310 (PCTOF)
    "UBPRE016": 63500 / 1505800 * (4/3) * 100,      # ~5.6224
    "UBPRE017": 24000 / 1505800 * (4/3) * 100,      # ~2.1248
    "UBPRE018": 39500 / 1505800 * (4/3) * 100,      # ~3.4976

    # Loan loss ratio
    "UBPRE019": 2250 / 884800 * (4/3) * 100,        # ~0.3390

    # ACL ratio (PCTOF)
    "UBPRE022": 10000 / 890000 * 100,                # ~1.1236

    # Balance sheet ratios (PCTOF)
    "UBPRE024": 885000 / 1720000 * 100,              # ~51.4535
    "UBPRE600": 885000 / 1400000 * 100,              # ~63.2143

    # Growth rates (PCTOF)
    "UBPR7316": 80000 / 1640000 * 100,               # ~4.8780
    "UBPR7408": 12000 / 133000 * 100,                # ~9.0226
    "UBPRE027": 72000 / 813000 * 100,                # ~8.8561

    # Direct lookups
    "UBPRD486": 8.53,                                 # Leverage ratio
    "UBPRD506": 16000.0,                              # CAVG05X of sub notes

    # Cash dividends to net income
    "UBPR7402": 6000 / 20440 * 100,                  # ~29.3542
}


# ─── Intermediate concept golden values for SQLite verification ──────────
INTERMEDIATE_VALUES = {
    ("UBPRD659", "2024-09-30"): 1680000.0,
    ("UBPRE878", "2024-03-31"): 1660000.0,
    ("UBPRE878", "2024-06-30"): 1680000.0,
    ("UBPR3200", "2023-12-31"): 15000.0,
    ("UBPR3200", "2024-03-31"): 16000.0,
    ("UBPRD362", "2024-09-30"): 1505800.0,
    ("UBPRE386", "2024-09-30"): 884800.0,
    ("UBPRD088", "2024-09-30"): 1640000.0,
    ("UBPRD087", "2024-09-30"): 80000.0,
    ("UBPRE119", "2024-09-30"): 885000.0,
    ("UBPR4107", "2024-09-30"): 63500.0,
    ("UBPR4074", "2024-09-30"): 39500.0,
}

# Concepts whose numerator values come exclusively from XBRL (RIAD schedule).
# If XBRL parsing fails, these will be null or wrong.
XBRL_DEPENDENT_CONCEPTS = [
    "UBPRE001",  # depends on RIAD4010 (total interest income)
    "UBPRE002",  # depends on RIAD4073 (interest expense)
    "UBPRE005",  # depends on RIAD4135, RIAD4217, RIAD4092 (overhead)
    "UBPRE010",  # depends on RIAD4300 (net operating income)
    "UBPR7402",  # depends on RIAD4460 (dividends) and RIAD4340 (net income)
    "UBPR7408",  # depends on RCONA8274 (Tier 1 capital from XBRL)
]


@pytest.fixture
def output_data():
    output_path = "/app/output/ratios.json"
    assert os.path.exists(output_path), f"Output file not found: {output_path}"
    with open(output_path) as f:
        data = json.load(f)
    assert isinstance(data, dict), "Output must be a JSON object"
    return data


@pytest.fixture
def db():
    db_path = "/app/output/ubpr.db"
    assert os.path.exists(db_path), f"SQLite database not found: {db_path}"
    conn = sqlite3.connect(db_path)
    yield conn
    conn.close()


def test_output_file_exists():
    """The output file must exist and be valid JSON."""
    assert os.path.exists("/app/output/ratios.json"), "Output file missing"
    with open("/app/output/ratios.json") as f:
        data = json.load(f)
    assert isinstance(data, dict)


def test_all_output_concepts_present(output_data):
    """All 25 required output concepts must be present."""
    missing = []
    for concept_id in EXPECTED_VALUES:
        if concept_id not in output_data:
            missing.append(concept_id)
    assert not missing, f"Missing output concepts: {missing}"


def test_no_unexpected_nulls(output_data):
    """None of the expected output values should be null."""
    null_concepts = []
    for concept_id in EXPECTED_VALUES:
        if concept_id in output_data and output_data[concept_id] is None:
            null_concepts.append(concept_id)
    assert not null_concepts, f"Concepts unexpectedly null: {null_concepts}"


class TestXBRLDataIngestion:
    """Verify that income-statement data from XBRL is correctly parsed and merged."""

    def test_xbrl_dependent_concepts_not_null(self, output_data):
        """Concepts that depend on RIAD/RCONA items from XBRL must not be null.
        If any are null, XBRL parsing likely failed."""
        null_concepts = []
        for cid in XBRL_DEPENDENT_CONCEPTS:
            if output_data.get(cid) is None:
                null_concepts.append(cid)
        assert not null_concepts, (
            f"XBRL-dependent concepts are null (XBRL parsing may have failed): "
            f"{null_concepts}"
        )

    def test_total_interest_income_from_xbrl(self, output_data):
        """UBPRE001 numerator (UBPR4107) requires RIAD4010 from XBRL.
        Verifies XBRL data was correctly merged into the Call Report lookup."""
        expected = EXPECTED_VALUES["UBPRE001"]
        actual = output_data.get("UBPRE001")
        assert actual is not None, "UBPRE001 is null — RIAD4010 from XBRL not parsed"
        assert abs(actual - expected) < 0.02, (
            f"UBPRE001: expected {expected:.4f}, got {actual:.4f}. "
            f"RIAD4010 from XBRL may have wrong value."
        )

    def test_rcona_tier1_capital_from_xbrl(self, output_data):
        """UBPR7408 (Tier 1 growth) depends on RCONA8274 from XBRL instant contexts."""
        expected = EXPECTED_VALUES["UBPR7408"]
        actual = output_data.get("UBPR7408")
        assert actual is not None, "UBPR7408 is null — RCONA8274 from XBRL not parsed"
        assert abs(actual - expected) < 0.02, (
            f"UBPR7408: expected {expected:.4f}, got {actual:.4f}. "
            f"RCONA8274 from XBRL instant contexts may have wrong value."
        )

    def test_xbrl_duration_context_handling(self, output_data):
        """UBPRE010 depends on RIAD4300 which uses duration contexts in XBRL.
        Verifies that startDate/endDate contexts are correctly resolved."""
        expected = EXPECTED_VALUES["UBPRE010"]
        actual = output_data.get("UBPRE010")
        assert actual is not None, "UBPRE010 null — XBRL duration context parsing failed"
        assert abs(actual - expected) < 0.02, (
            f"UBPRE010: expected {expected:.4f}, got {actual:.4f}. "
            f"RIAD4300 duration context may not be correctly resolved to endDate."
        )


class TestEarningsRatios:
    """Test annualized earnings ratios (PCTOFANN with avg assets denominator)."""

    @pytest.mark.parametrize("concept_id", [
        "UBPRE001", "UBPRE002", "UBPRE003", "UBPRE004", "UBPRE005",
        "UBPRPG69", "UBPRE006", "UBPRE007", "UBPRE008",
        "UBPRE010", "UBPRE013",
    ])
    def test_earnings_ratio(self, output_data, concept_id):
        expected = EXPECTED_VALUES[concept_id]
        actual = output_data.get(concept_id)
        assert actual is not None, f"{concept_id} is null"
        assert isinstance(actual, (int, float)), f"{concept_id} is not numeric: {actual}"
        assert abs(actual - expected) < 0.02, (
            f"{concept_id}: expected {expected:.4f}, got {actual:.4f}, "
            f"diff={abs(actual - expected):.6f}"
        )


class TestEarningAssetRatios:
    """Test earning asset ratios (mix of PCTOF and PCTOFANN)."""

    @pytest.mark.parametrize("concept_id", [
        "UBPRE014", "UBPRE016", "UBPRE017", "UBPRE018",
    ])
    def test_earning_asset_ratio(self, output_data, concept_id):
        expected = EXPECTED_VALUES[concept_id]
        actual = output_data.get(concept_id)
        assert actual is not None, f"{concept_id} is null"
        assert abs(actual - expected) < 0.02, (
            f"{concept_id}: expected {expected:.4f}, got {actual:.4f}"
        )


class TestLoanAndBalanceSheetRatios:
    """Test loan loss, ACL, and balance sheet ratios."""

    @pytest.mark.parametrize("concept_id", [
        "UBPRE019", "UBPRE022", "UBPRE024", "UBPRE600",
    ])
    def test_ratio(self, output_data, concept_id):
        expected = EXPECTED_VALUES[concept_id]
        actual = output_data.get(concept_id)
        assert actual is not None, f"{concept_id} is null"
        assert abs(actual - expected) < 0.02, (
            f"{concept_id}: expected {expected:.4f}, got {actual:.4f}"
        )


class TestGrowthRates:
    """Test year-over-year growth rates (require [-P1Y] period lookups)."""

    @pytest.mark.parametrize("concept_id", [
        "UBPR7316", "UBPR7408", "UBPRE027",
    ])
    def test_growth_rate(self, output_data, concept_id):
        expected = EXPECTED_VALUES[concept_id]
        actual = output_data.get(concept_id)
        assert actual is not None, f"{concept_id} is null"
        assert abs(actual - expected) < 0.02, (
            f"{concept_id}: expected {expected:.4f}, got {actual:.4f}"
        )


class TestDirectLookups:
    """Test values sourced directly from Call Report (leverage ratio, etc.)."""

    def test_leverage_ratio(self, output_data):
        expected = EXPECTED_VALUES["UBPRD486"]
        actual = output_data.get("UBPRD486")
        assert actual is not None, "UBPRD486 is null"
        assert abs(actual - expected) < 0.02, (
            f"UBPRD486: expected {expected}, got {actual}"
        )

    def test_cavg05x_subordinated_notes(self, output_data):
        """CAVG05X must include prior December in the average window."""
        expected = EXPECTED_VALUES["UBPRD506"]
        actual = output_data.get("UBPRD506")
        assert actual is not None, "UBPRD506 is null"
        assert abs(actual - expected) < 1.0, (
            f"UBPRD506: expected {expected}, got {actual}"
        )

    def test_cash_dividends_to_net_income(self, output_data):
        expected = EXPECTED_VALUES["UBPR7402"]
        actual = output_data.get("UBPR7402")
        assert actual is not None, "UBPR7402 is null"
        assert abs(actual - expected) < 0.02, (
            f"UBPR7402: expected {expected:.4f}, got {actual:.4f}"
        )


class TestComputationChain:
    """Verify the multi-layer dependency chain is correctly resolved."""

    def test_avg_assets_is_cavg04x(self, output_data):
        """UBPRD659 should be the 3-quarter average for Q3 report date.
        (1660000 + 1680000 + 1700000) / 3 = 1680000"""
        expected_e001 = 63500 / 1680000 * (4/3) * 100
        actual_e001 = output_data.get("UBPRE001")
        assert actual_e001 is not None
        assert abs(actual_e001 - expected_e001) < 0.02

    def test_avg_earning_assets_chain(self, output_data):
        """UBPRD362 depends on 5 averaged sub-components. Test via UBPRE014."""
        expected = 1505800 / 1680000 * 100
        actual = output_data.get("UBPRE014")
        assert actual is not None
        assert abs(actual - expected) < 0.02, (
            f"UBPRE014 (avg earning assets / avg assets): "
            f"expected {expected:.4f}, got {actual:.4f}. "
            f"This implies UBPRD362 = {actual * 1680000 / 100:.0f} "
            f"(expected 1505800)"
        )

    def test_annualization_factor(self, output_data):
        """Verify ANN = 4/3 is applied correctly for Q3 (September).
        Compare annualized vs non-annualized ratio to extract the factor."""
        e001 = output_data.get("UBPRE001")
        if e001 is not None:
            raw_pct = 63500 / 1680000 * 100  # ~3.7798
            implied_ann = e001 / raw_pct
            assert abs(implied_ann - 4/3) < 0.01, (
                f"Implied annualization factor: {implied_ann:.4f}, expected {4/3:.4f}"
            )

    def test_negative_value_handled(self, output_data):
        """UBPRE008 should be negative (securities loss)."""
        actual = output_data.get("UBPRE008")
        assert actual is not None
        assert actual < 0, f"UBPRE008 should be negative (securities loss), got {actual}"

    def test_growth_rate_prior_year_lookup(self, output_data):
        """UBPR7316 requires [-P1Y] lookup of total assets.
        80000 / 1640000 * 100 = 4.878%"""
        expected = 80000 / 1640000 * 100
        actual = output_data.get("UBPR7316")
        assert actual is not None
        assert abs(actual - expected) < 0.02


class TestSQLiteDatabase:
    """Verify the SQLite audit database structure and contents."""

    def test_database_exists(self):
        assert os.path.exists("/app/output/ubpr.db"), "SQLite database not found"

    def test_evaluations_table_exists(self, db):
        cursor = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='evaluations'"
        )
        assert cursor.fetchone() is not None, "Table 'evaluations' does not exist"

    def test_formula_deps_table_exists(self, db):
        cursor = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='formula_deps'"
        )
        assert cursor.fetchone() is not None, "Table 'formula_deps' does not exist"

    def test_evaluations_schema(self, db):
        """evaluations table must have concept_id, eval_date, value columns."""
        cursor = db.execute("PRAGMA table_info(evaluations)")
        columns = {row[1] for row in cursor.fetchall()}
        assert 'concept_id' in columns, "Missing column: concept_id"
        assert 'eval_date' in columns, "Missing column: eval_date"
        assert 'value' in columns, "Missing column: value"

    def test_formula_deps_schema(self, db):
        """formula_deps table must have source_id, target_id columns."""
        cursor = db.execute("PRAGMA table_info(formula_deps)")
        columns = {row[1] for row in cursor.fetchall()}
        assert 'source_id' in columns, "Missing column: source_id"
        assert 'target_id' in columns, "Missing column: target_id"

    def test_all_output_concepts_in_evaluations(self, db):
        """All 25 output concepts must have evaluations at the report date."""
        missing = []
        for concept_id in EXPECTED_VALUES:
            cursor = db.execute(
                "SELECT value FROM evaluations WHERE concept_id = ? AND eval_date = '2024-09-30'",
                (concept_id,)
            )
            row = cursor.fetchone()
            if row is None:
                missing.append(concept_id)
        assert not missing, f"Output concepts missing from evaluations table: {missing}"

    @pytest.mark.parametrize("key,expected_val", [
        (("UBPRD659", "2024-09-30"), 1680000.0),
        (("UBPRE878", "2024-03-31"), 1660000.0),
        (("UBPRE878", "2024-06-30"), 1680000.0),
        (("UBPR3200", "2023-12-31"), 15000.0),
        (("UBPRD362", "2024-09-30"), 1505800.0),
        (("UBPRE386", "2024-09-30"), 884800.0),
        (("UBPRD088", "2024-09-30"), 1640000.0),
        (("UBPR4107", "2024-09-30"), 63500.0),
        (("UBPR4074", "2024-09-30"), 39500.0),
    ])
    def test_intermediate_concept_value(self, db, key, expected_val):
        """Intermediate concepts must have correct values in the evaluations table."""
        concept_id, eval_date = key
        cursor = db.execute(
            "SELECT value FROM evaluations WHERE concept_id = ? AND eval_date = ?",
            (concept_id, eval_date)
        )
        row = cursor.fetchone()
        assert row is not None, (
            f"{concept_id} at {eval_date} not found in evaluations table"
        )
        assert abs(row[0] - expected_val) < 1.0, (
            f"{concept_id} at {eval_date}: expected {expected_val}, got {row[0]}"
        )

    def test_historical_evaluations_for_cavg(self, db):
        """CAVG04X requires evaluation at Q1, Q2, Q3. Verify Q1 2024 has entries."""
        cursor = db.execute(
            "SELECT COUNT(DISTINCT concept_id) FROM evaluations "
            "WHERE eval_date = '2024-03-31'"
        )
        count = cursor.fetchone()[0]
        assert count >= 5, (
            f"Expected >= 5 distinct concepts evaluated at 2024-03-31 "
            f"(for CAVG averaging), got {count}"
        )

    def test_cavg05x_includes_prior_december(self, db):
        """CAVG05X for UBPRD506 should evaluate UBPR3200 at 2023-12-31."""
        cursor = db.execute(
            "SELECT value FROM evaluations "
            "WHERE concept_id = 'UBPR3200' AND eval_date = '2023-12-31'"
        )
        row = cursor.fetchone()
        assert row is not None, (
            "UBPR3200 at 2023-12-31 missing from evaluations "
            "(required by CAVG05X for UBPRD506)"
        )
        assert abs(row[0] - 15000.0) < 1.0

    def test_total_evaluation_count(self, db):
        """Engine should evaluate many concepts at multiple dates."""
        cursor = db.execute("SELECT COUNT(*) FROM evaluations")
        count = cursor.fetchone()[0]
        assert count >= 80, (
            f"Expected >= 80 evaluation rows (formulas at multiple dates), got {count}"
        )

    def test_multiple_eval_dates(self, db):
        """Evaluations should span at least 3 distinct dates."""
        cursor = db.execute("SELECT COUNT(DISTINCT eval_date) FROM evaluations")
        count = cursor.fetchone()[0]
        assert count >= 3, (
            f"Expected evaluations at >= 3 distinct dates, got {count}"
        )

    def test_dependency_ubpre001(self, db):
        """UBPRE001's formula PCTOFANN(uc:UBPR4107, uc:UBPRD659) depends on both."""
        cursor = db.execute(
            "SELECT target_id FROM formula_deps WHERE source_id = 'UBPRE001'"
        )
        deps = {row[0] for row in cursor.fetchall()}
        assert 'UBPR4107' in deps, (
            f"UBPRE001 should depend on UBPR4107, got deps: {deps}"
        )
        assert 'UBPRD659' in deps, (
            f"UBPRE001 should depend on UBPRD659, got deps: {deps}"
        )

    def test_dependency_ubprd362(self, db):
        """UBPRD362 depends on 5 averaged sub-components."""
        cursor = db.execute(
            "SELECT target_id FROM formula_deps WHERE source_id = 'UBPRD362'"
        )
        deps = {row[0] for row in cursor.fetchall()}
        expected = {'UBPRD337', 'UBPRD498', 'UBPRD377', 'UBPRD151', 'UBPRD272'}
        assert expected.issubset(deps), (
            f"UBPRD362 should depend on {expected}, got {deps}"
        )

    def test_dependency_edge_count(self, db):
        """There should be a significant number of dependency edges."""
        cursor = db.execute("SELECT COUNT(*) FROM formula_deps")
        count = cursor.fetchone()[0]
        assert count >= 50, (
            f"Expected >= 50 dependency edges in formula_deps, got {count}"
        )

    def test_no_self_dependencies(self, db):
        """No concept should depend on itself."""
        cursor = db.execute(
            "SELECT source_id FROM formula_deps WHERE source_id = target_id"
        )
        self_deps = [row[0] for row in cursor.fetchall()]
        assert not self_deps, f"Self-dependencies found: {self_deps}"

    def test_system_concepts_excluded(self, db):
        """System concepts (UBPRC752, UBPR9999) should not be in evaluations."""
        for sys_concept in ['UBPRC752', 'UBPR9999']:
            cursor = db.execute(
                "SELECT COUNT(*) FROM evaluations WHERE concept_id = ?",
                (sys_concept,)
            )
            count = cursor.fetchone()[0]
            assert count == 0, (
                f"System concept {sys_concept} should not be in evaluations "
                f"table, but found {count} rows"
            )

    def test_evaluation_consistency_with_json(self, output_data, db):
        """Values in evaluations table must match ratios.json for output concepts."""
        mismatches = []
        for concept_id in list(EXPECTED_VALUES.keys())[:10]:
            cursor = db.execute(
                "SELECT value FROM evaluations "
                "WHERE concept_id = ? AND eval_date = '2024-09-30'",
                (concept_id,)
            )
            row = cursor.fetchone()
            if row is not None and row[0] is not None and concept_id in output_data:
                json_val = output_data[concept_id]
                if json_val is not None and abs(row[0] - json_val) >= 0.1:
                    mismatches.append(
                        f"{concept_id}: DB={row[0]:.4f} vs JSON={json_val:.4f}"
                    )
        assert not mismatches, (
            f"DB evaluations do not match ratios.json: {mismatches}"
        )

    def test_cavg_concept_has_dependency(self, db):
        """CAVG04X/CAVG05X concepts should have exactly 1 dependency (the averaged concept)."""
        cavg_concepts = {
            'UBPRD659': 'UBPRE878',
            'UBPRD151': 'UBPRD142',
            'UBPRD506': 'UBPR3200',
        }
        for src, expected_dep in cavg_concepts.items():
            cursor = db.execute(
                "SELECT target_id FROM formula_deps WHERE source_id = ?",
                (src,)
            )
            deps = {row[0] for row in cursor.fetchall()}
            assert expected_dep in deps, (
                f"{src} should depend on {expected_dep}, got {deps}"
            )


class TestQoQTrendsView:
    """Verify the qoq_trends SQL view with window function analysis."""

    def test_view_exists(self, db):
        """qoq_trends must exist as a view (not a table)."""
        cursor = db.execute(
            "SELECT name FROM sqlite_master WHERE type='view' AND name='qoq_trends'"
        )
        assert cursor.fetchone() is not None, "View 'qoq_trends' does not exist"

    def test_view_columns(self, db):
        """qoq_trends must have the required columns."""
        cursor = db.execute("SELECT * FROM qoq_trends LIMIT 1")
        col_names = [desc[0] for desc in cursor.description]
        required = {'concept_id', 'eval_date', 'value', 'prior_value',
                     'abs_change', 'pct_change'}
        missing = required - set(col_names)
        assert not missing, (
            f"qoq_trends view missing columns: {missing}. Got: {col_names}"
        )

    def test_view_returns_data(self, db):
        """qoq_trends must return rows."""
        cursor = db.execute("SELECT COUNT(*) FROM qoq_trends")
        count = cursor.fetchone()[0]
        assert count >= 80, f"Expected >=80 rows in qoq_trends, got {count}"

    def test_first_date_has_null_prior(self, db):
        """The earliest evaluation for a concept should have NULL prior_value."""
        cursor = db.execute(
            "SELECT prior_value, abs_change FROM qoq_trends "
            "WHERE concept_id = 'UBPRE878' "
            "ORDER BY eval_date ASC LIMIT 1"
        )
        row = cursor.fetchone()
        assert row is not None, "UBPRE878 not found in qoq_trends"
        assert row[0] is None, (
            f"First eval of UBPRE878 should have NULL prior_value, got {row[0]}"
        )
        assert row[1] is None, (
            f"First eval of UBPRE878 should have NULL abs_change, got {row[1]}"
        )

    def test_prior_value_correct(self, db):
        """Verify prior_value for UBPRE878 at Q2 2024 = Q1 2024 value."""
        cursor = db.execute(
            "SELECT value, prior_value, abs_change FROM qoq_trends "
            "WHERE concept_id = 'UBPRE878' AND eval_date = '2024-06-30'"
        )
        row = cursor.fetchone()
        assert row is not None, "UBPRE878 at 2024-06-30 not in qoq_trends"
        value, prior_value, abs_change = row
        assert prior_value is not None, "prior_value should not be NULL for Q2"
        assert abs(prior_value - 1660000.0) < 1.0, (
            f"prior_value should be 1660000 (Q1 value), got {prior_value}"
        )
        assert abs(abs_change - 20000.0) < 1.0, (
            f"abs_change should be 20000, got {abs_change}"
        )

    def test_pct_change_calculation(self, db):
        """Verify pct_change = (value - prior) / prior * 100."""
        cursor = db.execute(
            "SELECT pct_change FROM qoq_trends "
            "WHERE concept_id = 'UBPRE878' AND eval_date = '2024-09-30'"
        )
        row = cursor.fetchone()
        assert row is not None, "UBPRE878 at 2024-09-30 not in qoq_trends"
        pct_change = row[0]
        assert pct_change is not None, "pct_change should not be NULL"
        # 20000 / 1680000 * 100 ≈ 1.1905
        expected_pct = 20000.0 / 1680000.0 * 100.0
        assert abs(pct_change - expected_pct) < 0.01, (
            f"pct_change should be ~{expected_pct:.4f}, got {pct_change:.4f}"
        )

    def test_ordering(self, db):
        """View must be ordered by concept_id then eval_date."""
        cursor = db.execute(
            "SELECT concept_id, eval_date FROM qoq_trends "
            "WHERE concept_id IN ('UBPRD659', 'UBPRE878') "
            "ORDER BY concept_id, eval_date"
        )
        rows = cursor.fetchall()
        assert len(rows) >= 2, "Expected multiple rows for ordering test"
        # Verify concept_id ordering
        prev_concept = None
        prev_date = None
        for concept_id, eval_date in rows:
            if prev_concept is not None and concept_id == prev_concept:
                assert eval_date >= prev_date, (
                    f"Dates not ordered for {concept_id}: {prev_date} > {eval_date}"
                )
            prev_concept = concept_id
            prev_date = eval_date
