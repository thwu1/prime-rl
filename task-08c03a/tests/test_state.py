
"""Tests verifying the partition reconciliation pipeline is correctly fixed
and the cost-optimal source assignment optimizer is correctly implemented."""

import subprocess
import sys
import sqlite3
import pytest

sys.path.insert(0, "/app")


# ---------------------------------------------------------------------------
# Validation script
# ---------------------------------------------------------------------------


class TestValidation:
    """The validation script must pass all checks."""

    def test_validate_exits_zero(self):
        result = subprocess.run(
            ["python3", "/app/validate.py"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"validate.py failed (exit {result.returncode}):\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )

    def test_validate_reports_all_passed(self):
        result = subprocess.run(
            ["python3", "/app/validate.py"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert "ALL CHECKS PASSED" in result.stdout


# ---------------------------------------------------------------------------
# YAML configuration
# ---------------------------------------------------------------------------


class TestYAMLConfig:
    """YAML configuration must load with correct types."""

    def test_all_instruments_are_strings(self):
        import yaml

        with open("/app/pipeline.yaml") as f:
            config = yaml.safe_load(f)
        for src, cfg in config["sources"].items():
            for inst in cfg["instruments"]:
                assert isinstance(inst, str), (
                    f"Source '{src}': instrument {inst!r} has type "
                    f"{type(inst).__name__}, expected str"
                )

    def test_all_dates_are_strings(self):
        import yaml

        with open("/app/pipeline.yaml") as f:
            config = yaml.safe_load(f)
        for src, cfg in config["sources"].items():
            for d in cfg["available_dates"]:
                assert isinstance(d, str), (
                    f"Source '{src}': date {d!r} has type "
                    f"{type(d).__name__}, expected str"
                )

    def test_delta_has_instrument_0050(self):
        import yaml

        with open("/app/pipeline.yaml") as f:
            config = yaml.safe_load(f)
        instruments = config["sources"]["delta"]["instruments"]
        assert "0050" in instruments, (
            f"delta instruments should contain '0050', got {instruments}"
        )

    def test_five_sources_present(self):
        import yaml

        with open("/app/pipeline.yaml") as f:
            config = yaml.safe_load(f)
        assert set(config["sources"].keys()) == {
            "alpha",
            "beta",
            "gamma",
            "delta",
            "epsilon",
        }


# ---------------------------------------------------------------------------
# Database integrity
# ---------------------------------------------------------------------------


class TestDatabase:
    """SQLite database must have clean data."""

    def test_no_trailing_whitespace_in_instruments(self):
        conn = sqlite3.connect("/app/partitions.db")
        cur = conn.execute(
            "SELECT source_name, instrument FROM source_instruments "
            "WHERE instrument != TRIM(instrument)"
        )
        dirty = cur.fetchall()
        conn.close()
        assert dirty == [], f"Instruments with trailing whitespace: {dirty}"

    def test_instrument_counts_per_source(self):
        conn = sqlite3.connect("/app/partitions.db")
        cur = conn.execute(
            "SELECT source_name, COUNT(DISTINCT TRIM(instrument)) "
            "FROM source_instruments GROUP BY source_name ORDER BY source_name"
        )
        counts = {row[0]: row[1] for row in cur.fetchall()}
        conn.close()
        assert counts == {
            "alpha": 3,
            "beta": 3,
            "gamma": 3,
            "delta": 3,
            "epsilon": 3,
        }


# ---------------------------------------------------------------------------
# Reconciliation correctness
# ---------------------------------------------------------------------------


class TestReconciliation:
    """Reconciliation must produce correct results."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        from pipeline.loader import get_sources_config
        from pipeline.reconciler import PartitionReconciler

        self.config = get_sources_config()
        self.reconciler = PartitionReconciler(self.config)
        self.plan = self.reconciler.reconcile()

    def test_nine_materializable_dates(self):
        expected = {f"2024-01-0{i}" for i in range(1, 10)}
        assert self.plan.materializable == expected

    def test_delta_in_coverage_for_its_dates(self):
        for d in [
            "2024-01-02",
            "2024-01-03",
            "2024-01-04",
            "2024-01-05",
            "2024-01-06",
        ]:
            assert "delta" in self.plan.source_coverage[d], (
                f"delta missing from coverage on {d}"
            )

    def test_epsilon_in_coverage_for_its_dates(self):
        for d in [
            "2024-01-05",
            "2024-01-06",
            "2024-01-07",
            "2024-01-08",
            "2024-01-09",
        ]:
            assert "epsilon" in self.plan.source_coverage[d]

    def test_tiebreak_alpha_over_epsilon_for_msft(self):
        """alpha(1) and epsilon(1) both have MSFT on 2024-01-05.
        Alphabetical tiebreak should select alpha."""
        ism = self.plan.instrument_source_map["2024-01-05"]
        assert ism["MSFT"] == "alpha", f"Expected alpha, got {ism['MSFT']}"

    def test_epsilon_wins_msft_on_01_06(self):
        """epsilon(1) vs beta(2) for MSFT on 2024-01-06."""
        ism = self.plan.instrument_source_map["2024-01-06"]
        assert ism["MSFT"] == "epsilon"

    def test_delta_instrument_0050(self):
        """0050 should be assigned to delta on its available dates."""
        for d in [
            "2024-01-02",
            "2024-01-03",
            "2024-01-04",
            "2024-01-05",
            "2024-01-06",
        ]:
            ism = self.plan.instrument_source_map[d]
            assert "0050" in ism, f"'0050' not in instrument map for {d}"
            assert ism["0050"] == "delta"

    def test_coverage_date_01_05(self):
        assert self.plan.source_coverage["2024-01-05"] == {
            "alpha",
            "beta",
            "delta",
            "epsilon",
        }

    def test_coverage_date_01_01(self):
        assert self.plan.source_coverage["2024-01-01"] == {"alpha", "gamma"}


# ---------------------------------------------------------------------------
# Backfill plan
# ---------------------------------------------------------------------------


class TestBackfillPlan:
    """Backfill execution plan must be correct."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        from pipeline.loader import get_sources_config, get_backfill_config
        from pipeline.reconciler import PartitionReconciler
        from pipeline.planner import AssetNode, build_execution_plan

        config = get_sources_config()
        reconciler = PartitionReconciler(config)
        plan = reconciler.reconcile()
        all_dates = sorted(plan.materializable)

        backfill = get_backfill_config()
        nodes = {}
        for name, adef in backfill["assets"].items():
            nodes[name] = AssetNode(
                key=name,
                partition_keys=all_dates,
                dependencies=adef.get("dependencies", []),
                sequential=adef.get("sequential", False),
            )
        self.waves = build_execution_plan(
            nodes, concurrency_limit=backfill["concurrency_limit"]
        )
        self.all_steps = [s for w in self.waves for s in w]

    def test_total_step_count(self):
        assert len(self.all_steps) == 27  # 9 dates * 3 assets

    def test_raw_before_enriched(self):
        raw_max = max(
            i for i, s in enumerate(self.all_steps) if s.asset_key == "raw_prices"
        )
        enriched_min = min(
            i
            for i, s in enumerate(self.all_steps)
            if s.asset_key == "enriched_prices"
        )
        assert raw_max < enriched_min

    def test_enriched_before_analytics(self):
        enriched_max = max(
            i
            for i, s in enumerate(self.all_steps)
            if s.asset_key == "enriched_prices"
        )
        analytics_min = min(
            i for i, s in enumerate(self.all_steps) if s.asset_key == "analytics"
        )
        assert enriched_max < analytics_min

    def test_raw_prices_sequential_order(self):
        raw_steps = [s for s in self.all_steps if s.asset_key == "raw_prices"]
        dates = [s.partition_key for s in raw_steps]
        assert dates == sorted(dates)

    def test_wave_concurrency_limit(self):
        for wave in self.waves:
            assert len(wave) <= 3


# ---------------------------------------------------------------------------
# Cost-optimal source assignment (optimizer)
# ---------------------------------------------------------------------------


class TestOptimizer:
    """Cost-optimal source assignment must be correct."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        from pipeline.loader import get_sources_config, get_cost_config
        from pipeline.optimizer import SourceOptimizer

        self.config = get_sources_config()
        self.cost_config = get_cost_config()
        self.optimizer = SourceOptimizer(self.config, self.cost_config)
        self.result = self.optimizer.optimize_all()

    def test_all_nine_dates_assigned(self):
        expected = {f"2024-01-0{i}" for i in range(1, 10)}
        assert set(self.result.keys()) == expected

    def test_all_instruments_covered_per_date(self):
        """Every instrument available from any source on each date must appear."""
        for date_str, da in self.result.items():
            expected_insts = set()
            for src, cfg in self.config.items():
                if date_str in cfg["available_dates"]:
                    expected_insts.update(cfg["instruments"])
            assert set(da.mapping.keys()) == expected_insts, (
                f"Date {date_str}: got {sorted(da.mapping.keys())}, "
                f"expected {sorted(expected_insts)}"
            )

    def test_each_instrument_assigned_to_valid_source(self):
        """Each instrument must be assigned to a source that actually
        provides it and is available on that date."""
        for date_str, da in self.result.items():
            for inst, src in da.mapping.items():
                cfg = self.config[src]
                assert date_str in cfg["available_dates"], (
                    f"{date_str}: source {src} not available"
                )
                assert inst in cfg["instruments"], (
                    f"{date_str}: source {src} doesn't have {inst}"
                )

    def test_affinity_constraint_aapl_msft(self):
        """AAPL and MSFT must be assigned to the same source on every date
        where both are available."""
        for date_str, da in self.result.items():
            if "AAPL" in da.mapping and "MSFT" in da.mapping:
                assert da.mapping["AAPL"] == da.mapping["MSFT"], (
                    f"Date {date_str}: affinity violated — AAPL→{da.mapping['AAPL']}, "
                    f"MSFT→{da.mapping['MSFT']}"
                )

    def test_affinity_binding_on_01_03(self):
        """On 2024-01-03, the affinity constraint forces both AAPL and MSFT
        to beta (pair cost 2.6) rather than the individually cheaper
        AAPL→alpha(1.5), MSFT→beta(0.8)."""
        da = self.result["2024-01-03"]
        assert da.mapping["AAPL"] == "beta", (
            f"Expected AAPL→beta, got {da.mapping['AAPL']}"
        )
        assert da.mapping["MSFT"] == "beta", (
            f"Expected MSFT→beta, got {da.mapping['MSFT']}"
        )

    def test_affinity_binding_on_01_05(self):
        """On 2024-01-05, beta(2.6) is cheaper than alpha(3.5) for the
        AAPL+MSFT pair despite epsilon(1.1) being available for MSFT alone."""
        da = self.result["2024-01-05"]
        assert da.mapping["AAPL"] == "beta"
        assert da.mapping["MSFT"] == "beta"

    def test_affinity_trivial_on_01_01(self):
        """On 2024-01-01 only alpha has both AAPL and MSFT,
        so the constraint is satisfied but not binding."""
        da = self.result["2024-01-01"]
        assert da.mapping["AAPL"] == "alpha"
        assert da.mapping["MSFT"] == "alpha"

    def test_affinity_trivial_on_01_08(self):
        """On 2024-01-08 AAPL is not available; only MSFT is present,
        so no affinity constraint applies. MSFT goes to cheapest: epsilon."""
        da = self.result["2024-01-08"]
        assert "AAPL" not in da.mapping
        assert da.mapping["MSFT"] == "epsilon"

    def test_cheapest_non_affinity_selections(self):
        """Non-affinity instruments should go to cheapest source."""
        # 01-01: GOOGL→gamma(0.7) cheaper than alpha(1.0)
        assert self.result["2024-01-01"].mapping["GOOGL"] == "gamma"
        # 01-05: TSLA→epsilon(0.4) cheaper than beta(1.5)
        assert self.result["2024-01-05"].mapping["TSLA"] == "epsilon"
        # 01-06: AMZN→gamma(0.6) cheaper than delta(1.0)
        assert self.result["2024-01-06"].mapping["AMZN"] == "gamma"
        # 01-05: NFLX→delta(0.8) cheaper than epsilon(1.3)
        assert self.result["2024-01-05"].mapping["NFLX"] == "delta"

    def test_per_date_costs(self):
        """Verify the computed cost for each date."""
        expected_costs = {
            "2024-01-01": 6.0,
            "2024-01-02": 8.8,
            "2024-01-03": 8.9,
            "2024-01-04": 8.9,
            "2024-01-05": 7.8,
            "2024-01-06": 7.1,
            "2024-01-07": 5.6,
            "2024-01-08": 4.1,
            "2024-01-09": 2.8,
        }
        for date_str, expected_cost in expected_costs.items():
            actual = self.result[date_str].cost
            assert abs(actual - expected_cost) < 0.01, (
                f"Date {date_str}: cost {actual} != expected {expected_cost}"
            )

    def test_total_cost(self):
        total = self.optimizer.total_cost()
        assert abs(total - 60.0) < 0.01, f"Total cost {total} != 60.0"

    def test_date_01_06_full_assignment(self):
        """Full assignment for 01-06 (beta, gamma, delta, epsilon available)."""
        da = self.result["2024-01-06"]
        expected = {
            "AAPL": "beta",
            "GOOGL": "gamma",
            "MSFT": "beta",
            "TSLA": "epsilon",
            "AMZN": "gamma",
            "NFLX": "delta",
            "0050": "delta",
        }
        assert da.mapping == expected, (
            f"01-06 assignment mismatch: {da.mapping} != {expected}"
        )

    def test_date_01_09_single_source(self):
        """On 01-09, only epsilon is available."""
        da = self.result["2024-01-09"]
        expected = {"MSFT": "epsilon", "TSLA": "epsilon", "NFLX": "epsilon"}
        assert da.mapping == expected

    def test_date_01_02_full_assignment(self):
        """Full assignment for 01-02 (alpha, gamma, delta)."""
        da = self.result["2024-01-02"]
        expected = {
            "AAPL": "alpha",
            "GOOGL": "gamma",
            "MSFT": "alpha",
            "TSLA": "gamma",
            "AMZN": "gamma",
            "NFLX": "delta",
            "0050": "delta",
        }
        assert da.mapping == expected
