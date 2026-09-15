
import json
import os
import subprocess
import pytest

RESULTS_PATH = "/app/results.json"

EXPECTED = {
    "1": {"work": 1048575, "span": 20},
    "2": {"work": 131070, "span": 32},
    "3": {"work": 14155776, "span": 171},
    "4": {"work": 159744, "span": 15},
    "5": {"work": 395599, "span": 15},
    "6": {"work": 128878019, "span": 120},
    "7": {"T_P": 491730},
    "8": {"T_P": 262164},
    "9": {"T_P": 5226532},
    "10": {"work": 63963135, "span": 230},
    "11": {"work": 196605, "span": 48},
    "12": {"n": 8192},
    "13": {"processors": 524288},
    "14": {"n": 32768},
    "15": {"threshold": 4096, "T_P": 639108},
    "16": {"T_P": 258318},
    "17": {"threshold": 256, "T_P": 44221},
    "18": {"processors": 262144},
    "19": {"threshold": 16, "T_P": 29323},
}


@pytest.fixture(scope="module")
def results():
    assert os.path.exists(RESULTS_PATH), (
        f"Results file not found at {RESULTS_PATH}"
    )
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


class TestEvaluateReduce:
    def test_work(self, results):
        assert int(results["1"]["work"]) == EXPECTED["1"]["work"]

    def test_span(self, results):
        assert int(results["1"]["span"]) == EXPECTED["1"]["span"]


class TestEvaluateScan:
    def test_work(self, results):
        assert int(results["2"]["work"]) == EXPECTED["2"]["work"]

    def test_span(self, results):
        assert int(results["2"]["span"]) == EXPECTED["2"]["span"]


class TestEvaluateMergesort:
    def test_work(self, results):
        assert int(results["3"]["work"]) == EXPECTED["3"]["work"]

    def test_span(self, results):
        assert int(results["3"]["span"]) == EXPECTED["3"]["span"]


class TestEvaluateStandardMatmul:
    def test_work(self, results):
        assert int(results["4"]["work"]) == EXPECTED["4"]["work"]

    def test_span(self, results):
        assert int(results["4"]["span"]) == EXPECTED["4"]["span"]


class TestEvaluateStrassenMatmul:
    def test_work(self, results):
        assert int(results["5"]["work"]) == EXPECTED["5"]["work"]

    def test_span(self, results):
        assert int(results["5"]["span"]) == EXPECTED["5"]["span"]


class TestEvaluateKaratsuba:
    def test_work(self, results):
        assert int(results["6"]["work"]) == EXPECTED["6"]["work"]

    def test_span(self, results):
        assert int(results["6"]["span"]) == EXPECTED["6"]["span"]


class TestBrentMergesort:
    def test_t_p(self, results):
        assert int(results["7"]["T_P"]) == EXPECTED["7"]["T_P"]


class TestBrentReduce:
    def test_t_p(self, results):
        assert int(results["8"]["T_P"]) == EXPECTED["8"]["T_P"]


class TestBrentStandardMatmul:
    def test_t_p(self, results):
        assert int(results["9"]["T_P"]) == EXPECTED["9"]["T_P"]


class TestCompositionMergesortReduce:
    def test_work(self, results):
        assert int(results["10"]["work"]) == EXPECTED["10"]["work"]

    def test_span(self, results):
        assert int(results["10"]["span"]) == EXPECTED["10"]["span"]


class TestCompositionScanReduce:
    def test_work(self, results):
        assert int(results["11"]["work"]) == EXPECTED["11"]["work"]

    def test_span(self, results):
        assert int(results["11"]["span"]) == EXPECTED["11"]["span"]


class TestCrossover:
    def test_n(self, results):
        assert int(results["12"]["n"]) == EXPECTED["12"]["n"]


class TestOptimalProcessors:
    def test_processors(self, results):
        assert int(results["13"]["processors"]) == EXPECTED["13"]["processors"]


class TestMinParallelismN:
    def test_n(self, results):
        assert int(results["14"]["n"]) == EXPECTED["14"]["n"]


class TestGranularity:
    def test_threshold(self, results):
        assert int(results["15"]["threshold"]) == EXPECTED["15"]["threshold"]

    def test_t_p(self, results):
        assert int(results["15"]["T_P"]) == EXPECTED["15"]["T_P"]


class TestCompositionBrent:
    def test_t_p(self, results):
        assert int(results["16"]["T_P"]) == EXPECTED["16"]["T_P"]


class TestPipelineGranularity:
    def test_threshold(self, results):
        assert int(results["17"]["threshold"]) == EXPECTED["17"]["threshold"]

    def test_t_p(self, results):
        assert int(results["17"]["T_P"]) == EXPECTED["17"]["T_P"]


class TestEfficiencyThreshold:
    def test_processors(self, results):
        assert int(results["18"]["processors"]) == EXPECTED["18"]["processors"]


class TestStrassenGranularity:
    def test_threshold(self, results):
        assert int(results["19"]["threshold"]) == EXPECTED["19"]["threshold"]

    def test_t_p(self, results):
        assert int(results["19"]["T_P"]) == EXPECTED["19"]["T_P"]


class TestMakefilePipeline:
    """Verify the Makefile pipeline works end-to-end."""

    def test_makefile_exists(self):
        assert os.path.exists("/app/Makefile"), "Makefile not found at /app/Makefile"

    def test_make_rebuilds_correctly(self):
        result = subprocess.run(
            ["make", "-C", "/app", "clean"],
            capture_output=True, timeout=60
        )
        assert result.returncode == 0, f"make clean failed: {result.stderr.decode()}"

        result = subprocess.run(
            ["make", "-C", "/app", "results"],
            capture_output=True, timeout=120
        )
        assert result.returncode == 0, f"make results failed: {result.stderr.decode()}"

        assert os.path.exists(RESULTS_PATH), "make results did not produce results.json"
        with open(RESULTS_PATH) as f:
            rebuilt = json.load(f)
        for qid, expected in EXPECTED.items():
            for field, val in expected.items():
                assert int(rebuilt[qid][field]) == val, (
                    f"Rebuilt result mismatch: query {qid} field {field}"
                )

    def test_makefile_uses_sqlite(self):
        with open("/app/Makefile") as f:
            content = f.read()
        assert "sqlite3" in content, (
            "Makefile must use sqlite3 for database extraction"
        )
