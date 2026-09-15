
import json
import os
import sys

sys.path.insert(0, "/tests")

import grpc
import pytest

import interface_pb2
import interface_pb2_grpc


def load_train_data():
    with open("/app/train_data.json") as f:
        return json.load(f)


def load_test_data():
    with open("/app/test_data.json") as f:
        return json.load(f)


def load_ground_truth():
    with open("/tests/ground_truth.json") as f:
        return json.load(f)


def load_results():
    with open("/app/results.json") as f:
        return json.load(f)


def compute_apfd(prioritized_order, ground_truth):
    n = len(prioritized_order)
    failed_positions = []
    for i, tid in enumerate(prioritized_order):
        if ground_truth[tid]["test_outcome"] == "FAIL":
            failed_positions.append(i + 1)
    m = len(failed_positions)
    if n == 0 or m == 0:
        return 1.0
    return 1 - sum(failed_positions) / (n * m) + 1 / (2 * n)


def compute_apfdc(prioritized_order, ground_truth):
    cumulative_time = 0.0
    total_cost = 0.0
    cumulative_costs_to_faults = []
    num_failed = 0
    for tid in prioritized_order:
        duration = ground_truth[tid]["test_duration"]
        cumulative_time += duration
        total_cost += duration
        if ground_truth[tid]["test_outcome"] == "FAIL":
            cumulative_costs_to_faults.append(cumulative_time)
            num_failed += 1
    if num_failed == 0 or total_cost == 0:
        return 1.0
    return (
        1
        - sum(cumulative_costs_to_faults) / (total_cost * num_failed)
        + 1 / (2 * num_failed)
    )


def compute_last_fault_position(prioritized_order, ground_truth):
    """Return the 1-indexed position of the last fault in the ordering."""
    last_pos = 0
    for i, tid in enumerate(prioritized_order):
        if ground_truth[tid]["test_outcome"] == "FAIL":
            last_pos = i + 1
    return last_pos


def compute_first_fault_position(prioritized_order, ground_truth):
    """Return the 1-indexed position of the first fault in the ordering."""
    for i, tid in enumerate(prioritized_order):
        if ground_truth[tid]["test_outcome"] == "FAIL":
            return i + 1
    return len(prioritized_order) + 1


def _make_oracle_stream(train_data):
    for tc in train_data:
        oracle = interface_pb2.Oracle()
        oracle.testCase.testId = tc["_id"]["$oid"]
        for pt in tc["road_points"]:
            rp = oracle.testCase.roadPoints.add()
            rp.x = pt["x"]
            rp.y = pt["y"]
        oracle.hasFailed = tc["meta_data"]["test_info"]["test_outcome"] == "FAIL"
        yield oracle


def _make_test_stream(test_data):
    for tc in test_data:
        sdc = interface_pb2.SDCTestCase()
        sdc.testId = tc["_id"]["$oid"]
        for pt in tc["road_points"]:
            rp = sdc.roadPoints.add()
            rp.x = pt["x"]
            rp.y = pt["y"]
        yield sdc


class TestGRPCServerReachable:
    """Verify the gRPC server is running on port 50051."""

    def test_server_responds_to_name(self):
        channel = grpc.insecure_channel("localhost:50051")
        stub = interface_pb2_grpc.CompetitionToolStub(channel)
        resp = stub.Name(interface_pb2.Empty(), timeout=10)
        assert resp.name and len(resp.name) > 0, "Name RPC returned empty name"
        channel.close()


class TestGRPCPrioritizationPipeline:
    """Full gRPC pipeline: Initialize with training data, Prioritize test data, verify quality."""

    def test_initialize_and_prioritize(self):
        channel = grpc.insecure_channel("localhost:50051")
        stub = interface_pb2_grpc.CompetitionToolStub(channel)

        # Initialize with training data
        train_data = load_train_data()
        init_resp = stub.Initialize(_make_oracle_stream(train_data), timeout=120)
        assert init_resp.ok, "Initialize RPC returned ok=False"

        # Prioritize test cases
        test_data = load_test_data()
        responses = list(stub.Prioritize(_make_test_stream(test_data), timeout=120))

        # Verify all test IDs returned exactly once
        expected_ids = {tc["_id"]["$oid"] for tc in test_data}
        actual_ids = [r.testId for r in responses]
        assert len(actual_ids) == len(test_data), (
            f"Expected {len(test_data)} responses, got {len(actual_ids)}"
        )
        assert set(actual_ids) == expected_ids, "Prioritize returned different test IDs"
        assert len(actual_ids) == len(set(actual_ids)), "Duplicate IDs in gRPC response"

        # Verify prioritization quality against ground truth
        gt = load_ground_truth()
        apfd = compute_apfd(actual_ids, gt)
        apfdc = compute_apfdc(actual_ids, gt)
        assert apfd >= 0.58, f"gRPC pipeline APFD {apfd:.4f} < 0.58"
        assert apfdc >= 0.55, f"gRPC pipeline APFDc {apfdc:.4f} < 0.55"

        channel.close()

    def test_last_fault_position(self):
        """All faults must appear within the first 90% of the ordering."""
        channel = grpc.insecure_channel("localhost:50051")
        stub = interface_pb2_grpc.CompetitionToolStub(channel)

        train_data = load_train_data()
        init_resp = stub.Initialize(_make_oracle_stream(train_data), timeout=120)
        assert init_resp.ok

        test_data = load_test_data()
        responses = list(stub.Prioritize(_make_test_stream(test_data), timeout=120))
        actual_ids = [r.testId for r in responses]

        gt = load_ground_truth()
        last_pos = compute_last_fault_position(actual_ids, gt)
        n = len(actual_ids)
        max_allowed = int(n * 0.90)
        assert last_pos <= max_allowed, (
            f"Last fault at position {last_pos}, must be within first {max_allowed} "
            f"(90% of {n} tests). Ordering fails to concentrate faults early enough."
        )

        channel.close()


class TestResultsFileExists:
    def test_results_file_exists(self):
        assert os.path.isfile("/app/results.json"), "results.json not found"

    def test_results_valid_json(self):
        results = load_results()
        assert isinstance(results, dict)


class TestResultsSchema:
    def test_has_required_keys(self):
        results = load_results()
        required = [
            "tool_name",
            "train_size",
            "test_size",
            "prioritized_order",
            "apfd",
            "apfdc",
        ]
        for key in required:
            assert key in results, f"Missing key: {key}"

    def test_train_size(self):
        results = load_results()
        assert results["train_size"] == 200

    def test_test_size(self):
        results = load_results()
        assert results["test_size"] == 50

    def test_prioritized_order_is_list(self):
        results = load_results()
        assert isinstance(results["prioritized_order"], list)

    def test_metrics_are_numeric(self):
        results = load_results()
        assert isinstance(results["apfd"], (int, float))
        assert isinstance(results["apfdc"], (int, float))
        assert 0.0 <= results["apfd"] <= 1.0
        assert 0.0 <= results["apfdc"] <= 1.0

    def test_estimated_metrics_above_random(self):
        """Solver's estimated metrics should indicate better-than-random performance."""
        results = load_results()
        assert results["apfd"] > 0.52, (
            f"Estimated APFD {results['apfd']:.4f} is near random baseline — "
            "the model should predict better than random"
        )
        assert results["apfdc"] > 0.50, (
            f"Estimated APFDc {results['apfdc']:.4f} is near random baseline"
        )


class TestResultsPrioritizationValidity:
    def test_correct_count(self):
        test_data = load_test_data()
        results = load_results()
        assert len(results["prioritized_order"]) == len(test_data), (
            f"Expected {len(test_data)} tests, got {len(results['prioritized_order'])}"
        )

    def test_no_duplicates(self):
        results = load_results()
        order = results["prioritized_order"]
        assert len(order) == len(set(order)), "Duplicate test IDs in prioritized_order"

    def test_all_test_ids_present(self):
        test_data = load_test_data()
        expected_ids = {t["_id"]["$oid"] for t in test_data}
        results = load_results()
        actual_ids = set(results["prioritized_order"])
        missing = expected_ids - actual_ids
        extra = actual_ids - expected_ids
        assert not missing, f"Missing test IDs: {missing}"
        assert not extra, f"Unexpected test IDs: {extra}"


class TestResultsMetricQuality:
    def test_apfd_threshold(self):
        gt = load_ground_truth()
        results = load_results()
        apfd = compute_apfd(results["prioritized_order"], gt)
        assert apfd >= 0.58, f"APFD {apfd:.4f} < 0.58 threshold"

    def test_apfdc_threshold(self):
        gt = load_ground_truth()
        results = load_results()
        apfdc = compute_apfdc(results["prioritized_order"], gt)
        assert apfdc >= 0.55, f"APFDc {apfdc:.4f} < 0.55 threshold"

    def test_last_fault_within_budget(self):
        """All faults must be detected within 90% of the ordering."""
        gt = load_ground_truth()
        results = load_results()
        order = results["prioritized_order"]
        last_pos = compute_last_fault_position(order, gt)
        n = len(order)
        max_allowed = int(n * 0.90)
        assert last_pos <= max_allowed, (
            f"Last fault at position {last_pos}/{n}, must be within {max_allowed} "
            f"(90%). The ordering fails to concentrate all faults early enough."
        )

    def test_first_fault_reasonable(self):
        """First fault should appear within the first 30% of the ordering."""
        gt = load_ground_truth()
        results = load_results()
        order = results["prioritized_order"]
        first_pos = compute_first_fault_position(order, gt)
        n = len(order)
        max_allowed = max(1, int(n * 0.30))
        assert first_pos <= max_allowed, (
            f"First fault at position {first_pos}/{n} — expected within first {max_allowed}. "
            f"The prioritizer is not surfacing likely failures early."
        )


class TestStartServerScript:
    def test_start_server_exists(self):
        assert os.path.isfile("/app/start_server.sh"), "start_server.sh not found"

    def test_start_server_executable(self):
        assert os.access("/app/start_server.sh", os.X_OK), "start_server.sh not executable"
