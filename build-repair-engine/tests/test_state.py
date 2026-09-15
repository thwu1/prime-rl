
import os
import json
import shutil
import subprocess
import pytest

SUBJECTS_DIR = "/app/subjects"
SUBJECTS = ["merge_intervals", "edit_distance", "poly_eval", "lis", "matrix_chain"]

# ---------------------------------------------------------------------------
# Hidden subjects for anti-cheat: repair.py must generalise to unseen code.
# Each has a single-line bug fixable by standard mutation operators.
# ---------------------------------------------------------------------------

MAKEFILE_CONTENT = "\n".join([
    "CC = gcc",
    "CFLAGS ?= -g -O0",
    "",
    "all: test_driver",
    "",
    "test_driver: buggy.c test_driver.c",
    "\t$(CC) $(CFLAGS) -o test_driver buggy.c test_driver.c",
    "",
    "clean:",
    "\trm -f test_driver *.gcno *.gcda *.gcov",
    "",
    ".PHONY: all clean",
    "",
])

HIDDEN_SUBJECTS = {
    "fibonacci": {
        "buggy_c": (
            "#include <stdlib.h>\n"
            "\n"
            "int factorial(int n) {\n"
            "    if (n <= 1) return 1;\n"
            "    int result = 1;\n"
            "    for (int i = 2; i <= n; i++)\n"
            "        result *= i;\n"
            "    return result;\n"
            "}\n"
            "\n"
            "int fibonacci(int n) {\n"
            "    if (n <= 0) return 0;\n"
            "    if (n == 1) return 1;\n"
            "    int a = 0, b = 1;\n"
            "    for (int i = 2; i <= n; i++) {\n"
            "        int tmp = a - b;\n"
            "        a = b;\n"
            "        b = tmp;\n"
            "    }\n"
            "    return b;\n"
            "}\n"
        ),
        "test_driver_c": (
            "#include <stdio.h>\n"
            "#include <stdlib.h>\n"
            "\n"
            "extern int fibonacci(int n);\n"
            "extern int factorial(int n);\n"
            "\n"
            "typedef int (*test_func)(void);\n"
            "\n"
            "int test_0(void) { return (fibonacci(0) == 0) ? 0 : 1; }\n"
            "int test_1(void) { return (fibonacci(1) == 1) ? 0 : 1; }\n"
            "int test_2(void) { return (fibonacci(3) == 2) ? 0 : 1; }\n"
            "int test_3(void) { return (fibonacci(2) == 1) ? 0 : 1; }\n"
            "int test_4(void) { return (fibonacci(4) == 3) ? 0 : 1; }\n"
            "int test_5(void) { return (fibonacci(6) == 8) ? 0 : 1; }\n"
            "int test_6(void) { return (fibonacci(10) == 55) ? 0 : 1; }\n"
            "int test_7(void) { return (factorial(5) == 120) ? 0 : 1; }\n"
            "\n"
            "int main(int argc, char *argv[]) {\n"
            "    test_func tests[] = {test_0, test_1, test_2, test_3,\n"
            "                         test_4, test_5, test_6, test_7};\n"
            "    int n_tests = sizeof(tests) / sizeof(tests[0]);\n"
            "    int start = 0, end = n_tests;\n"
            "    if (argc > 1) {\n"
            "        int t = atoi(argv[1]);\n"
            "        if (t >= 0 && t < n_tests) { start = t; end = t + 1; }\n"
            "    }\n"
            "    int all_pass = 1;\n"
            "    for (int i = start; i < end; i++) {\n"
            "        int r = tests[i]();\n"
            '        printf("%s: test_%d\\n", r == 0 ? "PASS" : "FAIL", i);\n'
            "        if (r != 0) all_pass = 0;\n"
            "    }\n"
            "    return all_pass ? 0 : 1;\n"
            "}\n"
        ),
    },
    "inversions": {
        "buggy_c": (
            "#include <stdlib.h>\n"
            "\n"
            "int array_sum(const int *arr, int n) {\n"
            "    int s = 0;\n"
            "    for (int i = 0; i < n; i++) s += arr[i];\n"
            "    return s;\n"
            "}\n"
            "\n"
            "int count_inversions(const int *arr, int n) {\n"
            "    int count = 0;\n"
            "    for (int i = 0; i < n; i++) {\n"
            "        for (int j = i + 1; j < n; j++) {\n"
            "            if (arr[i] >= arr[j]) {\n"
            "                count++;\n"
            "            }\n"
            "        }\n"
            "    }\n"
            "    return count;\n"
            "}\n"
        ),
        "test_driver_c": (
            "#include <stdio.h>\n"
            "#include <stdlib.h>\n"
            "\n"
            "extern int count_inversions(const int *arr, int n);\n"
            "extern int array_sum(const int *arr, int n);\n"
            "\n"
            "typedef int (*test_func)(void);\n"
            "\n"
            "int test_0(void) {\n"
            "    int a[] = {1, 2, 3, 4, 5};\n"
            "    return (count_inversions(a, 5) == 0) ? 0 : 1;\n"
            "}\n"
            "\n"
            "int test_1(void) {\n"
            "    int a[] = {5, 4, 3, 2, 1};\n"
            "    return (count_inversions(a, 5) == 10) ? 0 : 1;\n"
            "}\n"
            "\n"
            "int test_2(void) {\n"
            "    int a[] = {2, 1, 3};\n"
            "    return (count_inversions(a, 3) == 1) ? 0 : 1;\n"
            "}\n"
            "\n"
            "int test_3(void) {\n"
            "    int a[] = {3, 1, 2};\n"
            "    return (count_inversions(a, 3) == 2) ? 0 : 1;\n"
            "}\n"
            "\n"
            "int test_4(void) {\n"
            "    int a[] = {1};\n"
            "    return (count_inversions(a, 1) == 0) ? 0 : 1;\n"
            "}\n"
            "\n"
            "int test_5(void) {\n"
            "    int a[] = {1, 1};\n"
            "    return (count_inversions(a, 2) == 0) ? 0 : 1;\n"
            "}\n"
            "\n"
            "int test_6(void) {\n"
            "    int a[] = {2, 2, 2};\n"
            "    return (count_inversions(a, 3) == 0) ? 0 : 1;\n"
            "}\n"
            "\n"
            "int test_7(void) {\n"
            "    int a[] = {1, 2, 3, 4};\n"
            "    return (array_sum(a, 4) == 10) ? 0 : 1;\n"
            "}\n"
            "\n"
            "int main(int argc, char *argv[]) {\n"
            "    test_func tests[] = {test_0, test_1, test_2, test_3,\n"
            "                         test_4, test_5, test_6, test_7};\n"
            "    int n_tests = sizeof(tests) / sizeof(tests[0]);\n"
            "    int start = 0, end = n_tests;\n"
            "    if (argc > 1) {\n"
            "        int t = atoi(argv[1]);\n"
            "        if (t >= 0 && t < n_tests) { start = t; end = t + 1; }\n"
            "    }\n"
            "    int all_pass = 1;\n"
            "    for (int i = start; i < end; i++) {\n"
            "        int r = tests[i]();\n"
            '        printf("%s: test_%d\\n", r == 0 ? "PASS" : "FAIL", i);\n'
            "        if (r != 0) all_pass = 0;\n"
            "    }\n"
            "    return all_pass ? 0 : 1;\n"
            "}\n"
        ),
    },
    "bsearch": {
        "buggy_c": (
            "#include <stdlib.h>\n"
            "\n"
            "int linear_search(const int *arr, int n, int target) {\n"
            "    for (int i = 0; i < n; i++) {\n"
            "        if (arr[i] == target) return i;\n"
            "    }\n"
            "    return -1;\n"
            "}\n"
            "\n"
            "int binary_search(const int *arr, int n, int target) {\n"
            "    int lo = 0, hi = n - 1;\n"
            "    while (lo < hi) {\n"
            "        int mid = lo + (hi - lo) / 2;\n"
            "        if (arr[mid] == target) return mid;\n"
            "        if (arr[mid] < target) lo = mid + 1;\n"
            "        else hi = mid - 1;\n"
            "    }\n"
            "    return -1;\n"
            "}\n"
        ),
        "test_driver_c": (
            "#include <stdio.h>\n"
            "#include <stdlib.h>\n"
            "\n"
            "extern int binary_search(const int *arr, int n, int target);\n"
            "extern int linear_search(const int *arr, int n, int target);\n"
            "\n"
            "typedef int (*test_func)(void);\n"
            "\n"
            "int test_0(void) {\n"
            "    int a[] = {1, 3, 5, 7, 9};\n"
            "    return (binary_search(a, 5, 5) == 2) ? 0 : 1;\n"
            "}\n"
            "\n"
            "int test_1(void) {\n"
            "    int a[] = {1, 3, 5, 7, 9};\n"
            "    return (binary_search(a, 5, 9) == 4) ? 0 : 1;\n"
            "}\n"
            "\n"
            "int test_2(void) {\n"
            "    int a[] = {42};\n"
            "    return (binary_search(a, 1, 42) == 0) ? 0 : 1;\n"
            "}\n"
            "\n"
            "int test_3(void) {\n"
            "    int a[] = {1, 3, 5};\n"
            "    return (binary_search(a, 3, 4) == -1) ? 0 : 1;\n"
            "}\n"
            "\n"
            "int test_4(void) {\n"
            "    int a[] = {1, 3};\n"
            "    return (binary_search(a, 2, 3) == 1) ? 0 : 1;\n"
            "}\n"
            "\n"
            "int test_5(void) {\n"
            "    int a[] = {1, 3};\n"
            "    return (binary_search(a, 2, 1) == 0) ? 0 : 1;\n"
            "}\n"
            "\n"
            "int test_6(void) {\n"
            "    int a[] = {1, 2, 3, 4};\n"
            "    return (binary_search(a, 4, 4) == 3) ? 0 : 1;\n"
            "}\n"
            "\n"
            "int test_7(void) {\n"
            "    int a[] = {10, 20, 30};\n"
            "    return (linear_search(a, 3, 20) == 1) ? 0 : 1;\n"
            "}\n"
            "\n"
            "int main(int argc, char *argv[]) {\n"
            "    test_func tests[] = {test_0, test_1, test_2, test_3,\n"
            "                         test_4, test_5, test_6, test_7};\n"
            "    int n_tests = sizeof(tests) / sizeof(tests[0]);\n"
            "    int start = 0, end = n_tests;\n"
            "    if (argc > 1) {\n"
            "        int t = atoi(argv[1]);\n"
            "        if (t >= 0 && t < n_tests) { start = t; end = t + 1; }\n"
            "    }\n"
            "    int all_pass = 1;\n"
            "    for (int i = start; i < end; i++) {\n"
            "        int r = tests[i]();\n"
            '        printf("%s: test_%d\\n", r == 0 ? "PASS" : "FAIL", i);\n'
            "        if (r != 0) all_pass = 0;\n"
            "    }\n"
            "    return all_pass ? 0 : 1;\n"
            "}\n"
        ),
    },
}


# ===================================================================
# Test class 1: verify provided subjects have correct repair outputs
# ===================================================================

class TestProvidedSubjects:
    """Verify that the five provided subjects were repaired correctly."""

    @pytest.mark.parametrize("subject", SUBJECTS)
    def test_fixed_c_exists(self, subject):
        path = os.path.join(SUBJECTS_DIR, subject, "fixed.c")
        assert os.path.isfile(path), f"fixed.c not found for {subject}"

    @pytest.mark.parametrize("subject", SUBJECTS)
    def test_repair_json_valid(self, subject):
        path = os.path.join(SUBJECTS_DIR, subject, "repair.json")
        assert os.path.isfile(path), f"repair.json not found for {subject}"
        with open(path) as f:
            data = json.load(f)
        assert "line" in data and isinstance(data["line"], int) and data["line"] > 0, \
            "'line' must be a positive integer"
        assert "original" in data and isinstance(data["original"], str) and len(data["original"].strip()) > 0, \
            "'original' must be a non-empty string"
        assert "fixed" in data and isinstance(data["fixed"], str) and len(data["fixed"].strip()) > 0, \
            "'fixed' must be a non-empty string"
        assert data["original"] != data["fixed"], "original and fixed should differ"

    @pytest.mark.parametrize("subject", SUBJECTS)
    def test_fixed_compiles_and_passes(self, subject):
        subject_dir = os.path.join(SUBJECTS_DIR, subject)
        fixed_path = os.path.join(subject_dir, "fixed.c")
        buggy_path = os.path.join(subject_dir, "buggy.c")
        backup_path = buggy_path + ".verify_backup"

        assert os.path.isfile(fixed_path), f"fixed.c not found for {subject}"

        shutil.copy2(buggy_path, backup_path)
        try:
            shutil.copy2(fixed_path, buggy_path)

            subprocess.run(["make", "clean"], cwd=subject_dir,
                           capture_output=True, timeout=30)
            build = subprocess.run(["make"], cwd=subject_dir,
                                   capture_output=True, timeout=30)
            assert build.returncode == 0, (
                f"Fixed {subject} does not compile:\n"
                f"{build.stderr.decode(errors='replace')}"
            )

            run = subprocess.run(["./test_driver"], cwd=subject_dir,
                                 capture_output=True, timeout=30)
            stdout = run.stdout.decode(errors="replace")
            assert run.returncode == 0, f"Tests failed for fixed {subject}:\n{stdout}"
            assert "FAIL" not in stdout, f"Some tests failed for {subject}:\n{stdout}"
        finally:
            shutil.copy2(backup_path, buggy_path)
            if os.path.exists(backup_path):
                os.unlink(backup_path)
            subprocess.run(["make", "clean"], cwd=subject_dir,
                           capture_output=True, timeout=10)


# ===================================================================
# Test class 2: verify repair.py generalises to unseen subjects
# ===================================================================

class TestRepairEngine:
    """Run repair.py on hidden subjects not present in the Docker image."""

    @staticmethod
    def _create_subject(name, base_dir):
        d = os.path.join(base_dir, name)
        os.makedirs(d, exist_ok=True)
        subj = HIDDEN_SUBJECTS[name]
        with open(os.path.join(d, "buggy.c"), "w") as f:
            f.write(subj["buggy_c"])
        with open(os.path.join(d, "test_driver.c"), "w") as f:
            f.write(subj["test_driver_c"])
        with open(os.path.join(d, "Makefile"), "w") as f:
            f.write(MAKEFILE_CONTENT)
        return d

    def test_repair_py_exists(self):
        assert os.path.isfile("/app/repair.py"), \
            "repair.py not found at /app/repair.py"

    @pytest.mark.parametrize("name", list(HIDDEN_SUBJECTS.keys()))
    def test_hidden_subject_repaired(self, name, tmp_path):
        d = self._create_subject(name, str(tmp_path))

        result = subprocess.run(
            ["python3", "/app/repair.py", d],
            capture_output=True, timeout=180,
        )
        engine_out = (result.stdout.decode(errors="replace")
                      + result.stderr.decode(errors="replace"))

        # -- fixed.c must exist --
        fixed_path = os.path.join(d, "fixed.c")
        assert os.path.isfile(fixed_path), (
            f"repair.py did not produce fixed.c for hidden subject '{name}'.\n"
            f"Engine output:\n{engine_out}"
        )

        # -- fixed.c must differ from buggy.c --
        with open(fixed_path) as f:
            fixed_content = f.read()
        assert fixed_content != HIDDEN_SUBJECTS[name]["buggy_c"], \
            f"fixed.c is identical to buggy.c for hidden subject '{name}'"

        # -- repair.json must be valid --
        json_path = os.path.join(d, "repair.json")
        assert os.path.isfile(json_path), (
            f"repair.py did not produce repair.json for hidden subject '{name}'"
        )
        with open(json_path) as f:
            data = json.load(f)
        assert isinstance(data.get("line"), int) and data["line"] > 0
        assert isinstance(data.get("original"), str) and len(data["original"].strip()) > 0
        assert isinstance(data.get("fixed"), str) and len(data["fixed"].strip()) > 0
        assert data["original"] != data["fixed"]

        # -- repair.json line must match the original buggy source --
        orig_lines = HIDDEN_SUBJECTS[name]["buggy_c"].splitlines(keepends=True)
        ln = data["line"]
        assert 1 <= ln <= len(orig_lines), f"line {ln} out of range"
        assert orig_lines[ln - 1].strip() == data["original"].strip(), (
            f"repair.json 'original' does not match buggy.c line {ln}"
        )

        # -- fixed.c must compile and pass all tests --
        shutil.copy2(fixed_path, os.path.join(d, "buggy.c"))
        subprocess.run(["make", "clean"], cwd=d, capture_output=True, timeout=30)
        build = subprocess.run(["make"], cwd=d, capture_output=True, timeout=30)
        assert build.returncode == 0, (
            f"fixed.c does not compile for hidden subject '{name}':\n"
            f"{build.stderr.decode(errors='replace')}"
        )
        run = subprocess.run(["./test_driver"], cwd=d,
                             capture_output=True, timeout=30)
        stdout = run.stdout.decode(errors="replace")
        assert run.returncode == 0, (
            f"Tests failed for hidden subject '{name}':\n{stdout}"
        )
        assert "FAIL" not in stdout, (
            f"Some tests failed for hidden subject '{name}':\n{stdout}"
        )
