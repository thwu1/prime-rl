"""
Tests for the Universal Life Insurance Cashflow Projector.

Verifies structural correctness, mathematical invariants, SQLite time-series
with views/indexes, Parquet output, and mortality/lapse stress scenario outputs.
"""


import json
import os
import sqlite3
from collections import defaultdict

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

OUT_DIR = "/app/output"
DATA_DIR = "/app/data"


@pytest.fixture(scope="module")
def pv_results():
    return pd.read_csv(os.path.join(OUT_DIR, "pv_results.csv"))


@pytest.fixture(scope="module")
def checks():
    with open(os.path.join(OUT_DIR, "checks.json")) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def model_points():
    return pd.read_csv(os.path.join(DATA_DIR, "model_points.csv"))


@pytest.fixture(scope="module")
def product_specs():
    return pd.read_csv(os.path.join(DATA_DIR, "product_spec.csv"), index_col="spec_id")


@pytest.fixture(scope="module")
def stress_mort_pv():
    return pd.read_csv(os.path.join(OUT_DIR, "stress_mort_pv.csv"))


@pytest.fixture(scope="module")
def stress_lapse_pv():
    return pd.read_csv(os.path.join(OUT_DIR, "stress_lapse_pv.csv"))


@pytest.fixture(scope="module")
def db_conn():
    conn = sqlite3.connect(os.path.join(OUT_DIR, "timeseries.db"))
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def disc_rate_ann():
    return pd.read_csv(os.path.join(DATA_DIR, "disc_rate_ann.csv"), index_col="year")[
        "disc_rate_ann"
    ]


@pytest.fixture(scope="module")
def parquet_table():
    return pq.read_table(os.path.join(OUT_DIR, "timeseries.parquet"))


PV_COLUMNS = {
    "point_id",
    "pv_premiums",
    "pv_claims_death",
    "pv_claims_lapse",
    "pv_claims_maturity",
    "pv_expenses",
    "pv_commissions",
    "pv_inv_income",
    "pv_av_change",
    "pv_net_cf",
}


# ── File Existence and Schema ───────────────────────────────────────────


class TestOutputSchema:
    def test_pv_results_exists(self):
        assert os.path.isfile(os.path.join(OUT_DIR, "pv_results.csv"))

    def test_checks_exists(self):
        assert os.path.isfile(os.path.join(OUT_DIR, "checks.json"))

    def test_timeseries_db_exists(self):
        assert os.path.isfile(os.path.join(OUT_DIR, "timeseries.db"))

    def test_timeseries_parquet_exists(self):
        assert os.path.isfile(os.path.join(OUT_DIR, "timeseries.parquet"))

    def test_stress_mort_pv_exists(self):
        assert os.path.isfile(os.path.join(OUT_DIR, "stress_mort_pv.csv"))

    def test_stress_lapse_pv_exists(self):
        assert os.path.isfile(os.path.join(OUT_DIR, "stress_lapse_pv.csv"))

    def test_pv_results_columns(self, pv_results):
        assert PV_COLUMNS.issubset(set(pv_results.columns))

    def test_pv_results_row_count(self, pv_results, model_points):
        assert len(pv_results) == len(model_points)

    def test_all_point_ids_present(self, pv_results, model_points):
        expected_ids = set(model_points["point_id"])
        actual_ids = set(pv_results["point_id"])
        assert expected_ids == actual_ids

    def test_checks_has_required_keys(self, checks):
        for key in ["av_roll_forward_ok", "margin_ok", "pv_ok"]:
            assert key in checks


# ── Self-Consistency Checks ─────────────────────────────────────────────


class TestSelfConsistency:
    def test_av_roll_forward(self, checks):
        assert checks["av_roll_forward_ok"] is True, (
            "Account value roll-forward identity failed."
        )

    def test_margin_decomposition(self, checks):
        assert checks["margin_ok"] is True, (
            "Margin decomposition failed. "
            "net_cf != expense_margin + mortality_margin at some t."
        )

    def test_pv_consistency(self, checks):
        assert checks["pv_ok"] is True, (
            "PV consistency failed. "
            "pv_net_cf != sum of PV components for some model point."
        )


# ── PV Identity from Output ────────────────────────────────────────────


class TestPVIdentity:
    def test_pv_net_cf_equals_component_sum(self, pv_results):
        computed = (
            pv_results["pv_premiums"]
            + pv_results["pv_inv_income"]
            - pv_results["pv_claims_death"]
            - pv_results["pv_claims_lapse"]
            - pv_results["pv_claims_maturity"]
            - pv_results["pv_expenses"]
            - pv_results["pv_commissions"]
            - pv_results["pv_av_change"]
        )
        np.testing.assert_allclose(
            pv_results["pv_net_cf"].values,
            computed.values,
            rtol=1e-6,
            atol=1e-8,
            err_msg="PV identity does not hold from output CSV",
        )


# ── Non-Negativity and Sanity ───────────────────────────────────────────


class TestSanity:
    def test_no_nan_values(self, pv_results):
        numeric_cols = pv_results.select_dtypes(include=[np.number]).columns
        assert not pv_results[numeric_cols].isna().any().any(), (
            "Output contains NaN values"
        )

    def test_no_inf_values(self, pv_results):
        numeric_cols = pv_results.select_dtypes(include=[np.number]).columns
        assert not np.isinf(pv_results[numeric_cols].values).any(), (
            "Output contains infinite values"
        )

    def test_pv_premiums_non_negative(self, pv_results):
        assert (pv_results["pv_premiums"] >= -1e-8).all()

    def test_pv_claims_death_non_negative(self, pv_results):
        assert (pv_results["pv_claims_death"] >= -1e-8).all()

    def test_pv_claims_maturity_non_negative(self, pv_results):
        assert (pv_results["pv_claims_maturity"] >= -1e-8).all()

    def test_pv_expenses_non_negative(self, pv_results):
        assert (pv_results["pv_expenses"] >= -1e-8).all()

    def test_pv_commissions_non_negative(self, pv_results):
        assert (pv_results["pv_commissions"] >= -1e-8).all()

    def test_pv_inv_income_non_negative(self, pv_results):
        assert (pv_results["pv_inv_income"] >= -1e-8).all()

    def test_aggregate_pv_net_cf_positive(self, pv_results):
        assert pv_results["pv_net_cf"].sum() > 0


# ── Premium-Specific Checks ────────────────────────────────────────────


class TestPremiums:
    def test_single_premium_at_issue(self, pv_results, model_points, product_specs):
        for _, mp in model_points.iterrows():
            spec = product_specs.loc[mp["spec_id"]]
            if spec["premium_type"] == "SINGLE" and mp["duration_mth"] == 0:
                pv_row = pv_results[pv_results["point_id"] == mp["point_id"]]
                np.testing.assert_allclose(
                    pv_row["pv_premiums"].values[0],
                    mp["premium_pp"],
                    rtol=1e-10,
                    err_msg=f"Point {mp['point_id']}: SINGLE premium at issue "
                    f"should equal premium_pp={mp['premium_pp']}",
                )

    def test_single_premium_past_issue(self, pv_results, model_points, product_specs):
        for _, mp in model_points.iterrows():
            spec = product_specs.loc[mp["spec_id"]]
            if spec["premium_type"] == "SINGLE" and mp["duration_mth"] > 0:
                pv_row = pv_results[pv_results["point_id"] == mp["point_id"]]
                assert abs(pv_row["pv_premiums"].values[0]) < 1e-8, (
                    f"Point {mp['point_id']}: SINGLE premium with "
                    f"duration_mth={mp['duration_mth']} should have 0 PV premiums"
                )

    def test_future_new_biz_has_premiums(self, pv_results, model_points):
        for _, mp in model_points.iterrows():
            if mp["duration_mth"] < 0:
                pv_row = pv_results[pv_results["point_id"] == mp["point_id"]]
                assert pv_row["pv_premiums"].values[0] > 0, (
                    f"Point {mp['point_id']}: future NB (duration_mth="
                    f"{mp['duration_mth']}) should have positive PV premiums"
                )

    def test_level_premium_pv_positive(self, pv_results, model_points, product_specs):
        for _, mp in model_points.iterrows():
            spec = product_specs.loc[mp["spec_id"]]
            if spec["premium_type"] == "LEVEL" and mp["duration_mth"] > 0:
                pv_row = pv_results[pv_results["point_id"] == mp["point_id"]]
                assert pv_row["pv_premiums"].values[0] > 0, (
                    f"Point {mp['point_id']}: LEVEL premium with "
                    f"duration_mth={mp['duration_mth']} should have positive PV premiums"
                )


# ── Claims Checks ───────────────────────────────────────────────────────


class TestClaims:
    def test_death_claims_less_than_total(self, pv_results):
        for _, row in pv_results.iterrows():
            tc = (
                row["pv_claims_death"]
                + row["pv_claims_lapse"]
                + row["pv_claims_maturity"]
            )
            if tc > 1.0:
                assert row["pv_claims_death"] / tc < 0.20, (
                    f"Point {row['point_id']}: death claims are an unexpectedly "
                    f"large fraction of total claims"
                )

    def test_maturity_claims_non_negative(self, pv_results):
        assert (pv_results["pv_claims_maturity"] >= -1e-8).all()

    def test_all_points_have_claims(self, pv_results, model_points):
        for _, mp in model_points.iterrows():
            pv_row = pv_results[pv_results["point_id"] == mp["point_id"]]
            total_claims = (
                pv_row["pv_claims_death"].values[0]
                + pv_row["pv_claims_lapse"].values[0]
                + pv_row["pv_claims_maturity"].values[0]
            )
            if mp["duration_mth"] >= 0:
                assert total_claims > 0, (
                    f"Point {mp['point_id']}: should have positive total claims"
                )


# ── Whole-Life vs Term Checks ───────────────────────────────────────────


class TestProductTypes:
    def test_wl_has_maturity_claims(self, pv_results, model_points, product_specs):
        for _, mp in model_points.iterrows():
            spec = product_specs.loc[mp["spec_id"]]
            if str(spec.get("is_wl", "False")).lower() == "true":
                if mp["duration_mth"] >= 0:
                    pv_row = pv_results[
                        pv_results["point_id"] == mp["point_id"]
                    ]
                    assert pv_row["pv_claims_maturity"].values[0] > 0, (
                        f"Point {mp['point_id']}: WL policy should have "
                        f"maturity claims"
                    )

    def test_commissions_proportional_to_premiums(self, pv_results):
        for _, row in pv_results.iterrows():
            if row["pv_premiums"] > 1.0:
                np.testing.assert_allclose(
                    row["pv_commissions"],
                    0.05 * row["pv_premiums"],
                    rtol=1e-6,
                    err_msg=f"Point {row['point_id']}: PV commissions should "
                    f"be 5% of PV premiums",
                )


# ── SQLite Output Tests ─────────────────────────────────────────────────


class TestSQLiteOutput:
    def test_monthly_cf_table_exists(self, db_conn):
        cursor = db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='monthly_cf'"
        )
        assert cursor.fetchone() is not None, "Table monthly_cf does not exist"

    def test_monthly_cf_columns(self, db_conn):
        cursor = db_conn.execute("PRAGMA table_info(monthly_cf)")
        cols = {row[1] for row in cursor.fetchall()}
        expected = {
            "t", "point_id", "premiums", "claims_death", "claims_lapse",
            "claims_maturity", "expenses", "commissions", "inv_income",
            "net_cf", "pols_if", "av_pp",
        }
        assert expected.issubset(cols), f"Missing columns: {expected - cols}"

    def test_monthly_cf_has_data(self, db_conn):
        cursor = db_conn.execute("SELECT COUNT(*) FROM monthly_cf")
        count = cursor.fetchone()[0]
        assert count >= 1000, f"Expected >= 1000 rows, got {count}"

    def test_monthly_cf_row_count(self, db_conn, model_points):
        """All model points should appear at each timestep."""
        cursor = db_conn.execute(
            "SELECT COUNT(DISTINCT point_id) FROM monthly_cf"
        )
        n_points = cursor.fetchone()[0]
        assert n_points == len(model_points), (
            f"Expected {len(model_points)} distinct point_ids, got {n_points}"
        )

    def test_monthly_cf_all_point_ids(self, db_conn, model_points):
        cursor = db_conn.execute("SELECT DISTINCT point_id FROM monthly_cf")
        db_pids = {row[0] for row in cursor.fetchall()}
        expected_pids = set(model_points["point_id"])
        assert db_pids == expected_pids

    def test_pols_if_non_negative(self, db_conn):
        cursor = db_conn.execute(
            "SELECT MIN(pols_if) FROM monthly_cf"
        )
        min_pols = cursor.fetchone()[0]
        assert min_pols >= -1e-8, f"Negative pols_if found: {min_pols}"

    def test_av_pp_non_negative(self, db_conn):
        cursor = db_conn.execute(
            "SELECT MIN(av_pp) FROM monthly_cf"
        )
        min_av = cursor.fetchone()[0]
        assert min_av >= -1e-8, f"Negative av_pp found: {min_av}"

    def test_index_exists(self, db_conn):
        """Verify the composite index idx_monthly_cf_point_t exists."""
        cursor = db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_monthly_cf_point_t'"
        )
        assert cursor.fetchone() is not None, (
            "Index idx_monthly_cf_point_t does not exist"
        )

    def test_index_covers_correct_columns(self, db_conn):
        """Verify the index covers (point_id, t)."""
        cursor = db_conn.execute(
            "PRAGMA index_info(idx_monthly_cf_point_t)"
        )
        cols = [row[2] for row in cursor.fetchall()]
        assert "point_id" in cols, "Index must cover point_id"
        assert "t" in cols, "Index must cover t"

    def test_cumulative_cf_view_exists(self, db_conn):
        """Verify the cumulative_cf view exists."""
        cursor = db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view' "
            "AND name='cumulative_cf'"
        )
        assert cursor.fetchone() is not None, (
            "View cumulative_cf does not exist"
        )

    def test_cumulative_cf_columns(self, db_conn):
        """Verify cumulative_cf has the expected columns."""
        cursor = db_conn.execute("SELECT * FROM cumulative_cf LIMIT 1")
        col_names = {desc[0] for desc in cursor.description}
        expected = {"t", "point_id", "cum_premiums", "cum_net_cf", "cum_claims_death"}
        assert expected.issubset(col_names), (
            f"Missing columns in cumulative_cf: {expected - col_names}"
        )

    def test_cumulative_cf_running_sums_correct(self, db_conn, model_points):
        """Verify running sums in cumulative_cf are mathematically correct."""
        pid = int(model_points["point_id"].iloc[0])

        # Get raw data for this point
        cursor = db_conn.execute(
            "SELECT t, premiums, net_cf, claims_death FROM monthly_cf "
            "WHERE point_id=? ORDER BY t", (pid,)
        )
        raw = cursor.fetchall()
        assert len(raw) > 0, f"No data for point_id={pid}"

        # Compute expected cumulative values
        cum_prem = 0.0
        cum_ncf = 0.0
        cum_cd = 0.0
        expected = {}
        for t, prem, ncf, cd in raw:
            cum_prem += prem
            cum_ncf += ncf
            cum_cd += cd
            expected[t] = (cum_prem, cum_ncf, cum_cd)

        # Get cumulative view data
        cursor = db_conn.execute(
            "SELECT t, cum_premiums, cum_net_cf, cum_claims_death "
            "FROM cumulative_cf WHERE point_id=? ORDER BY t", (pid,)
        )
        view_data = cursor.fetchall()
        assert len(view_data) == len(raw), (
            "cumulative_cf row count mismatch for point"
        )

        for t, cum_p, cum_n, cum_d in view_data:
            exp_p, exp_n, exp_d = expected[t]
            np.testing.assert_allclose(
                cum_p, exp_p, rtol=1e-10,
                err_msg=f"cum_premiums wrong at t={t} for point {pid}"
            )
            np.testing.assert_allclose(
                cum_n, exp_n, rtol=1e-10,
                err_msg=f"cum_net_cf wrong at t={t} for point {pid}"
            )
            np.testing.assert_allclose(
                cum_d, exp_d, rtol=1e-10,
                err_msg=f"cum_claims_death wrong at t={t} for point {pid}"
            )

    def test_cumulative_cf_multiple_points(self, db_conn, model_points):
        """Verify cumulative sums reset across different point_ids."""
        cursor = db_conn.execute(
            "SELECT point_id, MIN(cum_premiums) as min_cp "
            "FROM cumulative_cf GROUP BY point_id"
        )
        for pid, min_cp in cursor.fetchall():
            # First cumulative value should equal first raw value
            c2 = db_conn.execute(
                "SELECT premiums FROM monthly_cf "
                "WHERE point_id=? ORDER BY t LIMIT 1", (pid,)
            )
            first_raw = c2.fetchone()[0]
            c3 = db_conn.execute(
                "SELECT cum_premiums FROM cumulative_cf "
                "WHERE point_id=? ORDER BY t LIMIT 1", (pid,)
            )
            first_cum = c3.fetchone()[0]
            np.testing.assert_allclose(
                first_cum, first_raw, rtol=1e-10,
                err_msg=f"First cumulative premium != first raw premium for point {pid}"
            )

    def test_single_premium_at_issue_sqlite(self, db_conn, model_points, product_specs):
        """SINGLE premium NB at t=0: premiums should equal premium_pp."""
        for _, mp in model_points.iterrows():
            spec = product_specs.loc[mp["spec_id"]]
            if spec["premium_type"] == "SINGLE" and mp["duration_mth"] == 0:
                cursor = db_conn.execute(
                    "SELECT premiums FROM monthly_cf WHERE t=0 AND point_id=?",
                    (int(mp["point_id"]),),
                )
                row = cursor.fetchone()
                assert row is not None, f"No row for t=0, point_id={mp['point_id']}"
                np.testing.assert_allclose(
                    row[0], mp["premium_pp"], rtol=1e-10,
                    err_msg=f"Point {mp['point_id']}: SQLite premium at t=0 mismatch",
                )

    def test_single_premium_zero_after_issue(self, db_conn, model_points, product_specs):
        """SINGLE premium: premiums at t>0 should be 0 for NB entering at t=0."""
        for _, mp in model_points.iterrows():
            spec = product_specs.loc[mp["spec_id"]]
            if spec["premium_type"] == "SINGLE" and mp["duration_mth"] == 0:
                cursor = db_conn.execute(
                    "SELECT SUM(premiums) FROM monthly_cf WHERE t>0 AND point_id=?",
                    (int(mp["point_id"]),),
                )
                total = cursor.fetchone()[0]
                assert abs(total) < 1e-8, (
                    f"Point {mp['point_id']}: SINGLE premium should be 0 after t=0"
                )

    def test_discounted_net_cf_matches_pv(self, db_conn, pv_results, disc_rate_ann):
        """Sum of discounted net_cf from SQLite should match pv_net_cf."""
        cursor = db_conn.execute(
            "SELECT t, point_id, net_cf FROM monthly_cf ORDER BY point_id, t"
        )
        rows = cursor.fetchall()
        if not rows:
            pytest.fail("No rows in monthly_cf")

        max_t = max(r[0] for r in rows) + 1
        disc_rate_mth = np.zeros(max_t)
        for t in range(max_t):
            y = t // 12
            if y < len(disc_rate_ann):
                disc_rate_mth[t] = (1 + disc_rate_ann.iloc[y]) ** (1 / 12) - 1
            else:
                disc_rate_mth[t] = (1 + disc_rate_ann.iloc[-1]) ** (1 / 12) - 1
        disc_factors = np.array(
            [(1 + disc_rate_mth[t]) ** (-t) for t in range(max_t)]
        )

        point_sums = defaultdict(float)
        for t, pid, ncf in rows:
            point_sums[pid] += ncf * disc_factors[t]

        for _, pv_row in pv_results.iterrows():
            pid = pv_row["point_id"]
            np.testing.assert_allclose(
                point_sums[pid],
                pv_row["pv_net_cf"],
                rtol=1e-4,
                err_msg=f"Point {pid}: discounted net_cf from SQLite != pv_net_cf",
            )

    def test_undiscounted_premiums_geq_pv(self, db_conn, pv_results):
        """Undiscounted premiums from SQLite >= PV premiums (discount factors <= 1)."""
        cursor = db_conn.execute(
            "SELECT point_id, SUM(premiums) FROM monthly_cf GROUP BY point_id"
        )
        sqlite_prems = {row[0]: row[1] for row in cursor.fetchall()}
        for _, pv_row in pv_results.iterrows():
            pid = pv_row["point_id"]
            if pv_row["pv_premiums"] > 1.0:
                assert sqlite_prems[pid] >= pv_row["pv_premiums"] * 0.999, (
                    f"Point {pid}: undiscounted premiums should be >= PV premiums"
                )


# ── Parquet Output Tests ────────────────────────────────────────────────


class TestParquetOutput:
    def test_parquet_schema_t_type(self, parquet_table):
        assert parquet_table.schema.field("t").type == pa.int32(), (
            f"Column 't' should be int32, got {parquet_table.schema.field('t').type}"
        )

    def test_parquet_schema_point_id_type(self, parquet_table):
        assert parquet_table.schema.field("point_id").type == pa.int32(), (
            f"Column 'point_id' should be int32, got "
            f"{parquet_table.schema.field('point_id').type}"
        )

    def test_parquet_schema_float_columns(self, parquet_table):
        float_cols = [
            "premiums", "claims_death", "claims_lapse", "claims_maturity",
            "expenses", "commissions", "inv_income", "net_cf", "pols_if", "av_pp",
        ]
        for col in float_cols:
            assert parquet_table.schema.field(col).type == pa.float64(), (
                f"Column '{col}' should be float64, got "
                f"{parquet_table.schema.field(col).type}"
            )

    def test_parquet_snappy_compression(self):
        pf = pq.ParquetFile(os.path.join(OUT_DIR, "timeseries.parquet"))
        metadata = pf.metadata
        rg_meta = metadata.row_group(0)
        for i in range(rg_meta.num_columns):
            col_meta = rg_meta.column(i)
            assert col_meta.compression == "SNAPPY", (
                f"Column {i} uses {col_meta.compression}, expected SNAPPY"
            )

    def test_parquet_has_all_columns(self, parquet_table):
        expected = {
            "t", "point_id", "premiums", "claims_death", "claims_lapse",
            "claims_maturity", "expenses", "commissions", "inv_income",
            "net_cf", "pols_if", "av_pp",
        }
        actual = set(parquet_table.schema.names)
        assert expected.issubset(actual), f"Missing columns: {expected - actual}"

    def test_parquet_row_count_matches_sqlite(self, parquet_table, db_conn):
        cursor = db_conn.execute("SELECT COUNT(*) FROM monthly_cf")
        sqlite_count = cursor.fetchone()[0]
        assert len(parquet_table) == sqlite_count, (
            f"Parquet rows ({len(parquet_table)}) != SQLite rows ({sqlite_count})"
        )

    def test_parquet_data_matches_sqlite(self, parquet_table, db_conn):
        """Spot-check: total premiums should match between Parquet and SQLite."""
        pq_total = parquet_table.column("premiums").to_pylist()
        pq_sum = sum(pq_total)

        cursor = db_conn.execute("SELECT SUM(premiums) FROM monthly_cf")
        sqlite_sum = cursor.fetchone()[0]

        np.testing.assert_allclose(
            pq_sum, sqlite_sum, rtol=1e-10,
            err_msg="Total premiums mismatch between Parquet and SQLite"
        )

    def test_parquet_net_cf_matches_sqlite(self, parquet_table, db_conn):
        """Spot-check: total net_cf should match between Parquet and SQLite."""
        pq_sum = sum(parquet_table.column("net_cf").to_pylist())
        cursor = db_conn.execute("SELECT SUM(net_cf) FROM monthly_cf")
        sqlite_sum = cursor.fetchone()[0]

        np.testing.assert_allclose(
            pq_sum, sqlite_sum, rtol=1e-10,
            err_msg="Total net_cf mismatch between Parquet and SQLite"
        )

    def test_parquet_point_ids_match_sqlite(self, parquet_table, db_conn):
        pq_pids = set(parquet_table.column("point_id").to_pylist())
        cursor = db_conn.execute("SELECT DISTINCT point_id FROM monthly_cf")
        sqlite_pids = {row[0] for row in cursor.fetchall()}
        assert pq_pids == sqlite_pids


# ── Mortality Stress Scenario Tests ─────────────────────────────────────


class TestStressMortality:
    def test_stress_mort_columns(self, stress_mort_pv):
        assert PV_COLUMNS.issubset(set(stress_mort_pv.columns))

    def test_stress_mort_row_count(self, stress_mort_pv, model_points):
        assert len(stress_mort_pv) == len(model_points)

    def test_stress_mort_same_point_ids(self, stress_mort_pv, pv_results):
        assert set(stress_mort_pv["point_id"]) == set(pv_results["point_id"])

    def test_stress_mort_pv_identity_holds(self, stress_mort_pv):
        computed = (
            stress_mort_pv["pv_premiums"]
            + stress_mort_pv["pv_inv_income"]
            - stress_mort_pv["pv_claims_death"]
            - stress_mort_pv["pv_claims_lapse"]
            - stress_mort_pv["pv_claims_maturity"]
            - stress_mort_pv["pv_expenses"]
            - stress_mort_pv["pv_commissions"]
            - stress_mort_pv["pv_av_change"]
        )
        np.testing.assert_allclose(
            stress_mort_pv["pv_net_cf"].values,
            computed.values,
            rtol=1e-6,
            atol=1e-8,
            err_msg="PV identity does not hold for mortality stress scenario",
        )

    def test_stress_mort_differs_from_base(self, stress_mort_pv, pv_results):
        """Mortality stress results must differ numerically from base."""
        base_sorted = pv_results.sort_values("point_id").reset_index(drop=True)
        stress_sorted = stress_mort_pv.sort_values("point_id").reset_index(drop=True)
        diff = (
            base_sorted["pv_net_cf"].values - stress_sorted["pv_net_cf"].values
        )
        assert np.abs(diff).sum() > 1.0, "Stress results should differ from base"

    def test_stress_mort_higher_death_claims(self, stress_mort_pv, pv_results):
        """30% mortality uplift should increase total death claims."""
        base_total = pv_results["pv_claims_death"].sum()
        stress_total = stress_mort_pv["pv_claims_death"].sum()
        assert stress_total > base_total * 1.01, (
            f"Stress death claims ({stress_total:.2f}) should exceed "
            f"base ({base_total:.2f}) by more than 1%"
        )

    def test_stress_mort_lower_net_cf(self, stress_mort_pv, pv_results):
        """Higher mortality should reduce overall profitability."""
        base_total = pv_results["pv_net_cf"].sum()
        stress_total = stress_mort_pv["pv_net_cf"].sum()
        assert stress_total < base_total, (
            f"Stress net CF ({stress_total:.2f}) should be less than "
            f"base ({base_total:.2f})"
        )

    def test_stress_mort_no_nan(self, stress_mort_pv):
        numeric_cols = stress_mort_pv.select_dtypes(include=[np.number]).columns
        assert not stress_mort_pv[numeric_cols].isna().any().any()

    def test_stress_mort_no_inf(self, stress_mort_pv):
        numeric_cols = stress_mort_pv.select_dtypes(include=[np.number]).columns
        assert not np.isinf(stress_mort_pv[numeric_cols].values).any()


# ── Lapse Stress Scenario Tests ─────────────────────────────────────────


class TestStressLapse:
    def test_stress_lapse_columns(self, stress_lapse_pv):
        assert PV_COLUMNS.issubset(set(stress_lapse_pv.columns))

    def test_stress_lapse_row_count(self, stress_lapse_pv, model_points):
        assert len(stress_lapse_pv) == len(model_points)

    def test_stress_lapse_same_point_ids(self, stress_lapse_pv, pv_results):
        assert set(stress_lapse_pv["point_id"]) == set(pv_results["point_id"])

    def test_stress_lapse_pv_identity_holds(self, stress_lapse_pv):
        computed = (
            stress_lapse_pv["pv_premiums"]
            + stress_lapse_pv["pv_inv_income"]
            - stress_lapse_pv["pv_claims_death"]
            - stress_lapse_pv["pv_claims_lapse"]
            - stress_lapse_pv["pv_claims_maturity"]
            - stress_lapse_pv["pv_expenses"]
            - stress_lapse_pv["pv_commissions"]
            - stress_lapse_pv["pv_av_change"]
        )
        np.testing.assert_allclose(
            stress_lapse_pv["pv_net_cf"].values,
            computed.values,
            rtol=1e-6,
            atol=1e-8,
            err_msg="PV identity does not hold for lapse stress scenario",
        )

    def test_stress_lapse_differs_from_base(self, stress_lapse_pv, pv_results):
        """Lapse stress results must differ numerically from base."""
        base_sorted = pv_results.sort_values("point_id").reset_index(drop=True)
        stress_sorted = stress_lapse_pv.sort_values("point_id").reset_index(drop=True)
        diff = (
            base_sorted["pv_net_cf"].values - stress_sorted["pv_net_cf"].values
        )
        assert np.abs(diff).sum() > 1.0, (
            "Lapse stress results should differ from base"
        )

    def test_stress_lapse_differs_from_mort_stress(
        self, stress_lapse_pv, stress_mort_pv
    ):
        """Lapse stress must differ from mortality stress."""
        mort_sorted = stress_mort_pv.sort_values("point_id").reset_index(drop=True)
        lapse_sorted = stress_lapse_pv.sort_values("point_id").reset_index(drop=True)
        diff = (
            mort_sorted["pv_net_cf"].values - lapse_sorted["pv_net_cf"].values
        )
        assert np.abs(diff).sum() > 1.0, (
            "Lapse stress and mortality stress should produce different results"
        )

    def test_stress_lapse_lower_death_claims(self, stress_lapse_pv, pv_results):
        """Higher lapses should reduce policies in-force, hence lower death claims."""
        base_total = pv_results["pv_claims_death"].sum()
        stress_total = stress_lapse_pv["pv_claims_death"].sum()
        assert stress_total < base_total * 0.999, (
            f"Lapse stress death claims ({stress_total:.2f}) should be less than "
            f"base ({base_total:.2f}) — fewer policies in-force means fewer deaths"
        )

    def test_stress_lapse_no_nan(self, stress_lapse_pv):
        numeric_cols = stress_lapse_pv.select_dtypes(include=[np.number]).columns
        assert not stress_lapse_pv[numeric_cols].isna().any().any()

    def test_stress_lapse_no_inf(self, stress_lapse_pv):
        numeric_cols = stress_lapse_pv.select_dtypes(include=[np.number]).columns
        assert not np.isinf(stress_lapse_pv[numeric_cols].values).any()
