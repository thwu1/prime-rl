"""
Verification tests for NIST SP 800-22 PRNG Forensic Analysis.

"""

import json
import os
import sqlite3

import pytest

EXPECTED_TESTS = [
    "frequency_monobit",
    "frequency_block",
    "runs",
    "longest_run_ones",
    "binary_matrix_rank",
    "dft_spectral",
    "non_overlapping_template",
    "serial",
    "approximate_entropy",
    "cumulative_sums",
]

EXPECTED_CLASSIFICATIONS = {
    "sample_alpha.bin": "high_quality_prng",
    "sample_beta.bin": "short_period_lcg",
    "sample_gamma.bin": "biased",
    "sample_delta.bin": "short_period_lfsr",
    "sample_epsilon.bin": "serial_correlated",
}

SAMPLES = list(EXPECTED_CLASSIFICATIONS.keys())
ALPHA = 0.01


# ===== Sample files exist and are correctly sized =====


class TestSamplesExist:
    def test_samples_directory_exists(self):
        assert os.path.isdir("/app/samples"), "/app/samples directory missing"

    @pytest.mark.parametrize("name", SAMPLES)
    def test_sample_file_exists(self, name):
        path = os.path.join("/app/samples", name)
        assert os.path.isfile(path), f"Missing sample: {name}"

    @pytest.mark.parametrize("name", SAMPLES)
    def test_sample_size(self, name):
        path = os.path.join("/app/samples", name)
        size = os.path.getsize(path)
        assert size == 125000, f"{name}: expected 125000 bytes, got {size}"


# ===== SQLite Database Structure =====


class TestDatabaseStructure:
    @pytest.fixture(autouse=True)
    def setup_db(self):
        path = "/app/rng_analysis.db"
        assert os.path.isfile(path), "rng_analysis.db not found at /app/"
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        yield
        self.conn.close()

    def test_test_results_table_exists(self):
        cur = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='test_results'"
        )
        assert cur.fetchone() is not None, "Table 'test_results' missing"

    def test_classifications_table_exists(self):
        cur = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='classifications'"
        )
        assert cur.fetchone() is not None, "Table 'classifications' missing"

    def test_test_results_columns(self):
        cur = self.conn.execute("PRAGMA table_info(test_results)")
        cols = {row[1] for row in cur.fetchall()}
        required = {"sample_name", "test_name", "p_value", "pass"}
        missing = required - cols
        assert not missing, f"test_results missing columns: {missing}"

    def test_classifications_columns(self):
        cur = self.conn.execute("PRAGMA table_info(classifications)")
        cols = {row[1] for row in cur.fetchall()}
        required = {"sample_name", "generator_type"}
        missing = required - cols
        assert not missing, f"classifications missing columns: {missing}"


# ===== Test Results Verification =====


class TestResultsData:
    @pytest.fixture(autouse=True)
    def setup_db(self):
        self.conn = sqlite3.connect("/app/rng_analysis.db")
        self.conn.row_factory = sqlite3.Row
        yield
        self.conn.close()

    def test_result_count(self):
        """Must have 5 samples x 10 tests = 50 results."""
        cur = self.conn.execute("SELECT COUNT(*) FROM test_results")
        count = cur.fetchone()[0]
        assert count >= 50, f"Expected >= 50 test results, got {count}"

    @pytest.mark.parametrize("sample", SAMPLES)
    @pytest.mark.parametrize("test_name", EXPECTED_TESTS)
    def test_result_present(self, sample, test_name):
        cur = self.conn.execute(
            "SELECT p_value, pass FROM test_results "
            "WHERE sample_name=? AND test_name=?",
            (sample, test_name),
        )
        row = cur.fetchone()
        assert row is not None, f"Missing result: {sample}/{test_name}"

    @pytest.mark.parametrize("sample", SAMPLES)
    @pytest.mark.parametrize("test_name", EXPECTED_TESTS)
    def test_p_value_valid(self, sample, test_name):
        cur = self.conn.execute(
            "SELECT p_value FROM test_results "
            "WHERE sample_name=? AND test_name=?",
            (sample, test_name),
        )
        row = cur.fetchone()
        if row is not None:
            p = row[0]
            assert 0.0 <= p <= 1.0, (
                f"{sample}/{test_name}: p_value {p} out of [0,1]"
            )

    @pytest.mark.parametrize("sample", SAMPLES)
    @pytest.mark.parametrize("test_name", EXPECTED_TESTS)
    def test_pass_consistent_with_p_value(self, sample, test_name):
        """Pass/fail must be consistent with p_value >= alpha."""
        cur = self.conn.execute(
            "SELECT p_value, pass FROM test_results "
            "WHERE sample_name=? AND test_name=?",
            (sample, test_name),
        )
        row = cur.fetchone()
        if row is not None:
            expected_pass = 1 if row[0] >= ALPHA else 0
            assert row[1] == expected_pass, (
                f"{sample}/{test_name}: pass={row[1]} but p={row[0]}"
            )


# ===== Known Statistical Outcomes =====


class TestKnownOutcomes:
    @pytest.fixture(autouse=True)
    def setup_db(self):
        self.conn = sqlite3.connect("/app/rng_analysis.db")
        self.conn.row_factory = sqlite3.Row
        yield
        self.conn.close()

    def _get_pass(self, sample, test_name):
        cur = self.conn.execute(
            "SELECT pass FROM test_results WHERE sample_name=? AND test_name=?",
            (sample, test_name),
        )
        row = cur.fetchone()
        assert row is not None, f"Missing result: {sample}/{test_name}"
        return row[0]

    # -- Biased generator (gamma): P(1) = 0.45 --

    def test_gamma_fails_monobit(self):
        """Biased generator must fail frequency monobit test."""
        assert self._get_pass("sample_gamma.bin", "frequency_monobit") == 0

    def test_gamma_fails_block_freq(self):
        """Biased generator must fail block frequency test."""
        assert self._get_pass("sample_gamma.bin", "frequency_block") == 0

    # -- LFSR-16 (delta): linear structure over GF(2) --

    def test_delta_fails_rank(self):
        """LFSR-16 must fail binary matrix rank (linear dependency)."""
        assert self._get_pass("sample_delta.bin", "binary_matrix_rank") == 0

    def test_delta_passes_monobit(self):
        """LFSR-16 is balanced and must pass monobit."""
        assert self._get_pass("sample_delta.bin", "frequency_monobit") == 1

    # -- Markov chain (epsilon): P(transition) = 0.3 --

    def test_epsilon_fails_runs(self):
        """Markov chain must fail runs test (serial correlation)."""
        assert self._get_pass("sample_epsilon.bin", "runs") == 0

    def test_epsilon_fails_serial(self):
        """Markov chain must fail serial test."""
        assert self._get_pass("sample_epsilon.bin", "serial") == 0

    def test_epsilon_passes_monobit(self):
        """Symmetric Markov chain is balanced and must pass monobit."""
        assert self._get_pass("sample_epsilon.bin", "frequency_monobit") == 1

    # -- LCG (beta): short period, high-byte extraction --

    def test_beta_fails_spectral(self):
        """Short-period LCG must fail DFT spectral test."""
        assert self._get_pass("sample_beta.bin", "dft_spectral") == 0

    def test_beta_passes_monobit(self):
        """LCG high-byte is balanced and must pass monobit."""
        assert self._get_pass("sample_beta.bin", "frequency_monobit") == 1

    # -- SHA-256 counter mode (alpha): high quality --

    def test_alpha_passes_most(self):
        """SHA-256 counter mode should pass at least 8 of 10 tests."""
        cur = self.conn.execute(
            "SELECT SUM(pass) FROM test_results "
            "WHERE sample_name='sample_alpha.bin'"
        )
        passes = cur.fetchone()[0]
        assert passes is not None and passes >= 8, (
            f"SHA-256 passed only {passes}/10 tests"
        )


# ===== results.json Verification =====


class TestResultsJSON:
    @pytest.fixture(autouse=True)
    def load_results(self):
        path = "/app/results.json"
        assert os.path.isfile(path), "results.json not found"
        with open(path) as f:
            self.results = json.load(f)

    @pytest.mark.parametrize("name", SAMPLES)
    def test_sample_in_results(self, name):
        assert name in self.results, f"Missing results for {name}"

    @pytest.mark.parametrize("name", SAMPLES)
    @pytest.mark.parametrize("test_name", EXPECTED_TESTS)
    def test_test_present(self, name, test_name):
        assert test_name in self.results[name], (
            f"Missing test '{test_name}' for {name}"
        )

    @pytest.mark.parametrize("name", SAMPLES)
    @pytest.mark.parametrize("test_name", EXPECTED_TESTS)
    def test_p_value_valid(self, name, test_name):
        entry = self.results[name][test_name]
        assert "p_value" in entry, f"{name}/{test_name}: missing p_value"
        p = entry["p_value"]
        assert isinstance(p, (int, float)), (
            f"{name}/{test_name}: p_value not numeric"
        )
        assert 0.0 <= p <= 1.0, f"{name}/{test_name}: p_value {p} out of [0,1]"

    @pytest.mark.parametrize("name", SAMPLES)
    @pytest.mark.parametrize("test_name", EXPECTED_TESTS)
    def test_pass_field_valid(self, name, test_name):
        entry = self.results[name][test_name]
        assert "pass" in entry, f"{name}/{test_name}: missing 'pass'"
        assert isinstance(entry["pass"], bool), (
            f"{name}/{test_name}: 'pass' not bool"
        )

    @pytest.mark.parametrize("name", SAMPLES)
    @pytest.mark.parametrize("test_name", EXPECTED_TESTS)
    def test_pass_consistent_with_p_value(self, name, test_name):
        """Pass/fail must be consistent with p_value >= alpha."""
        entry = self.results[name][test_name]
        p = entry["p_value"]
        expected_pass = p >= ALPHA
        assert entry["pass"] == expected_pass, (
            f"{name}/{test_name}: pass={entry['pass']} but p={p} "
            f"(expected pass={expected_pass} at alpha={ALPHA})"
        )


# ===== Classification correctness =====


class TestClassification:
    @pytest.fixture(autouse=True)
    def load_data(self):
        path = "/app/analysis.json"
        assert os.path.isfile(path), "analysis.json not found"
        with open(path) as f:
            self.classification = json.load(f)
        self.conn = sqlite3.connect("/app/rng_analysis.db")
        yield
        self.conn.close()

    @pytest.mark.parametrize(
        "name,expected", list(EXPECTED_CLASSIFICATIONS.items())
    )
    def test_classification_correct_json(self, name, expected):
        assert name in self.classification, f"Missing classification for {name}"
        assert self.classification[name] == expected, (
            f"{name}: expected '{expected}', got '{self.classification[name]}'"
        )

    @pytest.mark.parametrize(
        "name,expected", list(EXPECTED_CLASSIFICATIONS.items())
    )
    def test_classification_correct_db(self, name, expected):
        cur = self.conn.execute(
            "SELECT generator_type FROM classifications WHERE sample_name=?",
            (name,),
        )
        row = cur.fetchone()
        assert row is not None, f"Missing DB classification for {name}"
        assert row[0] == expected, (
            f"{name}: DB says '{row[0]}', expected '{expected}'"
        )
