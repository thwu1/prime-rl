"""Common validation checks shared across all CSV dataset files."""


import re

# --- Field validation patterns ---

URL_PATTERN = re.compile(r"(https://github\.com)(/[\w.\-]+){2}(?<!\.git)")

SHA_PATTERN = re.compile(r"[0-9a-f]{7,40}")

MODULE_PATH_PATTERN = re.compile(r"((\w|\.|-)+(\/|\w|\.|-)*)|^$")

JAVA_TEST_PATTERN = re.compile(
    r"((\w|\s)+\.)+(\w+|\d+|\W+)+(\[((\d+)|(\w+|\s)+)\])?"
)

PY_TEST_PATTERN = re.compile(
    r"[\w./\\-]+(?:::|\s)(?:[A-Za-z_][A-Za-z0-9_]*(?:::|\s))?[A-Za-z_][A-Za-z0-9_]*"
)

# --- Column name constants ---

JAVA_TEST_COL = "Fully-Qualified Test Name (packageName.ClassName.methodName)"
PY_TEST_COL = "Pytest Test Name (PathToFile::TestClass::TestMethod or PathToFile::TestMethod)"


def check_url(tracker, filename, row_num, row):
    """Validate Project URL format."""
    url = row["Project URL"]
    if not URL_PATTERN.match(url):
        tracker.add_error(filename, row_num, "invalid_url", "Project URL",
                         url, "Project URL doesn't match required format")


def check_sha(tracker, filename, row_num, row):
    """Validate SHA Detected field — must be exactly 40 lowercase hex chars."""
    sha = row["SHA Detected"]
    if not SHA_PATTERN.fullmatch(sha):
        tracker.add_error(filename, row_num, "invalid_sha", "SHA Detected",
                         sha, "SHA must be exactly 40 lowercase hex characters")


def check_module_path(tracker, filename, row_num, row):
    """Validate Module Path field (Java files only)."""
    mp = row["Module Path"]
    if not MODULE_PATH_PATTERN.fullmatch(mp):
        tracker.add_error(filename, row_num, "invalid_module_path",
                         "Module Path", mp,
                         "Module path contains invalid characters")


def check_test_name(tracker, filename, row_num, row, is_python):
    """Validate test name format based on file type."""
    if is_python:
        col = PY_TEST_COL
        test_name = row[col]
        if not PY_TEST_PATTERN.fullmatch(test_name) or "#" in test_name:
            tracker.add_error(filename, row_num, "invalid_test_name", col,
                             test_name,
                             "Pytest test name doesn't match required format")
    else:
        col = JAVA_TEST_COL
        test_name = row[col]
        if not JAVA_TEST_PATTERN.fullmatch(test_name) or "#" in test_name:
            tracker.add_error(filename, row_num, "invalid_test_name", col,
                             test_name,
                             "Java test name doesn't match required format")


def check_sort(tracker, filename, rows, is_python):
    """Check if file is properly sorted by Project URL then Test Name."""
    if is_python:
        test_col = PY_TEST_COL
    else:
        test_col = JAVA_TEST_COL

    for i in range(len(rows) - 1):
        key_a = (rows[i]["Project URL"].casefold(),
                 rows[i][test_col].casefold())
        key_b = (rows[i + 1]["Project URL"].casefold(),
                 rows[i + 1][test_col].casefold())
        if key_a > key_b:
            tracker.add_error(filename, None, "sort_order", None, None,
                             "File is not properly sorted by Project URL "
                             "then Test Name")
            break


def check_duplicates(tracker, filename, rows, is_python):
    """Check for duplicate entries based on composite key."""
    if is_python:
        test_col = PY_TEST_COL
    else:
        test_col = JAVA_TEST_COL

    seen = {}
    for i, row in enumerate(rows):
        if is_python:
            key = (row["Project URL"], row[test_col])
        else:
            key = (row["Project URL"], row["Module Path"], row[test_col])

        rn = i + 1
        if key in seen:
            tracker.add_error(filename, rn, "duplicate_entry", None, None,
                             f"Duplicate of row {seen[key]}")
        else:
            seen[key] = rn
