
import json
import pytest


EXPECTED_VERDICTS = {
    1: "ALLOW",
    2: "DENY",
    3: "ALLOW",
    4: "ALLOW",
    5: "DENY",
    6: "ALLOW",
    7: "ALLOW",
    8: "ALLOW",
    9: "DENY",
    10: "DENY",
    11: "DENY",
    12: "ALLOW",
    13: "DENY",
    14: "DENY",
    15: "ALLOW",
    16: "DENY",
    17: "ALLOW",
    18: "ALLOW",
    19: "DENY",
    20: "DENY",
    21: "ALLOW",
    22: "DENY",
    23: "DENY",
    24: "DENY",
    25: "ALLOW",
    26: "DENY",
    27: "DENY",
    28: "DENY",
    29: "DENY",
    30: "DENY",
}


def load_verdicts():
    with open("/app/verdicts.json") as f:
        return json.load(f)


def test_verdicts_file_exists_and_has_correct_count():
    data = load_verdicts()
    assert isinstance(data, list), "verdicts.json must be a JSON array"
    assert len(data) == 30, f"Expected 30 verdicts, got {len(data)}"


def test_verdicts_have_required_fields():
    data = load_verdicts()
    for entry in data:
        assert "id" in entry, f"Missing 'id' field in verdict entry: {entry}"
        assert "verdict" in entry, f"Missing 'verdict' field in verdict entry: {entry}"
        assert entry["verdict"] in ("ALLOW", "DENY"), \
            f"Invalid verdict '{entry['verdict']}' for connection {entry['id']}"


def test_all_connection_ids_present():
    data = load_verdicts()
    ids = {v["id"] for v in data}
    expected_ids = set(range(1, 31))
    missing = expected_ids - ids
    assert not missing, f"Missing connection IDs: {missing}"


@pytest.mark.parametrize("conn_id,expected", sorted(EXPECTED_VERDICTS.items()))
def test_verdict_correct(conn_id, expected):
    data = load_verdicts()
    verdict_map = {v["id"]: v["verdict"] for v in data}
    assert conn_id in verdict_map, f"Connection {conn_id} not found in verdicts"
    actual = verdict_map[conn_id]
    assert actual == expected, \
        f"Connection {conn_id}: expected {expected}, got {actual}"
