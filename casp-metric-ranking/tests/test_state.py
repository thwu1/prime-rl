
import csv
import json
import math
import os
import sqlite3
import pytest


RESULTS_DIR = "/app/results"


class TestOutputFilesExist:
    def test_group_rankings_exists(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "group_rankings.csv")), \
            "group_rankings.csv not found"

    def test_metric_correlations_exists(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "metric_correlations.csv")), \
            "metric_correlations.csv not found"

    def test_discriminating_domains_exists(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "discriminating_domains.csv")), \
            "discriminating_domains.csv not found"

    def test_summary_json_exists(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "summary.json")), \
            "summary.json not found"

    def test_sqlite_db_exists(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "casp16_analysis.db")), \
            "casp16_analysis.db not found"


def load_csv(filename):
    path = os.path.join(RESULTS_DIR, filename)
    with open(path) as f:
        reader = csv.DictReader(f)
        return list(reader)


def load_json(filename):
    path = os.path.join(RESULTS_DIR, filename)
    with open(path) as f:
        return json.load(f)


class TestSQLiteDatabase:
    @pytest.fixture(autouse=True)
    def setup(self):
        db_path = os.path.join(RESULTS_DIR, "casp16_analysis.db")
        self.conn = sqlite3.connect(db_path)
        self.cursor = self.conn.cursor()
        yield
        self.conn.close()

    def test_first_models_row_count(self):
        self.cursor.execute("SELECT count(*) FROM first_models")
        count = self.cursor.fetchone()[0]
        assert count == 10159, \
            f"Expected 10159 first model rows, got {count}"

    def test_first_models_schema(self):
        self.cursor.execute("PRAGMA table_info(first_models)")
        cols = {row[1] for row in self.cursor.fetchall()}
        expected = {"target", "group_id", "domain", "GDT_TS", "LDDT",
                    "TMscore", "CAD_AA", "GDT_HA"}
        missing = expected - cols
        assert not missing, f"Missing columns in first_models: {missing}"

    def test_first_models_distinct_domains(self):
        self.cursor.execute(
            "SELECT count(DISTINCT target || '-' || domain) FROM first_models")
        count = self.cursor.fetchone()[0]
        assert count == 154, \
            f"Expected 154 distinct target-domain combinations, got {count}"

    def test_first_models_distinct_groups(self):
        self.cursor.execute("SELECT count(DISTINCT group_id) FROM first_models")
        count = self.cursor.fetchone()[0]
        assert count == 111, \
            f"Expected 111 distinct groups in first_models, got {count}"

    def test_group_rankings_total_rows(self):
        self.cursor.execute("SELECT count(*) FROM group_rankings")
        count = self.cursor.fetchone()[0]
        assert count == 555, \
            f"Expected 555 rows (111 groups x 5 metrics), got {count}"

    def test_group_rankings_schema(self):
        self.cursor.execute("PRAGMA table_info(group_rankings)")
        cols = {row[1] for row in self.cursor.fetchall()}
        expected = {"group_id", "n_domains", "metric", "sum_zscore",
                    "avg_zscore", "rank"}
        missing = expected - cols
        assert not missing, f"Missing columns in group_rankings: {missing}"

    def test_group_rankings_metrics(self):
        self.cursor.execute(
            "SELECT DISTINCT metric FROM group_rankings ORDER BY metric")
        metrics = [row[0] for row in self.cursor.fetchall()]
        assert len(metrics) == 5, f"Expected 5 metrics, got {len(metrics)}"
        assert set(metrics) == {"GDT_TS", "LDDT", "TMscore", "CAD_AA", "GDT_HA"}

    def test_gdt_top3_from_db(self):
        self.cursor.execute("""
            SELECT group_id FROM group_rankings
            WHERE metric='GDT_TS' ORDER BY rank LIMIT 3
        """)
        top3 = [row[0] for row in self.cursor.fetchall()]
        assert top3 == ["022", "052", "456"], \
            f"Expected GDT_TS top 3 ['022', '052', '456'], got {top3}"

    def test_group_022_gdt_sum_zscore(self):
        self.cursor.execute("""
            SELECT sum_zscore FROM group_rankings
            WHERE group_id='022' AND metric='GDT_TS'
        """)
        val = self.cursor.fetchone()[0]
        assert abs(val - 70.17) < 0.5, \
            f"Group 022 GDT_TS sum zscore expected ~70.17, got {val}"

    def test_group_022_n_domains(self):
        self.cursor.execute("""
            SELECT n_domains FROM group_rankings
            WHERE group_id='022' AND metric='GDT_TS'
        """)
        val = self.cursor.fetchone()[0]
        assert val == 154, \
            f"Group 022 expected 154 domains, got {val}"


class TestSummaryJson:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.summary = load_json("summary.json")

    def test_total_first_models(self):
        assert self.summary["total_first_models"] == 10159, \
            f"Expected 10159 first models, got {self.summary['total_first_models']}"

    def test_total_domains(self):
        assert self.summary["total_domains"] == 154, \
            f"Expected 154 domains, got {self.summary['total_domains']}"

    def test_total_groups(self):
        assert self.summary["total_groups"] == 111, \
            f"Expected 111 groups, got {self.summary['total_groups']}"

    def test_domains_with_outliers_removed(self):
        val = self.summary["domains_with_outliers_removed"]
        assert val == 145, \
            f"Expected 145 domains with outlier removal, got {val}"

    def test_top3_gdt(self):
        top3 = self.summary["top3_gdt"]
        assert top3 == ["022", "052", "456"], \
            f"Expected top3 GDT_TS = ['022', '052', '456'], got {top3}"

    def test_top3_lddt(self):
        top3 = self.summary["top3_lddt"]
        assert top3 == ["052", "022", "241"], \
            f"Expected top3 LDDT = ['052', '022', '241'], got {top3}"


class TestGroupRankings:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.rows = load_csv("group_rankings.csv")
        self.by_group = {r["group"]: r for r in self.rows}

    def test_row_count(self):
        assert len(self.rows) == 111, \
            f"Expected 111 group rows, got {len(self.rows)}"

    def test_required_columns(self):
        expected = {"group", "n_domains", "sum_z_gdt", "rank_gdt",
                    "sum_z_lddt", "rank_lddt", "sum_z_tm", "rank_tm",
                    "sum_z_cad", "rank_cad", "sum_z_ha", "rank_ha"}
        actual = set(self.rows[0].keys())
        missing = expected - actual
        assert not missing, f"Missing columns: {missing}"

    def test_gdt_rank1_is_022(self):
        first_row = self.rows[0]
        assert first_row["group"] == "022", \
            f"Expected rank 1 GDT_TS group to be 022, got {first_row['group']}"
        assert int(first_row["rank_gdt"]) == 1

    def test_gdt_rank2_is_052(self):
        assert self.by_group["052"]["rank_gdt"] == "2"

    def test_gdt_rank3_is_456(self):
        assert self.by_group["456"]["rank_gdt"] == "3"

    def test_group_022_gdt_sum_z(self):
        val = float(self.by_group["022"]["sum_z_gdt"])
        assert abs(val - 70.17) < 0.5, \
            f"Group 022 GDT_TS SUM z-score expected ~70.17, got {val}"

    def test_group_052_gdt_sum_z(self):
        val = float(self.by_group["052"]["sum_z_gdt"])
        assert abs(val - 68.79) < 0.5, \
            f"Group 052 GDT_TS SUM z-score expected ~68.79, got {val}"

    def test_group_022_domains(self):
        val = int(self.by_group["022"]["n_domains"])
        assert val == 154, \
            f"Group 022 expected 154 domains, got {val}"

    def test_group_028_domains(self):
        val = int(self.by_group["028"]["n_domains"])
        assert val == 117, \
            f"Group 028 expected 117 domains, got {val}"

    def test_lddt_rank1_is_052(self):
        lddt_sorted = sorted(self.rows, key=lambda r: int(r["rank_lddt"]))
        assert lddt_sorted[0]["group"] == "052", \
            f"Expected LDDT rank 1 to be group 052, got {lddt_sorted[0]['group']}"

    def test_lddt_rank3_is_241(self):
        assert self.by_group["241"]["rank_lddt"] == "3", \
            f"Expected group 241 LDDT rank 3, got {self.by_group['241']['rank_lddt']}"

    def test_sorted_by_rank_gdt(self):
        ranks = [int(r["rank_gdt"]) for r in self.rows]
        assert ranks == sorted(ranks), "Rows should be sorted by rank_gdt ascending"


class TestMetricCorrelations:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.rows = load_csv("metric_correlations.csv")
        self.by_pair = {}
        for r in self.rows:
            key = (r["metric1"], r["metric2"])
            self.by_pair[key] = float(r["kendall_tau"])

    def test_row_count(self):
        assert len(self.rows) == 10, \
            f"Expected 10 correlation pairs, got {len(self.rows)}"

    def test_gdt_tm_correlation(self):
        key = ("GDT_TS", "TMscore")
        if key not in self.by_pair:
            key = ("TMscore", "GDT_TS")
        tau = self.by_pair[key]
        assert abs(tau - 0.9043) < 0.03, \
            f"GDT_TS-TMscore tau expected ~0.904, got {tau}"

    def test_gdt_ha_correlation(self):
        key = ("GDT_TS", "GDT_HA")
        if key not in self.by_pair:
            key = ("GDT_HA", "GDT_TS")
        tau = self.by_pair[key]
        assert abs(tau - 0.9178) < 0.03, \
            f"GDT_TS-GDT_HA tau expected ~0.918, got {tau}"

    def test_lddt_cad_correlation(self):
        key = ("LDDT", "CAD_AA")
        if key not in self.by_pair:
            key = ("CAD_AA", "LDDT")
        tau = self.by_pair[key]
        assert abs(tau - 0.886) < 0.03, \
            f"LDDT-CAD_AA tau expected ~0.886, got {tau}"

    def test_all_correlations_positive(self):
        for r in self.rows:
            tau = float(r["kendall_tau"])
            assert tau > 0.5, \
                f"Expected all correlations > 0.5, got {tau} for {r['metric1']}-{r['metric2']}"

    def test_highest_correlation_is_gdt_ha(self):
        max_row = max(self.rows, key=lambda r: float(r["kendall_tau"]))
        pair = {max_row["metric1"], max_row["metric2"]}
        assert pair == {"GDT_TS", "GDT_HA"}, \
            f"Expected highest correlation to be GDT_TS-GDT_HA, got {pair}"

    def test_lowest_correlation_is_tm_cad(self):
        min_row = min(self.rows, key=lambda r: float(r["kendall_tau"]))
        pair = {min_row["metric1"], min_row["metric2"]}
        assert pair == {"TMscore", "CAD_AA"}, \
            f"Expected lowest correlation to be TMscore-CAD_AA, got {pair}"


class TestDiscriminatingDomains:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.rows = load_csv("discriminating_domains.csv")

    def test_row_count(self):
        assert len(self.rows) == 10, \
            f"Expected 10 discriminating domains, got {len(self.rows)}"

    def test_required_columns(self):
        expected = {"domain", "std_gdt", "mean_gdt", "median_gdt", "n_groups"}
        actual = set(self.rows[0].keys())
        missing = expected - actual
        assert not missing, f"Missing columns: {missing}"

    def test_top_domain(self):
        top = self.rows[0]
        assert top["domain"] == "T1245s2-D1", \
            f"Expected most discriminating domain T1245s2-D1, got {top['domain']}"

    def test_top_domain_std(self):
        val = float(self.rows[0]["std_gdt"])
        assert abs(val - 26.92) < 0.5, \
            f"Expected top domain std ~26.92, got {val}"

    def test_second_domain(self):
        assert self.rows[1]["domain"] == "T0245s2-D1", \
            f"Expected 2nd domain T0245s2-D1, got {self.rows[1]['domain']}"

    def test_third_domain(self):
        assert self.rows[2]["domain"] == "T2257-D1", \
            f"Expected 3rd domain T2257-D1, got {self.rows[2]['domain']}"

    def test_sorted_by_std_desc(self):
        stds = [float(r["std_gdt"]) for r in self.rows]
        assert stds == sorted(stds, reverse=True), \
            "Domains should be sorted by std_gdt descending"

    def test_top_domain_n_groups(self):
        val = int(self.rows[0]["n_groups"])
        assert val == 84, \
            f"Expected T1245s2-D1 n_groups=84, got {val}"
