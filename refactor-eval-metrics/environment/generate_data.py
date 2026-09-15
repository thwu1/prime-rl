#!/usr/bin/env python3
"""Generate evaluation benchmark data files for the SARIF evaluation pipeline task."""
import json
import os


def mkdir(path):
    os.makedirs(path, exist_ok=True)


def write_json(path, data):
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


def write_text(path, text):
    with open(path, 'w') as f:
        f.write(text)


def make_sarif(runs_list):
    """Create a SARIF 2.1.0 document with one or more runs."""
    return {
        "$schema": "https://docs.oasis-open.org/sarif/sarif/v2.1.0/os/schemas/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": runs_list
    }


def make_run(rules, results, notifications=None):
    """Create a single SARIF run."""
    invocation = {
        "executionSuccessful": True,
        "toolExecutionNotifications": notifications or []
    }
    return {
        "tool": {
            "driver": {
                "name": "Opengrep OSS",
                "rules": rules
            }
        },
        "invocations": [invocation],
        "results": results
    }


def result_by_id(rule_id, message, uri, start_line, end_line=None):
    """Create a SARIF result referencing a rule by ruleId."""
    return {
        "ruleId": rule_id,
        "message": {"text": message},
        "locations": [{
            "physicalLocation": {
                "artifactLocation": {"uri": uri},
                "region": {
                    "startLine": start_line,
                    "endLine": end_line or start_line
                }
            }
        }]
    }


def result_by_index(rule_index, message, uri, start_line, end_line=None):
    """Create a SARIF result referencing a rule by ruleIndex."""
    return {
        "ruleIndex": rule_index,
        "message": {"text": message},
        "locations": [{
            "physicalLocation": {
                "artifactLocation": {"uri": uri},
                "region": {
                    "startLine": start_line,
                    "endLine": end_line or start_line
                }
            }
        }]
    }


BASE = "/app/data/instances"

# ================================================================
# Instance 001: rename-method
# 5 positive rules, 3 match; 4 negative rules, 1 still matches
# Tests valid (high pass rate). Alignment = 6/9.
# ================================================================
d = f"{BASE}/instance_001"
mkdir(d)

write_text(f"{d}/rules_positive.yml", """\
rules:
  - id: pos-001-use-process-data
    pattern: "process_data($...ARGS)"
    message: Uses new process_data function name
    severity: INFO
    languages:
      - python
  - id: pos-002-use-validate-input
    pattern: "validate_input($X)"
    message: Uses new validate_input function name
    severity: INFO
    languages:
      - python
  - id: pos-003-dataclass-config
    patterns:
      - pattern: |
          @dataclass
          class Config:
              ...
    message: Config uses dataclass decorator
    severity: INFO
    languages:
      - python
  - id: pos-004-type-annotations
    pattern: "def $FUNC($...PARAMS) -> $RET:"
    message: Function has return type annotation
    severity: INFO
    languages:
      - python
  - id: pos-005-use-pathlib
    pattern: "Path($X)"
    message: Uses pathlib.Path
    severity: INFO
    languages:
      - python
""")

# Positive SARIF: rules 001, 002, 005 match (3 of 5)
write_json(f"{d}/positive.sarif", make_sarif([make_run(
    rules=[
        {"id": "pos-001-use-process-data", "shortDescription": {"text": "Uses new process_data function name"}},
        {"id": "pos-002-use-validate-input", "shortDescription": {"text": "Uses new validate_input function name"}},
        {"id": "pos-003-dataclass-config", "shortDescription": {"text": "Config uses dataclass decorator"}},
        {"id": "pos-004-type-annotations", "shortDescription": {"text": "Function has return type annotation"}},
        {"id": "pos-005-use-pathlib", "shortDescription": {"text": "Uses pathlib.Path"}},
    ],
    results=[
        result_by_id("pos-001-use-process-data", "Uses new process_data function name", "src/pipeline.py", 42),
        result_by_id("pos-001-use-process-data", "Uses new process_data function name", "src/pipeline.py", 88),
        result_by_id("pos-002-use-validate-input", "Uses new validate_input function name", "src/utils.py", 15),
        result_by_id("pos-005-use-pathlib", "Uses pathlib.Path", "src/io_handler.py", 7),
        result_by_id("pos-005-use-pathlib", "Uses pathlib.Path", "src/io_handler.py", 23),
        result_by_id("pos-005-use-pathlib", "Uses pathlib.Path", "src/config.py", 11),
    ]
)]))

write_text(f"{d}/rules_negative.yml", """\
rules:
  - id: neg-001-old-handle-data
    pattern: "handle_data($...ARGS)"
    message: Still uses old handle_data name
    severity: WARNING
    languages:
      - python
  - id: neg-002-old-check-input
    pattern: "check_input($X)"
    message: Still uses old check_input name
    severity: WARNING
    languages:
      - python
  - id: neg-003-os-path-join
    pattern: "os.path.join($...ARGS)"
    message: Still uses os.path.join instead of pathlib
    severity: WARNING
    languages:
      - python
  - id: neg-004-dict-config
    pattern: "config = {$...ITEMS}"
    message: Still uses dict for config instead of dataclass
    severity: WARNING
    languages:
      - python
""")

# Negative SARIF: only neg-003 still matches (1 of 4)
write_json(f"{d}/negative.sarif", make_sarif([make_run(
    rules=[
        {"id": "neg-001-old-handle-data", "shortDescription": {"text": "Still uses old handle_data name"}},
        {"id": "neg-002-old-check-input", "shortDescription": {"text": "Still uses old check_input name"}},
        {"id": "neg-003-os-path-join", "shortDescription": {"text": "Still uses os.path.join instead of pathlib"}},
        {"id": "neg-004-dict-config", "shortDescription": {"text": "Still uses dict for config instead of dataclass"}},
    ],
    results=[
        result_by_id("neg-003-os-path-join", "Still uses os.path.join instead of pathlib", "src/legacy.py", 34),
    ]
)]))

# Test results: 3 runs, best_passed=50, worst_failed=2, total=55
write_json(f"{d}/test_results.json", {
    "runs": [
        {"passed": 48, "failed": 4, "skipped": 3, "total": 55},
        {"passed": 50, "failed": 2, "skipped": 3, "total": 55},
        {"passed": 49, "failed": 3, "skipped": 3, "total": 55}
    ],
    "error": None
})

# ================================================================
# Instance 002: extract-interface (uses ruleIndex in SARIF)
# 3 positive rules, 1 match; 6 negative rules, 4 still match
# Tests valid. Alignment = 3/9.
# ================================================================
d = f"{BASE}/instance_002"
mkdir(d)

write_text(f"{d}/rules_positive.yml", """\
rules:
  - id: pos-ext-001-interface-decl
    pattern: "interface $NAME { ... }"
    message: Interface declaration found
    severity: INFO
    languages:
      - typescript
  - id: pos-ext-002-impl-class
    pattern: "class $NAME implements $IFACE { ... }"
    message: Implementation class extends interface
    severity: INFO
    languages:
      - typescript
  - id: pos-ext-003-factory-method
    pattern: "create$TYPE($...ARGS): $IFACE"
    message: Factory method returns interface
    severity: INFO
    languages:
      - typescript
""")

# Positive SARIF: uses ruleIndex! Only rule at index 1 (pos-ext-002) matches.
write_json(f"{d}/positive.sarif", make_sarif([make_run(
    rules=[
        {"id": "pos-ext-001-interface-decl", "shortDescription": {"text": "Interface declaration found"}},
        {"id": "pos-ext-002-impl-class", "shortDescription": {"text": "Implementation class extends interface"}},
        {"id": "pos-ext-003-factory-method", "shortDescription": {"text": "Factory method returns interface"}},
    ],
    results=[
        result_by_index(1, "Implementation class extends interface", "src/services/UserService.ts", 12, 45),
        result_by_index(1, "Implementation class extends interface", "src/services/AuthService.ts", 8, 32),
    ]
)]))

write_text(f"{d}/rules_negative.yml", """\
rules:
  - id: neg-ext-001-direct-instantiation
    pattern: "new ConcreteService($...ARGS)"
    message: Direct concrete instantiation
    severity: WARNING
    languages:
      - typescript
  - id: neg-ext-002-tight-coupling
    pattern: "$X: ConcreteService"
    message: Tight coupling to concrete class
    severity: WARNING
    languages:
      - typescript
  - id: neg-ext-003-no-abstraction
    pattern: "class $NAME { constructor($...ARGS) { ... } }"
    message: Class without interface
    severity: WARNING
    languages:
      - typescript
  - id: neg-ext-004-hardcoded-dep
    pattern: "this.$FIELD = new $CLASS()"
    message: Hardcoded dependency
    severity: WARNING
    languages:
      - typescript
  - id: neg-ext-005-concrete-param
    pattern: "function $F($X: ConcreteService)"
    message: Concrete type as parameter
    severity: WARNING
    languages:
      - typescript
  - id: neg-ext-006-no-inject
    pattern: "const $NAME = new $CLASS($...ARGS)"
    message: Manual construction instead of injection
    severity: WARNING
    languages:
      - typescript
""")

# Negative SARIF: 4 of 6 rules still match (002, 003, 004, 006)
write_json(f"{d}/negative.sarif", make_sarif([make_run(
    rules=[
        {"id": "neg-ext-001-direct-instantiation", "shortDescription": {"text": "Direct concrete instantiation"}},
        {"id": "neg-ext-002-tight-coupling", "shortDescription": {"text": "Tight coupling to concrete class"}},
        {"id": "neg-ext-003-no-abstraction", "shortDescription": {"text": "Class without interface"}},
        {"id": "neg-ext-004-hardcoded-dep", "shortDescription": {"text": "Hardcoded dependency"}},
        {"id": "neg-ext-005-concrete-param", "shortDescription": {"text": "Concrete type as parameter"}},
        {"id": "neg-ext-006-no-inject", "shortDescription": {"text": "Manual construction instead of injection"}},
    ],
    results=[
        result_by_id("neg-ext-002-tight-coupling", "Tight coupling to concrete class", "src/controllers/UserController.ts", 5),
        result_by_id("neg-ext-003-no-abstraction", "Class without interface", "src/utils/Logger.ts", 1, 20),
        result_by_id("neg-ext-004-hardcoded-dep", "Hardcoded dependency", "src/app.ts", 15),
        result_by_id("neg-ext-006-no-inject", "Manual construction instead of injection", "src/index.ts", 8),
    ]
)]))

# Test results: single run
write_json(f"{d}/test_results.json", {
    "runs": [
        {"passed": 30, "failed": 1, "skipped": 0, "total": 31}
    ],
    "error": None
})

# ================================================================
# Instance 003: update-imports (multiple SARIF runs, broken tests)
# 8 positive rules, 7 match (dedup across 2 SARIF runs); 2 neg, 0 match
# Tests INVALID (pass rate < 0.3). Alignment = 0.0.
# SARIF has 2 runs with overlapping rule (pos-imp-001 in both).
# ================================================================
d = f"{BASE}/instance_003"
mkdir(d)

write_text(f"{d}/rules_positive.yml", """\
rules:
  - id: pos-imp-001
    pattern: "from tests import mock"
    message: Uses project mock import
    severity: INFO
    languages:
      - python
  - id: pos-imp-002
    pattern: "from awscli.testutils import mock"
    message: Uses testutils mock import
    severity: INFO
    languages:
      - python
  - id: pos-imp-003
    pattern: "from unittest.mock import patch"
    message: Uses unittest.mock.patch
    severity: INFO
    languages:
      - python
  - id: pos-imp-004
    pattern: "from unittest.mock import MagicMock"
    message: Uses MagicMock from unittest.mock
    severity: INFO
    languages:
      - python
  - id: pos-imp-005
    pattern: "mock.patch($...ARGS)"
    message: Uses mock.patch call
    severity: INFO
    languages:
      - python
  - id: pos-imp-006
    pattern: "mock.MagicMock($...ARGS)"
    message: Uses mock.MagicMock
    severity: INFO
    languages:
      - python
  - id: pos-imp-007
    pattern: "mock.Mock($...ARGS)"
    message: Uses mock.Mock
    severity: INFO
    languages:
      - python
  - id: pos-imp-008
    pattern-either:
      - pattern: "@mock.patch($...ARGS)"
      - pattern: "@mock.patch.object($...ARGS)"
    message: Uses mock.patch as decorator
    severity: INFO
    languages:
      - python
""")

# Positive SARIF: TWO runs, with pos-imp-001 appearing in BOTH.
# Run 1: matches 001, 002, 003 (3 rules)
# Run 2: matches 001 (duplicate!), 005, 006, 007, 008 (5 results, 4 new rules)
# Total distinct matched = 7 (pos-imp-004 never matches)
run1 = make_run(
    rules=[
        {"id": "pos-imp-001", "shortDescription": {"text": "Uses project mock import"}},
        {"id": "pos-imp-002", "shortDescription": {"text": "Uses testutils mock import"}},
        {"id": "pos-imp-003", "shortDescription": {"text": "Uses unittest.mock.patch"}},
        {"id": "pos-imp-004", "shortDescription": {"text": "Uses MagicMock from unittest.mock"}},
    ],
    results=[
        result_by_id("pos-imp-001", "Uses project mock import", "tests/test_s3.py", 3),
        result_by_id("pos-imp-001", "Uses project mock import", "tests/test_ec2.py", 2),
        result_by_id("pos-imp-002", "Uses testutils mock import", "tests/test_cli.py", 5),
        result_by_id("pos-imp-003", "Uses unittest.mock.patch", "tests/test_utils.py", 8),
    ]
)

run2 = make_run(
    rules=[
        {"id": "pos-imp-001", "shortDescription": {"text": "Uses project mock import"}},
        {"id": "pos-imp-005", "shortDescription": {"text": "Uses mock.patch call"}},
        {"id": "pos-imp-006", "shortDescription": {"text": "Uses mock.MagicMock"}},
        {"id": "pos-imp-007", "shortDescription": {"text": "Uses mock.Mock"}},
        {"id": "pos-imp-008", "shortDescription": {"text": "Uses mock.patch as decorator"}},
    ],
    results=[
        result_by_id("pos-imp-001", "Uses project mock import", "tests/test_iam.py", 4),
        result_by_id("pos-imp-005", "Uses mock.patch call", "tests/test_s3.py", 15),
        result_by_id("pos-imp-005", "Uses mock.patch call", "tests/test_ec2.py", 12),
        result_by_id("pos-imp-006", "Uses mock.MagicMock", "tests/test_cli.py", 20),
        result_by_id("pos-imp-007", "Uses mock.Mock", "tests/test_utils.py", 25),
        result_by_id("pos-imp-008", "Uses mock.patch as decorator", "tests/test_s3.py", 30),
    ],
    notifications=[{
        "level": "warning",
        "message": {"text": "Scan timed out for file tests/test_large.py after 60s"},
        "descriptor": {"id": "timeout-warning"}
    }]
)

write_json(f"{d}/positive.sarif", make_sarif([run1, run2]))

write_text(f"{d}/rules_negative.yml", """\
rules:
  - id: neg-imp-001
    pattern: "import mock"
    message: Uses old mock import
    severity: WARNING
    languages:
      - python
  - id: neg-imp-002
    pattern: "from mock import $X"
    message: Imports from mock package
    severity: WARNING
    languages:
      - python
""")

# Negative SARIF: 0 matches (all old patterns removed successfully)
write_json(f"{d}/negative.sarif", make_sarif([make_run(
    rules=[
        {"id": "neg-imp-001", "shortDescription": {"text": "Uses old mock import"}},
        {"id": "neg-imp-002", "shortDescription": {"text": "Imports from mock package"}},
    ],
    results=[]
)]))

# Test results: broken (best pass rate = 7/25 = 0.28 < 0.3)
write_json(f"{d}/test_results.json", {
    "runs": [
        {"passed": 5, "failed": 20, "skipped": 0, "total": 25},
        {"passed": 7, "failed": 18, "skipped": 0, "total": 25},
        {"passed": 3, "failed": 22, "skipped": 0, "total": 25}
    ],
    "error": None
})

# ================================================================
# Instance 004: modernize-types (no positive rules, all negative avoided)
# 0 positive rules (empty); 3 negative rules, 0 match
# Tests valid. positive_ifr = null. ifr = 1.0. Alignment = 1.0.
# ================================================================
d = f"{BASE}/instance_004"
mkdir(d)

write_text(f"{d}/rules_positive.yml", """\
rules: []
""")

# Positive SARIF: empty (no rules, no results)
write_json(f"{d}/positive.sarif", make_sarif([make_run(
    rules=[],
    results=[]
)]))

write_text(f"{d}/rules_negative.yml", """\
rules:
  - id: neg-mod-001-interface-brace
    pattern: "interface{}"
    message: Uses interface{} instead of any
    severity: WARNING
    languages:
      - go
  - id: neg-mod-002-empty-interface
    pattern: "var $X interface{}"
    message: Variable declared with interface{}
    severity: WARNING
    languages:
      - go
  - id: neg-mod-003-param-interface
    pattern: "func $F($X interface{}) $RET"
    message: Parameter uses interface{}
    severity: WARNING
    languages:
      - go
""")

# Negative SARIF: 0 matches (all interface{} replaced with any)
write_json(f"{d}/negative.sarif", make_sarif([make_run(
    rules=[
        {"id": "neg-mod-001-interface-brace", "shortDescription": {"text": "Uses interface{} instead of any"}},
        {"id": "neg-mod-002-empty-interface", "shortDescription": {"text": "Variable declared with interface{}"}},
        {"id": "neg-mod-003-param-interface", "shortDescription": {"text": "Parameter uses interface{}"}},
    ],
    results=[]
)]))

# Test results: mostly passing, 3 runs
write_json(f"{d}/test_results.json", {
    "runs": [
        {"passed": 100, "failed": 0, "skipped": 5, "total": 105},
        {"passed": 99, "failed": 1, "skipped": 5, "total": 105},
        {"passed": 100, "failed": 0, "skipped": 5, "total": 105}
    ],
    "error": None
})

# ================================================================
# Instance 005: inline-method (SARIF suppression edge case)
# 4 positive rules, 3 SARIF matches but 1 suppressed -> 2 effective
# 3 negative rules, 2 match
# Tests valid. positive_ifr = 0.5, ifr = 3/7, alignment = 3/7.
# ================================================================
d = f"{BASE}/instance_005"
mkdir(d)

write_text(f"{d}/rules_positive.yml", """\
rules:
  - id: pos-inl-001
    pattern: "inline_transform($...ARGS)"
    message: Uses inline_transform function
    severity: INFO
    languages:
      - python
  - id: pos-inl-002
    pattern: "apply_inline($X, $Y)"
    message: Uses apply_inline function
    severity: INFO
    languages:
      - python
  - id: pos-inl-003
    pattern: "@cached"
    message: Uses cached decorator
    severity: INFO
    languages:
      - python
  - id: pos-inl-004
    patterns:
      - pattern: |
          try:
              ...
          except InlineError:
              ...
    message: Handles InlineError
    severity: INFO
    languages:
      - python
""")

# Positive SARIF: 3 results, but pos-inl-002 is suppressed
pos_005_results = [
    result_by_id("pos-inl-001", "Uses inline_transform function", "src/transform.py", 25),
    {
        "ruleId": "pos-inl-002",
        "message": {"text": "Uses apply_inline function"},
        "locations": [{
            "physicalLocation": {
                "artifactLocation": {"uri": "src/legacy_compat.py"},
                "region": {"startLine": 10, "endLine": 10}
            }
        }],
        "suppressions": [{"kind": "inSource", "justification": "Legacy compatibility shim"}]
    },
    result_by_id("pos-inl-003", "Uses cached decorator", "src/cache.py", 5),
]

write_json(f"{d}/positive.sarif", make_sarif([make_run(
    rules=[
        {"id": "pos-inl-001", "shortDescription": {"text": "Uses inline_transform function"}},
        {"id": "pos-inl-002", "shortDescription": {"text": "Uses apply_inline function"}},
        {"id": "pos-inl-003", "shortDescription": {"text": "Uses cached decorator"}},
        {"id": "pos-inl-004", "shortDescription": {"text": "Handles InlineError"}},
    ],
    results=pos_005_results
)]))

write_text(f"{d}/rules_negative.yml", """\
rules:
  - id: neg-inl-001
    pattern: "manual_inline($...ARGS)"
    message: Uses deprecated manual_inline
    severity: WARNING
    languages:
      - python
  - id: neg-inl-002
    pattern: "force_expand($X)"
    message: Uses deprecated force_expand
    severity: WARNING
    languages:
      - python
  - id: neg-inl-003
    pattern: "no_cache"
    message: Uses deprecated no_cache flag
    severity: WARNING
    languages:
      - python
""")

# Negative SARIF: 2 of 3 rules match (neg-inl-001 and neg-inl-003)
write_json(f"{d}/negative.sarif", make_sarif([make_run(
    rules=[
        {"id": "neg-inl-001", "shortDescription": {"text": "Uses deprecated manual_inline"}},
        {"id": "neg-inl-002", "shortDescription": {"text": "Uses deprecated force_expand"}},
        {"id": "neg-inl-003", "shortDescription": {"text": "Uses deprecated no_cache flag"}},
    ],
    results=[
        result_by_id("neg-inl-001", "Uses deprecated manual_inline", "src/old_api.py", 42),
        result_by_id("neg-inl-003", "Uses deprecated no_cache flag", "src/config.py", 15),
    ]
)]))

# Test results: 1 run, valid (40/45 = 0.889 > 0.3)
write_json(f"{d}/test_results.json", {
    "runs": [
        {"passed": 40, "failed": 5, "skipped": 0, "total": 45}
    ],
    "error": None
})


# ================================================================
# Instance 006: extract-class
# EXPERT-LEVEL SARIF COMPLEXITY:
#   - tool.extensions: results reference rules in tool.extensions[].rules
#     via the SARIF toolComponent property
#   - Result kind filtering: kind="pass" results must be excluded
#   - Result level filtering: level="none" results must be excluded
#   - Phantom rules: SARIF references rule IDs not in YAML definitions
#
# 5 positive rules, 3 effective matches (1 via extension)
#   - pos-cls-001: matched via ruleId (driver)
#   - pos-cls-002: matched via ruleId (driver)
#   - pos-cls-004: matched via ruleIndex + toolComponent (extension)
#   - pos-cls-005: excluded (kind="pass")
#   - pos-cls-003: excluded (level="none")
#   - phantom-quality-check: phantom (not in YAML), excluded from match count
#
# 3 negative rules, 2 match
# Tests valid. ifr = 4/8 = 0.5, alignment = 0.5.
# phantom_positive = 1, phantom_negative = 0
# ================================================================
d = f"{BASE}/instance_006"
mkdir(d)

write_text(f"{d}/rules_positive.yml", """\
rules:
  - id: pos-cls-001-extracted-class
    pattern: "class DataProcessor:"
    message: Uses extracted DataProcessor class
    severity: INFO
    languages:
      - python
  - id: pos-cls-002-composition
    pattern: "$OBJ.process($...ARGS)"
    message: Uses composition via delegation
    severity: INFO
    languages:
      - python
  - id: pos-cls-003-interface-protocol
    pattern: "class $NAME(Protocol):"
    message: Uses Protocol interface
    severity: INFO
    languages:
      - python
  - id: pos-cls-004-dependency-inject
    pattern: "def __init__(self, $DEP: $TYPE):"
    message: Uses dependency injection
    severity: INFO
    languages:
      - python
  - id: pos-cls-005-single-resp
    patterns:
      - pattern: |
          class $NAME:
              \"\"\"$DOCSTRING\"\"\"
              ...
    message: Class has focused docstring
    severity: INFO
    languages:
      - python
""")

# Positive SARIF: tool.extensions with custom-architecture-checks rules.
# Driver rules: 001, 002, 003. Extension rules: 004, 005.
# Results include kind="pass", level="none", and a phantom rule.
pos_006_sarif = {
    "$schema": "https://docs.oasis-open.org/sarif/sarif/v2.1.0/os/schemas/sarif-schema-2.1.0.json",
    "version": "2.1.0",
    "runs": [{
        "tool": {
            "driver": {
                "name": "Opengrep OSS",
                "rules": [
                    {"id": "pos-cls-001-extracted-class", "shortDescription": {"text": "Uses extracted DataProcessor class"}},
                    {"id": "pos-cls-002-composition", "shortDescription": {"text": "Uses composition via delegation"}},
                    {"id": "pos-cls-003-interface-protocol", "shortDescription": {"text": "Uses Protocol interface"}}
                ]
            },
            "extensions": [{
                "name": "custom-architecture-checks",
                "rules": [
                    {"id": "pos-cls-004-dependency-inject", "shortDescription": {"text": "Uses dependency injection"}},
                    {"id": "pos-cls-005-single-resp", "shortDescription": {"text": "Class has focused docstring"}}
                ]
            }]
        },
        "invocations": [{"executionSuccessful": True, "toolExecutionNotifications": []}],
        "results": [
            # Match via ruleId (driver rule) — counts
            {
                "ruleId": "pos-cls-001-extracted-class",
                "message": {"text": "Uses extracted DataProcessor class"},
                "locations": [{"physicalLocation": {"artifactLocation": {"uri": "src/processor.py"}, "region": {"startLine": 15, "endLine": 45}}}]
            },
            # Match via ruleId (driver rule) — counts
            {
                "ruleId": "pos-cls-002-composition",
                "message": {"text": "Uses composition via delegation"},
                "locations": [{"physicalLocation": {"artifactLocation": {"uri": "src/app.py"}, "region": {"startLine": 22, "endLine": 22}}}]
            },
            # Match via ruleIndex + toolComponent (extension rule) — counts
            {
                "ruleIndex": 0,
                "rule": {"toolComponent": {"name": "custom-architecture-checks", "index": 0}},
                "message": {"text": "Uses dependency injection"},
                "locations": [{"physicalLocation": {"artifactLocation": {"uri": "src/processor.py"}, "region": {"startLine": 16, "endLine": 16}}}]
            },
            # kind="pass" means the rule was checked but did NOT find a match — excluded
            {
                "ruleId": "pos-cls-005-single-resp",
                "kind": "pass",
                "message": {"text": "Class docstring check — not matched"},
                "locations": [{"physicalLocation": {"artifactLocation": {"uri": "src/processor.py"}, "region": {"startLine": 1, "endLine": 1}}}]
            },
            # level="none" is informational only — excluded
            {
                "ruleId": "pos-cls-003-interface-protocol",
                "level": "none",
                "message": {"text": "Protocol interface — informational only"},
                "locations": [{"physicalLocation": {"artifactLocation": {"uri": "src/interfaces.py"}, "region": {"startLine": 5, "endLine": 5}}}]
            },
            # Phantom rule — ID not in rules YAML. Passes jq filter but must be
            # detected by Python cross-validation and excluded from match count.
            {
                "ruleId": "phantom-quality-check",
                "message": {"text": "Quality check from stale configuration"},
                "locations": [{"physicalLocation": {"artifactLocation": {"uri": "src/app.py"}, "region": {"startLine": 1, "endLine": 1}}}]
            }
        ]
    }]
}
write_json(f"{d}/positive.sarif", pos_006_sarif)

write_text(f"{d}/rules_negative.yml", """\
rules:
  - id: neg-cls-001-god-class
    pattern: "class App:"
    message: God class still exists
    severity: WARNING
    languages:
      - python
  - id: neg-cls-002-direct-access
    pattern: "self._data[$KEY]"
    message: Direct data access instead of delegation
    severity: WARNING
    languages:
      - python
  - id: neg-cls-003-circular-import
    pattern: "from app import App"
    message: Circular import pattern
    severity: WARNING
    languages:
      - python
""")

# Negative SARIF: 2 of 3 rules still match (001, 002)
write_json(f"{d}/negative.sarif", make_sarif([make_run(
    rules=[
        {"id": "neg-cls-001-god-class", "shortDescription": {"text": "God class still exists"}},
        {"id": "neg-cls-002-direct-access", "shortDescription": {"text": "Direct data access instead of delegation"}},
        {"id": "neg-cls-003-circular-import", "shortDescription": {"text": "Circular import pattern"}},
    ],
    results=[
        result_by_id("neg-cls-001-god-class", "God class still exists", "src/app.py", 1, 200),
        result_by_id("neg-cls-002-direct-access", "Direct data access instead of delegation", "src/app.py", 55),
    ]
)]))

# Test results: 2 runs, best_passed=35, worst_failed=5, total=40
write_json(f"{d}/test_results.json", {
    "runs": [
        {"passed": 33, "failed": 7, "skipped": 0, "total": 40},
        {"passed": 35, "failed": 5, "skipped": 0, "total": 40}
    ],
    "error": None
})


print("Data generation complete: 6 instances created under /app/data/instances/")
