
import json
import os
import pytest

# Expected linearizability results
EXPECTED_RESULTS = {
    "h1_sequential": {"linearizable": True, "violating_op_index": -1},
    "h2_concurrent": {"linearizable": True, "violating_op_index": -1},
    "h3_error_valid": {"linearizable": True, "violating_op_index": -1},
    "h4_stale_read": {"linearizable": False, "violating_op_index": 2},
    "h5_error_invalid": {"linearizable": False, "violating_op_index": 3},
    "h6_txn_complex": {"linearizable": True, "violating_op_index": -1},
}

# Expected ground-truth final states for linearizable histories
EXPECTED_GROUNDTRUTH = {
    "h1_sequential": {"k1": "gamma", "k2": "beta"},
    "h2_concurrent": {"k1": "x", "k2": "y"},
    "h3_error_valid": {"k1": "c"},
    "h6_txn_complex": {"k1": "v2", "k2": "w1"},
}

HISTORY_NAMES = sorted(EXPECTED_RESULTS.keys())


def load_json(path):
    with open(path) as f:
        return json.load(f)


# ---- results.json checks ----

class TestResultsFile:
    def test_exists(self):
        assert os.path.exists("/app/results.json"), "results.json not found"

    def test_valid_json(self):
        results = load_json("/app/results.json")
        assert isinstance(results, dict), "results.json must be a JSON object"

    def test_all_histories_present(self):
        results = load_json("/app/results.json")
        for name in HISTORY_NAMES:
            assert name in results, f"Missing history: {name}"

    def test_no_extra_histories(self):
        results = load_json("/app/results.json")
        for name in results:
            assert name in EXPECTED_RESULTS, f"Unexpected history: {name}"


@pytest.mark.parametrize("name", HISTORY_NAMES)
class TestLinearizabilityVerdict:
    def test_linearizable_field(self, name):
        results = load_json("/app/results.json")
        assert name in results, f"Missing history: {name}"
        actual = results[name]["linearizable"]
        expected = EXPECTED_RESULTS[name]["linearizable"]
        assert actual == expected, (
            f"{name}: expected linearizable={expected}, got {actual}"
        )

    def test_violating_op_index(self, name):
        results = load_json("/app/results.json")
        assert name in results, f"Missing history: {name}"
        actual = results[name]["violating_op_index"]
        expected = EXPECTED_RESULTS[name]["violating_op_index"]
        assert actual == expected, (
            f"{name}: expected violating_op_index={expected}, got {actual}"
        )


# ---- groundtruth.json checks ----

class TestGroundtruth:
    def test_exists(self):
        assert os.path.exists("/app/groundtruth.json"), "groundtruth.json not found"

    def test_valid_json(self):
        gt = load_json("/app/groundtruth.json")
        assert isinstance(gt, dict), "groundtruth.json must be a JSON object"

    def test_linearizable_histories_present(self):
        gt = load_json("/app/groundtruth.json")
        for name in EXPECTED_GROUNDTRUTH:
            assert name in gt, f"Missing linearizable history in groundtruth: {name}"

    def test_non_linearizable_absent(self):
        gt = load_json("/app/groundtruth.json")
        for name in EXPECTED_RESULTS:
            if not EXPECTED_RESULTS[name]["linearizable"]:
                assert name not in gt, (
                    f"Non-linearizable history should not be in groundtruth: {name}"
                )

    @pytest.mark.parametrize("name", sorted(EXPECTED_GROUNDTRUTH.keys()))
    def test_final_state(self, name):
        gt = load_json("/app/groundtruth.json")
        assert name in gt, f"Missing: {name}"
        actual = gt[name]
        expected = EXPECTED_GROUNDTRUTH[name]
        assert actual == expected, (
            f"{name}: expected state {expected}, got {actual}"
        )


# ---- etcd tool usage evidence ----

class TestEtcdToolUsage:
    def test_snapshot_exists(self):
        assert os.path.exists("/app/etcd-snapshot.db"), (
            "etcd snapshot not found at /app/etcd-snapshot.db — "
            "must use etcdctl snapshot save"
        )

    def test_snapshot_nonempty(self):
        size = os.path.getsize("/app/etcd-snapshot.db")
        assert size > 0, "etcd snapshot file is empty"

    def test_etcd_data_dir_exists(self):
        # Evidence that an etcd server was started
        found = False
        for candidate in ["/app/etcd-data", "/tmp/etcd-data", "/app/default.etcd"]:
            if os.path.isdir(candidate):
                found = True
                break
        # Also check if any directory contains member/snap or member/wal
        if not found:
            for root, dirs, files in os.walk("/app"):
                if "member" in dirs:
                    member_path = os.path.join(root, "member")
                    if os.path.isdir(os.path.join(member_path, "snap")) or \
                       os.path.isdir(os.path.join(member_path, "wal")):
                        found = True
                        break
            for root, dirs, files in os.walk("/tmp"):
                if "member" in dirs:
                    member_path = os.path.join(root, "member")
                    if os.path.isdir(os.path.join(member_path, "snap")) or \
                       os.path.isdir(os.path.join(member_path, "wal")):
                        found = True
                        break
        assert found, (
            "No etcd data directory found — must start an etcd server instance"
        )
