
import sqlite3
import os
import subprocess
import json
import glob
import pytest

DB_PATH = "/app/results.db"
REPORT_PATH = "/app/report.json"


@pytest.fixture(scope="module")
def db():
    assert os.path.exists(DB_PATH), f"Database {DB_PATH} does not exist"
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def report_data():
    assert os.path.exists(REPORT_PATH), f"Report {REPORT_PATH} does not exist"
    with open(REPORT_PATH) as f:
        return json.load(f)


def qe(db, entity_id, year):
    """Query entity_results."""
    row = db.execute(
        "SELECT * FROM entity_results WHERE entity_id=? AND year=?",
        (entity_id, year),
    ).fetchone()
    assert row is not None, f"No entity_results row for {entity_id}/{year}"
    return dict(row)


def qa(db, partnership_id, partner_id, year):
    """Query partner_allocations."""
    row = db.execute(
        "SELECT * FROM partner_allocations WHERE partnership_id=? AND partner_id=? AND year=?",
        (partnership_id, partner_id, year),
    ).fetchone()
    assert row is not None, f"No partner_allocations row for {partnership_id}/{partner_id}/{year}"
    return dict(row)


def qeb(db, entity_id, partnership_id, year):
    """Query ebie_balances."""
    row = db.execute(
        "SELECT * FROM ebie_balances WHERE entity_id=? AND partnership_id=? AND year=?",
        (entity_id, partnership_id, year),
    ).fetchone()
    assert row is not None, f"No ebie_balances row for {entity_id}/{partnership_id}/{year}"
    return dict(row)


def qlr(db, loan_id):
    """Query loan_recharacterizations."""
    row = db.execute(
        "SELECT * FROM loan_recharacterizations WHERE loan_id=?",
        (loan_id,),
    ).fetchone()
    assert row is not None, f"No loan_recharacterizations row for {loan_id}"
    return dict(row)


# ============================================================
# Schema validation
# ============================================================

class TestSchema:
    def test_entity_results_table_exists(self, db):
        tables = [
            r[0]
            for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        assert "entity_results" in tables

    def test_partner_allocations_table_exists(self, db):
        tables = [
            r[0]
            for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        assert "partner_allocations" in tables

    def test_ebie_balances_table_exists(self, db):
        tables = [
            r[0]
            for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        assert "ebie_balances" in tables

    def test_loan_recharacterizations_table_exists(self, db):
        tables = [
            r[0]
            for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        assert "loan_recharacterizations" in tables

    def test_entity_results_columns(self, db):
        cols = {
            r[1]
            for r in db.execute("PRAGMA table_info(entity_results)").fetchall()
        }
        expected = {
            "entity_id", "year", "ati", "limitation",
            "deductible_bie", "disallowed_bie", "carryforward_bie",
            "excess_bie", "excess_taxable_income", "excess_bii",
            "ebie_converted",
        }
        assert expected.issubset(cols), f"Missing columns: {expected - cols}"

    def test_makefile_exists(self, db):
        assert os.path.exists("/app/Makefile"), "Makefile not found at /app/Makefile"

    def test_makefile_clean_target(self, db):
        result = subprocess.run(
            ["make", "-n", "-C", "/app", "clean"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"make clean -n failed: {result.stderr}"


# ============================================================
# Section 385 recharacterization tests
# ============================================================

class TestRecharacterization:
    def test_l001_recharacterized(self, db):
        r = qlr(db, "L001")
        assert r["recharacterized"] == 1

    def test_l001_amount(self, db):
        r = qlr(db, "L001")
        assert r["recharacterized_amount"] == pytest.approx(200.0, abs=0.01)

    def test_l001_interest_removed(self, db):
        r = qlr(db, "L001")
        assert r["annual_interest_removed"] == pytest.approx(20.0, abs=0.01)

    def test_l002_not_recharacterized(self, db):
        r = qlr(db, "L002")
        assert r["recharacterized"] == 0

    def test_l002_amount_zero(self, db):
        r = qlr(db, "L002")
        assert r["recharacterized_amount"] == pytest.approx(0.0, abs=0.01)

    def test_l002_interest_removed_zero(self, db):
        r = qlr(db, "L002")
        assert r["annual_interest_removed"] == pytest.approx(0.0, abs=0.01)

    def test_all_loans_present(self, db):
        count = db.execute(
            "SELECT COUNT(*) FROM loan_recharacterizations"
        ).fetchone()[0]
        assert count == 2


# ============================================================
# corp_alpha 2021 — BII reduced by 385 recharacterization
# ============================================================

class TestCorpAlpha:
    def test_ati(self, db):
        r = qe(db, "corp_alpha", 2021)
        assert r["ati"] == pytest.approx(120.0, abs=0.01)

    def test_limitation(self, db):
        r = qe(db, "corp_alpha", 2021)
        assert r["limitation"] == pytest.approx(46.0, abs=0.01)

    def test_deductible(self, db):
        r = qe(db, "corp_alpha", 2021)
        assert r["deductible_bie"] == pytest.approx(46.0, abs=0.01)

    def test_disallowed(self, db):
        r = qe(db, "corp_alpha", 2021)
        assert r["disallowed_bie"] == pytest.approx(4.0, abs=0.01)

    def test_carryforward(self, db):
        r = qe(db, "corp_alpha", 2021)
        assert r["carryforward_bie"] == pytest.approx(4.0, abs=0.01)


# ============================================================
# corp_beta 2021 — BIE reduced by 385 recharacterization
# ============================================================

class TestCorpBeta2021:
    def test_ati(self, db):
        r = qe(db, "corp_beta", 2021)
        assert r["ati"] == pytest.approx(80.0, abs=0.01)

    def test_limitation(self, db):
        r = qe(db, "corp_beta", 2021)
        assert r["limitation"] == pytest.approx(54.0, abs=0.01)

    def test_deductible(self, db):
        r = qe(db, "corp_beta", 2021)
        assert r["deductible_bie"] == pytest.approx(54.0, abs=0.01)

    def test_disallowed(self, db):
        r = qe(db, "corp_beta", 2021)
        assert r["disallowed_bie"] == pytest.approx(6.0, abs=0.01)

    def test_carryforward(self, db):
        r = qe(db, "corp_beta", 2021)
        assert r["carryforward_bie"] == pytest.approx(6.0, abs=0.01)


# ============================================================
# corp_beta 2022 — carryforward from 385-adjusted 2021
# ============================================================

class TestCorpBeta2022:
    def test_ati(self, db):
        r = qe(db, "corp_beta", 2022)
        assert r["ati"] == pytest.approx(100.0, abs=0.01)

    def test_limitation(self, db):
        r = qe(db, "corp_beta", 2022)
        assert r["limitation"] == pytest.approx(40.0, abs=0.01)

    def test_deductible(self, db):
        r = qe(db, "corp_beta", 2022)
        assert r["deductible_bie"] == pytest.approx(26.0, abs=0.01)

    def test_disallowed(self, db):
        r = qe(db, "corp_beta", 2022)
        assert r["disallowed_bie"] == pytest.approx(0.0, abs=0.01)

    def test_carryforward(self, db):
        r = qe(db, "corp_beta", 2022)
        assert r["carryforward_bie"] == pytest.approx(0.0, abs=0.01)


# ============================================================
# corp_gamma 2020 — CARES Act 50% for non-partnerships
# ============================================================

class TestCorpGamma2020:
    def test_ati(self, db):
        r = qe(db, "corp_gamma", 2020)
        assert r["ati"] == pytest.approx(90.0, abs=0.01)

    def test_limitation(self, db):
        r = qe(db, "corp_gamma", 2020)
        assert r["limitation"] == pytest.approx(75.0, abs=0.01)

    def test_deductible(self, db):
        r = qe(db, "corp_gamma", 2020)
        assert r["deductible_bie"] == pytest.approx(50.0, abs=0.01)


# ============================================================
# corp_gamma 2023 — different year rules, same inputs as 2020
# ============================================================

class TestCorpGamma2023:
    def test_ati(self, db):
        r = qe(db, "corp_gamma", 2023)
        assert r["ati"] == pytest.approx(75.0, abs=0.01)

    def test_limitation(self, db):
        r = qe(db, "corp_gamma", 2023)
        assert r["limitation"] == pytest.approx(52.5, abs=0.01)

    def test_deductible(self, db):
        r = qe(db, "corp_gamma", 2023)
        assert r["deductible_bie"] == pytest.approx(50.0, abs=0.01)

    def test_year_dependent_ati_differs(self, db):
        r2020 = qe(db, "corp_gamma", 2020)
        r2023 = qe(db, "corp_gamma", 2023)
        assert r2020["ati"] != pytest.approx(r2023["ati"], abs=0.01)

    def test_year_dependent_limitation_differs(self, db):
        r2020 = qe(db, "corp_gamma", 2020)
        r2023 = qe(db, "corp_gamma", 2023)
        assert r2020["limitation"] != pytest.approx(r2023["limitation"], abs=0.01)


# ============================================================
# prs 2021 — partnership with excess business interest expense
# ============================================================

class TestPRS2021:
    def test_ati(self, db):
        r = qe(db, "prs", 2021)
        assert r["ati"] == pytest.approx(100.0, abs=0.01)

    def test_limitation(self, db):
        r = qe(db, "prs", 2021)
        assert r["limitation"] == pytest.approx(30.0, abs=0.01)

    def test_deductible(self, db):
        r = qe(db, "prs", 2021)
        assert r["deductible_bie"] == pytest.approx(30.0, abs=0.01)

    def test_excess_bie(self, db):
        r = qe(db, "prs", 2021)
        assert r["excess_bie"] == pytest.approx(10.0, abs=0.01)

    def test_eti_zero(self, db):
        r = qe(db, "prs", 2021)
        assert r["excess_taxable_income"] == pytest.approx(0.0, abs=0.01)

    def test_ebii_zero(self, db):
        r = qe(db, "prs", 2021)
        assert r["excess_bii"] == pytest.approx(0.0, abs=0.01)

    def test_partner_x_allocation(self, db):
        pa = qa(db, "prs", "partner_x", 2021)
        assert pa["deductible_bie"] == pytest.approx(15.0, abs=0.01)
        assert pa["excess_bie"] == pytest.approx(5.0, abs=0.01)
        assert pa["excess_taxable_income"] == pytest.approx(0.0, abs=0.01)

    def test_partner_y_allocation(self, db):
        pa = qa(db, "prs", "partner_y", 2021)
        assert pa["deductible_bie"] == pytest.approx(15.0, abs=0.01)
        assert pa["excess_bie"] == pytest.approx(5.0, abs=0.01)


# ============================================================
# prs 2022 — partnership with excess taxable income
# ============================================================

class TestPRS2022:
    def test_ati(self, db):
        r = qe(db, "prs", 2022)
        assert r["ati"] == pytest.approx(200.0, abs=0.01)

    def test_limitation(self, db):
        r = qe(db, "prs", 2022)
        assert r["limitation"] == pytest.approx(60.0, abs=0.01)

    def test_deductible(self, db):
        r = qe(db, "prs", 2022)
        assert r["deductible_bie"] == pytest.approx(30.0, abs=0.01)

    def test_excess_bie_zero(self, db):
        r = qe(db, "prs", 2022)
        assert r["excess_bie"] == pytest.approx(0.0, abs=0.01)

    def test_eti(self, db):
        r = qe(db, "prs", 2022)
        assert r["excess_taxable_income"] == pytest.approx(100.0, abs=0.01)

    def test_partner_x_eti(self, db):
        pa = qa(db, "prs", "partner_x", 2022)
        assert pa["excess_taxable_income"] == pytest.approx(50.0, abs=0.01)
        assert pa["excess_bie"] == pytest.approx(0.0, abs=0.01)

    def test_partner_y_eti(self, db):
        pa = qa(db, "prs", "partner_y", 2022)
        assert pa["excess_taxable_income"] == pytest.approx(50.0, abs=0.01)


# ============================================================
# prs_two 2019 — partnership CARES Act 30% exception
# ============================================================

class TestPrsTwo2019:
    def test_ati(self, db):
        r = qe(db, "prs_two", 2019)
        assert r["ati"] == pytest.approx(200.0, abs=0.01)

    def test_limitation(self, db):
        r = qe(db, "prs_two", 2019)
        assert r["limitation"] == pytest.approx(60.0, abs=0.01)

    def test_deductible(self, db):
        r = qe(db, "prs_two", 2019)
        assert r["deductible_bie"] == pytest.approx(60.0, abs=0.01)

    def test_excess_bie(self, db):
        r = qe(db, "prs_two", 2019)
        assert r["excess_bie"] == pytest.approx(20.0, abs=0.01)

    def test_eti_zero(self, db):
        r = qe(db, "prs_two", 2019)
        assert r["excess_taxable_income"] == pytest.approx(0.0, abs=0.01)

    def test_corp_delta_allocation(self, db):
        pa = qa(db, "prs_two", "corp_delta", 2019)
        assert pa["deductible_bie"] == pytest.approx(30.0, abs=0.01)
        assert pa["excess_bie"] == pytest.approx(10.0, abs=0.01)
        assert pa["excess_taxable_income"] == pytest.approx(0.0, abs=0.01)

    def test_indiv_phi_allocation(self, db):
        pa = qa(db, "prs_two", "indiv_phi", 2019)
        assert pa["deductible_bie"] == pytest.approx(30.0, abs=0.01)
        assert pa["excess_bie"] == pytest.approx(10.0, abs=0.01)


# ============================================================
# prs_two 2021 — partnership with excess taxable income
# ============================================================

class TestPrsTwo2021:
    def test_ati(self, db):
        r = qe(db, "prs_two", 2021)
        assert r["ati"] == pytest.approx(210.0, abs=0.01)

    def test_limitation(self, db):
        r = qe(db, "prs_two", 2021)
        assert r["limitation"] == pytest.approx(63.0, abs=0.01)

    def test_deductible(self, db):
        r = qe(db, "prs_two", 2021)
        assert r["deductible_bie"] == pytest.approx(30.0, abs=0.01)

    def test_excess_bie_zero(self, db):
        r = qe(db, "prs_two", 2021)
        assert r["excess_bie"] == pytest.approx(0.0, abs=0.01)

    def test_eti(self, db):
        r = qe(db, "prs_two", 2021)
        assert r["excess_taxable_income"] == pytest.approx(110.0, abs=0.01)

    def test_corp_delta_eti(self, db):
        pa = qa(db, "prs_two", "corp_delta", 2021)
        assert pa["excess_taxable_income"] == pytest.approx(55.0, abs=0.01)
        assert pa["excess_bie"] == pytest.approx(0.0, abs=0.01)

    def test_indiv_phi_eti(self, db):
        pa = qa(db, "prs_two", "indiv_phi", 2021)
        assert pa["excess_taxable_income"] == pytest.approx(55.0, abs=0.01)


# ============================================================
# corp_delta 2019 — C corp partner, CARES Act 50% applies
# ============================================================

class TestCorpDelta2019:
    def test_ati(self, db):
        r = qe(db, "corp_delta", 2019)
        assert r["ati"] == pytest.approx(130.0, abs=0.01)

    def test_limitation(self, db):
        r = qe(db, "corp_delta", 2019)
        assert r["limitation"] == pytest.approx(75.0, abs=0.01)

    def test_deductible(self, db):
        r = qe(db, "corp_delta", 2019)
        assert r["deductible_bie"] == pytest.approx(40.0, abs=0.01)

    def test_ebie_converted_zero(self, db):
        r = qe(db, "corp_delta", 2019)
        assert r["ebie_converted"] == pytest.approx(0.0, abs=0.01)

    def test_ebie_balance(self, db):
        eb = qeb(db, "corp_delta", "prs_two", 2019)
        assert eb["balance"] == pytest.approx(10.0, abs=0.01)


# ============================================================
# corp_delta 2021 — EBIE resolution via ETI
# ============================================================

class TestCorpDelta2021:
    def test_ati_includes_eti(self, db):
        r = qe(db, "corp_delta", 2021)
        assert r["ati"] == pytest.approx(185.0, abs=0.01)

    def test_limitation(self, db):
        r = qe(db, "corp_delta", 2021)
        assert r["limitation"] == pytest.approx(65.5, abs=0.01)

    def test_deductible(self, db):
        r = qe(db, "corp_delta", 2021)
        assert r["deductible_bie"] == pytest.approx(50.0, abs=0.01)

    def test_ebie_converted(self, db):
        r = qe(db, "corp_delta", 2021)
        assert r["ebie_converted"] == pytest.approx(10.0, abs=0.01)

    def test_ebie_balance_resolved(self, db):
        eb = qeb(db, "corp_delta", "prs_two", 2021)
        assert eb["balance"] == pytest.approx(0.0, abs=0.01)


# ============================================================
# indiv_phi 2019 — individual partner, CARES Act 50%
# ============================================================

class TestIndivPhi2019:
    def test_ati(self, db):
        r = qe(db, "indiv_phi", 2019)
        assert r["ati"] == pytest.approx(70.0, abs=0.01)

    def test_limitation(self, db):
        r = qe(db, "indiv_phi", 2019)
        assert r["limitation"] == pytest.approx(35.0, abs=0.01)

    def test_deductible(self, db):
        r = qe(db, "indiv_phi", 2019)
        assert r["deductible_bie"] == pytest.approx(20.0, abs=0.01)

    def test_ebie_balance(self, db):
        eb = qeb(db, "indiv_phi", "prs_two", 2019)
        assert eb["balance"] == pytest.approx(10.0, abs=0.01)


# ============================================================
# indiv_phi 2021 — EBIE resolution via ETI
# ============================================================

class TestIndivPhi2021:
    def test_ati_includes_eti(self, db):
        r = qe(db, "indiv_phi", 2021)
        assert r["ati"] == pytest.approx(125.0, abs=0.01)

    def test_limitation(self, db):
        r = qe(db, "indiv_phi", 2021)
        assert r["limitation"] == pytest.approx(37.5, abs=0.01)

    def test_deductible(self, db):
        r = qe(db, "indiv_phi", 2021)
        assert r["deductible_bie"] == pytest.approx(30.0, abs=0.01)

    def test_ebie_converted(self, db):
        r = qe(db, "indiv_phi", 2021)
        assert r["ebie_converted"] == pytest.approx(10.0, abs=0.01)

    def test_ebie_balance_resolved(self, db):
        eb = qeb(db, "indiv_phi", "prs_two", 2021)
        assert eb["balance"] == pytest.approx(0.0, abs=0.01)


# ============================================================
# partner_x 2021 — partner with EBIE tracking
# ============================================================

class TestPartnerX2021:
    def test_ati(self, db):
        r = qe(db, "partner_x", 2021)
        assert r["ati"] == pytest.approx(100.0, abs=0.01)

    def test_limitation(self, db):
        r = qe(db, "partner_x", 2021)
        assert r["limitation"] == pytest.approx(30.0, abs=0.01)

    def test_deductible(self, db):
        r = qe(db, "partner_x", 2021)
        assert r["deductible_bie"] == pytest.approx(20.0, abs=0.01)

    def test_ebie_not_converted(self, db):
        r = qe(db, "partner_x", 2021)
        assert r["ebie_converted"] == pytest.approx(0.0, abs=0.01)

    def test_ebie_balance(self, db):
        eb = qeb(db, "partner_x", "prs", 2021)
        assert eb["balance"] == pytest.approx(5.0, abs=0.01)


# ============================================================
# partner_x 2022 — EBIE resolved via ETI
# ============================================================

class TestPartnerX2022:
    def test_ati_includes_eti(self, db):
        r = qe(db, "partner_x", 2022)
        assert r["ati"] == pytest.approx(150.0, abs=0.01)

    def test_limitation(self, db):
        r = qe(db, "partner_x", 2022)
        assert r["limitation"] == pytest.approx(45.0, abs=0.01)

    def test_deductible(self, db):
        r = qe(db, "partner_x", 2022)
        assert r["deductible_bie"] == pytest.approx(25.0, abs=0.01)

    def test_ebie_converted(self, db):
        r = qe(db, "partner_x", 2022)
        assert r["ebie_converted"] == pytest.approx(5.0, abs=0.01)

    def test_ebie_balance_resolved(self, db):
        eb = qeb(db, "partner_x", "prs", 2022)
        assert eb["balance"] == pytest.approx(0.0, abs=0.01)


# ============================================================
# partner_y 2021 — zero ATI, all BIE disallowed
# ============================================================

class TestPartnerY2021:
    def test_ati_clamped_zero(self, db):
        r = qe(db, "partner_y", 2021)
        assert r["ati"] == pytest.approx(0.0, abs=0.01)

    def test_limitation_zero(self, db):
        r = qe(db, "partner_y", 2021)
        assert r["limitation"] == pytest.approx(0.0, abs=0.01)

    def test_deductible_zero(self, db):
        r = qe(db, "partner_y", 2021)
        assert r["deductible_bie"] == pytest.approx(0.0, abs=0.01)

    def test_disallowed(self, db):
        r = qe(db, "partner_y", 2021)
        assert r["disallowed_bie"] == pytest.approx(20.0, abs=0.01)

    def test_carryforward(self, db):
        r = qe(db, "partner_y", 2021)
        assert r["carryforward_bie"] == pytest.approx(20.0, abs=0.01)

    def test_ebie_balance(self, db):
        eb = qeb(db, "partner_y", "prs", 2021)
        assert eb["balance"] == pytest.approx(5.0, abs=0.01)


# ============================================================
# partner_y 2022 — EBIE resolved, carryforward interaction
# ============================================================

class TestPartnerY2022:
    def test_ati(self, db):
        r = qe(db, "partner_y", 2022)
        assert r["ati"] == pytest.approx(50.0, abs=0.01)

    def test_limitation(self, db):
        r = qe(db, "partner_y", 2022)
        assert r["limitation"] == pytest.approx(15.0, abs=0.01)

    def test_deductible(self, db):
        r = qe(db, "partner_y", 2022)
        assert r["deductible_bie"] == pytest.approx(15.0, abs=0.01)

    def test_disallowed(self, db):
        r = qe(db, "partner_y", 2022)
        assert r["disallowed_bie"] == pytest.approx(30.0, abs=0.01)

    def test_carryforward(self, db):
        r = qe(db, "partner_y", 2022)
        assert r["carryforward_bie"] == pytest.approx(30.0, abs=0.01)

    def test_ebie_converted(self, db):
        r = qe(db, "partner_y", 2022)
        assert r["ebie_converted"] == pytest.approx(5.0, abs=0.01)

    def test_ebie_balance_resolved(self, db):
        eb = qeb(db, "partner_y", "prs", 2022)
        assert eb["balance"] == pytest.approx(0.0, abs=0.01)


# ============================================================
# Cross-entity consistency checks
# ============================================================

class TestCrossEntityConsistency:
    def test_partnership_allocations_sum_to_total(self, db):
        """Partner allocations must sum to partnership totals."""
        partnerships = [("prs", [2021, 2022]), ("prs_two", [2019, 2021])]
        for prs_id, years in partnerships:
            for year in years:
                er = qe(db, prs_id, year)
                rows = db.execute(
                    "SELECT SUM(deductible_bie), SUM(excess_bie), SUM(excess_taxable_income) "
                    "FROM partner_allocations WHERE partnership_id=? AND year=?",
                    (prs_id, year),
                ).fetchone()
                assert rows[0] == pytest.approx(er["deductible_bie"], abs=0.01), \
                    f"{prs_id}/{year}: alloc ded sum"
                assert rows[1] == pytest.approx(er["excess_bie"], abs=0.01), \
                    f"{prs_id}/{year}: alloc ebie sum"
                assert rows[2] == pytest.approx(er["excess_taxable_income"], abs=0.01), \
                    f"{prs_id}/{year}: alloc eti sum"

    def test_all_entities_present(self, db):
        entities = {
            r[0] for r in db.execute(
                "SELECT DISTINCT entity_id FROM entity_results"
            ).fetchall()
        }
        expected = {
            "corp_alpha", "corp_beta", "corp_gamma",
            "prs", "partner_x", "partner_y",
            "prs_two", "corp_delta", "indiv_phi",
        }
        assert expected.issubset(entities)

    def test_deductible_never_exceeds_limitation(self, db):
        rows = db.execute(
            "SELECT entity_id, year, deductible_bie, limitation "
            "FROM entity_results"
        ).fetchall()
        for r in rows:
            assert r[2] <= r[3] + 0.01, (
                f"{r[0]}/{r[1]}: deductible {r[2]} > limitation {r[3]}"
            )

    def test_cares_act_differential(self, db):
        """Partnership 30% exception: prs_two at 30% vs corp_delta at 50% in 2019."""
        prs_lim = qe(db, "prs_two", 2019)["limitation"]
        assert prs_lim == pytest.approx(60.0, abs=0.01)
        delta_lim = qe(db, "corp_delta", 2019)["limitation"]
        assert delta_lim == pytest.approx(75.0, abs=0.01)

    def test_total_entity_year_rows(self, db):
        """Verify expected number of entity-year rows."""
        count = db.execute("SELECT COUNT(*) FROM entity_results").fetchone()[0]
        assert count == 17

    def test_total_partner_allocation_rows(self, db):
        """Verify expected number of partner allocation rows."""
        count = db.execute("SELECT COUNT(*) FROM partner_allocations").fetchone()[0]
        assert count == 8

    def test_385_affects_corp_alpha_differently(self, db):
        """Without 385, corp_alpha would have ATI=100, limitation=60.
        With 385 (BII removed), ATI=120, limitation=46."""
        r = qe(db, "corp_alpha", 2021)
        assert r["ati"] != pytest.approx(100.0, abs=0.01)
        assert r["limitation"] != pytest.approx(60.0, abs=0.01)

    def test_385_cascades_to_corp_beta_2022(self, db):
        """385 reduces corp_beta 2021 BIE, which changes carryforward to 2022."""
        r = qe(db, "corp_beta", 2022)
        assert r["deductible_bie"] == pytest.approx(26.0, abs=0.01)
        assert r["carryforward_bie"] == pytest.approx(0.0, abs=0.01)


# ============================================================
# SQLite query validation — verify data is queryable via SQL
# ============================================================

class TestSQLQueryability:
    def test_aggregate_query(self, db):
        """Total deductible BIE across all entities and years."""
        row = db.execute(
            "SELECT SUM(deductible_bie) FROM entity_results"
        ).fetchone()
        assert row[0] is not None
        assert row[0] > 0

    def test_join_query(self, db):
        """Join entity_results with partner_allocations."""
        rows = db.execute(
            "SELECT er.entity_id, pa.partner_id, pa.year, pa.excess_taxable_income "
            "FROM entity_results er "
            "JOIN partner_allocations pa ON er.entity_id = pa.partnership_id AND er.year = pa.year "
            "WHERE pa.excess_taxable_income > 0"
        ).fetchall()
        assert len(rows) > 0

    def test_ebie_balance_query(self, db):
        """Query EBIE balance tracking across years."""
        rows = db.execute(
            "SELECT entity_id, year, balance FROM ebie_balances "
            "WHERE entity_id='partner_x' ORDER BY year"
        ).fetchall()
        assert len(rows) == 2
        assert rows[0][2] == pytest.approx(5.0, abs=0.01)
        assert rows[1][2] == pytest.approx(0.0, abs=0.01)


# ============================================================
# Report validation — verify report.json structure and values
# ============================================================

class TestReport:
    def test_report_is_valid_json(self, report_data):
        assert isinstance(report_data, dict)

    def test_total_entities(self, report_data):
        assert report_data["total_entities"] == 9

    def test_total_entity_years(self, report_data):
        assert report_data["total_entity_years"] == 17

    def test_aggregate_deductible(self, report_data):
        assert report_data["aggregate_deductible"] == pytest.approx(576.0, abs=0.5)

    def test_aggregate_disallowed(self, report_data):
        assert report_data["aggregate_disallowed"] == pytest.approx(90.0, abs=0.5)

    def test_recharacterized_loans(self, report_data):
        assert report_data["recharacterized_loans"] == 1

    def test_total_interest_removed(self, report_data):
        assert report_data["total_interest_removed"] == pytest.approx(20.0, abs=0.5)

    def test_max_carryforward_entity(self, report_data):
        assert report_data["max_carryforward_entity"] == "partner_y"

    def test_max_carryforward_amount(self, report_data):
        assert report_data["max_carryforward_amount"] == pytest.approx(30.0, abs=0.5)

    def test_ebie_fully_resolved(self, report_data):
        assert report_data["ebie_fully_resolved"] == 4

    def test_all_keys_present(self, report_data):
        required = {
            "total_entities", "total_entity_years",
            "aggregate_deductible", "aggregate_disallowed",
            "recharacterized_loans", "total_interest_removed",
            "max_carryforward_entity", "max_carryforward_amount",
            "ebie_fully_resolved",
        }
        assert required.issubset(set(report_data.keys())), \
            f"Missing keys: {required - set(report_data.keys())}"


# ============================================================
# Report mechanism — verify sqlite3 + jq toolchain
# ============================================================

class TestReportMechanism:
    def test_report_target_dry_run(self, db):
        result = subprocess.run(
            ["make", "-n", "-C", "/app", "report"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"make -n report failed: {result.stderr}"

    def test_report_uses_required_tools(self, db):
        """Report pipeline must use sqlite3 CLI and jq, not Python."""
        texts = []
        with open("/app/Makefile") as f:
            texts.append(f.read())
        result = subprocess.run(
            ["make", "-n", "-C", "/app", "report"],
            capture_output=True, text=True,
        )
        texts.append(result.stdout)
        for pattern in ["/app/*.sh", "/app/**/*.sh"]:
            for sh_file in glob.glob(pattern, recursive=True):
                try:
                    with open(sh_file) as f:
                        texts.append(f.read())
                except Exception:
                    pass
        combined = " ".join(texts)
        assert "sqlite3" in combined, \
            "Report pipeline must use sqlite3 CLI (not Python) to query the database"
        assert "jq" in combined, \
            "Report pipeline must use jq to assemble the JSON report"
