"""
Verification tests for the automated program repair tool.

"""

import json
import os
import shutil
import subprocess
import tempfile

SUBJECTS = {
    "sorting_utils": {"buggy_line": 21, "top_n": 5},
    "graph_utils": {"buggy_line": 23, "top_n": 5},
    "string_utils": {"buggy_line": 23, "top_n": 5},
    "cache_utils": {"buggy_line": 22, "top_n": 5},
}


def run_tool(subject_dir):
    """Run the autorepair tool on a subject directory."""
    result = subprocess.run(
        ["python3", "/app/autorepair.py", subject_dir],
        capture_output=True,
        text=True,
        timeout=300,
        cwd="/app",
    )
    assert result.returncode == 0, (
        f"Tool failed on {subject_dir}:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    return result


def check_output_files(subject_name):
    """Verify all expected output files exist."""
    output_dir = f"/app/output/{subject_name}"
    assert os.path.isdir(output_dir), f"Output directory missing: {output_dir}"

    diagnosis = os.path.join(output_dir, "diagnosis.json")
    fixed = os.path.join(output_dir, "program_fixed.py")
    patch = os.path.join(output_dir, "repair.patch")

    assert os.path.isfile(diagnosis), f"Missing diagnosis.json for {subject_name}"
    assert os.path.isfile(fixed), f"Missing program_fixed.py for {subject_name}"
    assert os.path.isfile(patch), f"Missing repair.patch for {subject_name}"

    return diagnosis, fixed, patch


def validate_diagnosis(diagnosis_path, subject_name, buggy_line, top_n):
    """Validate structure and content of diagnosis.json."""
    with open(diagnosis_path) as f:
        data = json.load(f)

    assert "suspicious_lines" in data, f"Missing 'suspicious_lines' key for {subject_name}"
    rankings = data["suspicious_lines"]
    assert isinstance(rankings, list), "suspicious_lines must be a list"
    assert len(rankings) >= 3, (
        f"Too few ranked lines for {subject_name}: {len(rankings)}"
    )

    for entry in rankings:
        assert "line" in entry, "Each entry must have 'line'"
        assert "score" in entry, "Each entry must have 'score'"
        assert isinstance(entry["line"], int), f"line must be int, got {type(entry['line'])}"
        assert isinstance(entry["score"], (int, float)), "score must be numeric"
        assert -1e-9 <= entry["score"] <= 1.0 + 1e-9, (
            f"Score out of range [0,1]: {entry['score']}"
        )

    scores = [e["score"] for e in rankings]
    for i in range(len(scores) - 1):
        assert scores[i] >= scores[i + 1] - 1e-9, (
            f"Rankings not sorted descending at position {i}: "
            f"{scores[i]} < {scores[i + 1]}"
        )

    top_lines = [e["line"] for e in rankings[:top_n]]
    assert buggy_line in top_lines, (
        f"Buggy line {buggy_line} not in top {top_n} for {subject_name}. "
        f"Top lines: {top_lines}"
    )


def validate_repair(fixed_path, subject_dir):
    """Verify the repaired program passes all original tests."""
    tmp_dir = tempfile.mkdtemp(prefix="verify_repair_")
    try:
        shutil.copy(fixed_path, os.path.join(tmp_dir, "program.py"))
        shutil.copy(
            os.path.join(subject_dir, "test_program.py"),
            os.path.join(tmp_dir, "test_program.py"),
        )
        result = subprocess.run(
            ["python3", "-m", "pytest", "test_program.py", "-v", "--tb=short"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=tmp_dir,
        )
        assert result.returncode == 0, (
            f"Repaired program fails tests:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def validate_patch(patch_path, subject_name):
    """Verify patch is valid unified diff with minimal changes."""
    with open(patch_path) as f:
        patch_text = f.read()

    assert len(patch_text.strip()) > 0, f"Empty patch for {subject_name}"

    lines = patch_text.split('\n')
    has_minus_header = any(l.startswith('---') for l in lines)
    has_plus_header = any(l.startswith('+++') for l in lines)
    has_hunk = any(l.startswith('@@') for l in lines)
    assert has_minus_header and has_plus_header and has_hunk, (
        f"Patch for {subject_name} is not valid unified diff format"
    )

    changed_lines = 0
    for line in lines:
        if (line.startswith('+') and not line.startswith('+++')) or \
           (line.startswith('-') and not line.startswith('---')):
            changed_lines += 1

    assert changed_lines <= 6, (
        f"Patch too large for {subject_name}: {changed_lines} changed diff lines "
        f"(max 6, corresponding to 3 source line modifications)"
    )


def run_subject_test(subject_name):
    """Full validation pipeline for a single subject."""
    info = SUBJECTS[subject_name]
    subject_dir = f"/app/subjects/{subject_name}"

    run_tool(subject_dir)
    diagnosis_path, fixed_path, patch_path = check_output_files(subject_name)
    validate_diagnosis(diagnosis_path, subject_name, info["buggy_line"], info["top_n"])
    validate_repair(fixed_path, subject_dir)
    validate_patch(patch_path, subject_name)


class TestToolExists:
    def test_autorepair_exists(self):
        assert os.path.exists("/app/autorepair.py"), "/app/autorepair.py not found"

    def test_autorepair_parseable(self):
        result = subprocess.run(
            ["python3", "-c",
             "import py_compile; py_compile.compile('/app/autorepair.py', doraise=True)"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"Syntax error in autorepair.py: {result.stderr}"
        )


class TestSortingUtils:
    def test_repair(self):
        run_subject_test("sorting_utils")


class TestGraphUtils:
    def test_repair(self):
        run_subject_test("graph_utils")


class TestStringUtils:
    def test_repair(self):
        run_subject_test("string_utils")


class TestCacheUtils:
    def test_repair(self):
        run_subject_test("cache_utils")


class TestGeneralization:
    def test_novel_subject(self):
        """Verify the tool generalizes to an unseen subject."""
        tmp_dir = tempfile.mkdtemp(dir="/tmp", prefix="novel_repair_")
        subject_name = os.path.basename(tmp_dir)

        try:
            source_code = (
                "def count_inversions(arr):\n"
                '    """Count pairs (i,j) where i<j and arr[i]>arr[j]."""\n'
                "    count = 0\n"
                "    for i in range(len(arr)):\n"
                "        for j in range(i + 1, len(arr)):\n"
                "            if arr[i] >= arr[j]:\n"
                "                count += 1\n"
                "    return count\n"
            )

            test_code = (
                "from program import count_inversions\n"
                "\n"
                "\n"
                "def test_sorted():\n"
                "    assert count_inversions([1, 2, 3, 4]) == 0\n"
                "\n"
                "\n"
                "def test_reversed():\n"
                "    assert count_inversions([4, 3, 2, 1]) == 6\n"
                "\n"
                "\n"
                "def test_one_inversion():\n"
                "    assert count_inversions([1, 3, 2]) == 1\n"
                "\n"
                "\n"
                "def test_empty():\n"
                "    assert count_inversions([]) == 0\n"
                "\n"
                "\n"
                "def test_with_duplicates():\n"
                "    assert count_inversions([1, 2, 2, 3]) == 0\n"
                "\n"
                "\n"
                "def test_single():\n"
                "    assert count_inversions([5]) == 0\n"
            )

            with open(os.path.join(tmp_dir, "program.py"), "w") as f:
                f.write(source_code)
            with open(os.path.join(tmp_dir, "test_program.py"), "w") as f:
                f.write(test_code)

            run_tool(tmp_dir)

            output_dir = f"/app/output/{subject_name}"
            assert os.path.isdir(output_dir), "No output for novel subject"

            diagnosis_path = os.path.join(output_dir, "diagnosis.json")
            fixed_path = os.path.join(output_dir, "program_fixed.py")
            patch_path = os.path.join(output_dir, "repair.patch")

            assert os.path.isfile(diagnosis_path), "Missing diagnosis.json"
            assert os.path.isfile(fixed_path), "Missing program_fixed.py"
            assert os.path.isfile(patch_path), "Missing repair.patch"

            with open(diagnosis_path) as f:
                data = json.load(f)
            assert "suspicious_lines" in data
            rankings = data["suspicious_lines"]
            assert len(rankings) > 0, "No rankings produced"

            scores = [e["score"] for e in rankings]
            assert all(-1e-9 <= s <= 1.0 + 1e-9 for s in scores), "Scores out of range"
            for i in range(len(scores) - 1):
                assert scores[i] >= scores[i + 1] - 1e-9, "Not sorted descending"

            top_lines = [e["line"] for e in rankings[:5]]
            assert 6 in top_lines, (
                f"Novel subject: buggy line 6 not in top 5: {top_lines}"
            )

            validate_repair(fixed_path, tmp_dir)

            with open(patch_path) as f:
                patch_text = f.read()
            assert len(patch_text.strip()) > 0, "Empty patch for novel subject"

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            output_dir = f"/app/output/{subject_name}"
            if os.path.isdir(output_dir):
                shutil.rmtree(output_dir, ignore_errors=True)
