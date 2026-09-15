
import json
import os
import pytest

RESULTS_FILE = "/app/results.json"

# Expected anomalies based on deterministic data generation (seed=314159).
EXPECTED_ANOMALIES = [
    {"type": "write_skew", "txs": {"T_0601", "T_0602"}, "label": "write_skew_shard0"},
    {"type": "write_skew", "txs": {"T_0603", "T_0604"}, "label": "write_skew_shard1"},
    {"type": "lost_update", "txs": {"T_0905", "T_0906"}, "label": "lost_update_shard2"},
    {"type": "atomicity_violation", "txs": {"X_0051"}, "label": "atomicity_violation_1"},
    {"type": "atomicity_violation", "txs": {"X_0052"}, "label": "atomicity_violation_2"},
    {"type": "dirty_read", "txs": {"T_1207", "T_1208"}, "label": "dirty_read_shard0"},
    {"type": "non_repeatable_read", "txs": {"T_1209"}, "label": "non_repeatable_read_shard1"},
    {"type": "serializability_cycle", "txs": {"T_1511", "T_1512", "T_1513"}, "label": "cycle_shard2"},
]


def load_results():
    assert os.path.exists(RESULTS_FILE), f"Results file not found: {RESULTS_FILE}"
    with open(RESULTS_FILE) as f:
        return json.load(f)


def find_anomaly(data, expected_txs):
    """Check if any reported anomaly references all expected tx IDs."""
    for anomaly in data.get("anomalies", []):
        tx_ids = set()
        for field in ["transactions", "tx_ids", "transaction_ids", "involved_transactions"]:
            val = anomaly.get(field, [])
            if isinstance(val, str):
                tx_ids.add(val)
            elif isinstance(val, list):
                tx_ids.update(str(v) for v in val)
        desc = str(anomaly.get("description", "")) + str(anomaly.get("details", ""))
        for tx in expected_txs:
            if tx in desc:
                tx_ids.add(tx)
        if expected_txs.issubset(tx_ids):
            return anomaly
    return None


class TestResultsStructure:
    def test_results_file_exists(self):
        assert os.path.exists(RESULTS_FILE), "results.json not found at /app/results.json"

    def test_valid_json_with_required_fields(self):
        data = load_results()
        assert isinstance(data, dict), "results.json root must be a JSON object"
        assert "anomalies" in data, "Missing 'anomalies' field"
        assert "total_transactions" in data, "Missing 'total_transactions' field"
        assert "cross_shard_transactions" in data, "Missing 'cross_shard_transactions' field"
        assert "anomaly_count" in data, "Missing 'anomaly_count' field"
        assert isinstance(data["anomalies"], list), "'anomalies' must be a list"

    def test_transaction_counts(self):
        data = load_results()
        total = data["total_transactions"]
        cross = data["cross_shard_transactions"]
        assert 2000 <= total <= 2500, f"Expected ~2215 total transactions, got {total}"
        assert 80 <= cross <= 130, f"Expected ~102 cross-shard transactions, got {cross}"

    def test_anomaly_count_reasonable(self):
        data = load_results()
        count = data["anomaly_count"]
        assert count >= 5, f"Too few anomalies reported ({count}), expected at least 5"
        assert count <= 20, f"Too many anomalies reported ({count}), likely false positives"
        assert count == len(data["anomalies"]), "anomaly_count doesn't match length of anomalies list"


class TestAnomalyDetection:
    def test_atomicity_violations(self):
        """Atomicity violations (mixed commit/abort) are the most distinctive."""
        data = load_results()
        a1 = find_anomaly(data, {"X_0051"})
        a2 = find_anomaly(data, {"X_0052"})
        assert a1 is not None, "Atomicity violation X_0051 not detected"
        assert a2 is not None, "Atomicity violation X_0052 not detected"

    def test_read_anomalies(self):
        """At least one of dirty_read or non_repeatable_read must be found."""
        data = load_results()
        found = 0
        if find_anomaly(data, {"T_1208"}):
            found += 1
        if find_anomaly(data, {"T_1207", "T_1208"}):
            found += 1
        if find_anomaly(data, {"T_1209"}):
            found += 1
        assert found >= 1, "Neither dirty read (T_1207/T_1208) nor non-repeatable read (T_1209) detected"

    def test_serialization_graph_anomalies(self):
        """At least one cycle-based anomaly must be found."""
        data = load_results()
        found = 0
        cycle_anomalies = [
            {"T_0601", "T_0602"},
            {"T_0603", "T_0604"},
            {"T_0905", "T_0906"},
            {"T_1511", "T_1512"},
            {"T_1512", "T_1513"},
            {"T_1511", "T_1513"},
            {"T_1511", "T_1512", "T_1513"},
        ]
        for expected_txs in cycle_anomalies:
            if find_anomaly(data, expected_txs):
                found += 1
        assert found >= 1, "No serialization graph anomalies detected"

    def test_overall_anomaly_coverage(self):
        """At least 6 of 8 expected anomalies must be detected."""
        data = load_results()
        found = 0
        for expected in EXPECTED_ANOMALIES:
            if find_anomaly(data, expected["txs"]):
                found += 1
        assert found >= 6, (
            f"Detected only {found}/8 expected anomalies, need at least 6. "
            f"Expected anomalies: {[e['label'] for e in EXPECTED_ANOMALIES]}"
        )
