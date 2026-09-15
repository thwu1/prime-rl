"""
Tests for the NDJSON stream analyzer built on simdjson.

Tests cover: format detection and data-flow integrity, stream processing
(batch size, truncation, error recovery), aggregation correctness
(avg, median, stddev, percentile), JSON Pointer resolution, and
group-by functionality with per-group aggregation state.
"""

import json
import math
import os
import subprocess
import tempfile

import pytest

ANALYZER = "/app/stream_analyzer"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _write(content: str | bytes, suffix: str = ".ndjson") -> str:
    fd, path = tempfile.mkstemp(suffix=suffix, dir="/tmp")
    with os.fdopen(fd, "wb") as f:
        if isinstance(content, str):
            f.write(content.encode("utf-8"))
        else:
            f.write(content)
    return path


def _run(path: str, fmt: str, pointer: str, agg: str,
         group_by: str = None) -> dict:
    cmd = [ANALYZER, path, fmt, pointer, agg]
    if group_by is not None:
        cmd.extend(["--group-by", group_by])
    r = subprocess.run(
        cmd, capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0, (
        f"stream_analyzer exited {r.returncode}\nstderr: {r.stderr}\nstdout: {r.stdout}"
    )
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        pytest.fail(
            f"stream_analyzer produced invalid JSON output:\n{r.stdout}\nstderr: {r.stderr}"
        )


# ---------------------------------------------------------------------------
# Test: basic NDJSON count & sum  (smoke test for core pipeline)
# ---------------------------------------------------------------------------
class TestBasicNDJSON:
    """Small documents, top-level field — verifies core pipeline."""

    @pytest.fixture(autouse=True)
    def data(self, tmp_path):
        lines = [json.dumps({"id": i, "price": 10.0 + i * 2.5}) for i in range(10)]
        self.path = _write("\n".join(lines) + "\n")
        yield
        os.unlink(self.path)

    def test_count(self):
        r = _run(self.path, "ndjson", "/price", "count")
        assert r["valid_documents"] == 10
        assert r["total_documents"] == 10
        assert r["error_documents"] == 0
        assert r["result"] == 10.0

    def test_sum(self):
        r = _run(self.path, "ndjson", "/price", "sum")
        assert abs(r["result"] - 212.5) < 0.01

    def test_max(self):
        r = _run(self.path, "ndjson", "/price", "max")
        assert abs(r["result"] - 32.5) < 0.01


# ---------------------------------------------------------------------------
# Test: large documents  (catches BATCH_SIZE = 256 bug)
# ---------------------------------------------------------------------------
class TestLargeDocuments:
    """Documents > 256 bytes must not trigger CAPACITY errors."""

    @pytest.fixture(autouse=True)
    def data(self, tmp_path):
        lines = []
        for i in range(5):
            doc = {
                "id": i,
                "price": 100.0 + i * 10.0,
                "description": "X" * 300,
                "tags": ["benchmark", "test", "large"],
            }
            lines.append(json.dumps(doc))
        self.path = _write("\n".join(lines) + "\n")
        yield
        os.unlink(self.path)

    def test_all_processed(self):
        r = _run(self.path, "ndjson", "/price", "count")
        assert r["valid_documents"] == 5
        assert r["total_documents"] == 5
        assert r["result"] == 5.0

    def test_sum(self):
        r = _run(self.path, "ndjson", "/price", "sum")
        assert abs(r["result"] - 600.0) < 0.01


# ---------------------------------------------------------------------------
# Test: nested JSON Pointer  (catches find_field vs at_pointer bug)
# ---------------------------------------------------------------------------
class TestNestedPointer:
    """Nested paths like /metrics/latency require at_pointer, not operator[]."""

    @pytest.fixture(autouse=True)
    def data(self, tmp_path):
        lines = []
        for i in range(8):
            doc = {"id": i, "metrics": {"latency": 5.0 + i * 1.5, "throughput": 100}}
            lines.append(json.dumps(doc))
        self.path = _write("\n".join(lines) + "\n")
        yield
        os.unlink(self.path)

    def test_nested_count(self):
        r = _run(self.path, "ndjson", "/metrics/latency", "count")
        assert r["valid_documents"] == 8
        assert r["result"] == 8.0

    def test_nested_sum(self):
        r = _run(self.path, "ndjson", "/metrics/latency", "sum")
        assert abs(r["result"] - 82.0) < 0.01

    def test_nested_min(self):
        r = _run(self.path, "ndjson", "/metrics/latency", "min")
        assert abs(r["result"] - 5.0) < 0.01


# ---------------------------------------------------------------------------
# Test: min aggregation with all positive values  (catches min_val=0 bug)
# ---------------------------------------------------------------------------
class TestMinPositive:
    """min must be smallest value, not 0."""

    @pytest.fixture(autouse=True)
    def data(self, tmp_path):
        lines = [json.dumps({"v": 5.0 + i * 3.0}) for i in range(5)]
        self.path = _write("\n".join(lines) + "\n")
        yield
        os.unlink(self.path)

    def test_min(self):
        r = _run(self.path, "ndjson", "/v", "min")
        assert abs(r["result"] - 5.0) < 0.01


# ---------------------------------------------------------------------------
# Test: auto-detect RFC 7464  (catches detect_format + data-flow bugs)
# ---------------------------------------------------------------------------
class TestAutoDetectRFC7464:
    """0x1E-delimited input must be detected as rfc7464 and parsed correctly."""

    @pytest.fixture(autouse=True)
    def data(self, tmp_path):
        parts = []
        for i in range(5):
            doc = json.dumps({"value": 20.0 + i}).encode("utf-8")
            parts.append(b"\x1e" + doc + b"\n")
        self.path = _write(b"".join(parts))
        yield
        os.unlink(self.path)

    def test_format_detected(self):
        r = _run(self.path, "auto", "/value", "count")
        assert r["detected_format"] == "rfc7464"
        assert r["valid_documents"] == 5

    def test_sum(self):
        r = _run(self.path, "auto", "/value", "sum")
        assert abs(r["result"] - 110.0) < 0.01


# ---------------------------------------------------------------------------
# Test: explicit RFC 7464  (catches data-flow bug: raw vs processed)
# ---------------------------------------------------------------------------
class TestExplicitRFC7464:
    """Explicit rfc7464 format — RS bytes must be stripped before parsing."""

    @pytest.fixture(autouse=True)
    def data(self, tmp_path):
        parts = []
        for i in range(4):
            doc = json.dumps({"x": float(i + 1)}).encode("utf-8")
            parts.append(b"\x1e" + doc + b"\n")
        self.path = _write(b"".join(parts))
        yield
        os.unlink(self.path)

    def test_count_and_sum(self):
        r = _run(self.path, "rfc7464", "/x", "sum")
        assert r["valid_documents"] == 4
        assert abs(r["result"] - 10.0) < 0.01


# ---------------------------------------------------------------------------
# Test: auto-detect NDJSON does not misfire  (catches '[' → rfc7464 bug)
# ---------------------------------------------------------------------------
class TestAutoDetectNDJSONArray:
    """NDJSON where first document is a JSON array (starts with '[')."""

    @pytest.fixture(autouse=True)
    def data(self, tmp_path):
        lines = [
            "[10.0, 20.0, 30.0]",
            "[40.0, 50.0, 60.0]",
        ]
        self.path = _write("\n".join(lines) + "\n")
        yield
        os.unlink(self.path)

    def test_not_rfc7464(self):
        r = _run(self.path, "auto", "/1", "sum")
        assert r["detected_format"] == "ndjson"
        assert r["valid_documents"] == 2
        assert abs(r["result"] - 70.0) < 0.01


# ---------------------------------------------------------------------------
# Test: truncated stream  (catches truncated_bytes=0 bug)
# ---------------------------------------------------------------------------
class TestTruncatedStream:
    """Truncated final document must be reported via truncated_bytes."""

    @pytest.fixture(autouse=True)
    def data(self, tmp_path):
        valid = json.dumps({"val": 1.0}) + "\n"
        valid += json.dumps({"val": 2.0}) + "\n"
        truncated = '{"val": 3.0'
        self.path = _write(valid + truncated)
        yield
        os.unlink(self.path)

    def test_truncated_reported(self):
        r = _run(self.path, "ndjson", "/val", "count")
        assert r["truncated_bytes"] > 0, "truncated_bytes must be > 0 for incomplete stream"
        assert r["valid_documents"] == 2


# ---------------------------------------------------------------------------
# Test: avg denominator  (catches avg/total_documents bug)
# ---------------------------------------------------------------------------
class TestAvgDenominator:
    """avg must divide by valid_documents, not total_documents."""

    @pytest.fixture(autouse=True)
    def data(self, tmp_path):
        lines = []
        for i in range(4):
            lines.append(json.dumps({"price": 10.0 * (i + 1)}))
        lines.append(json.dumps({"name": "no_price_1"}))
        lines.append(json.dumps({"name": "no_price_2"}))
        self.path = _write("\n".join(lines) + "\n")
        yield
        os.unlink(self.path)

    def test_avg(self):
        r = _run(self.path, "ndjson", "/price", "avg")
        assert abs(r["result"] - 25.0) < 0.01


# ---------------------------------------------------------------------------
# Test: error counting  (catches error_documents = total-valid bug)
# ---------------------------------------------------------------------------
class TestErrorCounting:
    """Malformed docs must be counted as errors, not conflated with missing fields."""

    @pytest.fixture(autouse=True)
    def data(self, tmp_path):
        lines = []
        for i in range(3):
            lines.append(json.dumps({"score": 10.0 * (i + 1)}))
        lines.append(json.dumps({"other": 99}))
        lines.append(json.dumps({"other": 100}))
        lines.append('{"score": INVALID}')
        self.path = _write("\n".join(lines) + "\n")
        yield
        os.unlink(self.path)

    def test_error_vs_missing(self):
        r = _run(self.path, "ndjson", "/score", "count")
        assert r["valid_documents"] == 3
        assert r["error_documents"] == 1
        assert r["total_documents"] == 6


# ---------------------------------------------------------------------------
# Test: values aggregation  (end-to-end smoke test)
# ---------------------------------------------------------------------------
class TestValuesAggregation:
    """values aggregation must return all extracted values in order."""

    @pytest.fixture(autouse=True)
    def data(self, tmp_path):
        lines = [json.dumps({"v": float(i + 1)}) for i in range(5)]
        self.path = _write("\n".join(lines) + "\n")
        yield
        os.unlink(self.path)

    def test_values(self):
        r = _run(self.path, "ndjson", "/v", "values")
        assert "values" in r
        assert len(r["values"]) == 5
        assert r["values"] == [1.0, 2.0, 3.0, 4.0, 5.0]


# ---------------------------------------------------------------------------
# Test: median with odd count  (catches unsorted values bug)
# ---------------------------------------------------------------------------
class TestMedianOdd:
    """Median of odd-length set requires sorting values first."""

    @pytest.fixture(autouse=True)
    def data(self, tmp_path):
        vals = [50.0, 10.0, 40.0, 20.0, 30.0]
        lines = [json.dumps({"v": x}) for x in vals]
        self.path = _write("\n".join(lines) + "\n")
        yield
        os.unlink(self.path)

    def test_median_odd(self):
        r = _run(self.path, "ndjson", "/v", "median")
        assert abs(r["result"] - 30.0) < 0.01


# ---------------------------------------------------------------------------
# Test: median with even count  (catches even-length averaging bug)
# ---------------------------------------------------------------------------
class TestMedianEven:
    """Median of even-length set averages the two middle values."""

    @pytest.fixture(autouse=True)
    def data(self, tmp_path):
        vals = [40.0, 10.0, 30.0, 20.0]
        lines = [json.dumps({"v": x}) for x in vals]
        self.path = _write("\n".join(lines) + "\n")
        yield
        os.unlink(self.path)

    def test_median_even(self):
        r = _run(self.path, "ndjson", "/v", "median")
        assert abs(r["result"] - 25.0) < 0.01


# ---------------------------------------------------------------------------
# Test: stddev  (catches wrong mean denominator + Bessel's correction bugs)
# ---------------------------------------------------------------------------
class TestStddev:
    """Population stddev must use valid_documents for mean and N for variance."""

    @pytest.fixture(autouse=True)
    def data(self, tmp_path):
        lines = []
        for val in [10.0, 20.0, 30.0]:
            lines.append(json.dumps({"v": val}))
        lines.append(json.dumps({"other": 1}))
        lines.append(json.dumps({"other": 2}))
        self.path = _write("\n".join(lines) + "\n")
        yield
        os.unlink(self.path)

    def test_stddev(self):
        expected = math.sqrt(200.0 / 3.0)
        r = _run(self.path, "ndjson", "/v", "stddev")
        assert abs(r["result"] - expected) < 0.01, (
            f"expected stddev ~ {expected:.5f}, got {r['result']}"
        )


# ---------------------------------------------------------------------------
# Test: stddev single value  (catches division by (n-1) when n=1)
# ---------------------------------------------------------------------------
class TestStddevSingleValue:
    """Stddev of a single value must be 0, not NaN from division by zero."""

    @pytest.fixture(autouse=True)
    def data(self, tmp_path):
        lines = [json.dumps({"v": 42.0})]
        self.path = _write("\n".join(lines) + "\n")
        yield
        os.unlink(self.path)

    def test_stddev_single(self):
        r = _run(self.path, "ndjson", "/v", "stddev")
        assert abs(r["result"]) < 0.01, (
            f"expected stddev = 0.0 for single value, got {r['result']}"
        )


# ---------------------------------------------------------------------------
# Test: stddev all same values  (verifies formula correctness)
# ---------------------------------------------------------------------------
class TestStddevAllSame:
    """Stddev of identical values must be 0."""

    @pytest.fixture(autouse=True)
    def data(self, tmp_path):
        lines = [json.dumps({"v": 7.0}) for _ in range(6)]
        self.path = _write("\n".join(lines) + "\n")
        yield
        os.unlink(self.path)

    def test_stddev_zero(self):
        r = _run(self.path, "ndjson", "/v", "stddev")
        assert abs(r["result"]) < 0.01


# ---------------------------------------------------------------------------
# Test: percentile:50 (catches unsorted values + wrong rank formula)
# ---------------------------------------------------------------------------
class TestPercentile50:
    """P50 of unsorted values requires sorting and correct rank formula."""

    @pytest.fixture(autouse=True)
    def data(self, tmp_path):
        vals = [50.0, 10.0, 40.0, 20.0, 30.0]
        lines = [json.dumps({"v": x}) for x in vals]
        self.path = _write("\n".join(lines) + "\n")
        yield
        os.unlink(self.path)

    def test_percentile_50(self):
        # sorted: [10, 20, 30, 40, 50], rank = 0.5 * 4 = 2.0, result = 30.0
        r = _run(self.path, "ndjson", "/v", "percentile:50")
        assert abs(r["result"] - 30.0) < 0.01, (
            f"expected P50 = 30.0, got {r['result']}"
        )


# ---------------------------------------------------------------------------
# Test: percentile:75 with interpolation (catches formula + sort + interp)
# ---------------------------------------------------------------------------
class TestPercentile75Interp:
    """P75 of 4 values requires interpolation between adjacent ranks."""

    @pytest.fixture(autouse=True)
    def data(self, tmp_path):
        vals = [40.0, 10.0, 30.0, 20.0]
        lines = [json.dumps({"v": x}) for x in vals]
        self.path = _write("\n".join(lines) + "\n")
        yield
        os.unlink(self.path)

    def test_percentile_75_interp(self):
        # sorted: [10, 20, 30, 40], rank = 0.75 * 3 = 2.25
        # result = 30 + 0.25 * (40 - 30) = 32.5
        r = _run(self.path, "ndjson", "/v", "percentile:75")
        assert abs(r["result"] - 32.5) < 0.01, (
            f"expected P75 = 32.5, got {r['result']}"
        )


# ---------------------------------------------------------------------------
# Test: group-by basic (catches rewind + accumulation bugs)
# ---------------------------------------------------------------------------
class TestGroupByBasic:
    """Group-by must produce per-group counts and sums."""

    @pytest.fixture(autouse=True)
    def data(self, tmp_path):
        docs = [
            {"category": "A", "value": 10.0},
            {"category": "B", "value": 20.0},
            {"category": "A", "value": 30.0},
            {"category": "B", "value": 40.0},
            {"category": "A", "value": 50.0},
        ]
        lines = [json.dumps(d) for d in docs]
        self.path = _write("\n".join(lines) + "\n")
        yield
        os.unlink(self.path)

    def test_groups_exist_with_counts(self):
        r = _run(self.path, "ndjson", "/value", "count",
                 group_by="/category")
        assert "groups" in r, "output must include 'groups' when --group-by is used"
        assert "A" in r["groups"], "group 'A' should exist"
        assert "B" in r["groups"], "group 'B' should exist"
        assert r["groups"]["A"]["count"] == 3
        assert r["groups"]["B"]["count"] == 2

    def test_per_group_sums(self):
        r = _run(self.path, "ndjson", "/value", "sum",
                 group_by="/category")
        assert abs(r["groups"]["A"]["sum"] - 90.0) < 0.01
        assert abs(r["groups"]["B"]["sum"] - 60.0) < 0.01
        assert abs(r["groups"]["A"]["result"] - 90.0) < 0.01
        assert abs(r["groups"]["B"]["result"] - 60.0) < 0.01


# ---------------------------------------------------------------------------
# Test: group-by accumulation (catches replace-instead-of-accumulate bug)
# ---------------------------------------------------------------------------
class TestGroupByAccumulation:
    """Same group key across multiple documents must accumulate, not replace."""

    @pytest.fixture(autouse=True)
    def data(self, tmp_path):
        docs = [
            {"region": "us", "latency": 10.0},
            {"region": "us", "latency": 20.0},
            {"region": "us", "latency": 30.0},
        ]
        lines = [json.dumps(d) for d in docs]
        self.path = _write("\n".join(lines) + "\n")
        yield
        os.unlink(self.path)

    def test_accumulation(self):
        r = _run(self.path, "ndjson", "/latency", "sum",
                 group_by="/region")
        assert "us" in r["groups"], "group 'us' should exist"
        assert r["groups"]["us"]["count"] == 3, (
            f"expected count 3 for 'us', got {r['groups']['us']['count']}"
        )
        assert abs(r["groups"]["us"]["sum"] - 60.0) < 0.01, (
            f"expected sum 60.0, got {r['groups']['us']['sum']}"
        )


# ---------------------------------------------------------------------------
# Test: group-by with avg (catches per-group denominator bug)
# ---------------------------------------------------------------------------
class TestGroupByAvg:
    """Per-group avg must use per-group count, not global total_documents."""

    @pytest.fixture(autouse=True)
    def data(self, tmp_path):
        docs = [
            {"region": "us", "latency": 10.0},
            {"region": "eu", "latency": 20.0},
            {"region": "us", "latency": 30.0},
            {"region": "eu", "latency": 40.0},
            {"name": "missing_fields"},
            {"name": "also_missing"},
        ]
        lines = [json.dumps(d) for d in docs]
        self.path = _write("\n".join(lines) + "\n")
        yield
        os.unlink(self.path)

    def test_per_group_avg(self):
        r = _run(self.path, "ndjson", "/latency", "avg",
                 group_by="/region")
        # Global: values=[10,20,30,40], avg = 100/4 = 25.0
        assert abs(r["result"] - 25.0) < 0.01, (
            f"expected global avg 25.0, got {r['result']}"
        )
        # Per-group: us=[10,30] avg=20, eu=[20,40] avg=30
        assert abs(r["groups"]["us"]["result"] - 20.0) < 0.01, (
            f"expected us avg 20.0, got {r['groups']['us']['result']}"
        )
        assert abs(r["groups"]["eu"]["result"] - 30.0) < 0.01, (
            f"expected eu avg 30.0, got {r['groups']['eu']['result']}"
        )
