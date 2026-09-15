
import subprocess
import pytest

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def run_r(code: str, timeout: int = 60):
    """Source the library, run R code via stdin, return (stdout, stderr, rc)."""
    full = f'source("/app/mseries.R")\n{code}'
    p = subprocess.run(
        ["Rscript", "--vanilla", "-"],
        input=full,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return p.stdout.strip(), p.stderr.strip(), p.returncode


def r_nums(code: str) -> list:
    """Run R code that cats space-separated numbers; return as float list."""
    out, err, rc = run_r(code)
    if rc != 0:
        raise RuntimeError(f"R exit {rc}: {err}")
    return [float(x) for x in out.split()]


def r_strs(code: str) -> list:
    """Run R code that cats space-separated strings; return as str list."""
    out, err, rc = run_r(code)
    if rc != 0:
        raise RuntimeError(f"R exit {rc}: {err}")
    return out.split()


# ---------------------------------------------------------------------------
# Basic sanity
# ---------------------------------------------------------------------------

class TestBasic:
    def test_library_loads(self):
        out, err, rc = run_r('cat("OK")')
        assert rc == 0 and out == "OK"

    def test_constructor_sorts(self):
        vals = r_nums(
            'ms <- mseries(c(3, 1, 2), c(30, 10, 20))\n'
            'cat(ms$values)'
        )
        assert vals == [10, 20, 30]

    def test_length(self):
        vals = r_nums(
            'ms <- mseries(1:5, 11:15)\n'
            'cat(length(ms))'
        )
        assert vals == [5]

    def test_subset(self):
        vals = r_nums(
            'ms <- mseries(1:5, c(10,20,30,40,50))\n'
            'sub <- ms[c(2,4)]\n'
            'cat(sub$timestamps, sub$values)'
        )
        assert vals == [2, 4, 20, 40]


# ---------------------------------------------------------------------------
# window_aggregate
# ---------------------------------------------------------------------------

class TestWindowAggregate:
    def test_boundary_observation_included(self):
        """When t_max falls exactly on a break, its observation must be kept."""
        vals = r_nums(
            'ms <- mseries(c(0, 10, 20, 30), c(1, 2, 3, 4))\n'
            'agg <- window_aggregate(ms, 10)\n'
            'cat(agg$values)'
        )
        assert len(vals) == 3
        assert abs(vals[0] - 1.0) < 1e-10
        assert abs(vals[1] - 2.0) < 1e-10
        assert abs(vals[2] - 3.5) < 1e-10, (
            f"Last window should be mean(3,4)=3.5, got {vals[2]}"
        )

    def test_total_sum_preserved(self):
        """Sum across all windows must equal sum of original values."""
        vals = r_nums(
            'ms <- mseries(seq(0, 100, by = 10), seq(0, 100, by = 10))\n'
            'agg <- window_aggregate(ms, 10, FUN = sum)\n'
            'cat(sum(agg$values))'
        )
        assert abs(vals[0] - 550.0) < 1e-10, (
            f"Sum of all windows should equal 550, got {vals[0]}"
        )

    def test_non_boundary_unchanged(self):
        """Non-boundary case should work correctly (regression guard)."""
        vals = r_nums(
            'ms <- mseries(c(0, 5, 15, 25), c(10, 20, 30, 40))\n'
            'agg <- window_aggregate(ms, 10)\n'
            'cat(agg$values)'
        )
        assert abs(vals[0] - 15.0) < 1e-10   # mean(10,20)
        assert abs(vals[1] - 30.0) < 1e-10   # mean(30)
        assert abs(vals[2] - 40.0) < 1e-10   # mean(40)


# ---------------------------------------------------------------------------
# deduplicate
# ---------------------------------------------------------------------------

class TestDeduplicate:
    def test_exact_duplicates_removed(self):
        """Exact timestamp duplicates should be removed (regression guard)."""
        vals = r_nums(
            'ms <- mseries(c(1, 1, 2, 3, 3, 3), c(10,11,20,30,31,32))\n'
            'cat(length(deduplicate(ms)))'
        )
        assert vals == [3]

    def test_precision_14_significant_digits(self):
        """Timestamps differing at the 14th sig digit must remain distinct."""
        vals = r_nums(
            't1 <- 1234567890.12345\n'
            't2 <- 1234567890.12346\n'
            'ms <- mseries(c(t1, t2), c(100, 200))\n'
            'cat(length(deduplicate(ms)))'
        )
        assert vals == [2], (
            f"Two distinct 14-sig-digit timestamps should survive dedup, got {vals}"
        )

    def test_precision_epoch_magnitude(self):
        """Large timestamps (Unix epoch) with sub-ms differences must stay."""
        vals = r_nums(
            'base <- 1700000000\n'
            'ms <- mseries(c(base + 0.001, base + 0.002, base + 0.003),\n'
            '              c(1, 2, 3))\n'
            'cat(length(deduplicate(ms)))'
        )
        assert vals == [3], (
            f"Three epoch-range timestamps with ms-level diffs should survive, got {vals}"
        )

    def test_deduplicate_by_time_and_label(self):
        """Dedup by time_and_label keeps same-time different-label entries."""
        vals = r_nums(
            'ms <- mseries(c(1, 1, 2), c(10, 20, 30),\n'
            '              labels = c("A", "B", "A"))\n'
            'cat(length(deduplicate(ms, by = "time_and_label")))'
        )
        assert vals == [3]


# ---------------------------------------------------------------------------
# nearest_merge
# ---------------------------------------------------------------------------

class TestNearestMerge:
    def test_closer_to_right_neighbor(self):
        """When query is closer to the right reference, use that reference."""
        vals = r_nums(
            'x   <- mseries(c(16), c(999))\n'
            'ref <- mseries(c(10, 20), c(100, 200))\n'
            'merged <- nearest_merge(x, ref)\n'
            'cat(merged$ref_value, merged$distance)'
        )
        assert abs(vals[0] - 200.0) < 1e-10, (
            f"t=16 is closer to t=20 (dist 4) than t=10 (dist 6); "
            f"expected ref_value=200, got {vals[0]}"
        )
        assert abs(vals[1] - 4.0) < 1e-10

    def test_closer_to_left_neighbor(self):
        """Left-is-closer case should still work (regression guard)."""
        vals = r_nums(
            'x   <- mseries(c(12), c(999))\n'
            'ref <- mseries(c(10, 20), c(100, 200))\n'
            'merged <- nearest_merge(x, ref)\n'
            'cat(merged$ref_value, merged$distance)'
        )
        assert abs(vals[0] - 100.0) < 1e-10
        assert abs(vals[1] - 2.0) < 1e-10

    def test_multiple_mixed_queries(self):
        """Multiple queries with different nearest sides."""
        vals = r_nums(
            'x   <- mseries(c(3, 8, 14, 19), c(0, 0, 0, 0))\n'
            'ref <- mseries(c(5, 10, 15), c(50, 100, 150))\n'
            'merged <- nearest_merge(x, ref)\n'
            'cat(merged$ref_value)'
        )
        assert vals == [50, 100, 150, 150], (
            f"Expected [50,100,150,150], got {vals}"
        )

    def test_max_gap_filtering(self):
        """Observations beyond max_gap must become NA."""
        out, err, rc = run_r(
            'x   <- mseries(c(1, 50), c(0, 0))\n'
            'ref <- mseries(c(10), c(42))\n'
            'merged <- nearest_merge(x, ref, max_gap = 15)\n'
            'cat(is.na(merged$ref_value[1]), is.na(merged$ref_value[2]))'
        )
        assert rc == 0
        parts = out.split()
        assert parts[0] == "FALSE"
        assert parts[1] == "TRUE"


# ---------------------------------------------------------------------------
# diff_series
# ---------------------------------------------------------------------------

class TestDiffSeries:
    def test_timestamps_use_later_endpoint(self):
        """Differences must be aligned with the later timestamp."""
        vals = r_nums(
            'ms <- mseries(c(10, 20, 30, 40), c(100, 400, 900, 1600))\n'
            'd  <- diff_series(ms)\n'
            'cat(d$timestamps)'
        )
        assert vals == [20, 30, 40], (
            f"Diff timestamps should be [20,30,40], got {vals}"
        )

    def test_diff_values_correct(self):
        """Numeric difference values must be correct (regression guard)."""
        vals = r_nums(
            'ms <- mseries(c(10, 20, 30, 40), c(100, 400, 900, 1600))\n'
            'd  <- diff_series(ms)\n'
            'cat(d$values)'
        )
        assert vals == [300, 500, 700]

    def test_lag2_timestamps(self):
        """Lag-2 differences must use timestamps from position lag+1 onward."""
        vals = r_nums(
            'ms <- mseries(c(1, 2, 3, 4, 5), c(1, 4, 9, 16, 25))\n'
            'd  <- diff_series(ms, lag = 2)\n'
            'cat(d$timestamps)'
        )
        assert vals == [3, 4, 5], (
            f"Lag-2 diff timestamps should be [3,4,5], got {vals}"
        )

    def test_labels_match_later_timestamp(self):
        """Labels must correspond to the later (not earlier) observation."""
        strs = r_strs(
            'ms <- mseries(c(10, 20, 30, 40), c(1,2,3,4),\n'
            '              labels = c("A","B","C","D"))\n'
            'd  <- diff_series(ms)\n'
            'cat(d$labels)'
        )
        assert strs == ["B", "C", "D"], (
            f"Diff labels should be [B,C,D], got {strs}"
        )

    def test_second_order_diff(self):
        """Second-order differences must also have correct timestamps."""
        vals = r_nums(
            'ms <- mseries(c(1,2,3,4,5), c(1,4,9,16,25))\n'
            'd2 <- diff_series(ms, differences = 2)\n'
            'cat(d2$timestamps)'
        )
        assert vals == [3, 4, 5]


# ---------------------------------------------------------------------------
# resample
# ---------------------------------------------------------------------------

class TestResampleLinear:
    def test_linear_basic(self):
        """Linear interpolation between two known points."""
        vals = r_nums(
            'x <- mseries(c(0, 10), c(0, 100))\n'
            'r <- resample(x, c(2.5, 5, 7.5))\n'
            'cat(r$values)'
        )
        assert len(vals) == 3
        assert abs(vals[0] - 25.0) < 1e-10
        assert abs(vals[1] - 50.0) < 1e-10
        assert abs(vals[2] - 75.0) < 1e-10

    def test_linear_outside_range(self):
        """Targets outside the time range must produce NA."""
        out, _, rc = run_r(
            'x <- mseries(c(5, 10), c(50, 100))\n'
            'r <- resample(x, c(0, 7, 15))\n'
            'cat(is.na(r$values[1]), !is.na(r$values[2]), is.na(r$values[3]))'
        )
        assert rc == 0
        parts = out.split()
        assert parts[0] == "TRUE", "t=0 outside range should be NA"
        assert parts[1] == "TRUE", "t=7 within range should have a value"
        assert parts[2] == "TRUE", "t=15 outside range should be NA"

    def test_linear_max_gap(self):
        """When bracket gap exceeds max_gap, the result must be NA."""
        out, _, rc = run_r(
            'x <- mseries(c(0, 100), c(0, 1000))\n'
            'r <- resample(x, c(50), method = "linear", max_gap = 20)\n'
            'cat(is.na(r$values[1]))'
        )
        assert rc == 0
        assert out.strip() == "TRUE", (
            "Gap of 50 to each bracket exceeds max_gap=20, should be NA"
        )

    def test_linear_exact_endpoints(self):
        """Targets at exact observation timestamps must return exact values."""
        vals = r_nums(
            'x <- mseries(c(0, 10, 20), c(100, 200, 300))\n'
            'r <- resample(x, c(0, 10, 20))\n'
            'cat(r$values)'
        )
        assert abs(vals[0] - 100.0) < 1e-10
        assert abs(vals[1] - 200.0) < 1e-10
        assert abs(vals[2] - 300.0) < 1e-10


class TestResampleNearest:
    def test_nearest_basic(self):
        """Nearest picks the closest observation."""
        vals = r_nums(
            'x <- mseries(c(0, 10, 20), c(100, 200, 300))\n'
            'r <- resample(x, c(3, 12, 18), method = "nearest")\n'
            'cat(r$values)'
        )
        assert abs(vals[0] - 100.0) < 1e-10   # closest to t=0
        assert abs(vals[1] - 200.0) < 1e-10   # closest to t=10
        assert abs(vals[2] - 300.0) < 1e-10   # closest to t=20

    def test_nearest_right_neighbor(self):
        """Nearest must consider the right neighbor when it is closer."""
        vals = r_nums(
            'x <- mseries(c(0, 10), c(100, 200))\n'
            'r <- resample(x, c(7), method = "nearest")\n'
            'cat(r$values)'
        )
        assert abs(vals[0] - 200.0) < 1e-10, (
            f"t=7 is closer to t=10 (dist 3) than t=0 (dist 7), expected 200 got {vals[0]}"
        )

    def test_nearest_max_gap(self):
        """Nearest: if closest observation exceeds max_gap, result is NA."""
        out, _, rc = run_r(
            'x <- mseries(c(0, 100), c(1, 2))\n'
            'r <- resample(x, c(50), method = "nearest", max_gap = 10)\n'
            'cat(is.na(r$values[1]))'
        )
        assert rc == 0
        assert out.strip() == "TRUE"


class TestResampleLocf:
    def test_locf_basic(self):
        """LOCF carries forward the last observation."""
        vals = r_nums(
            'x <- mseries(c(0, 10, 20), c(100, 200, 300))\n'
            'r <- resample(x, c(5, 15, 25), method = "locf")\n'
            'cat(r$values)'
        )
        assert abs(vals[0] - 100.0) < 1e-10   # carried from t=0
        assert abs(vals[1] - 200.0) < 1e-10   # carried from t=10
        assert abs(vals[2] - 300.0) < 1e-10   # carried from t=20

    def test_locf_before_first(self):
        """Targets before first observation must produce NA."""
        out, _, rc = run_r(
            'x <- mseries(c(10, 20), c(100, 200))\n'
            'r <- resample(x, c(5), method = "locf")\n'
            'cat(is.na(r$values[1]))'
        )
        assert rc == 0
        assert out.strip() == "TRUE"

    def test_locf_max_gap(self):
        """LOCF: if gap to carried observation exceeds max_gap, result is NA."""
        out, _, rc = run_r(
            'x <- mseries(c(0, 100), c(1, 2))\n'
            'r <- resample(x, c(50), method = "locf", max_gap = 10)\n'
            'cat(is.na(r$values[1]))'
        )
        assert rc == 0
        assert out.strip() == "TRUE"


class TestResampleLabels:
    def test_linear_labels_na(self):
        """Linear interpolation must not propagate labels (should be NA or NULL)."""
        out, _, rc = run_r(
            'x <- mseries(c(0, 10), c(0, 100), labels = c("A", "B"))\n'
            'r <- resample(x, c(5))\n'
            'cat(is.null(r$labels) || all(is.na(r$labels)))'
        )
        assert rc == 0
        assert out.strip() == "TRUE"

    def test_nearest_labels_inherited(self):
        """Nearest must inherit labels from the matched observation."""
        strs = r_strs(
            'x <- mseries(c(0, 10), c(0, 100), labels = c("A", "B"))\n'
            'r <- resample(x, c(3, 8), method = "nearest")\n'
            'cat(r$labels)'
        )
        assert strs == ["A", "B"], (
            f"t=3 should inherit A, t=8 should inherit B, got {strs}"
        )

    def test_locf_labels_inherited(self):
        """LOCF must inherit labels from the carried-forward observation."""
        strs = r_strs(
            'x <- mseries(c(0, 10), c(0, 100), labels = c("A", "B"))\n'
            'r <- resample(x, c(5, 15), method = "locf")\n'
            'cat(r$labels)'
        )
        assert strs == ["A", "B"], (
            f"t=5 should inherit A, t=15 should inherit B, got {strs}"
        )


# ---------------------------------------------------------------------------
# Composition: cross-function correctness
# ---------------------------------------------------------------------------

class TestComposition:
    def test_resample_then_diff(self):
        """Resampled series must produce correct lagged differences."""
        vals = r_nums(
            'x <- mseries(c(0, 10, 20, 30), c(0, 100, 400, 900))\n'
            'r <- resample(x, c(5, 15, 25), method = "linear")\n'
            'd <- diff_series(r)\n'
            'cat(d$timestamps, d$values)'
        )
        # r values: 50, 250, 650
        # diff: [t=15] 200, [t=25] 400
        assert abs(vals[0] - 15.0) < 1e-10
        assert abs(vals[1] - 25.0) < 1e-10
        assert abs(vals[2] - 200.0) < 1e-10
        assert abs(vals[3] - 400.0) < 1e-10

    def test_nearest_merge_resample_consistency(self):
        """nearest_merge and resample(nearest) must agree on closest ref."""
        vals = r_nums(
            'x   <- mseries(c(7, 14), c(0, 0))\n'
            'ref <- mseries(c(0, 10, 20), c(100, 200, 300))\n'
            'merged <- nearest_merge(x, ref)\n'
            'r <- resample(ref, c(7, 14), method = "nearest")\n'
            'cat(merged$ref_value, r$values)'
        )
        # t=7: nearest is t=10 (dist 3) => 200
        # t=14: nearest is t=10 (dist 4) => 200
        assert abs(vals[0] - 200.0) < 1e-10
        assert abs(vals[1] - 200.0) < 1e-10
        assert abs(vals[2] - 200.0) < 1e-10
        assert abs(vals[3] - 200.0) < 1e-10
