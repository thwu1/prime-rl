
import json
import os
import pytest

TOLERANCE = 0.01

# Expected ca, ce for each component (hand-computed from the full dependency graph)
# Format: name -> (ca, ce, abstract_types, concrete_types)
COMPONENT_DATA = {
    "web-frontend":        (0,  4,  3, 15),
    "mobile-app":          (0,  2,  2, 12),
    "admin-panel":         (0,  4,  1,  8),
    "api-gateway":         (3,  6,  4, 10),
    "user-service":        (3,  8,  5, 18),
    "order-service":       (3, 13,  4, 22),
    "payment-service":     (1, 11,  6, 14),
    "notification-service":(2,  4,  3, 11),
    "inventory-service":   (2,  6,  4, 16),
    "reporting-service":   (2,  5,  2, 19),
    "auth-service":        (3,  6,  7, 13),
    "search-service":      (1,  3,  3, 15),
    "shipping-service":    (1,  7,  3, 12),
    "pricing-service":     (1,  2,  2,  9),
    "analytics-service":   (1,  3,  1, 14),
    "user-domain":         (2,  0,  8, 12),
    "order-domain":        (3,  2, 10, 15),
    "product-domain":      (4,  0,  7, 11),
    "payment-domain":      (1,  1,  6,  8),
    "shipping-domain":     (1,  1,  5,  7),
    "db-adapter":          (10, 3, 10, 20),
    "cache-adapter":       (4,  3,  4,  8),
    "message-queue":       (3,  3,  6, 10),
    "email-adapter":       (1,  1,  3,  6),
    "storage-adapter":     (0,  2,  5,  9),
    "logging-framework":   (1,  1,  4, 12),
    "monitoring-adapter":  (0,  1,  3,  7),
    "common-utils":        (18, 1,  2, 25),
    "shared-types":        (6,  0, 15, 10),
    "event-bus":           (5,  0,  8,  5),
    "config-manager":      (7,  1,  3,  9),
    "security-core":       (3,  0,  9, 11),
    "validation-lib":      (3,  0,  4, 14),
    "serialization-lib":   (4,  0,  3,  8),
    "metrics-collector":   (5,  0,  5,  7),
}

# Expected strongly connected components (size > 1)
EXPECTED_CYCLE_GROUPS = [
    {"components": ["inventory-service", "order-service", "shipping-service"], "min_edges_to_break": 1},
    {"components": ["analytics-service", "reporting-service"], "min_edges_to_break": 1},
    {"components": ["auth-service", "user-service"], "min_edges_to_break": 1},
    {"components": ["common-utils", "logging-framework"], "min_edges_to_break": 1},
    {"components": ["config-manager", "db-adapter"], "min_edges_to_break": 1},
]

EXPECTED_TOTAL_IN_CYCLES = 11

# Expected layer violations
EXPECTED_VIOLATIONS = [
    {"from": "admin-panel", "to": "db-adapter", "from_layer": "ui", "to_layer": "infrastructure"},
    {"from": "common-utils", "to": "logging-framework", "from_layer": "shared", "to_layer": "infrastructure"},
    {"from": "config-manager", "to": "db-adapter", "from_layer": "shared", "to_layer": "infrastructure"},
    {"from": "web-frontend", "to": "cache-adapter", "from_layer": "ui", "to_layer": "infrastructure"},
]


def _compute_expected(ca, ce, abstract_types, concrete_types):
    total = ca + ce
    instability = ce / total if total > 0 else 0.0
    abstractness = abstract_types / (abstract_types + concrete_types)
    distance = abs(abstractness + instability - 1.0)
    return instability, abstractness, distance


class TestMetrics:
    @pytest.fixture(autouse=True)
    def load_metrics(self):
        path = "/app/results/metrics.json"
        assert os.path.exists(path), f"Missing output file: {path}"
        with open(path) as f:
            self.metrics = json.load(f)

    def test_all_components_present(self):
        for name in COMPONENT_DATA:
            assert name in self.metrics, f"Component '{name}' missing from metrics"

    def test_no_extra_components(self):
        for name in self.metrics:
            assert name in COMPONENT_DATA, f"Unexpected component '{name}' in metrics"

    def test_component_count(self):
        assert len(self.metrics) == 35

    @pytest.mark.parametrize("name", list(COMPONENT_DATA.keys()))
    def test_ca(self, name):
        expected_ca = COMPONENT_DATA[name][0]
        actual = self.metrics[name]["ca"]
        assert actual == expected_ca, (
            f"{name}: ca expected {expected_ca}, got {actual}"
        )

    @pytest.mark.parametrize("name", list(COMPONENT_DATA.keys()))
    def test_ce(self, name):
        expected_ce = COMPONENT_DATA[name][1]
        actual = self.metrics[name]["ce"]
        assert actual == expected_ce, (
            f"{name}: ce expected {expected_ce}, got {actual}"
        )

    @pytest.mark.parametrize("name", list(COMPONENT_DATA.keys()))
    def test_instability(self, name):
        ca, ce, at, ct = COMPONENT_DATA[name]
        expected_i, _, _ = _compute_expected(ca, ce, at, ct)
        actual = self.metrics[name]["instability"]
        assert abs(actual - expected_i) < TOLERANCE, (
            f"{name}: instability expected {expected_i:.5f}, got {actual}"
        )

    @pytest.mark.parametrize("name", list(COMPONENT_DATA.keys()))
    def test_abstractness(self, name):
        ca, ce, at, ct = COMPONENT_DATA[name]
        _, expected_a, _ = _compute_expected(ca, ce, at, ct)
        actual = self.metrics[name]["abstractness"]
        assert abs(actual - expected_a) < TOLERANCE, (
            f"{name}: abstractness expected {expected_a:.5f}, got {actual}"
        )

    @pytest.mark.parametrize("name", list(COMPONENT_DATA.keys()))
    def test_distance(self, name):
        ca, ce, at, ct = COMPONENT_DATA[name]
        _, _, expected_d = _compute_expected(ca, ce, at, ct)
        actual = self.metrics[name]["distance"]
        assert abs(actual - expected_d) < TOLERANCE, (
            f"{name}: distance expected {expected_d:.5f}, got {actual}"
        )


class TestCycles:
    @pytest.fixture(autouse=True)
    def load_cycles(self):
        path = "/app/results/cycles.json"
        assert os.path.exists(path), f"Missing output file: {path}"
        with open(path) as f:
            self.cycles = json.load(f)

    def test_cycle_groups_key_exists(self):
        assert "cycle_groups" in self.cycles

    def test_total_components_in_cycles(self):
        assert self.cycles["total_components_in_cycles"] == EXPECTED_TOTAL_IN_CYCLES

    def test_cycle_group_count(self):
        assert len(self.cycles["cycle_groups"]) == len(EXPECTED_CYCLE_GROUPS), (
            f"Expected {len(EXPECTED_CYCLE_GROUPS)} cycle groups, "
            f"got {len(self.cycles['cycle_groups'])}"
        )

    def test_cycle_group_components(self):
        actual_groups = self.cycles["cycle_groups"]
        actual_sets = [frozenset(g["components"]) for g in actual_groups]
        for expected in EXPECTED_CYCLE_GROUPS:
            expected_set = frozenset(expected["components"])
            assert expected_set in actual_sets, (
                f"Expected cycle group {sorted(expected_set)} not found. "
                f"Actual groups: {[sorted(s) for s in actual_sets]}"
            )

    def test_cycle_group_min_edges(self):
        actual_groups = self.cycles["cycle_groups"]
        actual_by_key = {frozenset(g["components"]): g["min_edges_to_break"] for g in actual_groups}
        for expected in EXPECTED_CYCLE_GROUPS:
            key = frozenset(expected["components"])
            assert key in actual_by_key, f"Cycle group {sorted(key)} not found"
            assert actual_by_key[key] == expected["min_edges_to_break"], (
                f"Cycle group {sorted(key)}: min_edges_to_break expected "
                f"{expected['min_edges_to_break']}, got {actual_by_key[key]}"
            )

    def test_cycle_groups_sorted_by_size_desc(self):
        groups = self.cycles["cycle_groups"]
        sizes = [len(g["components"]) for g in groups]
        assert sizes == sorted(sizes, reverse=True), (
            f"Cycle groups not sorted by size descending: {sizes}"
        )

    def test_components_within_groups_sorted(self):
        for group in self.cycles["cycle_groups"]:
            comps = group["components"]
            assert comps == sorted(comps), (
                f"Components not sorted alphabetically: {comps}"
            )


class TestViolations:
    @pytest.fixture(autouse=True)
    def load_violations(self):
        path = "/app/results/violations.json"
        assert os.path.exists(path), f"Missing output file: {path}"
        with open(path) as f:
            self.violations = json.load(f)

    def test_violations_key_exists(self):
        assert "violations" in self.violations

    def test_total_violations(self):
        assert self.violations["total_violations"] == len(EXPECTED_VIOLATIONS)

    def test_violation_count(self):
        assert len(self.violations["violations"]) == len(EXPECTED_VIOLATIONS)

    def test_each_violation_present(self):
        actual = self.violations["violations"]
        for expected_v in EXPECTED_VIOLATIONS:
            found = False
            for actual_v in actual:
                if (actual_v["from"] == expected_v["from"] and
                    actual_v["to"] == expected_v["to"] and
                    actual_v["from_layer"] == expected_v["from_layer"] and
                    actual_v["to_layer"] == expected_v["to_layer"]):
                    found = True
                    break
            assert found, (
                f"Expected violation {expected_v} not found in actual violations"
            )

    def test_no_extra_violations(self):
        actual = self.violations["violations"]
        expected_keys = {(v["from"], v["to"]) for v in EXPECTED_VIOLATIONS}
        for actual_v in actual:
            key = (actual_v["from"], actual_v["to"])
            assert key in expected_keys, (
                f"Unexpected violation: {actual_v['from']} -> {actual_v['to']}"
            )

    def test_violations_sorted(self):
        violations = self.violations["violations"]
        keys = [(v["from"], v["to"]) for v in violations]
        assert keys == sorted(keys), (
            f"Violations not sorted by (from, to)"
        )
