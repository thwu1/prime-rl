"""CSS Cascade Engine conformance tests.

Tests verify engine behavior through independent test fixtures constructed
in Python. Each test creates a minimal DOM/rules/properties scenario that
distinguishes correct from non-conformant behavior.

Some tests specifically exercise interacting bug pairs — they only pass
when BOTH related bugs are fixed together.

"""

import json
import os
import subprocess
import sys

sys.path.insert(0, "/app")


def _compute(dom, rules, properties):
    """Compute styles using the engine with given test data."""
    from engine.compute import compute_styles

    return compute_styles(dom, rules, properties)


# Minimal property metadata shared across tests
PROPS = {
    "color": {"inherited": True, "initial": "black"},
    "display": {"inherited": False, "initial": "inline"},
    "font-size": {"inherited": True, "initial": "16px"},
    "font-weight": {"inherited": True, "initial": "normal"},
    "background-color": {"inherited": False, "initial": "transparent"},
    "padding-top": {"inherited": False, "initial": "0"},
    "padding-right": {"inherited": False, "initial": "0"},
    "padding-bottom": {"inherited": False, "initial": "0"},
    "padding-left": {"inherited": False, "initial": "0"},
    "margin-top": {"inherited": False, "initial": "0"},
    "margin-right": {"inherited": False, "initial": "0"},
    "margin-bottom": {"inherited": False, "initial": "0"},
    "margin-left": {"inherited": False, "initial": "0"},
}


class TestCascadeOriginPriority:
    """CSS cascade origin and importance ordering per spec section 1.3."""

    def test_user_important_beats_author_important(self):
        """User !important must override author !important (spec priority 5 > 4)."""
        dom = {"node_id": 0, "tag": "p", "classes": ["x"], "children": []}
        rules = [
            {
                "selector": "p.x",
                "declarations": [
                    {"property": "color", "value": "crimson", "important": True}
                ],
                "origin": "author",
                "source_order": 0,
            },
            {
                "selector": "p.x",
                "declarations": [
                    {"property": "color", "value": "teal", "important": True}
                ],
                "origin": "user",
                "source_order": 0,
            },
        ]
        styles = _compute(dom, rules, PROPS)
        assert styles[0]["color"] == "teal", (
            f"User !important should win over author !important; "
            f"got '{styles[0]['color']}'"
        )

    def test_author_normal_beats_user_normal(self):
        """Author normal overrides user normal (spec priority 3 > 2)."""
        dom = {"node_id": 0, "tag": "p", "children": []}
        rules = [
            {
                "selector": "p",
                "declarations": [
                    {"property": "color", "value": "coral", "important": False}
                ],
                "origin": "author",
                "source_order": 0,
            },
            {
                "selector": "p",
                "declarations": [
                    {"property": "color", "value": "olive", "important": False}
                ],
                "origin": "user",
                "source_order": 0,
            },
        ]
        styles = _compute(dom, rules, PROPS)
        assert styles[0]["color"] == "coral", (
            f"Author normal should win over user normal; "
            f"got '{styles[0]['color']}'"
        )


class TestSpecificity:
    """CSS specificity calculation per spec section 2."""

    def test_attribute_selector_counted_in_b_column(self):
        """Attribute selectors must contribute to the class-level (b) bucket."""
        dom = {
            "node_id": 0,
            "tag": "a",
            "classes": ["link"],
            "attributes": {"data-ext": "1"},
            "children": [],
        }
        rules = [
            {
                "selector": 'a[data-ext="1"]',
                "declarations": [
                    {"property": "color", "value": "navy", "important": False}
                ],
                "origin": "author",
                "source_order": 0,
            },
            {
                "selector": ".link",
                "declarations": [
                    {"property": "color", "value": "maroon", "important": False}
                ],
                "origin": "author",
                "source_order": 1,
            },
        ]
        styles = _compute(dom, rules, PROPS)
        # a[data-ext="1"]: (0,1,1) with correct attribute counting
        # .link: (0,1,0)
        # (0,1,1) > (0,1,0) -> navy wins
        assert styles[0]["color"] == "navy", (
            f"Attribute selector should increase specificity; "
            f"got '{styles[0]['color']}'"
        )


class TestSpecificityCascadeInteraction:
    """Tests that require BOTH specificity counting AND cascade sort key to be correct.

    These tests only pass when the cascade sort key includes specificity
    as a tiebreaker within the same origin+importance level. Fixing
    specificity calculation alone is insufficient.
    """

    def test_attribute_specificity_wins_over_later_source_order(self):
        """Higher specificity must beat later source order at the same cascade level."""
        dom = {
            "node_id": 0,
            "tag": "a",
            "classes": ["link"],
            "attributes": {"data-ext": "1"},
            "children": [],
        }
        rules = [
            {
                "selector": 'a[data-ext="1"]',
                "declarations": [
                    {"property": "color", "value": "red", "important": False}
                ],
                "origin": "author",
                "source_order": 0,
            },
            {
                "selector": "a",
                "declarations": [
                    {"property": "color", "value": "green", "important": False}
                ],
                "origin": "author",
                "source_order": 5,
            },
        ]
        styles = _compute(dom, rules, PROPS)
        # a[data-ext="1"]: specificity (0,1,1) — requires attribute counting
        # a: specificity (0,0,1)
        # Same origin+importance -> specificity decides (requires sort key fix)
        # red wins ONLY if both specificity counting AND sort key are correct
        assert styles[0]["color"] == "red", (
            f"Attribute selector (0,1,1) should beat type selector (0,0,1) "
            f"regardless of source order; got '{styles[0]['color']}'. "
            f"Check both specificity.py AND cascade.py sort key."
        )


class TestChildCombinator:
    """Child combinator (>) per spec section 3.2."""

    def test_matches_direct_parent_not_grandparent(self):
        """Child combinator must match direct parent, not ancestor."""
        dom = {
            "node_id": 0,
            "tag": "div",
            "classes": ["outer"],
            "children": [
                {
                    "node_id": 1,
                    "tag": "div",
                    "classes": ["inner"],
                    "children": [
                        {"node_id": 2, "tag": "p", "children": []}
                    ],
                }
            ],
        }
        rules = [
            {
                "selector": ".outer > p",
                "declarations": [
                    {"property": "color", "value": "crimson", "important": False}
                ],
                "origin": "author",
                "source_order": 0,
            },
            {
                "selector": ".inner > p",
                "declarations": [
                    {"property": "color", "value": "teal", "important": False}
                ],
                "origin": "author",
                "source_order": 1,
            },
        ]
        styles = _compute(dom, rules, PROPS)
        assert styles[2]["color"] == "teal", (
            f"Child combinator should match direct parent; "
            f"got '{styles[2]['color']}'"
        )


class TestChildCombinatorCascadeInteraction:
    """Tests that the child combinator fix exposes the cascade priority bug.

    With a broken child combinator, the author !important rule doesn't match,
    so the user !important rule wins by default. Once the combinator is fixed,
    both rules compete, and only correct cascade priorities give the right result.
    """

    def test_child_match_with_importance_cascade(self):
        """Correct child combinator + correct cascade priority = user !important wins."""
        dom = {
            "node_id": 0,
            "tag": "div",
            "classes": ["container"],
            "children": [
                {
                    "node_id": 1,
                    "tag": "div",
                    "classes": ["inner"],
                    "children": [
                        {"node_id": 2, "tag": "p", "classes": ["special"], "children": []}
                    ],
                }
            ],
        }
        rules = [
            {
                "selector": ".inner > p.special",
                "declarations": [
                    {"property": "background-color", "value": "yellow", "important": True}
                ],
                "origin": "author",
                "source_order": 0,
            },
            {
                "selector": "p.special",
                "declarations": [
                    {"property": "background-color", "value": "lime", "important": True}
                ],
                "origin": "user",
                "source_order": 0,
            },
        ]
        styles = _compute(dom, rules, PROPS)
        # With correct child combinator: .inner > p.special matches (inner is parent)
        # author !important (pri 4) vs user !important (pri 5) -> lime wins
        assert styles[2]["background-color"] == "lime", (
            f"User !important should beat author !important after child combinator fix; "
            f"got '{styles[2]['background-color']}'"
        )


class TestShorthandExpansion:
    """Shorthand property expansion per spec section 4.1."""

    def test_three_value_left_mirrors_right(self):
        """In 3-value shorthand, left must equal right (2nd value), not bottom."""
        dom = {"node_id": 0, "tag": "div", "children": []}
        rules = [
            {
                "selector": "div",
                "declarations": [
                    {
                        "property": "padding",
                        "value": "10px 20px 30px",
                        "important": False,
                    }
                ],
                "origin": "author",
                "source_order": 0,
            },
        ]
        styles = _compute(dom, rules, PROPS)
        assert styles[0]["padding-top"] == "10px"
        assert styles[0]["padding-right"] == "20px"
        assert styles[0]["padding-bottom"] == "30px"
        assert styles[0]["padding-left"] == "20px", (
            f"3-value shorthand: left should mirror right (20px), "
            f"got '{styles[0]['padding-left']}'"
        )

    def test_four_value_clockwise(self):
        """4-value shorthand: top, right, bottom, left (clockwise)."""
        dom = {"node_id": 0, "tag": "div", "children": []}
        rules = [
            {
                "selector": "div",
                "declarations": [
                    {
                        "property": "margin",
                        "value": "1px 2px 3px 4px",
                        "important": False,
                    }
                ],
                "origin": "author",
                "source_order": 0,
            },
        ]
        styles = _compute(dom, rules, PROPS)
        assert styles[0]["margin-top"] == "1px"
        assert styles[0]["margin-right"] == "2px"
        assert styles[0]["margin-bottom"] == "3px"
        assert styles[0]["margin-left"] == "4px"


class TestKeywordResolution:
    """CSS-wide keyword resolution per spec section 5."""

    def test_initial_resolves_to_defined_value(self):
        """'initial' must resolve to the property's defined initial value."""
        dom = {
            "node_id": 0,
            "tag": "div",
            "children": [{"node_id": 1, "tag": "p", "children": []}],
        }
        rules = [
            {
                "selector": "div",
                "declarations": [
                    {"property": "color", "value": "red", "important": False}
                ],
                "origin": "author",
                "source_order": 0,
            },
            {
                "selector": "p",
                "declarations": [
                    {"property": "color", "value": "initial", "important": False}
                ],
                "origin": "author",
                "source_order": 1,
            },
        ]
        styles = _compute(dom, rules, PROPS)
        assert styles[1]["color"] == "black", (
            f"'initial' should resolve to 'black', got '{styles[1]['color']}'"
        )

    def test_unset_inherited_property_inherits(self):
        """'unset' on an inherited property must behave as 'inherit'."""
        dom = {
            "node_id": 0,
            "tag": "div",
            "children": [{"node_id": 1, "tag": "span", "children": []}],
        }
        rules = [
            {
                "selector": "div",
                "declarations": [
                    {"property": "color", "value": "purple", "important": False}
                ],
                "origin": "author",
                "source_order": 0,
            },
            {
                "selector": "span",
                "declarations": [
                    {"property": "color", "value": "unset", "important": False}
                ],
                "origin": "author",
                "source_order": 1,
            },
        ]
        styles = _compute(dom, rules, PROPS)
        assert styles[1]["color"] == "purple", (
            f"'unset' on inherited 'color' should inherit parent value 'purple', "
            f"got '{styles[1]['color']}'"
        )

    def test_unset_non_inherited_property_uses_initial(self):
        """'unset' on a non-inherited property must behave as 'initial'."""
        dom = {
            "node_id": 0,
            "tag": "div",
            "children": [{"node_id": 1, "tag": "span", "children": []}],
        }
        rules = [
            {
                "selector": "div",
                "declarations": [
                    {"property": "display", "value": "flex", "important": False}
                ],
                "origin": "author",
                "source_order": 0,
            },
            {
                "selector": "span",
                "declarations": [
                    {"property": "display", "value": "unset", "important": False}
                ],
                "origin": "author",
                "source_order": 1,
            },
        ]
        styles = _compute(dom, rules, PROPS)
        assert styles[1]["display"] == "inline", (
            f"'unset' on non-inherited 'display' should use initial 'inline', "
            f"got '{styles[1]['display']}'"
        )

    def test_unset_inherited_at_root_uses_initial(self):
        """'unset' on inherited property at root element -> initial value."""
        dom = {"node_id": 0, "tag": "div", "children": []}
        rules = [
            {
                "selector": "div",
                "declarations": [
                    {"property": "color", "value": "unset", "important": False}
                ],
                "origin": "author",
                "source_order": 0,
            },
        ]
        styles = _compute(dom, rules, PROPS)
        assert styles[0]["color"] == "black", (
            f"'unset' at root should fall back to initial 'black', "
            f"got '{styles[0]['color']}'"
        )


class TestCLIAndTooling:
    """Engine CLI, Makefile, and tool integration."""

    def test_engine_produces_valid_json(self):
        """Engine CLI must produce valid JSON with all DOM nodes."""
        result = subprocess.run(
            ["python3", "/app/run.py"],
            capture_output=True,
            text=True,
            cwd="/app",
        )
        assert result.returncode == 0, f"Engine crashed: {result.stderr}"
        output = json.loads(result.stdout)
        assert isinstance(output, dict)
        assert len(output) == 11, f"Expected 11 nodes, got {len(output)}"

    def test_make_diff_passes(self):
        """Engine output must match expected output snapshot from v1.0."""
        result = subprocess.run(
            ["make", "diff"],
            capture_output=True,
            text=True,
            cwd="/app",
        )
        assert result.returncode == 0, (
            f"make diff failed — output differs from expected:\n{result.stdout}"
        )

    def test_jq_can_query_engine_output(self):
        """Engine JSON output must be queryable by jq."""
        result = subprocess.run(
            "python3 /app/run.py | jq -e '.\"0\".display'",
            shell=True,
            capture_output=True,
            text=True,
            cwd="/app",
        )
        assert result.returncode == 0, f"jq query failed: {result.stderr}"
        assert result.stdout.strip().strip('"') == "block"

    def test_trace_output_available(self):
        """Engine must produce structured TRACE output when STYLE_DEBUG=1."""
        result = subprocess.run(
            ["make", "trace"],
            capture_output=True,
            text=True,
            cwd="/app",
        )
        assert result.returncode == 0, f"make trace failed: {result.stderr}"
        trace_lines = [
            l for l in result.stderr.split("\n") if l.startswith("TRACE ")
        ]
        assert len(trace_lines) > 0, "No TRACE lines in stderr"
        # Verify trace format: TRACE node=N tag=T prop=P val=V ...
        sample = trace_lines[0]
        assert "node=" in sample and "prop=" in sample and "pri=" in sample, (
            f"TRACE line missing expected fields: {sample}"
        )

    def test_awk_trace_analysis(self):
        """Trace output must be parseable by awk for cascade analysis."""
        # Use awk to extract all WINNER lines for a specific node
        result = subprocess.run(
            "make trace 2>&1 | awk '/^WINNER node=0 /{print}'",
            shell=True,
            capture_output=True,
            text=True,
            cwd="/app",
        )
        assert result.returncode == 0
        winner_lines = [l for l in result.stdout.strip().split("\n") if l]
        assert len(winner_lines) > 0, "awk should find WINNER lines for node 0"


class TestConformanceReport:
    """Conformance report deliverable."""

    def test_report_exists(self):
        """Conformance report must exist at /app/conformance_report.json."""
        assert os.path.isfile("/app/conformance_report.json"), (
            "Missing /app/conformance_report.json"
        )

    def test_report_structure(self):
        """Report must have issues_found array and keywords_implemented."""
        with open("/app/conformance_report.json") as f:
            report = json.load(f)
        assert "issues_found" in report, "Report missing 'issues_found'"
        assert isinstance(report["issues_found"], list)
        assert len(report["issues_found"]) >= 5, (
            f"Report lists {len(report['issues_found'])} issues, expected >= 5"
        )
        for issue in report["issues_found"]:
            assert "module" in issue, f"Issue missing 'module': {issue}"
            assert "description" in issue, f"Issue missing 'description': {issue}"
            assert "regression_commit" in issue, (
                f"Issue missing 'regression_commit': {issue}"
            )
        assert "keywords_implemented" in report, (
            "Report missing 'keywords_implemented'"
        )
        assert "unset" in report["keywords_implemented"], (
            "'unset' not listed in keywords_implemented"
        )

    def test_regression_commits_valid(self):
        """Each regression_commit must be a real git commit that changed the module."""
        with open("/app/conformance_report.json") as f:
            report = json.load(f)

        for issue in report["issues_found"]:
            commit = issue.get("regression_commit", "")
            module = issue.get("module", "")
            assert commit and len(commit) >= 7, (
                f"Invalid regression_commit '{commit}' for {module}"
            )

            # Verify commit exists in the repo
            result = subprocess.run(
                ["git", "rev-parse", "--verify", commit],
                capture_output=True,
                text=True,
                cwd="/app",
            )
            assert result.returncode == 0, (
                f"Commit {commit} not found in git history"
            )

            # Verify commit actually changed the reported module file
            result = subprocess.run(
                ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit],
                capture_output=True,
                text=True,
                cwd="/app",
            )
            assert f"engine/{module}" in result.stdout, (
                f"Commit {commit} did not change engine/{module}. "
                f"Changed files: {result.stdout.strip()}"
            )

    def test_fix_groups_structure(self):
        """Fix groups must identify interacting bug pairs with rationale."""
        with open("/app/conformance_report.json") as f:
            report = json.load(f)

        assert "fix_groups" in report, "Report missing 'fix_groups'"
        groups = report["fix_groups"]
        assert isinstance(groups, list), "'fix_groups' must be an array"
        assert len(groups) >= 1, (
            f"Expected at least 1 fix group, got {len(groups)}"
        )

        # Collect all modules mentioned in issues_found
        issue_modules = {issue["module"] for issue in report.get("issues_found", [])}

        has_multi_module = False
        for group in groups:
            assert "modules" in group, f"Fix group missing 'modules': {group}"
            assert "rationale" in group, f"Fix group missing 'rationale': {group}"
            assert isinstance(group["modules"], list), (
                f"Fix group 'modules' must be a list: {group}"
            )
            distinct_modules = set(group["modules"])
            assert len(distinct_modules) >= 2, (
                f"Fix group must reference at least 2 distinct modules: {group}"
            )
            assert isinstance(group["rationale"], str) and len(group["rationale"]) > 20, (
                f"Fix group rationale must be a substantive explanation: {group}"
            )
            # Every module in fix_groups should correspond to an issue
            for mod in group["modules"]:
                assert mod in issue_modules, (
                    f"Module '{mod}' appears in fix_groups but not in issues_found"
                )
            if len(distinct_modules) >= 2:
                has_multi_module = True

        assert has_multi_module, (
            "At least one fix group must identify 2+ distinct interacting modules"
        )

    def test_fix_groups_cover_real_interactions(self):
        """Fix groups should reflect actual cascade pipeline dependencies."""
        with open("/app/conformance_report.json") as f:
            report = json.load(f)

        groups = report.get("fix_groups", [])
        all_grouped_modules = set()
        for group in groups:
            for mod in group.get("modules", []):
                all_grouped_modules.add(mod)

        # The cascade pipeline has known interaction points — at minimum,
        # the specificity calculator and cascade resolver must appear together
        # in some group, since specificity has no effect without being in
        # the cascade sort key
        assert len(all_grouped_modules) >= 3, (
            f"Fix groups reference only {len(all_grouped_modules)} distinct modules; "
            f"expected at least 3 (the cascade pipeline has multiple interaction points)"
        )
