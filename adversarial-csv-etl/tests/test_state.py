"""Tests for the financial analytics pipeline outputs."""

import json
import math
import os

import duckdb
import pytest

OUTPUT = "/app/output"
DB = "/app/warehouse.duckdb"


@pytest.fixture(scope="module")
def con():
    c = duckdb.connect()
    c.execute(f"ATTACH '{DB}' AS wh (READ_ONLY)")
    yield c
    c.close()


# ==================================================================
# Output 1: Rapid Transaction Chains
# ==================================================================
class TestRapidChains:
    P = f"{OUTPUT}/rapid_chains.parquet"

    def test_file_exists(self):
        assert os.path.exists(self.P), "rapid_chains.parquet not found"

    def test_columns(self, con):
        cols = set(
            r[0] for r in con.execute(f"DESCRIBE SELECT * FROM '{self.P}'").fetchall()
        )
        required = {
            "chain_id", "origin_account", "terminal_account",
            "hop_count", "total_amount", "chain_start", "chain_end",
        }
        assert required.issubset(cols), f"Missing columns: {required - cols}"

    def test_min_hop_count(self, con):
        v = con.execute(f"SELECT MIN(hop_count) FROM '{self.P}'").fetchone()[0]
        assert v >= 3, f"All chains must have >= 3 hops, min is {v}"

    def test_positive_amounts(self, con):
        n = con.execute(
            f"SELECT COUNT(*) FROM '{self.P}' WHERE total_amount <= 0"
        ).fetchone()[0]
        assert n == 0, "All chain amounts must be positive"

    def test_chain_end_after_start(self, con):
        n = con.execute(
            f"SELECT COUNT(*) FROM '{self.P}' WHERE chain_end <= chain_start"
        ).fetchone()[0]
        assert n == 0, "chain_end must be strictly after chain_start"

    def test_chain_duration_consistent(self, con):
        """Chain duration should not exceed 60 * hop_count minutes."""
        n = con.execute(f"""
            SELECT COUNT(*) FROM '{self.P}'
            WHERE EXTRACT(EPOCH FROM (chain_end - chain_start)) / 60.0
                  > hop_count * 60
        """).fetchone()[0]
        assert n == 0, "Chain duration exceeds hop_count * 60 minutes"

    def test_chain_count_range(self, con):
        cnt = con.execute(f"SELECT COUNT(*) FROM '{self.P}'").fetchone()[0]
        assert 28 <= cnt <= 45, f"Expected ~30 chains (30 injected), got {cnt}"

    def test_unique_chain_ids(self, con):
        total = con.execute(f"SELECT COUNT(*) FROM '{self.P}'").fetchone()[0]
        distinct = con.execute(
            f"SELECT COUNT(DISTINCT chain_id) FROM '{self.P}'"
        ).fetchone()[0]
        assert total == distinct, "chain_id values must be unique"

    def test_injected_origins_found(self, con):
        """At least 28 of 30 injected chain origins should appear."""
        origins = set(
            r[0] for r in con.execute(
                f"SELECT DISTINCT origin_account FROM '{self.P}'"
            ).fetchall()
        )
        injected = set(range(4001, 4121, 4))
        found = origins & injected
        assert len(found) >= 28, (
            f"Expected >= 28 injected origins, found {len(found)}"
        )

    def test_injected_terminals_found(self, con):
        """Injected chain terminals should be present."""
        terms = set(
            r[0] for r in con.execute(
                f"SELECT DISTINCT terminal_account FROM '{self.P}'"
            ).fetchall()
        )
        injected = set(range(4004, 4121, 4))
        found = terms & injected
        assert len(found) >= 28, (
            f"Expected >= 28 injected terminals, found {len(found)}"
        )

    def test_injected_chain_amounts(self, con):
        """Each injected 3-hop chain should have total_amount = 60000."""
        injected_origins = list(range(4001, 4121, 4))
        rows = con.execute(f"""
            SELECT origin_account, total_amount, hop_count
            FROM '{self.P}'
            WHERE origin_account IN ({','.join(str(x) for x in injected_origins)})
        """).fetchall()
        for row in rows:
            if row[2] == 3:
                assert abs(row[1] - 60000.0) < 0.01, (
                    f"Injected chain from {row[0]}: expected 60000, got {row[1]}"
                )

    def test_accounts_exist_in_db(self, con):
        n = con.execute(f"""
            SELECT COUNT(*) FROM '{self.P}' c
            WHERE c.origin_account NOT IN (
                SELECT account_id FROM wh.accounts
            )
        """).fetchone()[0]
        assert n == 0, "All origin_account values must exist in accounts table"


# ==================================================================
# Output 2: Portfolio Values
# ==================================================================
class TestPortfolioValues:
    P = f"{OUTPUT}/portfolio_values.parquet"

    def test_file_exists(self):
        assert os.path.exists(self.P), "portfolio_values.parquet not found"

    def test_columns(self, con):
        cols = set(
            r[0] for r in con.execute(f"DESCRIBE SELECT * FROM '{self.P}'").fetchall()
        )
        required = {"account_id", "trade_date", "portfolio_value", "num_positions"}
        assert required.issubset(cols), f"Missing columns: {required - cols}"

    def test_portfolio_value_positive(self, con):
        n = con.execute(
            f"SELECT COUNT(*) FROM '{self.P}' WHERE portfolio_value <= 0"
        ).fetchone()[0]
        assert n == 0, "All portfolio values must be positive"

    def test_num_positions_positive(self, con):
        n = con.execute(
            f"SELECT COUNT(*) FROM '{self.P}' WHERE num_positions <= 0"
        ).fetchone()[0]
        assert n == 0, "All num_positions must be positive"

    def test_row_count_range(self, con):
        cnt = con.execute(f"SELECT COUNT(*) FROM '{self.P}'").fetchone()[0]
        assert cnt > 100000, f"Expected > 100K portfolio rows, got {cnt}"

    def test_accounts_are_holders(self, con):
        """Only accounts with holdings should appear."""
        n = con.execute(f"""
            SELECT COUNT(DISTINCT p.account_id)
            FROM '{self.P}' p
            WHERE p.account_id NOT IN (
                SELECT DISTINCT account_id FROM wh.holdings
            )
        """).fetchone()[0]
        assert n == 0, "Only accounts with holdings should have valuations"

    def test_distinct_accounts_range(self, con):
        cnt = con.execute(
            f"SELECT COUNT(DISTINCT account_id) FROM '{self.P}'"
        ).fetchone()[0]
        assert cnt >= 1800, f"Expected >= 1800 valued accounts, got {cnt}"

    def test_trade_dates_in_market_range(self, con):
        """All trade dates must come from market_data."""
        n = con.execute(f"""
            SELECT COUNT(*) FROM '{self.P}' p
            WHERE p.trade_date NOT IN (
                SELECT DISTINCT price_date FROM wh.market_data
            )
        """).fetchone()[0]
        assert n == 0, "Trade dates must come from market_data"

    def test_num_positions_matches_holdings(self, con):
        """num_positions should equal the account's total distinct symbols held."""
        mismatches = con.execute(f"""
            WITH expected AS (
                SELECT account_id, COUNT(*) AS n FROM wh.holdings
                GROUP BY account_id
            )
            SELECT COUNT(*) FROM '{self.P}' p
            JOIN expected e ON p.account_id = e.account_id
            WHERE p.num_positions != e.n
        """).fetchone()[0]
        assert mismatches == 0, (
            f"num_positions should match holdings count, {mismatches} mismatches"
        )

    def test_no_duplicate_account_date(self, con):
        total = con.execute(f"SELECT COUNT(*) FROM '{self.P}'").fetchone()[0]
        distinct = con.execute(f"""
            SELECT COUNT(*) FROM (
                SELECT DISTINCT account_id, trade_date FROM '{self.P}'
            )
        """).fetchone()[0]
        assert total == distinct, "Duplicate (account_id, trade_date) pairs found"


# ==================================================================
# Output 3: Risk Scores
# ==================================================================
class TestRiskScores:
    P = f"{OUTPUT}/risk_scores.parquet"

    def test_file_exists(self):
        assert os.path.exists(self.P), "risk_scores.parquet not found"

    def test_columns(self, con):
        cols = set(
            r[0] for r in con.execute(f"DESCRIBE SELECT * FROM '{self.P}'").fetchall()
        )
        required = {
            "account_id", "velocity", "variability",
            "concentration", "composite_score",
        }
        assert required.issubset(cols), f"Missing columns: {required - cols}"

    def test_velocity_positive(self, con):
        n = con.execute(
            f"SELECT COUNT(*) FROM '{self.P}' WHERE velocity <= 0"
        ).fetchone()[0]
        assert n == 0, "velocity must be positive"

    def test_variability_nonneg(self, con):
        n = con.execute(
            f"SELECT COUNT(*) FROM '{self.P}' WHERE variability < 0"
        ).fetchone()[0]
        assert n == 0, "variability must be non-negative"

    def test_concentration_range(self, con):
        lo = con.execute(f"SELECT MIN(concentration) FROM '{self.P}'").fetchone()[0]
        hi = con.execute(f"SELECT MAX(concentration) FROM '{self.P}'").fetchone()[0]
        assert lo > 0, f"concentration must be positive, min={lo}"
        assert hi <= 1.0 + 1e-9, f"concentration must be <= 1, max={hi}"

    def test_row_count_range(self, con):
        cnt = con.execute(f"SELECT COUNT(*) FROM '{self.P}'").fetchone()[0]
        assert 3500 <= cnt <= 4200, (
            f"Expected 3500-4200 scored accounts, got {cnt}"
        )

    def test_accounts_qualified(self, con):
        """All scored accounts should have >= 10 completed txns."""
        low_txn = con.execute(f"""
            WITH all_txns AS (
                SELECT from_account AS aid FROM wh.transactions
                WHERE status = 'completed'
                UNION ALL
                SELECT to_account FROM wh.transactions
                WHERE status = 'completed'
            ),
            counts AS (
                SELECT aid, COUNT(*) AS cnt FROM all_txns GROUP BY aid
            )
            SELECT COUNT(*) FROM '{self.P}' r
            LEFT JOIN counts c ON r.account_id = c.aid
            WHERE c.cnt IS NULL OR c.cnt < 10
        """).fetchone()[0]
        assert low_txn == 0, "All scored accounts must have >= 10 completed txns"

    def test_zscore_mean_near_zero(self, con):
        """Composite score should have mean near 0 (z-score property)."""
        avg = con.execute(
            f"SELECT AVG(composite_score) FROM '{self.P}'"
        ).fetchone()[0]
        assert abs(avg) < 0.1, f"Mean composite_score should be ~0, got {avg}"

    def test_unique_accounts(self, con):
        total = con.execute(f"SELECT COUNT(*) FROM '{self.P}'").fetchone()[0]
        distinct = con.execute(
            f"SELECT COUNT(DISTINCT account_id) FROM '{self.P}'"
        ).fetchone()[0]
        assert total == distinct, "Duplicate account_id in risk_scores"

    def test_score_spread(self, con):
        """Scores should have meaningful spread (stddev > 0.5)."""
        sd = con.execute(
            f"SELECT STDDEV(composite_score) FROM '{self.P}'"
        ).fetchone()[0]
        assert sd > 0.5, f"composite_score stddev too low: {sd}"


# ==================================================================
# Output 4: Regional Flows
# ==================================================================
class TestRegionalFlows:
    P = f"{OUTPUT}/regional_flows.parquet"

    def test_file_exists(self):
        assert os.path.exists(self.P), "regional_flows.parquet not found"

    def test_columns(self, con):
        cols = set(
            r[0] for r in con.execute(f"DESCRIBE SELECT * FROM '{self.P}'").fetchall()
        )
        required = {
            "source_region", "dest_region", "total_flow",
            "txn_count", "avg_amount", "net_flow", "hhi",
        }
        assert required.issubset(cols), f"Missing columns: {required - cols}"

    def test_row_count(self, con):
        cnt = con.execute(f"SELECT COUNT(*) FROM '{self.P}'").fetchone()[0]
        assert cnt == 25, f"Expected 25 region pairs (5x5), got {cnt}"

    def test_all_region_pairs(self, con):
        pairs = con.execute(f"""
            SELECT DISTINCT source_region, dest_region FROM '{self.P}'
        """).fetchall()
        regions = {"North", "South", "East", "West", "Central"}
        expected = {(s, d) for s in regions for d in regions}
        actual = {(r[0], r[1]) for r in pairs}
        assert expected == actual, f"Missing region pairs: {expected - actual}"

    def test_total_flow_positive(self, con):
        n = con.execute(
            f"SELECT COUNT(*) FROM '{self.P}' WHERE total_flow <= 0"
        ).fetchone()[0]
        assert n == 0, "All corridors must have positive total_flow"

    def test_net_flow_zero_for_self(self, con):
        n = con.execute(f"""
            SELECT COUNT(*) FROM '{self.P}'
            WHERE source_region = dest_region AND ABS(net_flow) > 0.01
        """).fetchone()[0]
        assert n == 0, "Self-pair net_flow must be 0"

    def test_net_flow_antisymmetry(self, con):
        """net_flow(A,B) + net_flow(B,A) should be ~0 for A != B."""
        pairs = con.execute(f"""
            SELECT r1.source_region, r1.dest_region,
                   r1.net_flow, r2.net_flow AS rev
            FROM '{self.P}' r1
            JOIN '{self.P}' r2
                ON r1.source_region = r2.dest_region
                AND r1.dest_region = r2.source_region
            WHERE r1.source_region < r1.dest_region
        """).fetchall()
        for row in pairs:
            total = abs(row[2] + row[3])
            assert total < 0.01, (
                f"net_flow({row[0]},{row[1]}) + net_flow({row[1]},{row[0]}) "
                f"= {total}, should be ~0"
            )

    def test_hhi_range(self, con):
        lo = con.execute(f"SELECT MIN(hhi) FROM '{self.P}'").fetchone()[0]
        hi = con.execute(f"SELECT MAX(hhi) FROM '{self.P}'").fetchone()[0]
        assert lo > 0, f"HHI must be positive, min={lo}"
        assert hi <= 1.0 + 1e-9, f"HHI must be <= 1, max={hi}"

    def test_avg_amount_consistency(self, con):
        """avg_amount should equal total_flow / txn_count."""
        n = con.execute(f"""
            SELECT COUNT(*) FROM '{self.P}'
            WHERE ABS(avg_amount - total_flow / txn_count) > 0.01
        """).fetchone()[0]
        assert n == 0, "avg_amount must equal total_flow / txn_count"

    def test_total_flow_sum_matches_txns(self, con):
        """Sum of all corridor flows should match total completed txn amounts."""
        corridor_sum = con.execute(
            f"SELECT SUM(total_flow) FROM '{self.P}'"
        ).fetchone()[0]
        txn_sum = con.execute(
            "SELECT SUM(amount) FROM wh.transactions WHERE status = 'completed'"
        ).fetchone()[0]
        pct_diff = abs(corridor_sum - txn_sum) / txn_sum
        assert pct_diff < 0.01, (
            f"Corridor flow sum {corridor_sum:.2f} doesn't match "
            f"transaction sum {txn_sum:.2f}"
        )


# ==================================================================
# Output 5: Summary JSON
# ==================================================================
class TestSummaryJson:
    P = f"{OUTPUT}/summary.json"

    def test_file_exists(self):
        assert os.path.exists(self.P), "summary.json not found"

    def test_valid_json(self):
        with open(self.P) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_required_keys(self):
        with open(self.P) as f:
            data = json.load(f)
        required = {
            "total_chains", "longest_chain_hops",
            "total_accounts_valued", "highest_risk_account_id",
            "top_flow_corridor",
        }
        assert required.issubset(set(data.keys())), (
            f"Missing keys: {required - set(data.keys())}"
        )

    def test_total_chains_matches_parquet(self, con):
        with open(self.P) as f:
            data = json.load(f)
        actual = con.execute(
            f"SELECT COUNT(*) FROM '{OUTPUT}/rapid_chains.parquet'"
        ).fetchone()[0]
        assert data["total_chains"] == actual, (
            f"total_chains {data['total_chains']} != parquet count {actual}"
        )

    def test_longest_chain_hops(self):
        with open(self.P) as f:
            data = json.load(f)
        assert data["longest_chain_hops"] >= 3

    def test_total_accounts_valued_matches(self, con):
        with open(self.P) as f:
            data = json.load(f)
        actual = con.execute(
            f"SELECT COUNT(DISTINCT account_id) "
            f"FROM '{OUTPUT}/portfolio_values.parquet'"
        ).fetchone()[0]
        assert data["total_accounts_valued"] == actual

    def test_highest_risk_account_exists(self, con):
        with open(self.P) as f:
            data = json.load(f)
        aid = data["highest_risk_account_id"]
        exists = con.execute(
            f"SELECT COUNT(*) FROM '{OUTPUT}/risk_scores.parquet' "
            f"WHERE account_id = {aid}"
        ).fetchone()[0]
        assert exists == 1, f"highest_risk_account_id {aid} not in risk_scores"

    def test_top_corridor_structure(self):
        with open(self.P) as f:
            data = json.load(f)
        corr = data["top_flow_corridor"]
        assert "source" in corr and "dest" in corr and "volume" in corr
        assert corr["source"] != corr["dest"], "Top corridor should not be self-pair"
        assert corr["volume"] > 0

    def test_top_corridor_is_max(self, con):
        with open(self.P) as f:
            data = json.load(f)
        max_flow = con.execute(f"""
            SELECT MAX(total_flow) FROM '{OUTPUT}/regional_flows.parquet'
            WHERE source_region != dest_region
        """).fetchone()[0]
        assert abs(data["top_flow_corridor"]["volume"] - max_flow) < 1.0, (
            f"top_flow_corridor volume {data['top_flow_corridor']['volume']} "
            f"!= max non-self flow {max_flow}"
        )
