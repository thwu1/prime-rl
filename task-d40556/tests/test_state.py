"""
Tests for ROVER system combination optimization task.
"""
import os
import re
import subprocess
import tempfile
import itertools

import pytest

RESULTS_DIR = "/app/results"
DATA_DIR = "/app/data"
SCLITE = "/usr/local/bin/sclite"
ROVER = "/usr/local/bin/rover"


def run_cmd(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout, result.stderr, result.returncode


def parse_wer_from_sum(sum_file):
    """Parse overall WER from sclite sum report."""
    with open(sum_file, "r") as f:
        content = f.read()
    match = re.search(
        r"Sum/Avg\|.*?\|\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\|",
        content,
    )
    if match:
        return float(match.group(5))  # Err column
    return None


def parse_nce_from_sum(sum_file):
    """Parse NCE from sclite sum report."""
    with open(sum_file, "r") as f:
        content = f.read()
    match = re.search(
        r"Sum/Avg\|.*?\|\s*[\d.]+\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+[\d.]+\s*\|\s*([-\d.]+)\s*\|",
        content,
    )
    if match:
        return float(match.group(1))
    return None


def get_ground_truth_wers():
    """Run sclite on each system to get ground-truth WER values."""
    systems = ["sys1", "sys2", "sys3", "sys4", "sys5"]
    wers = {}
    nces = {}
    for sys_name in systems:
        workdir = tempfile.mkdtemp(prefix=f"test_score_{sys_name}_")
        ref = os.path.join(DATA_DIR, "ref.stm")
        hyp = os.path.join(DATA_DIR, f"{sys_name}.ctm")
        cmd = (
            f"{SCLITE} -r {ref} stm -h {hyp} ctm "
            f"-o sum -O {workdir} -f 0 -n {sys_name}"
        )
        run_cmd(cmd)
        sum_file = os.path.join(workdir, f"{sys_name}.sys")
        if os.path.exists(sum_file):
            wer = parse_wer_from_sum(sum_file)
            nce = parse_nce_from_sum(sum_file)
            if wer is not None:
                wers[sys_name] = wer
            if nce is not None:
                nces[sys_name] = nce
    return wers, nces


def get_rover_wer(sys_names, method_args):
    """Run ROVER and score the output, return WER."""
    workdir = tempfile.mkdtemp(prefix="test_rover_")
    hyp_args = " ".join(
        f"-h {os.path.join(DATA_DIR, s + '.ctm')} ctm" for s in sys_names
    )
    rover_out = os.path.join(workdir, "rover_out.ctm")
    cmd = f"{ROVER} {hyp_args} -o {rover_out} {method_args}"
    _, _, rc = run_cmd(cmd)
    if rc != 0:
        return None

    ref = os.path.join(DATA_DIR, "ref.stm")
    cmd = (
        f"{SCLITE} -r {ref} stm -h {rover_out} ctm "
        f"-o sum -O {workdir} -f 0 -n rover_score"
    )
    run_cmd(cmd)
    sum_file = os.path.join(workdir, "rover_score.sys")
    if os.path.exists(sum_file):
        return parse_wer_from_sum(sum_file)
    return None


def get_lur_categories(sys_name):
    """Run sclite with LUR output and parse category WER."""
    workdir = tempfile.mkdtemp(prefix="test_lur_")
    ref = os.path.join(DATA_DIR, "ref.stm")
    hyp = os.path.join(DATA_DIR, f"{sys_name}.ctm")
    cmd = (
        f"{SCLITE} -r {ref} stm -h {hyp} ctm "
        f"-o sum lur -O {workdir} -f 0 -n {sys_name}"
    )
    run_cmd(cmd)
    lur_file = os.path.join(workdir, f"{sys_name}.lur")
    if not os.path.exists(lur_file):
        return {}

    with open(lur_file, "r") as f:
        content = f.read()

    lines = content.split("\n")

    # Find column headers from the line before #Wrd %WE
    col_labels = []
    for i, line in enumerate(lines):
        if "#Wrd %WE" in line:
            prev = lines[i - 1] if i >= 1 else ""
            parts = [p.strip() for p in prev.split("|") if p.strip()]
            col_labels = [p for p in parts if p != "SPKR"]
            break

    label_title_to_id = {
        "Overall": "O",
        "Male": "M",
        "Female": "F",
        "Clean": "CL",
        "Noisy": "NS",
    }

    results = {}
    for line in lines:
        if "Set Sum" in line or "Sum/Avg" in line:
            pairs = re.findall(r"\[\s*(\d+)\]\s+([\d.]+)", line)
            for idx, (nwrd, wer) in enumerate(pairs):
                if idx < len(col_labels):
                    label_id = label_title_to_id.get(col_labels[idx], col_labels[idx])
                    results[label_id] = float(wer)
            break

    return results


class TestResultFilesExist:
    """Test that all required result files exist."""

    def test_individual_wer_exists(self):
        assert os.path.exists(os.path.join(RESULTS_DIR, "individual_wer.csv")), \
            "individual_wer.csv not found"

    def test_best_rover_combination_exists(self):
        assert os.path.exists(os.path.join(RESULTS_DIR, "best_rover_combination.txt")), \
            "best_rover_combination.txt not found"

    def test_best_rover_wer_exists(self):
        assert os.path.exists(os.path.join(RESULTS_DIR, "best_rover_wer.txt")), \
            "best_rover_wer.txt not found"

    def test_voting_comparison_exists(self):
        assert os.path.exists(os.path.join(RESULTS_DIR, "voting_comparison.csv")), \
            "voting_comparison.csv not found"

    def test_category_wer_exists(self):
        assert os.path.exists(os.path.join(RESULTS_DIR, "category_wer.csv")), \
            "category_wer.csv not found"

    def test_nce_scores_exists(self):
        assert os.path.exists(os.path.join(RESULTS_DIR, "nce_scores.csv")), \
            "nce_scores.csv not found"


class TestIndividualWER:
    """Test that individual system WER values are correct."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.truth_wers, self.truth_nces = get_ground_truth_wers()

    def test_individual_wer_format(self):
        path = os.path.join(RESULTS_DIR, "individual_wer.csv")
        with open(path, "r") as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]
        assert len(lines) == 5, f"Expected 5 lines, got {len(lines)}"
        for line in lines:
            parts = line.split(",")
            assert len(parts) == 2, f"Expected 2 fields, got {len(parts)} in: {line}"
            name, wer = parts
            assert name.startswith("sys"), f"Invalid system name: {name}"
            float(wer)  # Should not raise

    def test_individual_wer_values(self):
        path = os.path.join(RESULTS_DIR, "individual_wer.csv")
        submitted = {}
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    name, wer = line.split(",")
                    submitted[name] = float(wer)

        for sys_name, truth_wer in self.truth_wers.items():
            assert sys_name in submitted, f"Missing system: {sys_name}"
            assert abs(submitted[sys_name] - truth_wer) < 0.15, \
                f"{sys_name}: submitted WER {submitted[sys_name]} != truth {truth_wer}"


class TestBestROVERCombination:
    """Test that the best ROVER combination is correctly identified."""

    def test_best_rover_combination(self):
        # Find the true best combination
        systems = ["sys1", "sys2", "sys3", "sys4", "sys5"]
        best_combo = None
        best_wer = float("inf")

        for combo in itertools.combinations(systems, 3):
            wer = get_rover_wer(combo, "-m avgconf")
            if wer is not None and wer < best_wer:
                best_wer = wer
                best_combo = combo

        assert best_combo is not None, "Could not compute any ROVER combination"

        # Read submitted answer
        path = os.path.join(RESULTS_DIR, "best_rover_combination.txt")
        with open(path, "r") as f:
            submitted = f.read().strip()

        submitted_systems = sorted(submitted.split(","))
        expected_systems = sorted(best_combo)

        assert submitted_systems == expected_systems, \
            f"Best combination: submitted {submitted_systems} != expected {expected_systems}"

    def test_best_rover_wer(self):
        # Read submitted combination
        combo_path = os.path.join(RESULTS_DIR, "best_rover_combination.txt")
        with open(combo_path, "r") as f:
            combo_str = f.read().strip()
        combo = combo_str.split(",")

        # Compute true WER for submitted combination
        true_wer = get_rover_wer(combo, "-m avgconf")
        assert true_wer is not None, "Could not score submitted combination"

        # Read submitted WER
        wer_path = os.path.join(RESULTS_DIR, "best_rover_wer.txt")
        with open(wer_path, "r") as f:
            submitted_wer = float(f.read().strip())

        assert abs(submitted_wer - true_wer) < 0.15, \
            f"ROVER WER: submitted {submitted_wer} != truth {true_wer}"


class TestVotingComparison:
    """Test voting method comparison results."""

    def test_voting_comparison_format(self):
        path = os.path.join(RESULTS_DIR, "voting_comparison.csv")
        with open(path, "r") as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]
        assert len(lines) == 3, f"Expected 3 lines, got {len(lines)}"
        methods = set()
        for line in lines:
            parts = line.split(",")
            assert len(parts) == 2, f"Expected 2 fields in: {line}"
            methods.add(parts[0])
            float(parts[1])

        expected_methods = {"avgconf", "maxconf", "word_frequency"}
        assert methods == expected_methods, \
            f"Methods: submitted {methods} != expected {expected_methods}"

    def test_voting_comparison_values(self):
        # Read submitted combination
        combo_path = os.path.join(RESULTS_DIR, "best_rover_combination.txt")
        with open(combo_path, "r") as f:
            combo = f.read().strip().split(",")

        voting_methods = {
            "avgconf": "-m avgconf",
            "maxconf": "-m maxconf",
            "word_frequency": "-m avgconf -a 1.0 -c 0.0",
        }

        truth = {}
        for method_name, args in voting_methods.items():
            wer = get_rover_wer(combo, args)
            if wer is not None:
                truth[method_name] = wer

        # Read submitted values
        path = os.path.join(RESULTS_DIR, "voting_comparison.csv")
        submitted = {}
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    name, wer = line.split(",")
                    submitted[name] = float(wer)

        for method_name, truth_wer in truth.items():
            assert method_name in submitted, f"Missing method: {method_name}"
            assert abs(submitted[method_name] - truth_wer) < 0.15, \
                f"{method_name}: submitted {submitted[method_name]} != truth {truth_wer}"


class TestCategoryWER:
    """Test per-category WER values."""

    def test_category_wer_has_all_categories(self):
        path = os.path.join(RESULTS_DIR, "category_wer.csv")
        with open(path, "r") as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]

        categories = set()
        for line in lines:
            parts = line.split(",")
            categories.add(parts[0])

        expected = {"O", "M", "F", "CL", "NS"}
        assert categories == expected, \
            f"Categories: submitted {categories} != expected {expected}"

    def test_category_wer_values(self):
        # Determine best individual system
        truth_wers, _ = get_ground_truth_wers()
        best_sys = min(truth_wers, key=truth_wers.get)

        # Get ground truth category WER
        truth_cats = get_lur_categories(best_sys)

        # Read submitted values
        path = os.path.join(RESULTS_DIR, "category_wer.csv")
        submitted = {}
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    cat, wer = line.split(",")
                    submitted[cat] = float(wer)

        for cat, truth_wer in truth_cats.items():
            assert cat in submitted, f"Missing category: {cat}"
            assert abs(submitted[cat] - truth_wer) < 0.15, \
                f"Category {cat}: submitted {submitted[cat]} != truth {truth_wer}"


class TestNCEScores:
    """Test NCE score values."""

    def test_nce_format(self):
        path = os.path.join(RESULTS_DIR, "nce_scores.csv")
        with open(path, "r") as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]
        assert len(lines) == 5, f"Expected 5 lines, got {len(lines)}"
        for line in lines:
            parts = line.split(",")
            assert len(parts) == 2, f"Expected 2 fields in: {line}"
            float(parts[1])  # Should not raise

    def test_nce_values(self):
        _, truth_nces = get_ground_truth_wers()

        path = os.path.join(RESULTS_DIR, "nce_scores.csv")
        submitted = {}
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    name, nce = line.split(",")
                    submitted[name] = float(nce)

        for sys_name, truth_nce in truth_nces.items():
            assert sys_name in submitted, f"Missing system: {sys_name}"
            assert abs(submitted[sys_name] - truth_nce) < 0.005, \
                f"{sys_name}: submitted NCE {submitted[sys_name]} != truth {truth_nce}"
