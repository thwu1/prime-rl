"""
ISDA SIMM v2.5 1-Day Delta Margin Calculator - Verification Tests

Tests exact BigDecimal margin outputs against reference golden values.
Compilation is performed via Apache Ant.

"""
import os
import csv
import subprocess
import tempfile
import pytest

BUILD_DIR = "/app/build"
PORTFOLIO = "/app/portfolio.csv"
JAVA_CMD = ["java", "-cp", BUILD_DIR, "SimmCalculator"]


def compile_java():
    result = subprocess.run(
        ["ant", "compile"],
        cwd="/app",
        capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, (
        f"Ant compile failed:\n{result.stdout}\n{result.stderr}"
    )


def run_simm(csv_path):
    result = subprocess.run(JAVA_CMD + [csv_path], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, f"Calculator failed:\n{result.stderr}"
    return int(result.stdout.strip())


def write_csv(rows):
    f = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, dir='/tmp')
    writer = csv.writer(f)
    writer.writerow(["ProductClass", "RiskType", "Qualifier", "Bucket",
                     "Label1", "Label2", "AmountUSD"])
    for row in rows:
        writer.writerow(row)
    f.close()
    return f.name


def read_portfolio():
    records = []
    with open(PORTFOLIO, 'r') as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            if row:
                records.append(row)
    return records


@pytest.fixture(scope="session", autouse=True)
def setup():
    compile_java()


class TestSingleSensitivity:
    def test_ir_usd_2w(self):
        csv_path = write_csv([
            ["RatesFX", "Risk_IRCurve", "USD", "1", "2w", "OIS", "4000000"]
        ])
        assert run_simm(csv_path) == 76000000

    def test_ir_eur_10y(self):
        csv_path = write_csv([
            ["RatesFX", "Risk_IRCurve", "EUR", "1", "10y", "Libor12m", "35000000"]
        ])
        assert run_simm(csv_path) == 560000000

    def test_crq_bucket1(self):
        csv_path = write_csv([
            ["Credit", "Risk_CreditQ", "ISIN:BE0934259525", "1", "1y", "USD", "800000"]
        ])
        assert run_simm(csv_path) == 16800000


class TestIRCorrelation:
    def test_subcurve_same_tenor(self):
        csv_path = write_csv([
            ["RatesFX", "Risk_IRCurve", "USD", "1", "1y", "Municipal", "2000000"],
            ["RatesFX", "Risk_IRCurve", "USD", "1", "1y", "Prime", "3000000"],
        ])
        assert run_simm(csv_path) == 64843812

    def test_subcurve_diff_sign(self):
        csv_path = write_csv([
            ["RatesFX", "Risk_IRCurve", "EUR", "1", "3y", "Libor3m", "-2000000"],
            ["RatesFX", "Risk_IRCurve", "EUR", "1", "3y", "Libor6m", "5000000"],
        ])
        assert run_simm(csv_path) == 48530403

    def test_tenor_correlation(self):
        csv_path = write_csv([
            ["RatesFX", "Risk_IRCurve", "USD", "1", "3m", "Municipal", "-3000000"],
            ["RatesFX", "Risk_IRCurve", "USD", "1", "1y", "Prime", "-1000000"],
        ])
        assert run_simm(csv_path) == 45671094


class TestBaseCorrelation:
    def test_base_corr(self):
        csv_path = write_csv([
            ["Credit", "Risk_BaseCorr", "CDX IG", "", "", "", "500000"],
            ["Credit", "Risk_BaseCorr", "CDX IG", "", "", "", "-200000"],
            ["Credit", "Risk_BaseCorr", "iTraxx Main", "", "", "", "400000"],
        ])
        assert run_simm(csv_path) == 1386542


class TestFXDelta:
    def test_all_fx(self):
        records = read_portfolio()
        fx_records = [r for r in records if r[1] == "Risk_FX"]
        csv_path = write_csv(fx_records)
        assert run_simm(csv_path) == 10242651353


class TestRiskClassAggregation:
    def test_all_ir(self):
        records = read_portfolio()
        ir_records = [r for r in records
                      if r[1] in ("Risk_IRCurve", "Risk_Inflation", "Risk_XCcyBasis")]
        csv_path = write_csv(ir_records)
        assert run_simm(csv_path) == 3134574486

    def test_all_crq_with_basecorr(self):
        records = read_portfolio()
        crq_records = [r for r in records
                       if r[1] in ("Risk_CreditQ", "Risk_BaseCorr")]
        csv_path = write_csv(crq_records)
        assert run_simm(csv_path) == 79009113

    def test_all_crnq(self):
        records = read_portfolio()
        crnq_records = [r for r in records if r[1] == "Risk_CreditNonQ"]
        csv_path = write_csv(crnq_records)
        assert run_simm(csv_path) == 545124809

    def test_all_equity(self):
        records = read_portfolio()
        eq_records = [r for r in records if r[1] == "Risk_Equity"]
        csv_path = write_csv(eq_records)
        assert run_simm(csv_path) == 5933432851

    def test_all_commodity(self):
        records = read_portfolio()
        cm_records = [r for r in records if r[1] == "Risk_Commodity"]
        csv_path = write_csv(cm_records)
        assert run_simm(csv_path) == 16751844655


class TestProductClassAggregation:
    def test_credit_product(self):
        """Credit product class spans multiple risk classes; tests cross-risk-class aggregation."""
        records = read_portfolio()
        credit_records = [r for r in records if r[0] == "Credit"]
        csv_path = write_csv(credit_records)
        assert run_simm(csv_path) == 1681012453


class TestGlobalAggregation:
    def test_full_portfolio(self):
        result = run_simm(PORTFOLIO)
        assert result == 35135297361
