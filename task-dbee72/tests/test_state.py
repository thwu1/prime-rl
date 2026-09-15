
import json
import subprocess
import os
import pytest

PROBE_PATH = "/app/interaction_probe.py"
SAMPLES_DIR = "/app/samples"


def run_probe(html_file):
    """Run the interaction probe on a sample HTML file and return parsed JSON."""
    path = os.path.join(SAMPLES_DIR, html_file)
    result = subprocess.run(
        ["python3", PROBE_PATH, path],
        capture_output=True, text=True, timeout=180,
        env={**os.environ, "PLAYWRIGHT_BROWSERS_PATH": "/opt/pw-browsers"},
    )
    assert result.returncode == 0, (
        f"Probe failed on {html_file} with exit code {result.returncode}.\n"
        f"stderr: {result.stderr[:2000]}"
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        pytest.fail(
            f"Probe output for {html_file} is not valid JSON.\n"
            f"stdout (first 500 chars): {result.stdout[:500]}"
        )


# ---------------------------------------------------------------------------
# Module-scoped fixtures: each probe runs once per test module
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def calculator_report():
    return run_probe("calculator.html")


@pytest.fixture(scope="module")
def form_report():
    return run_probe("dynamic_form.html")


@pytest.fixture(scope="module")
def dashboard_report():
    return run_probe("tabbed_dashboard.html")


# ---------------------------------------------------------------------------
# 1. Probe existence
# ---------------------------------------------------------------------------

class TestProbeExists:
    def test_probe_file_exists(self):
        assert os.path.isfile(PROBE_PATH), f"Probe not found at {PROBE_PATH}"


# ---------------------------------------------------------------------------
# 2. Output schema validation (using calculator as representative)
# ---------------------------------------------------------------------------

class TestOutputSchema:
    def test_has_elements_key(self, calculator_report):
        assert "elements" in calculator_report
        assert isinstance(calculator_report["elements"], list)

    def test_has_summary_key(self, calculator_report):
        assert "summary" in calculator_report
        assert isinstance(calculator_report["summary"], dict)

    def test_summary_has_total_elements(self, calculator_report):
        s = calculator_report["summary"]
        assert "total_elements" in s
        assert isinstance(s["total_elements"], int)
        assert s["total_elements"] > 0

    def test_summary_has_interaction_rate(self, calculator_report):
        s = calculator_report["summary"]
        assert "interaction_rate" in s
        assert isinstance(s["interaction_rate"], (int, float))
        assert 0.0 <= s["interaction_rate"] <= 1.0

    def test_element_required_fields(self, calculator_report):
        required = {"action_type", "state_changed", "mutations_observed"}
        for i, elem in enumerate(calculator_report["elements"]):
            for field in required:
                assert field in elem, f"Element {i} missing required field '{field}'"

    def test_mutations_non_negative(self, calculator_report):
        for elem in calculator_report["elements"]:
            assert elem["mutations_observed"] >= 0, (
                f"Negative mutations_observed for {elem.get('selector', '?')}"
            )


# ---------------------------------------------------------------------------
# 3. Interaction Rate consistency
# ---------------------------------------------------------------------------

class TestIRComputation:
    def test_ir_matches_element_data(self, calculator_report):
        elements = calculator_report["elements"]
        total = len(elements)
        state_changing = sum(1 for e in elements if e.get("state_changed"))
        expected_ir = state_changing / total if total > 0 else 0.0
        actual_ir = calculator_report["summary"]["interaction_rate"]
        assert abs(actual_ir - expected_ir) < 0.02, (
            f"IR mismatch: summary says {actual_ir}, "
            f"computed from elements {expected_ir}"
        )


# ---------------------------------------------------------------------------
# 4. Calculator-specific assertions
# ---------------------------------------------------------------------------

class TestCalculator:
    def test_discovers_enough_elements(self, calculator_report):
        n = len(calculator_report["elements"])
        assert n >= 15, f"Expected >=15 interactive elements, found {n}"

    def test_interaction_rate_reasonable(self, calculator_report):
        ir = calculator_report["summary"]["interaction_rate"]
        assert ir >= 0.50, f"Calculator IR should be >= 0.50, got {ir}"

    def test_click_actions_dominate(self, calculator_report):
        click_count = sum(
            1 for e in calculator_report["elements"]
            if e["action_type"] == "click"
        )
        assert click_count >= 10, (
            f"Calculator buttons should yield >= 10 click actions, got {click_count}"
        )


# ---------------------------------------------------------------------------
# 5. Dynamic form assertions
# ---------------------------------------------------------------------------

class TestDynamicForm:
    def test_discovers_form_elements(self, form_report):
        n = len(form_report["elements"])
        assert n >= 4, f"Expected >= 4 form elements, found {n}"

    def test_has_select_action(self, form_report):
        action_types = {e["action_type"] for e in form_report["elements"]}
        assert "select" in action_types, (
            f"Should detect a select-type element; found actions: {action_types}"
        )

    def test_has_type_action(self, form_report):
        action_types = {e["action_type"] for e in form_report["elements"]}
        assert "type" in action_types, (
            f"Should detect text input elements; found actions: {action_types}"
        )

    def test_select_produces_state_change(self, form_report):
        select_elems = [
            e for e in form_report["elements"] if e["action_type"] == "select"
        ]
        assert len(select_elems) > 0, "No select elements found"
        assert any(e["state_changed"] for e in select_elems), (
            "Select element should produce a state change "
            "(toggling business fields visibility)"
        )


# ---------------------------------------------------------------------------
# 6. Tabbed dashboard assertions
# ---------------------------------------------------------------------------

class TestTabbedDashboard:
    def test_discovers_enough_elements(self, dashboard_report):
        n = len(dashboard_report["elements"])
        assert n >= 5, f"Expected >= 5 dashboard elements, found {n}"

    def test_tab_elements_found(self, dashboard_report):
        tab_related = [
            e for e in dashboard_report["elements"]
            if "tab" in e.get("role", "").lower()
            or "tab" in e.get("label", "").lower()
            or "tab" in e.get("selector", "").lower()
        ]
        assert len(tab_related) >= 2, (
            f"Should find >= 2 tab elements, found {len(tab_related)}"
        )

    def test_shadow_dom_element_discovered(self, dashboard_report):
        shadow_or_toggle = [
            e for e in dashboard_report["elements"]
            if e.get("in_shadow_dom", False)
            or "toggle" in e.get("label", "").lower()
            or "theme" in e.get("label", "").lower()
        ]
        assert len(shadow_or_toggle) >= 1, (
            "Should discover the toggle button inside Shadow DOM"
        )

    def test_slider_element_found(self, dashboard_report):
        sliders = [
            e for e in dashboard_report["elements"]
            if e["action_type"] == "slide"
        ]
        assert len(sliders) >= 1, "Should find the range slider element"


# ---------------------------------------------------------------------------
# 7. Mutation classification
# ---------------------------------------------------------------------------

class TestMutationClassification:
    def test_meaningful_mutations_tracked(self, calculator_report):
        has_meaningful = any(
            e.get("meaningful_mutations", 0) > 0
            for e in calculator_report["elements"]
        )
        assert has_meaningful, (
            "At least some calculator elements should have meaningful_mutations > 0"
        )

    def test_meaningful_leq_total(self, calculator_report):
        for elem in calculator_report["elements"]:
            m = elem.get("meaningful_mutations", 0)
            t = elem["mutations_observed"]
            assert m <= t, (
                f"meaningful_mutations ({m}) > mutations_observed ({t}) "
                f"for {elem.get('selector', '?')}"
            )
