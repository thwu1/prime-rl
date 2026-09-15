
"""Verification tests for interaction probe report."""

import json
import os
import pytest


REPORT_PATH = "/app/report.json"

EXPECTED_ELEMENT_IDS = {
    "algorithm-select",
    "iterations-input",
    "dimension-input",
    "advanced-checkbox",
    "configure-btn",
    "tolerance-input",
    "convergence-select",
    "run-btn",
    "sort-iteration",
    "sort-value",
    "sort-error",
    "scale-select",
    "toggle-gridlines",
    "export-csv-btn",
    "reset-btn",
}

EXPECTED_INITIALLY_VISIBLE = {
    "algorithm-select",
    "iterations-input",
    "dimension-input",
    "advanced-checkbox",
    "configure-btn",
}

EXPECTED_SHADOW_DOM = {"scale-select", "toggle-gridlines"}

EXPECTED_CHAINS = {
    "advanced-checkbox": {"tolerance-input", "convergence-select"},
    "configure-btn": {"run-btn"},
    "run-btn": {
        "sort-iteration",
        "sort-value",
        "sort-error",
        "scale-select",
        "toggle-gridlines",
        "export-csv-btn",
        "reset-btn",
    },
}

EXPECTED_TOTAL = 15


@pytest.fixture
def report():
    assert os.path.exists(REPORT_PATH), f"Report not found at {REPORT_PATH}"
    with open(REPORT_PATH) as f:
        data = json.load(f)
    return data


class TestReportStructure:
    def test_has_required_fields(self, report):
        for field in [
            "total_elements",
            "elements",
            "discovery_chains",
            "shadow_dom_elements",
            "interaction_rate",
        ]:
            assert field in report, f"Missing required field: {field}"

    def test_elements_is_list(self, report):
        assert isinstance(report["elements"], list)

    def test_element_has_required_fields(self, report):
        for el in report["elements"]:
            for field in ["id", "tag", "in_shadow_dom", "initially_visible", "produces_mutation"]:
                assert field in el, f"Element {el.get('id', '?')} missing field: {field}"


class TestElementDiscovery:
    def test_total_element_count(self, report):
        assert report["total_elements"] == EXPECTED_TOTAL, (
            f"Expected {EXPECTED_TOTAL} elements, got {report['total_elements']}"
        )

    def test_element_list_length_matches_total(self, report):
        assert len(report["elements"]) == report["total_elements"]

    def test_all_expected_elements_found(self, report):
        found_ids = {el["id"] for el in report["elements"]}
        missing = EXPECTED_ELEMENT_IDS - found_ids
        extra = found_ids - EXPECTED_ELEMENT_IDS
        assert found_ids == EXPECTED_ELEMENT_IDS, (
            f"Missing: {missing}, Extra: {extra}"
        )


class TestVisibility:
    def test_initially_visible_elements(self, report):
        for el in report["elements"]:
            if el["id"] in EXPECTED_INITIALLY_VISIBLE:
                assert el["initially_visible"] is True, (
                    f"{el['id']} should be initially visible"
                )

    def test_initially_hidden_elements(self, report):
        for el in report["elements"]:
            if el["id"] not in EXPECTED_INITIALLY_VISIBLE:
                assert el["initially_visible"] is False, (
                    f"{el['id']} should NOT be initially visible"
                )


class TestShadowDOM:
    def test_shadow_dom_list(self, report):
        shadow_set = set(report["shadow_dom_elements"])
        assert shadow_set == EXPECTED_SHADOW_DOM, (
            f"Expected shadow DOM elements {EXPECTED_SHADOW_DOM}, got {shadow_set}"
        )

    def test_shadow_dom_flags(self, report):
        for el in report["elements"]:
            if el["id"] in EXPECTED_SHADOW_DOM:
                assert el["in_shadow_dom"] is True, (
                    f"{el['id']} should have in_shadow_dom=True"
                )
            else:
                assert el["in_shadow_dom"] is False, (
                    f"{el['id']} should have in_shadow_dom=False"
                )


class TestDiscoveryChains:
    def test_discovery_chains_present(self, report):
        assert len(report["discovery_chains"]) >= len(EXPECTED_CHAINS), (
            f"Expected at least {len(EXPECTED_CHAINS)} discovery chains"
        )

    def test_discovery_chain_mappings(self, report):
        # Merge chains with the same trigger
        chains = {}
        for chain in report["discovery_chains"]:
            trigger = chain["trigger"]
            revealed = set(chain["revealed"])
            if trigger in chains:
                chains[trigger] |= revealed
            else:
                chains[trigger] = revealed

        assert chains == EXPECTED_CHAINS, (
            f"Expected chains:\n{EXPECTED_CHAINS}\nGot:\n{chains}"
        )


class TestInteractionRate:
    def test_all_elements_produce_mutations(self, report):
        for el in report["elements"]:
            assert el["produces_mutation"] is True, (
                f"{el['id']} should produce a DOM mutation"
            )

    def test_interaction_rate_value(self, report):
        assert abs(report["interaction_rate"] - 1.0) < 0.01, (
            f"Expected interaction_rate ~1.0, got {report['interaction_rate']}"
        )
