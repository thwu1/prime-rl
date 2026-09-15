#!/usr/bin/env python3
"""Tests for FIMI mining pipeline.

Verifies correctness across all modes, multi-tool pipeline integration,
SQLite results storage, AWK normalization, and GNU Make orchestration.
Uses dynamic dataset generation and brute-force reference computation
to prevent answer pre-computation.
"""


import subprocess
import os
import json
import sqlite3 as sqlite3_mod
import random
import pytest
from collections import defaultdict
from itertools import combinations


# ============================================================================
# Brute-force reference implementation for dynamic verification
# ============================================================================

def brute_force_all(transactions, min_support):
    """Compute all frequent itemsets by exhaustive enumeration."""
    n_txn = len(transactions)
    all_items = set()
    for t in transactions:
        all_items |= t

    results = []
    if n_txn >= min_support:
        results.append((frozenset(), n_txn))

    for size in range(1, len(all_items) + 1):
        found_any = False
        for combo in combinations(sorted(all_items), size):
            itemset = frozenset(combo)
            support = sum(1 for t in transactions if itemset <= t)
            if support >= min_support:
                results.append((itemset, support))
                found_any = True
        if not found_any:
            break
    return results


def filter_closed(all_frequent):
    """Filter to closed frequent itemsets."""
    closed = []
    for items, sup in all_frequent:
        is_closed = True
        for other, other_sup in all_frequent:
            if items < other and sup == other_sup:
                is_closed = False
                break
        if is_closed:
            closed.append((items, sup))
    return closed


def filter_maximal(all_frequent):
    """Filter to maximal frequent itemsets."""
    freq_sets = {items for items, _ in all_frequent}
    maximal = []
    for items, sup in all_frequent:
        is_maximal = True
        for other in freq_sets:
            if items < other:
                is_maximal = False
                break
        if is_maximal:
            maximal.append((items, sup))
    return maximal


def compute_per_length(itemsets):
    """Compute per-length count array from itemset list."""
    if not itemsets:
        return []
    max_len = max(len(s) for s, _ in itemsets)
    counts = [0] * (max_len + 1)
    for items, _ in itemsets:
        counts[len(items)] += 1
    return counts


def generate_dataset(seed, n_txn, items, density):
    """Generate a deterministic random transaction dataset."""
    rng = random.Random(seed)
    transactions = []
    for _ in range(n_txn):
        txn = frozenset(item for item in items if rng.random() < density)
        if not txn:
            txn = frozenset([rng.choice(items)])
        transactions.append(txn)
    return transactions


def write_fimi_dataset(transactions, path):
    """Write transactions in standard FIMI format."""
    with open(path, "w") as f:
        for txn in transactions:
            f.write(" ".join(str(x) for x in sorted(txn)) + "\n")


def parse_raw_dataset(path):
    """Parse a non-standard dataset for reference computation."""
    transactions = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '|' in line:
                parts = line.split('|', 1)
                if len(parts) == 2:
                    line = parts[1]
            if ',' in line:
                tokens = line.split(',')
            else:
                tokens = line.split()
            items = set()
            for t in tokens:
                t = t.strip()
                try:
                    items.add(int(t))
                except ValueError:
                    pass
            if items:
                transactions.append(frozenset(items))
    return transactions


# ============================================================================
# Tool execution helpers
# ============================================================================

def run_fim(mode, dataset, min_support, output_file=None, timeout=120):
    """Run the fim tool and return CompletedProcess."""
    cmd = ["/app/fim", mode, dataset, str(min_support)]
    if output_file:
        cmd.append(output_file)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def parse_fimi04_stdout(stdout):
    """Parse FIMI'04 stdout: total first, then per-length counts."""
    lines = [l.strip() for l in stdout.strip().split("\n") if l.strip()]
    nums = [int(x) for x in lines]
    total = nums[0]
    per_length = nums[1:]
    return total, per_length


def parse_output_file(filepath):
    """Parse FIMI output file into list of (frozenset, support)."""
    itemsets = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            paren_idx = line.rindex("(")
            items_part = line[:paren_idx].strip()
            support = int(line[paren_idx + 1:-1].strip())
            items = frozenset(int(x) for x in items_part.split()) if items_part else frozenset()
            itemsets.append((items, support))
    return itemsets


# ============================================================================
# Test: Basic executable checks
# ============================================================================

class TestFimExecutable:
    def test_exists(self):
        assert os.path.isfile("/app/fim"), "/app/fim must exist"

    def test_executable(self):
        assert os.access("/app/fim", os.X_OK), "/app/fim must be executable"

    def test_usage_error(self):
        result = subprocess.run(["/app/fim"], capture_output=True, text=True)
        assert result.returncode != 0


# ============================================================================
# Test: Dynamic dataset verification (anti-cheat - computed at test time)
# ============================================================================

class TestDynamicDatasetAll:
    """Verify all-mode on a dynamically generated dataset."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.items = list(range(8))
        self.txns = generate_dataset(seed=42, n_txn=15, items=self.items, density=0.5)
        self.dataset_path = str(tmp_path / "dynamic_42.dat")
        write_fimi_dataset(self.txns, self.dataset_path)
        self.min_support = 5
        self.expected_all = brute_force_all(self.txns, self.min_support)
        self.expected_per_length = compute_per_length(self.expected_all)

    def test_total_count(self, tmp_path):
        output = str(tmp_path / "out.txt")
        result = run_fim("all", self.dataset_path, self.min_support, output)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        total, _ = parse_fimi04_stdout(result.stdout)
        assert total == len(self.expected_all)

    def test_per_length_counts(self, tmp_path):
        result = run_fim("all", self.dataset_path, self.min_support)
        assert result.returncode == 0
        _, per_length = parse_fimi04_stdout(result.stdout)
        assert per_length == self.expected_per_length

    def test_total_first_line(self, tmp_path):
        result = run_fim("all", self.dataset_path, self.min_support)
        assert result.returncode == 0
        total, per_length = parse_fimi04_stdout(result.stdout)
        assert total == sum(per_length)

    def test_output_file_itemsets(self, tmp_path):
        output = str(tmp_path / "out.txt")
        result = run_fim("all", self.dataset_path, self.min_support, output)
        assert result.returncode == 0
        actual = parse_output_file(output)
        expected_map = {items: sup for items, sup in self.expected_all}
        actual_map = {items: sup for items, sup in actual}
        assert actual_map == expected_map


class TestDynamicDatasetClosed:
    """Verify closed-mode on a dynamically generated dataset."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.items = list(range(8))
        self.txns = generate_dataset(seed=42, n_txn=15, items=self.items, density=0.5)
        self.dataset_path = str(tmp_path / "dynamic_42.dat")
        write_fimi_dataset(self.txns, self.dataset_path)
        self.min_support = 5
        all_freq = brute_force_all(self.txns, self.min_support)
        self.expected_closed = filter_closed(all_freq)
        self.expected_per_length = compute_per_length(self.expected_closed)

    def test_total_count(self, tmp_path):
        output = str(tmp_path / "out.txt")
        result = run_fim("closed", self.dataset_path, self.min_support, output)
        assert result.returncode == 0
        total, _ = parse_fimi04_stdout(result.stdout)
        assert total == len(self.expected_closed)

    def test_per_length_counts(self, tmp_path):
        result = run_fim("closed", self.dataset_path, self.min_support)
        assert result.returncode == 0
        _, per_length = parse_fimi04_stdout(result.stdout)
        assert per_length == self.expected_per_length

    def test_closure_property(self, tmp_path):
        output = str(tmp_path / "out.txt")
        result = run_fim("closed", self.dataset_path, self.min_support, output)
        assert result.returncode == 0
        itemsets = parse_output_file(output)
        by_support = defaultdict(list)
        for items, sup in itemsets:
            by_support[sup].append(items)
        for sup, sets in by_support.items():
            for i, s1 in enumerate(sets):
                for s2 in sets[i + 1:]:
                    if s1 < s2 or s2 < s1:
                        pytest.fail(
                            f"Closure violation at support {sup}: "
                            f"{sorted(s1)} and {sorted(s2)}"
                        )


class TestDynamicDatasetMaximal:
    """Verify maximal-mode on a dynamically generated dataset."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.items = list(range(8))
        self.txns = generate_dataset(seed=42, n_txn=15, items=self.items, density=0.5)
        self.dataset_path = str(tmp_path / "dynamic_42.dat")
        write_fimi_dataset(self.txns, self.dataset_path)
        self.min_support = 5
        all_freq = brute_force_all(self.txns, self.min_support)
        self.expected_maximal = filter_maximal(all_freq)
        self.expected_per_length = compute_per_length(self.expected_maximal)

    def test_total_count(self, tmp_path):
        output = str(tmp_path / "out.txt")
        result = run_fim("maximal", self.dataset_path, self.min_support, output)
        assert result.returncode == 0
        total, _ = parse_fimi04_stdout(result.stdout)
        assert total == len(self.expected_maximal)

    def test_per_length_counts(self, tmp_path):
        result = run_fim("maximal", self.dataset_path, self.min_support)
        assert result.returncode == 0
        _, per_length = parse_fimi04_stdout(result.stdout)
        assert per_length == self.expected_per_length

    def test_maximality_property(self, tmp_path):
        output = str(tmp_path / "out.txt")
        all_output = str(tmp_path / "all.txt")
        run_fim("all", self.dataset_path, self.min_support, all_output)
        result = run_fim("maximal", self.dataset_path, self.min_support, output)
        assert result.returncode == 0
        all_sets = {items for items, _ in parse_output_file(all_output)}
        for max_set, _ in parse_output_file(output):
            for other in all_sets:
                if max_set < other:
                    pytest.fail(
                        f"Maximality violation: {sorted(max_set)} has "
                        f"frequent superset {sorted(other)}"
                    )


class TestDynamicDatasetSecond:
    """Second dynamic dataset with different parameters for robustness."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.items = [10, 20, 30, 40, 50, 60]
        self.txns = generate_dataset(seed=137, n_txn=12, items=self.items, density=0.55)
        self.dataset_path = str(tmp_path / "dynamic_137.dat")
        write_fimi_dataset(self.txns, self.dataset_path)
        self.min_support = 4
        self.all_freq = brute_force_all(self.txns, self.min_support)
        self.closed = filter_closed(self.all_freq)
        self.maximal = filter_maximal(self.all_freq)

    def test_all_counts(self, tmp_path):
        result = run_fim("all", self.dataset_path, self.min_support)
        assert result.returncode == 0
        total, per_length = parse_fimi04_stdout(result.stdout)
        assert total == len(self.all_freq)
        assert per_length == compute_per_length(self.all_freq)

    def test_closed_counts(self, tmp_path):
        result = run_fim("closed", self.dataset_path, self.min_support)
        assert result.returncode == 0
        total, per_length = parse_fimi04_stdout(result.stdout)
        assert total == len(self.closed)
        assert per_length == compute_per_length(self.closed)

    def test_maximal_counts(self, tmp_path):
        result = run_fim("maximal", self.dataset_path, self.min_support)
        assert result.returncode == 0
        total, per_length = parse_fimi04_stdout(result.stdout)
        assert total == len(self.maximal)
        assert per_length == compute_per_length(self.maximal)

    def test_all_output_exact(self, tmp_path):
        output = str(tmp_path / "out.txt")
        result = run_fim("all", self.dataset_path, self.min_support, output)
        assert result.returncode == 0
        actual = parse_output_file(output)
        expected_map = {items: sup for items, sup in self.all_freq}
        actual_map = {items: sup for items, sup in actual}
        assert actual_map == expected_map


# ============================================================================
# Test: Synth dataset verification (brute-force reference, not hardcoded)
# ============================================================================

class TestSynthDataset:
    """Verify on synth_test.dat using brute-force reference computation."""

    @pytest.fixture(autouse=True)
    def setup(self):
        txns = []
        with open("/app/data/synth_test.dat") as f:
            for line in f:
                line = line.strip()
                if line:
                    txns.append(frozenset(int(x) for x in line.split()))
        self.txns = txns
        self.min_support = 3
        self.all_freq = brute_force_all(txns, self.min_support)
        self.closed = filter_closed(self.all_freq)
        self.maximal = filter_maximal(self.all_freq)

    def test_all_total(self):
        result = run_fim("all", "/app/data/synth_test.dat", 3)
        assert result.returncode == 0
        total, _ = parse_fimi04_stdout(result.stdout)
        assert total == len(self.all_freq)

    def test_all_per_length(self):
        result = run_fim("all", "/app/data/synth_test.dat", 3)
        assert result.returncode == 0
        _, per_length = parse_fimi04_stdout(result.stdout)
        assert per_length == compute_per_length(self.all_freq)

    def test_closed_total(self):
        result = run_fim("closed", "/app/data/synth_test.dat", 3)
        assert result.returncode == 0
        total, _ = parse_fimi04_stdout(result.stdout)
        assert total == len(self.closed)

    def test_closed_per_length(self):
        result = run_fim("closed", "/app/data/synth_test.dat", 3)
        assert result.returncode == 0
        _, per_length = parse_fimi04_stdout(result.stdout)
        assert per_length == compute_per_length(self.closed)

    def test_maximal_total(self):
        result = run_fim("maximal", "/app/data/synth_test.dat", 3)
        assert result.returncode == 0
        total, _ = parse_fimi04_stdout(result.stdout)
        assert total == len(self.maximal)

    def test_maximal_per_length(self):
        result = run_fim("maximal", "/app/data/synth_test.dat", 3)
        assert result.returncode == 0
        _, per_length = parse_fimi04_stdout(result.stdout)
        assert per_length == compute_per_length(self.maximal)

    def test_output_file_all(self, tmp_path):
        output = str(tmp_path / "out.txt")
        result = run_fim("all", "/app/data/synth_test.dat", 3, output)
        assert result.returncode == 0
        actual = parse_output_file(output)
        expected_map = {items: sup for items, sup in self.all_freq}
        actual_map = {items: sup for items, sup in actual}
        assert actual_map == expected_map


# ============================================================================
# Test: Non-standard format handling (brute-force reference)
# ============================================================================

class TestNonStandardFormat:
    """Verify handling of non-standard mixed_basket.csv dataset."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.txns = parse_raw_dataset("/app/data/raw/mixed_basket.csv")
        self.min_support = 6
        self.all_freq = brute_force_all(self.txns, self.min_support)
        self.closed = filter_closed(self.all_freq)
        self.maximal = filter_maximal(self.all_freq)

    def test_all_total(self):
        result = run_fim("all", "/app/data/raw/mixed_basket.csv", 6)
        assert result.returncode == 0
        total, _ = parse_fimi04_stdout(result.stdout)
        assert total == len(self.all_freq)

    def test_all_per_length(self):
        result = run_fim("all", "/app/data/raw/mixed_basket.csv", 6)
        assert result.returncode == 0
        _, per_length = parse_fimi04_stdout(result.stdout)
        assert per_length == compute_per_length(self.all_freq)

    def test_closed_total(self):
        result = run_fim("closed", "/app/data/raw/mixed_basket.csv", 6)
        assert result.returncode == 0
        total, _ = parse_fimi04_stdout(result.stdout)
        assert total == len(self.closed)

    def test_maximal_total(self):
        result = run_fim("maximal", "/app/data/raw/mixed_basket.csv", 6)
        assert result.returncode == 0
        total, _ = parse_fimi04_stdout(result.stdout)
        assert total == len(self.maximal)

    def test_closed_output_exact(self, tmp_path):
        output = str(tmp_path / "out.txt")
        result = run_fim("closed", "/app/data/raw/mixed_basket.csv", 6, output)
        assert result.returncode == 0
        actual = parse_output_file(output)
        expected_map = {items: sup for items, sup in self.closed}
        actual_map = {items: sup for items, sup in actual}
        assert actual_map == expected_map


# ============================================================================
# Test: AWK normalizer (directly tests tool proficiency requirement)
# ============================================================================

class TestAWKNormalization:
    """Directly verify the AWK normalizer handles various formats."""

    def test_pipe_and_comma_format(self, tmp_path):
        input_file = str(tmp_path / "pipe.csv")
        with open(input_file, "w") as f:
            f.write("TX1|3,1,5,1\n")
            f.write("TX2|2,4\n")
        result = subprocess.run(
            ["awk", "-f", "/app/lib/normalize.awk", input_file],
            capture_output=True, text=True
        )
        assert result.returncode == 0
        lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
        assert len(lines) == 2, f"Expected 2 lines, got {len(lines)}: {lines}"
        items1 = [int(x) for x in lines[0].split()]
        assert items1 == [1, 3, 5], f"Expected [1,3,5] (deduped, sorted), got {items1}"
        items2 = [int(x) for x in lines[1].split()]
        assert items2 == [2, 4], f"Expected [2,4], got {items2}"

    def test_comment_skipping(self, tmp_path):
        input_file = str(tmp_path / "comments.csv")
        with open(input_file, "w") as f:
            f.write("# This is a comment with number 42\n")
            f.write("1 2 3\n")
            f.write("# Another comment 99\n")
            f.write("4 5\n")
        result = subprocess.run(
            ["awk", "-f", "/app/lib/normalize.awk", input_file],
            capture_output=True, text=True
        )
        assert result.returncode == 0
        lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
        assert len(lines) == 2, (
            f"Expected 2 lines (comments skipped), got {len(lines)}: {lines}"
        )

    def test_deduplication(self, tmp_path):
        input_file = str(tmp_path / "dupes.dat")
        with open(input_file, "w") as f:
            f.write("3 1 3 5 1\n")
        result = subprocess.run(
            ["awk", "-f", "/app/lib/normalize.awk", input_file],
            capture_output=True, text=True
        )
        assert result.returncode == 0
        items = [int(x) for x in result.stdout.strip().split()]
        assert items == [1, 3, 5], f"Expected [1,3,5] (deduped, sorted), got {items}"

    def test_mixed_basket_normalization(self):
        """Verify AWK produces correct FIMI output from mixed_basket.csv."""
        result = subprocess.run(
            ["awk", "-f", "/app/lib/normalize.awk", "/app/data/raw/mixed_basket.csv"],
            capture_output=True, text=True
        )
        assert result.returncode == 0
        lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
        ref_txns = parse_raw_dataset("/app/data/raw/mixed_basket.csv")
        assert len(lines) == len(ref_txns), (
            f"Expected {len(ref_txns)} transaction lines, got {len(lines)}"
        )
        for i, line in enumerate(lines):
            items = frozenset(int(x) for x in line.split())
            assert items == ref_txns[i], (
                f"Transaction {i}: expected {sorted(ref_txns[i])}, got {sorted(items)}"
            )


# ============================================================================
# Test: Make pipeline and SQLite (tests tool integration)
# ============================================================================

@pytest.fixture(scope="module")
def pipeline_result():
    """Run make pipeline once for all pipeline tests."""
    if os.path.exists("/app/results.db"):
        os.remove("/app/results.db")
    subprocess.run(["make", "-C", "/app", "clean"],
                    capture_output=True, timeout=60)
    result = subprocess.run(
        ["make", "-C", "/app", "pipeline"],
        capture_output=True, text=True, timeout=300
    )
    return result


class TestMakePipeline:
    """Verify make pipeline runs and populates SQLite database."""

    def test_pipeline_succeeds(self, pipeline_result):
        assert pipeline_result.returncode == 0, (
            f"make pipeline failed:\nstdout: {pipeline_result.stdout}\n"
            f"stderr: {pipeline_result.stderr}"
        )

    def test_db_exists(self, pipeline_result):
        assert pipeline_result.returncode == 0
        assert os.path.isfile("/app/results.db"), "results.db must exist"

    def test_db_schema(self, pipeline_result):
        assert pipeline_result.returncode == 0
        conn = sqlite3_mod.connect("/app/results.db")
        cursor = conn.execute("PRAGMA table_info(mining_results)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()
        required = {
            "job_id", "dataset", "mode", "min_support",
            "total_itemsets", "per_length_counts"
        }
        assert required <= columns, f"Missing columns: {required - columns}"

    def test_db_row_count(self, pipeline_result):
        assert pipeline_result.returncode == 0
        with open("/app/config/pipeline.json") as f:
            config = json.load(f)
        expected_jobs = len(config["jobs"])
        conn = sqlite3_mod.connect("/app/results.db")
        count = conn.execute(
            "SELECT COUNT(*) FROM mining_results"
        ).fetchone()[0]
        conn.close()
        assert count >= expected_jobs, (
            f"Expected >= {expected_jobs} results, got {count}"
        )

    def test_db_per_length_format(self, pipeline_result):
        assert pipeline_result.returncode == 0
        conn = sqlite3_mod.connect("/app/results.db")
        rows = conn.execute(
            "SELECT per_length_counts FROM mining_results"
        ).fetchall()
        conn.close()
        for row in rows:
            data = json.loads(row[0])
            assert isinstance(data, list), (
                f"per_length_counts should be JSON array: {row[0]}"
            )
            assert all(isinstance(x, int) for x in data)

    def test_db_consistency(self, pipeline_result):
        assert pipeline_result.returncode == 0
        conn = sqlite3_mod.connect("/app/results.db")
        rows = conn.execute(
            "SELECT total_itemsets, per_length_counts FROM mining_results"
        ).fetchall()
        conn.close()
        for total, per_length_json in rows:
            per_length = json.loads(per_length_json)
            assert total == sum(per_length), (
                f"total {total} != sum({per_length})"
            )


# ============================================================================
# Test: Output file format
# ============================================================================

class TestOutputFileFormat:
    """Verify FIMI output file format compliance."""

    def test_empty_set_included(self, tmp_path):
        output = str(tmp_path / "out.txt")
        result = run_fim("all", "/app/data/synth_test.dat", 3, output)
        assert result.returncode == 0
        itemsets = parse_output_file(output)
        m = {items for items, _ in itemsets}
        assert frozenset() in m, "Empty set must be in output file"

    def test_format_compliance(self, tmp_path):
        output = str(tmp_path / "out.txt")
        result = run_fim("all", "/app/data/synth_test.dat", 3, output)
        assert result.returncode == 0
        with open(output) as f:
            for line_num, line in enumerate(f, 1):
                line = line.rstrip("\n")
                assert "(" in line and line.endswith(")"), (
                    f"Line {line_num}: bad format: {line!r}"
                )
                paren_idx = line.rindex("(")
                support_str = line[paren_idx + 1:-1].strip()
                assert support_str.isdigit(), (
                    f"Line {line_num}: support not integer"
                )
                items_part = line[:paren_idx].strip()
                if items_part:
                    nums = [int(x) for x in items_part.split()]
                    assert nums == sorted(nums), (
                        f"Line {line_num}: items not sorted"
                    )

    def test_counts_match_output(self, tmp_path):
        output = str(tmp_path / "out.txt")
        result = run_fim("all", "/app/data/synth_test.dat", 3, output)
        assert result.returncode == 0
        total, per_length = parse_fimi04_stdout(result.stdout)
        itemsets = parse_output_file(output)
        assert total == len(itemsets)


# ============================================================================
# Test: Cross-mode consistency
# ============================================================================

class TestCrossMode:
    """Verify all >= closed >= maximal on real datasets."""

    def test_synth_consistency(self):
        totals = {}
        for mode in ("all", "closed", "maximal"):
            r = run_fim(mode, "/app/data/synth_test.dat", 3)
            assert r.returncode == 0
            total, _ = parse_fimi04_stdout(r.stdout)
            totals[mode] = total
        assert totals["all"] >= totals["closed"]
        assert totals["closed"] >= totals["maximal"]

    def test_mushroom_consistency(self):
        totals = {}
        for mode in ("all", "closed", "maximal"):
            r = run_fim(mode, "/app/data/mushroom.dat", 4000)
            assert r.returncode == 0
            total, _ = parse_fimi04_stdout(r.stdout)
            totals[mode] = total
        assert totals["all"] >= totals["closed"]
        assert totals["closed"] >= totals["maximal"]


# ============================================================================
# Test: Mushroom independent verification
# ============================================================================

class TestMushroomVerification:
    """Cross-check results on mushroom.dat via independent computation."""

    def test_1itemset_count(self):
        result = run_fim("all", "/app/data/mushroom.dat", 4000)
        assert result.returncode == 0
        _, per_length = parse_fimi04_stdout(result.stdout)
        item_counts = defaultdict(int)
        with open("/app/data/mushroom.dat") as f:
            for line in f:
                for item in line.split():
                    try:
                        item_counts[int(item)] += 1
                    except ValueError:
                        pass
        expected = sum(1 for c in item_counts.values() if c >= 4000)
        assert per_length[1] == expected

    def test_empty_set_support(self, tmp_path):
        output = str(tmp_path / "out.txt")
        result = run_fim("all", "/app/data/mushroom.dat", 4000, output)
        assert result.returncode == 0
        itemsets = parse_output_file(output)
        m = {items: sup for items, sup in itemsets}
        assert frozenset() in m
        with open("/app/data/mushroom.dat") as f:
            n_txn = sum(1 for line in f if line.strip())
        assert m[frozenset()] == n_txn


# ============================================================================
# Test: Mathematical properties on real data
# ============================================================================

class TestClosureProperty:
    """No subset-superset pair in closed results should share support."""

    def test_mushroom_closure(self, tmp_path):
        output = str(tmp_path / "closed.txt")
        result = run_fim("closed", "/app/data/mushroom.dat", 4000, output)
        assert result.returncode == 0
        itemsets = parse_output_file(output)
        by_support = defaultdict(list)
        for items, sup in itemsets:
            by_support[sup].append(items)
        for sup, sets in by_support.items():
            for i, s1 in enumerate(sets):
                for s2 in sets[i + 1:]:
                    if s1 < s2 or s2 < s1:
                        pytest.fail(
                            f"Closure violation at support {sup}"
                        )


class TestMaximalProperty:
    """No maximal itemset should have a frequent proper superset."""

    def test_mushroom_maximal(self, tmp_path):
        all_output = str(tmp_path / "all.txt")
        max_output = str(tmp_path / "max.txt")
        r1 = run_fim("all", "/app/data/mushroom.dat", 4000, all_output)
        r2 = run_fim("maximal", "/app/data/mushroom.dat", 4000, max_output)
        assert r1.returncode == 0 and r2.returncode == 0
        all_sets = {items for items, _ in parse_output_file(all_output)}
        for max_set, _ in parse_output_file(max_output):
            for other in all_sets:
                if max_set < other:
                    pytest.fail(
                        f"Maximality violation: {sorted(max_set)} has "
                        f"frequent superset {sorted(other)}"
                    )


# ============================================================================
# Test: Performance on benchmark datasets
# ============================================================================

class TestPerformance:
    def test_retail_all_500(self):
        result = run_fim("all", "/app/data/retail.dat", 500, timeout=120)
        assert result.returncode == 0
        total, _ = parse_fimi04_stdout(result.stdout)
        assert total > 0

    def test_chess_closed_2500(self):
        result = run_fim("closed", "/app/data/chess.dat", 2500, timeout=120)
        assert result.returncode == 0
        total, _ = parse_fimi04_stdout(result.stdout)
        assert total > 0

    def test_mushroom_maximal_4000(self):
        result = run_fim("maximal", "/app/data/mushroom.dat", 4000, timeout=120)
        assert result.returncode == 0
        total, _ = parse_fimi04_stdout(result.stdout)
        assert total > 0
