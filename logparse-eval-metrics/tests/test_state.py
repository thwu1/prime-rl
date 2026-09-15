
import pytest
import pandas as pd
import os
import math
import importlib.util


def _load_module(name, path):
    """Load a Python module from a file path."""
    if not os.path.exists(path):
        pytest.fail(f"Module file not found: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def eval_mod():
    return _load_module("evaluate", "/app/evaluation/evaluate.py")


@pytest.fixture(scope="session")
def pp_mod():
    return _load_module("post_process", "/app/evaluation/post_process.py")


# ═══════════════════════════════════════════════════
# 1. Evaluation metrics on synthetic data
# ═══════════════════════════════════════════════════

class TestMetricsPerfectMatch:
    """GT identical to parsed → all metrics = 1.0."""

    def test_ga_fga(self, eval_mod):
        s = pd.Series(["A", "A", "B", "B", "C"])
        GA, FGA = eval_mod.compute_ga_fga(s, s)
        assert abs(GA - 1.0) < 1e-6
        assert abs(FGA - 1.0) < 1e-6

    def test_pa(self, eval_mod):
        s = pd.Series(["A", "A", "B", "B", "C"])
        assert abs(eval_mod.compute_pa(s, s) - 1.0) < 1e-6

    def test_fta(self, eval_mod):
        s = pd.Series(["A", "A", "B", "B", "C"])
        assert abs(eval_mod.compute_fta(s, s) - 1.0) < 1e-6


class TestMetricsDegenerate:
    """All messages assigned the same template → GA=0, PA=0."""

    def test_ga_zero(self, eval_mod):
        gt = pd.Series(["A", "A", "B", "B", "C"])
        parsed = pd.Series(["X", "X", "X", "X", "X"])
        GA, _ = eval_mod.compute_ga_fga(gt, parsed)
        assert abs(GA) < 1e-6, f"Expected GA=0, got {GA}"

    def test_pa_zero(self, eval_mod):
        gt = pd.Series(["A", "A", "B", "B", "C"])
        parsed = pd.Series(["X", "X", "X", "X", "X"])
        assert abs(eval_mod.compute_pa(gt, parsed)) < 1e-6


class TestMetricsOverGeneralization:
    """Two GT groups merged into one parsed group."""

    def test_ga_fga_zero(self, eval_mod):
        gt = pd.Series(["A", "A", "A", "B", "B", "B"])
        parsed = pd.Series(["A", "A", "A", "A", "A", "A"])
        GA, FGA = eval_mod.compute_ga_fga(gt, parsed)
        assert abs(GA) < 1e-6, f"Expected GA=0, got {GA}"
        assert abs(FGA) < 1e-6, f"Expected FGA=0, got {FGA}"

    def test_pa_half(self, eval_mod):
        gt = pd.Series(["A", "A", "A", "B", "B", "B"])
        parsed = pd.Series(["A", "A", "A", "A", "A", "A"])
        PA = eval_mod.compute_pa(gt, parsed)
        assert abs(PA - 0.5) < 1e-6, f"Expected PA=0.5, got {PA}"

    def test_fta_zero(self, eval_mod):
        gt = pd.Series(["A", "A", "A", "B", "B", "B"])
        parsed = pd.Series(["A", "A", "A", "A", "A", "A"])
        FTA = eval_mod.compute_fta(gt, parsed)
        assert abs(FTA) < 1e-6, f"Expected FTA=0, got {FTA}"


class TestMetricsPartialOverlap:
    """One message misassigned across groups.
    GT:     A A A B B B C C
    Parsed: A A B B B B C C
    Expected: GA=0.25, FGA≈0.3333, PA=0.875, FTA≈0.6667
    """

    def test_ga(self, eval_mod):
        gt = pd.Series(["A", "A", "A", "B", "B", "B", "C", "C"])
        parsed = pd.Series(["A", "A", "B", "B", "B", "B", "C", "C"])
        GA, _ = eval_mod.compute_ga_fga(gt, parsed)
        assert abs(GA - 0.25) < 0.02, f"Expected GA≈0.25, got {GA}"

    def test_fga(self, eval_mod):
        gt = pd.Series(["A", "A", "A", "B", "B", "B", "C", "C"])
        parsed = pd.Series(["A", "A", "B", "B", "B", "B", "C", "C"])
        _, FGA = eval_mod.compute_ga_fga(gt, parsed)
        assert abs(FGA - 1 / 3) < 0.02, f"Expected FGA≈0.333, got {FGA}"

    def test_pa(self, eval_mod):
        gt = pd.Series(["A", "A", "A", "B", "B", "B", "C", "C"])
        parsed = pd.Series(["A", "A", "B", "B", "B", "B", "C", "C"])
        PA = eval_mod.compute_pa(gt, parsed)
        assert abs(PA - 0.875) < 0.02, f"Expected PA≈0.875, got {PA}"

    def test_fta(self, eval_mod):
        gt = pd.Series(["A", "A", "A", "B", "B", "B", "C", "C"])
        parsed = pd.Series(["A", "A", "B", "B", "B", "B", "C", "C"])
        FTA = eval_mod.compute_fta(gt, parsed)
        assert abs(FTA - 2 / 3) < 0.02, f"Expected FTA≈0.667, got {FTA}"


class TestMetricsGroupCorrectTextWrong:
    """Grouping is perfect but one group has wrong template text.
    GT:     tA tA tA tB tB
    Parsed: tA tA tA tBx tBx
    Expected: GA=1.0, FGA=1.0, PA=0.6, FTA=0.5
    """

    def test_ga_fga_perfect(self, eval_mod):
        gt = pd.Series(["tA", "tA", "tA", "tB", "tB"])
        parsed = pd.Series(["tA", "tA", "tA", "tBx", "tBx"])
        GA, FGA = eval_mod.compute_ga_fga(gt, parsed)
        assert abs(GA - 1.0) < 1e-6, f"Expected GA=1.0, got {GA}"
        assert abs(FGA - 1.0) < 1e-6, f"Expected FGA=1.0, got {FGA}"

    def test_pa_partial(self, eval_mod):
        gt = pd.Series(["tA", "tA", "tA", "tB", "tB"])
        parsed = pd.Series(["tA", "tA", "tA", "tBx", "tBx"])
        PA = eval_mod.compute_pa(gt, parsed)
        assert abs(PA - 0.6) < 1e-6, f"Expected PA=0.6, got {PA}"

    def test_fta_half(self, eval_mod):
        gt = pd.Series(["tA", "tA", "tA", "tB", "tB"])
        parsed = pd.Series(["tA", "tA", "tA", "tBx", "tBx"])
        FTA = eval_mod.compute_fta(gt, parsed)
        assert abs(FTA - 0.5) < 0.02, f"Expected FTA=0.5, got {FTA}"


# ═══════════════════════════════════════════════════
# 2. Post-processing correction rules
# ═══════════════════════════════════════════════════

class TestPostProcessing:
    def test_double_space(self, pp_mod):
        assert pp_mod.correct_template("Error    in   component  ") == \
            "Error in component"

    def test_digit_replacement(self, pp_mod):
        result = pp_mod.correct_template(
            "Block 42 at step 7 on 192.168.1.1")
        assert result == "Block <*> at step <*> on <*>"

    def test_word_variable(self, pp_mod):
        assert pp_mod.correct_template("node<*>_up") == "<*>"

    def test_dot_variable(self, pp_mod):
        assert pp_mod.correct_template("<*>.<*>.<*>.<*>") == "<*>"

    def test_colon_collapse(self, pp_mod):
        result = pp_mod.correct_template("src <*>:<*> dest <*>:<*>")
        assert result == "src <*> dest <*>"

    def test_slash_collapse(self, pp_mod):
        assert pp_mod.correct_template("Path <*>/<*>/<*>") == "Path <*>"

    def test_at_collapse(self, pp_mod):
        assert pp_mod.correct_template("user<*>@host<*>") == "<*>"

    def test_ip_address(self, pp_mod):
        result = pp_mod.correct_template("host 10.251.73.220 connected")
        assert result == "host <*> connected"

    def test_no_change(self, pp_mod):
        assert pp_mod.correct_template("System started successfully") == \
            "System started successfully"

    def test_hash_wildcard(self, pp_mod):
        result = pp_mod.correct_template("value #<*># end")
        assert result == "value <*> end"


# ═══════════════════════════════════════════════════
# 3. Content extraction from parsed output CSVs
# ═══════════════════════════════════════════════════

class TestContentExtraction:
    def test_hdfs_line1(self):
        """HDFS format: <Date> <Time> <Pid> <Level> <Component>: <Content>"""
        df = pd.read_csv("/app/results/parsed_HDFS.csv")
        expected = "PacketResponder 1 for block blk_38865049064139660 terminating"
        assert df.loc[0, "Content"] == expected, \
            f"HDFS line 1 Content: {df.loc[0, 'Content']}"

    def test_apache_line1(self):
        """Apache format: \\[<Time>\\] \\[<Level>\\] <Content>"""
        df = pd.read_csv("/app/results/parsed_Apache.csv")
        expected = "workerEnv.init() ok /etc/httpd/conf/workers2.properties"
        assert df.loc[0, "Content"] == expected, \
            f"Apache line 1 Content: {df.loc[0, 'Content']}"

    def test_linux_with_pid(self):
        """Linux line 1 has optional [PID] group present."""
        df = pd.read_csv("/app/results/parsed_Linux.csv")
        assert df.loc[0, "Content"].startswith(
            "authentication failure; logname="), \
            f"Linux line 1 Content: {df.loc[0, 'Content']}"

    def test_linux_without_pid(self):
        """Linux line 16 (idx 15) has no [PID] — logrotate has no PID."""
        df = pd.read_csv("/app/results/parsed_Linux.csv")
        assert df.loc[15, "Content"] == \
            "ALERT exited abnormally with [1]", \
            f"Linux line 16 Content: {df.loc[15, 'Content']}"


# ═══════════════════════════════════════════════════
# 4. Output file structure
# ═══════════════════════════════════════════════════

class TestOutputStructure:
    @pytest.mark.parametrize("system", ["HDFS", "Apache", "Linux"])
    def test_parsed_csv_schema(self, system):
        path = f"/app/results/parsed_{system}.csv"
        assert os.path.exists(path), f"Missing {path}"
        df = pd.read_csv(path)
        assert len(df) == 2000, \
            f"{system}: expected 2000 rows, got {len(df)}"
        for col in ("LineId", "Content", "EventId", "EventTemplate"):
            assert col in df.columns, \
                f"Missing column '{col}' in parsed_{system}.csv"

    def test_parsed_templates_not_empty(self):
        for system in ("HDFS", "Apache", "Linux"):
            df = pd.read_csv(f"/app/results/parsed_{system}.csv")
            assert df["EventTemplate"].notna().sum() > 0, \
                f"{system}: all EventTemplate values are NaN"

    def test_metrics_raw_csv(self):
        path = "/app/results/metrics_raw.csv"
        assert os.path.exists(path), f"Missing {path}"
        df = pd.read_csv(path)
        for col in ("System", "GA", "FGA", "PA", "FTA"):
            assert col in df.columns, f"Missing column '{col}'"
        systems = set(df["System"])
        for s in ("HDFS", "Apache", "Linux"):
            assert s in systems, f"'{s}' missing from metrics_raw.csv"

    def test_metrics_corrected_csv(self):
        path = "/app/results/metrics_corrected.csv"
        assert os.path.exists(path), f"Missing {path}"
        df = pd.read_csv(path)
        for col in ("System", "GA", "FGA", "PA", "FTA"):
            assert col in df.columns

    def test_improvement_csv(self):
        path = "/app/results/improvement.csv"
        assert os.path.exists(path), f"Missing {path}"
        df = pd.read_csv(path)
        for col in ("System", "GA_delta", "FGA_delta",
                     "PA_delta", "FTA_delta"):
            assert col in df.columns


# ═══════════════════════════════════════════════════
# 5. Integration: drain3 pipeline metric ranges
# ═══════════════════════════════════════════════════

class TestIntegrationMetrics:
    @pytest.fixture(scope="class")
    def raw_df(self):
        return pd.read_csv("/app/results/metrics_raw.csv")

    def test_all_metrics_valid(self, raw_df):
        """Every metric should be a finite float in [0, 1]."""
        for _, row in raw_df.iterrows():
            for m in ("GA", "FGA", "PA", "FTA"):
                val = row[m]
                assert not math.isnan(val), \
                    f"{row['System']} {m} is NaN"
                assert 0.0 <= val <= 1.0, \
                    f"{row['System']} {m}={val} out of [0,1]"

    def test_hdfs_ga(self, raw_df):
        """HDFS raw GA should be non-trivial (masking applied)."""
        row = raw_df[raw_df["System"] == "HDFS"].iloc[0]
        assert row["GA"] > 0.20, \
            f"HDFS GA={row['GA']}, expected >0.20"

    def test_apache_ga(self, raw_df):
        """Apache raw GA should be non-trivial (masking applied)."""
        row = raw_df[raw_df["System"] == "Apache"].iloc[0]
        assert row["GA"] > 0.20, \
            f"Apache GA={row['GA']}, expected >0.20"

    def test_linux_ga(self, raw_df):
        """Linux is the hardest system for Drain."""
        row = raw_df[raw_df["System"] == "Linux"].iloc[0]
        assert row["GA"] > 0.05, \
            f"Linux GA={row['GA']}, expected >0.05"

    def test_hdfs_template_count(self):
        df = pd.read_csv("/app/results/parsed_HDFS.csv")
        n = df["EventTemplate"].nunique()
        assert 5 <= n <= 40, \
            f"HDFS: {n} unique templates, expected 5-40"

    def test_apache_template_count(self):
        df = pd.read_csv("/app/results/parsed_Apache.csv")
        n = df["EventTemplate"].nunique()
        assert 3 <= n <= 20, \
            f"Apache: {n} unique templates, expected 3-20"


# ═══════════════════════════════════════════════════
# 6. Corrected metrics (post-processing applied)
# ═══════════════════════════════════════════════════

class TestCorrectedMetrics:
    @pytest.fixture(scope="class")
    def corr_df(self):
        return pd.read_csv("/app/results/metrics_corrected.csv")

    def test_hdfs_ga_corrected(self, corr_df):
        """After correction, HDFS grouping accuracy should improve."""
        row = corr_df[corr_df["System"] == "HDFS"].iloc[0]
        assert row["GA"] > 0.65, \
            f"Corrected HDFS GA={row['GA']}, expected >0.65"

    def test_apache_ga_corrected(self, corr_df):
        """After correction, Apache should achieve near-perfect grouping."""
        row = corr_df[corr_df["System"] == "Apache"].iloc[0]
        assert row["GA"] > 0.90, \
            f"Corrected Apache GA={row['GA']}, expected >0.90"

    def test_correction_improves_apache_ga(self, corr_df):
        """Correction pipeline must improve Apache GA over raw."""
        raw_df = pd.read_csv("/app/results/metrics_raw.csv")
        raw_ga = raw_df[raw_df["System"] == "Apache"].iloc[0]["GA"]
        corr_ga = corr_df[corr_df["System"] == "Apache"].iloc[0]["GA"]
        assert corr_ga > raw_ga, \
            f"Corrected Apache GA ({corr_ga}) not better than raw ({raw_ga})"

    def test_all_corrected_valid(self, corr_df):
        """All corrected metrics should be finite floats in [0, 1]."""
        for _, row in corr_df.iterrows():
            for m in ("GA", "FGA", "PA", "FTA"):
                val = row[m]
                assert not math.isnan(val), \
                    f"{row['System']} corrected {m} is NaN"
                assert 0.0 <= val <= 1.0, \
                    f"{row['System']} corrected {m}={val} out of [0,1]"


# ═══════════════════════════════════════════════════
# 7. Improvement analysis
# ═══════════════════════════════════════════════════

class TestImprovementAnalysis:
    def test_deltas_finite(self):
        df = pd.read_csv("/app/results/improvement.csv")
        for _, row in df.iterrows():
            for col in ("GA_delta", "FGA_delta",
                        "PA_delta", "FTA_delta"):
                assert not math.isnan(row[col]), \
                    f"{row['System']} {col} is NaN"
                assert -1.0 <= row[col] <= 1.0, \
                    f"{row['System']} {col}={row[col]} out of [-1,1]"

    def test_hdfs_pa_improves(self):
        """Post-processing colon-collapse should improve HDFS PA."""
        df = pd.read_csv("/app/results/improvement.csv")
        row = df[df["System"] == "HDFS"].iloc[0]
        assert row["PA_delta"] > 0, \
            f"Expected HDFS PA improvement, got delta={row['PA_delta']}"
