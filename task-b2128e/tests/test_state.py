
import json
import pytest
import jsonschema


EXPECTED = [
    # Query q01: R1 -> R7 loopback (inter-area, Area 0 -> Area 1 via ABR R4)
    {"router": "R1", "destination": "10.7.7.7/32",
     "next_hop": "R2", "cost": 21, "route_type": "O IA"},

    # Query q02: R1 -> R12 loopback (inter-area, Area 0 -> Area 3 via ABR R6)
    {"router": "R1", "destination": "10.12.12.12/32",
     "next_hop": "R6", "cost": 21, "route_type": "O IA"},

    # Query q03: R1 -> NSSA external E2 (Type 7->5 conversion at R5)
    {"router": "R1", "destination": "172.16.0.0/16",
     "next_hop": "R2", "cost": 20, "forward_cost": 38, "route_type": "O E2"},

    # Query q04: R1 -> NSSA external E1 (Type 7->5 conversion at R5)
    {"router": "R1", "destination": "172.17.0.0/16",
     "next_hop": "R2", "cost": 68, "route_type": "O E1"},

    # Query q05: R1 -> regular area external E2 (from R12 in Area 3)
    {"router": "R1", "destination": "192.168.0.0/16",
     "next_hop": "R6", "cost": 15, "forward_cost": 21, "route_type": "O E2"},

    # Query q06: R1 -> regular area external E1 (from R12 in Area 3)
    {"router": "R1", "destination": "192.168.1.0/24",
     "next_hop": "R6", "cost": 46, "route_type": "O E1"},

    # Query q07: R7 (stub) -> R2 loopback (inter-area through ABR R4)
    {"router": "R7", "destination": "10.2.2.2/32",
     "next_hop": "R4", "cost": 11, "route_type": "O IA"},

    # Query q08: R7 (stub) -> R11 (cross-area via backbone transit)
    {"router": "R7", "destination": "10.11.11.11/32",
     "next_hop": "R4", "cost": 40, "route_type": "O IA"},

    # Query q09: R7 (stub) -> external prefix (uses stub default route)
    {"router": "R7", "destination": "192.168.0.0/16",
     "next_hop": "R4", "cost": 4, "route_type": "O*IA"},

    # Query q10: R9 (NSSA) -> NSSA-local external E2 (Type 7 within NSSA)
    {"router": "R9", "destination": "172.16.0.0/16",
     "next_hop": "R10", "cost": 20, "forward_cost": 4, "route_type": "O N2"},

    # Query q11: R9 (NSSA) -> NSSA-local external E1 (Type 7 within NSSA)
    {"router": "R9", "destination": "172.17.0.0/16",
     "next_hop": "R10", "cost": 34, "route_type": "O N1"},

    # Query q12: R9 (NSSA) -> R1 loopback (inter-area through ABR R5)
    {"router": "R9", "destination": "10.1.1.1/32",
     "next_hop": "R5", "cost": 34, "route_type": "O IA"},

    # Query q13: R9 (NSSA) -> external from outside NSSA (uses NSSA default)
    {"router": "R9", "destination": "192.168.0.0/16",
     "next_hop": "R5", "cost": 1, "forward_cost": 7, "route_type": "O*N2"},

    # Query q14: R11 (regular) -> external E2 from local ASBR R12
    {"router": "R11", "destination": "192.168.0.0/16",
     "next_hop": "R12", "cost": 15, "forward_cost": 2, "route_type": "O E2"},

    # Query q15: R4 (ABR) -> R10 (inter-area via backbone to Area 2)
    {"router": "R4", "destination": "10.10.10.10/32",
     "next_hop": "R2", "cost": 36, "route_type": "O IA"},
]


@pytest.fixture
def results():
    with open("/app/results.json") as f:
        return json.load(f)


@pytest.fixture
def schema():
    with open("/app/result_schema.json") as f:
        return json.load(f)


def _find(results, router, destination):
    for r in results:
        if r.get("router") == router and r.get("destination") == destination:
            return r
    return None


class TestSchemaValidation:
    """Verify output conforms to the JSON schema."""

    def test_validates_against_schema(self, results, schema):
        jsonschema.validate(results, schema)

    def test_results_is_list(self, results):
        assert isinstance(results, list), "results.json must contain a JSON array"

    def test_results_has_15_entries(self, results):
        assert len(results) == 15, f"Expected 15 query results, got {len(results)}"


class TestIntraAreaAndInterArea:
    """Tests for O and O IA route computation."""

    def test_r1_to_r7_inter_area(self, results):
        exp = EXPECTED[0]
        act = _find(results, exp["router"], exp["destination"])
        assert act is not None, f"No result for {exp['router']} -> {exp['destination']}"
        assert act["next_hop"] == exp["next_hop"]
        assert act["cost"] == exp["cost"]
        assert act["route_type"] == exp["route_type"]

    def test_r1_to_r12_inter_area(self, results):
        exp = EXPECTED[1]
        act = _find(results, exp["router"], exp["destination"])
        assert act is not None, f"No result for {exp['router']} -> {exp['destination']}"
        assert act["next_hop"] == exp["next_hop"]
        assert act["cost"] == exp["cost"]
        assert act["route_type"] == exp["route_type"]

    def test_r7_to_r2_inter_area(self, results):
        exp = EXPECTED[6]
        act = _find(results, exp["router"], exp["destination"])
        assert act is not None, f"No result for {exp['router']} -> {exp['destination']}"
        assert act["next_hop"] == exp["next_hop"]
        assert act["cost"] == exp["cost"]
        assert act["route_type"] == exp["route_type"]

    def test_r7_to_r11_cross_area(self, results):
        exp = EXPECTED[7]
        act = _find(results, exp["router"], exp["destination"])
        assert act is not None, f"No result for {exp['router']} -> {exp['destination']}"
        assert act["next_hop"] == exp["next_hop"]
        assert act["cost"] == exp["cost"]
        assert act["route_type"] == exp["route_type"]

    def test_r9_to_r1_inter_area(self, results):
        exp = EXPECTED[11]
        act = _find(results, exp["router"], exp["destination"])
        assert act is not None, f"No result for {exp['router']} -> {exp['destination']}"
        assert act["next_hop"] == exp["next_hop"]
        assert act["cost"] == exp["cost"]
        assert act["route_type"] == exp["route_type"]

    def test_r4_to_r10_inter_area(self, results):
        exp = EXPECTED[14]
        act = _find(results, exp["router"], exp["destination"])
        assert act is not None, f"No result for {exp['router']} -> {exp['destination']}"
        assert act["next_hop"] == exp["next_hop"]
        assert act["cost"] == exp["cost"]
        assert act["route_type"] == exp["route_type"]


class TestExternalRoutes:
    """Tests for E1, E2, N1, N2 external route computation."""

    def test_r1_nssa_external_e2(self, results):
        exp = EXPECTED[2]
        act = _find(results, exp["router"], exp["destination"])
        assert act is not None, f"No result for {exp['router']} -> {exp['destination']}"
        assert act["next_hop"] == exp["next_hop"]
        assert act["cost"] == exp["cost"]
        assert act["route_type"] == exp["route_type"]
        assert act.get("forward_cost") == exp["forward_cost"]

    def test_r1_nssa_external_e1(self, results):
        exp = EXPECTED[3]
        act = _find(results, exp["router"], exp["destination"])
        assert act is not None, f"No result for {exp['router']} -> {exp['destination']}"
        assert act["next_hop"] == exp["next_hop"]
        assert act["cost"] == exp["cost"]
        assert act["route_type"] == exp["route_type"]

    def test_r1_regular_external_e2(self, results):
        exp = EXPECTED[4]
        act = _find(results, exp["router"], exp["destination"])
        assert act is not None, f"No result for {exp['router']} -> {exp['destination']}"
        assert act["next_hop"] == exp["next_hop"]
        assert act["cost"] == exp["cost"]
        assert act["route_type"] == exp["route_type"]
        assert act.get("forward_cost") == exp["forward_cost"]

    def test_r1_regular_external_e1(self, results):
        exp = EXPECTED[5]
        act = _find(results, exp["router"], exp["destination"])
        assert act is not None, f"No result for {exp['router']} -> {exp['destination']}"
        assert act["next_hop"] == exp["next_hop"]
        assert act["cost"] == exp["cost"]
        assert act["route_type"] == exp["route_type"]

    def test_r9_nssa_local_n2(self, results):
        exp = EXPECTED[9]
        act = _find(results, exp["router"], exp["destination"])
        assert act is not None, f"No result for {exp['router']} -> {exp['destination']}"
        assert act["next_hop"] == exp["next_hop"]
        assert act["cost"] == exp["cost"]
        assert act["route_type"] == exp["route_type"]
        assert act.get("forward_cost") == exp["forward_cost"]

    def test_r9_nssa_local_n1(self, results):
        exp = EXPECTED[10]
        act = _find(results, exp["router"], exp["destination"])
        assert act is not None, f"No result for {exp['router']} -> {exp['destination']}"
        assert act["next_hop"] == exp["next_hop"]
        assert act["cost"] == exp["cost"]
        assert act["route_type"] == exp["route_type"]

    def test_r11_local_external_e2(self, results):
        exp = EXPECTED[13]
        act = _find(results, exp["router"], exp["destination"])
        assert act is not None, f"No result for {exp['router']} -> {exp['destination']}"
        assert act["next_hop"] == exp["next_hop"]
        assert act["cost"] == exp["cost"]
        assert act["route_type"] == exp["route_type"]
        assert act.get("forward_cost") == exp["forward_cost"]


class TestDefaultRoutes:
    """Tests for stub and NSSA default route behavior."""

    def test_r7_stub_default(self, results):
        exp = EXPECTED[8]
        act = _find(results, exp["router"], exp["destination"])
        assert act is not None, f"No result for {exp['router']} -> {exp['destination']}"
        assert act["next_hop"] == exp["next_hop"]
        assert act["cost"] == exp["cost"]
        assert act["route_type"] == exp["route_type"]

    def test_r9_nssa_default(self, results):
        exp = EXPECTED[12]
        act = _find(results, exp["router"], exp["destination"])
        assert act is not None, f"No result for {exp['router']} -> {exp['destination']}"
        assert act["next_hop"] == exp["next_hop"]
        assert act["cost"] == exp["cost"]
        assert act["route_type"] == exp["route_type"]
        assert act.get("forward_cost") == exp["forward_cost"]
