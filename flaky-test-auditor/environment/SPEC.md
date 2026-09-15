# IDoFT Dataset Validation Specification

## Overview

The International Dataset of Flaky Tests (IDoFT) is a community-curated dataset of flaky tests from real Java and Python projects. It consists of three CSV files:

- **pr-data.csv**: Flaky tests from Java projects using Maven
- **gr-data.csv**: Flaky tests from Java projects using Gradle
- **py-data.csv**: Flaky tests from Python projects

Your task is to build an auditor that validates these files against the rules below and produces a structured JSON report.

## File Schemas

### pr-data.csv and gr-data.csv (Java)

| Column | Description |
|--------|-------------|
| Project URL | GitHub project URL |
| SHA Detected | Commit SHA where flakiness was detected |
| Module Path | Path to the module containing the test |
| Fully-Qualified Test Name (packageName.ClassName.methodName) | Java test identifier |
| Category | Flakiness category |
| Status | Current state of the flaky test |
| PR Link | Link to fix PR |
| Notes | Additional information (URLs) |

### py-data.csv (Python)

| Column | Description |
|--------|-------------|
| Project URL | GitHub project URL |
| SHA Detected | Commit SHA where flakiness was detected |
| Pytest Test Name (PathToFile::TestClass::TestMethod or PathToFile::TestMethod) | Python test identifier |
| Category | Flakiness category |
| Status | Current state of the flaky test |
| PR Link | Link to fix PR |
| Notes | Additional information (URLs) |

Note: Python data does NOT have the Module Path column.

## Field Validation Rules

### Project URL
- Must match pattern: `https://github.com/<owner>/<repo>`
- Owner and repo segments may contain word characters (`\w`), dots (`.`), and hyphens (`-`)
- Must NOT end with `.git`
- Regex: `(https://github\.com)(/[\w.\-]+){2}` with negative lookbehind `(?<!\.git)$`

### SHA Detected
- Must be exactly 40 lowercase hexadecimal characters
- Regex: `[0-9a-f]{40}` (full match)

### Module Path (pr-data.csv and gr-data.csv only)
- May contain word characters, dots, hyphens, and forward slashes
- Use `.` for tests at repository root
- May be empty
- Must NOT contain `@`, spaces, or other special characters
- Regex: `((\w|\.|-)+(\/|\w|\.|-)*)|^$`

### Fully-Qualified Test Name — Java (pr-data.csv and gr-data.csv)
- Dot-separated package, class, and method name
- Regex: `((\w|\s)+\.)+(\w+|\d+|\W+)+(\[((\d+)|(\w+|\s)+)\])?`
- Must NOT contain `#`

### Pytest Test Name — Python (py-data.csv)
- Format: `path/to/file.py::TestClass::test_method` or `path/to/file.py::test_method`
- Must use `::` as separator between file path and test identifiers
- Regex: `[\w./\\-]+::(?:[A-Za-z_][A-Za-z0-9_]*::)?[A-Za-z_][A-Za-z0-9_]*`
- Must NOT contain `#`

### Category
Valid single values: `OD`, `OD-Brit`, `OD-Vic`, `ID`, `ID-HtF`, `NIO`, `NOD`, `NDOD`, `NDOI`, `UD`, `OSD`, `TZD`, `TD`

- Multiple categories may be joined with `;` (no spaces): e.g., `OD;NOD`
- Every component in a compound category must be from the valid set
- The compound value must match: `(\w+|-|;)*\w+`

### Status
Valid values (including blank/empty):
`""` (blank), `Opened`, `Accepted`, `InspiredAFix`, `DeveloperWontFix`, `DeveloperFixed`, `RepoArchived`, `RepoDeleted`, `Deprecated`, `Deleted`, `Rejected`, `Skipped`, `Irreproducible`, `MovedOrRenamed`, `RepoRenamed`, `Claimed`, `MovedToGradle`, `FixedOrder`, `Unmaintained`

### PR Link
- Format: `https://github.com/<owner>/<repo>/pull/<number>`
- The base URL (removing `/pull/<number>`) must match the entry's Project URL (case-insensitive comparison)

### Notes
- If present, must be a valid URL or semicolon-separated URLs

## Consistency Rules

### Status requires PR Link
If Status is one of `Accepted`, `Opened`, or `Rejected`, a valid PR Link is **required** (error if missing or empty).

### Status blank with PR Link present
If Status is blank (`""`) but a PR Link is present, that is an **error** — status should not be empty when a PR link is provided.

### Status requires Notes
If Status is one of `MovedOrRenamed`, `Deleted`, `DeveloperFixed`, `RepoRenamed`, or `Irreproducible`, the Notes field is **required** (error if empty).

## File-Level Rules

### Sort Order
Each file must be sorted by:
- Primary key: Project URL (column 1)
- Secondary key: Test Name (column 4 for Java, column 3 for Python)
- Sort is case-insensitive (equivalent to `LC_ALL=C sort -f`)

Report one violation per file that is not properly sorted.

### No Duplicates
- For pr-data.csv and gr-data.csv: each tuple of (Project URL, Module Path, Test Name) must be unique
- For py-data.csv: each tuple of (Project URL, Test Name) must be unique

Report one violation per duplicate found (flag the later occurrence).

## Cross-File Consistency

### MovedToGradle
For any entry in pr-data.csv with Status `MovedToGradle`, there must be a corresponding entry in gr-data.csv with the same Project URL and the same Fully-Qualified Test Name. If no such entry exists, report a cross-file violation.

## Output Format

The auditor must write `/app/audit_report.json` with the following structure:

```json
{
  "violations": [
    {
      "file": "<filename>",
      "row": <row_number_or_null>,
      "type": "<violation_type>",
      "field": "<field_name_or_null>",
      "value": "<problematic_value_or_null>",
      "details": "<human-readable description>"
    }
  ],
  "summary": {
    "total": <int>,
    "by_file": {
      "pr-data.csv": <int>,
      "gr-data.csv": <int>,
      "py-data.csv": <int>
    },
    "by_type": {
      "<violation_type>": <int>
    }
  }
}
```

### Violation Types

Use these exact type identifiers:

| Type | Description |
|------|-------------|
| `invalid_sha` | SHA Detected doesn't match 40-char hex format |
| `invalid_category` | Category contains value(s) not in the valid set |
| `invalid_url` | Project URL format is invalid |
| `invalid_module_path` | Module Path contains invalid characters |
| `invalid_test_name` | Test Name doesn't match required format |
| `invalid_pr_link` | PR Link format is wrong or base URL doesn't match Project URL |
| `status_missing_pr_link` | Status requires PR Link but none provided |
| `status_missing_notes` | Status requires Notes but none provided |
| `status_blank_with_pr_link` | Status is blank but PR Link is present |
| `sort_order` | File is not properly sorted (one per unsorted file) |
| `duplicate_entry` | Duplicate entry detected (one per duplicate, flagging later row) |
| `cross_file_moved_to_gradle` | MovedToGradle entry has no matching gr-data entry |

### Row Numbering

Row numbers are **1-indexed**, counting from the first data row (the header row is row 0 / not counted).
