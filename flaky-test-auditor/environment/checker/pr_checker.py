"""Dataset-specific validation checks for category, status, and PR links."""


import re
from common_checks import JAVA_TEST_COL

CATEGORY_PATTERN = re.compile(r"(\w+|-|;)*\w+")

VALID_CATEGORIES = [
    "OD", "OD-Brit", "OD-Vic", "ID", "ID-HtF", "NIO", "NOD",
    "NDOD", "NDOI", "UD", "OSD", "TZD", "TD",
]

VALID_STATUSES = [
    "", "Opened", "Accepted", "InspiredAFix", "DeveloperWontFix",
    "DeveloperFixed", "RepoArchived", "RepoDeleted", "Deprecated",
    "Deleted", "Rejected", "Skipped", "Irreproducible", "MovedOrRenamed",
    "RepoRenamed", "Claimed", "MovedToGradle", "FixedOrder", "Unmaintained",
]

PR_LINK_PATTERN = re.compile(
    r"(https://github\.com/([\w.\-]+/[\w.\-]+))/pull/\d+"
)

STATUSES_REQUIRING_PR = ["Accepted", "Opened", "Rejected"]

STATUSES_REQUIRING_NOTES = [
    "Deleted", "DeveloperFixed", "RepoRenamed", "Irreproducible",
]


def check_category(tracker, filename, row_num, row):
    """Validate Category field against the flaky test taxonomy."""
    cat = row["Category"]
    if (not CATEGORY_PATTERN.fullmatch(cat)
            or not all(c in VALID_CATEGORIES for c in cat.split(";"))):
        tracker.add_error(filename, row_num, "invalid_category", "Category",
                         cat, "Category contains invalid value(s)")


def check_status(tracker, filename, row_num, row):
    """Validate Status field against allowed values."""
    if row["Status"] not in VALID_STATUSES:
        tracker.add_error(filename, row_num, "invalid_status", "Status",
                         row["Status"], "Invalid status value")


def check_status_consistency(tracker, filename, row_num, row):
    """Check consistency between Status, PR Link, and Notes fields."""
    status = row["Status"]
    pr_link = row["PR Link"]
    notes = row["Notes"]

    # Status requires PR Link
    if status in STATUSES_REQUIRING_PR and pr_link == "":
        tracker.add_error(filename, row_num, "status_missing_pr_link",
                         "PR Link", "",
                         f"Status '{status}' requires a PR Link")

    # PR Link format validation
    if pr_link != "":
        m = PR_LINK_PATTERN.fullmatch(pr_link)
        if not m or m.group(1).lower() != row["Project URL"].lower():
            tracker.add_error(filename, row_num, "invalid_pr_link", "PR Link",
                             pr_link,
                             "PR Link format invalid or base URL doesn't "
                             "match Project URL")

    # Status requires Notes
    if status in STATUSES_REQUIRING_NOTES and notes == "":
        tracker.add_error(filename, row_num, "status_missing_notes", "Notes",
                         "", f"Status '{status}' requires Notes")


def check_cross_file_moved_to_gradle(tracker, pr_rows, gr_rows):
    """Check that MovedToGradle entries in pr-data have matching gr-data."""
    gr_tests = set()
    for row in gr_rows:
        gr_tests.add((
            row["Project URL"].lower(),
            row[JAVA_TEST_COL].lower(),
        ))

    for i, row in enumerate(pr_rows):
        if row["Status"] == "MovedToGradle":
            key = (
                row["Project URL"].lower(),
                row[JAVA_TEST_COL].lower(),
            )
            if key not in gr_tests:
                tracker.add_error("pr-data.csv", i + 1,
                                "cross_file_moved_to_gradle", None, None,
                                "MovedToGradle status but no matching "
                                "entry in gr-data.csv")
