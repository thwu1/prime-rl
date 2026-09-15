"""Tests for the savepoint-based rescaling system.

Validates:
  - Key-group assignment properties (determinism, range, distribution)
  - Key-group range invariants (coverage, contiguity, ordering)
  - State redistribution correctness (scale up, scale down, value preservation)
  - End-to-end pipeline rescaling with fraud detection and exactly-once semantics
"""


import sys
sys.path.insert(0, "/app")

import pytest
import copy
from streaming import Transaction, KeyedStateBackend
from pipeline import FraudDetectionPipeline
from savepoint import (
    MAX_PARALLELISM,
    compute_key_group,
    compute_key_group_range,
    find_operator_for_key_group,
    redistribute_keyed_state,
    create_savepoint,
    restore_pipeline_from_savepoint,
)


# ================================================================
# Key-group assignment
# ================================================================

class TestKeyGroupAssignment:
    """Key-group mapping must be deterministic, in-range, and well-distributed."""

    def test_deterministic(self):
        """Same key must always produce the same key-group."""
        for key in [0, 1, 42, 100, 999, -1, -100]:
            assert compute_key_group(key) == compute_key_group(key), \
                f"Key {key} produced different key-groups on repeated calls"

    def test_string_keys_deterministic(self):
        """String keys must also be deterministic."""
        for key in ["hello", "world", "account_42", ""]:
            assert compute_key_group(key) == compute_key_group(key)

    def test_in_range(self):
        """All key-groups must be in [0, MAX_PARALLELISM)."""
        for key in list(range(500)) + [-1, -50, -999]:
            kg = compute_key_group(key)
            assert 0 <= kg < MAX_PARALLELISM, \
                f"Key {key} mapped to out-of-range key-group {kg}"

    def test_distribution(self):
        """Keys should distribute across at least 80% of key-groups."""
        used = set()
        for key in range(5000):
            used.add(compute_key_group(key))
        assert len(used) >= MAX_PARALLELISM * 0.8, \
            f"Only {len(used)}/{MAX_PARALLELISM} key-groups used"


# ================================================================
# Key-group range assignment
# ================================================================

class TestKeyGroupRanges:
    """Ranges must cover all key-groups with no gaps or overlaps."""

    def test_full_coverage_no_overlap(self):
        """All key-groups [0, MAX_PARALLELISM) must be covered exactly once."""
        for parallelism in [1, 2, 3, 4, 5, 7, 8, 16, 64, 128]:
            covered = set()
            for i in range(parallelism):
                start, end = compute_key_group_range(i, parallelism)
                assert start < end, \
                    f"Empty range for op {i} at p={parallelism}"
                for kg in range(start, end):
                    assert kg not in covered, \
                        f"Key-group {kg} assigned twice at p={parallelism}"
                    covered.add(kg)
            assert covered == set(range(MAX_PARALLELISM)), \
                f"Missing key-groups at p={parallelism}: " \
                f"{set(range(MAX_PARALLELISM)) - covered}"

    def test_contiguous_ordered(self):
        """Ranges must be contiguous and in ascending order."""
        for parallelism in [2, 3, 5, 7, 13]:
            prev_end = 0
            for i in range(parallelism):
                start, end = compute_key_group_range(i, parallelism)
                assert start == prev_end, \
                    f"Gap at op {i}, p={parallelism}: " \
                    f"prev_end={prev_end}, start={start}"
                prev_end = end
            assert prev_end == MAX_PARALLELISM, \
                f"Last range doesn't reach MAX_PARALLELISM at p={parallelism}"

    def test_find_operator_consistent(self):
        """find_operator_for_key_group must agree with ranges."""
        for parallelism in [2, 3, 5, 7]:
            for kg in range(MAX_PARALLELISM):
                op = find_operator_for_key_group(kg, parallelism)
                start, end = compute_key_group_range(op, parallelism)
                assert start <= kg < end, \
                    f"kg={kg} assigned to op={op} but range=[{start},{end})"


# ================================================================
# State redistribution
# ================================================================

class TestStateRedistribution:
    """Redistribution must preserve all state across parallelism changes."""

    def _make_state(self, keys, state_name="counter"):
        state = {}
        for k in keys:
            state[f"{k}:{state_name}"] = k * 10
        return state

    def _extract_keys(self, state):
        keys = set()
        for composite in state:
            key_str = composite.split(":", 1)[0]
            keys.add(int(key_str))
        return keys

    def _all_keys(self, states):
        result = set()
        for s in states:
            result |= self._extract_keys(s)
        return result

    def test_scale_up_preserves_all(self):
        """Scaling 2->3: all keys must be preserved, none duplicated."""
        old_states = [
            self._make_state([0, 2, 4, 6, 8]),
            self._make_state([1, 3, 5, 7, 9]),
        ]
        keys_before = self._all_keys(old_states)

        new_states = redistribute_keyed_state(old_states, 2, 3)

        assert len(new_states) == 3
        keys_after = set()
        for s in new_states:
            these_keys = self._extract_keys(s)
            overlap = keys_after & these_keys
            assert not overlap, f"Duplicate keys across operators: {overlap}"
            keys_after |= these_keys

        assert keys_before == keys_after, \
            f"Lost: {keys_before - keys_after}, gained: {keys_after - keys_before}"

    def test_scale_down_preserves_all(self):
        """Scaling 3->2: all keys must be preserved, none duplicated."""
        old_states = [
            self._make_state([0, 3, 6, 9]),
            self._make_state([1, 4, 7]),
            self._make_state([2, 5, 8]),
        ]
        keys_before = self._all_keys(old_states)

        new_states = redistribute_keyed_state(old_states, 3, 2)

        assert len(new_states) == 2
        assert keys_before == self._all_keys(new_states)

    def test_values_preserved(self):
        """State values must survive redistribution unchanged."""
        old_states = [
            {f"{k}:value": f"data-{k}" for k in range(10)},
            {f"{k}:value": f"data-{k}" for k in range(10, 20)},
        ]

        new_states = redistribute_keyed_state(old_states, 2, 3)

        all_values = {}
        for s in new_states:
            for composite, val in s.items():
                key_str = composite.split(":", 1)[0]
                all_values[int(key_str)] = val

        for k in range(20):
            assert all_values[k] == f"data-{k}", \
                f"Value for key {k} changed during redistribution"

    def test_key_group_consistent_routing(self):
        """Keys in redistributed state must match their operator's range."""
        old_states = [self._make_state(list(range(50)))]

        new_states = redistribute_keyed_state(old_states, 1, 4)

        assert len(new_states) == 4
        for op_idx in range(4):
            start, end = compute_key_group_range(op_idx, 4)
            for composite in new_states[op_idx]:
                key_str = composite.split(":", 1)[0]
                key = int(key_str)
                kg = compute_key_group(key)
                assert start <= kg < end, \
                    f"Key {key} (kg={kg}) in op {op_idx} " \
                    f"but range is [{start},{end})"

    def test_multiple_state_names(self):
        """Redistribution must handle multiple state names per key."""
        old_states = [{
            "5:counter": 50,
            "5:flag": True,
            "5:pending_small": {"eid": "e1", "ts": 1000},
            "10:counter": 100,
            "10:flag": False,
        }]

        new_states = redistribute_keyed_state(old_states, 1, 2)

        all_entries = {}
        for s in new_states:
            all_entries.update(s)

        assert all_entries["5:counter"] == 50
        assert all_entries["5:flag"] is True
        assert all_entries["5:pending_small"] == {"eid": "e1", "ts": 1000}
        assert all_entries["10:counter"] == 100
        assert all_entries["10:flag"] is False


# ================================================================
# Pipeline rescaling integration
# ================================================================

class TestPipelineRescale:
    """End-to-end tests for savepoint creation and rescaled restoration."""

    def _make_events(self):
        """Transaction stream with known fraud patterns.

        Phase 1 (before savepoint): small transactions for accounts 0, 2, 3.
        Phase 2 (after rescale): large transactions triggering fraud alerts.
        """
        return [
            Transaction(0, 0.50, 1000, "e0"),
            Transaction(1, 10.00, 2000, "e1"),
            Transaction(2, 0.90, 3000, "e2"),
            Transaction(3, 0.30, 4000, "e3"),
            # --- checkpoint / savepoint after 4 events ---
            Transaction(0, 600.00, 5000, "e4"),
            Transaction(2, 700.00, 6000, "e5"),
            Transaction(3, 800.00, 7000, "e6"),
            Transaction(1, 0.10, 8000, "e7"),
        ]

    def test_rescale_up_correctness(self):
        """Savepoint at p=2, restore at p=3: fraud detection must work."""
        events = self._make_events()

        pipeline = FraudDetectionPipeline(events, parallelism=2)
        pipeline.run(checkpoint_interval=4)

        savepoint = create_savepoint(pipeline)

        new_pipeline = restore_pipeline_from_savepoint(
            savepoint, events, new_parallelism=3
        )
        new_pipeline.resume()

        alerted = sorted(a.account_id for a in new_pipeline.alerts)
        assert alerted == [0, 2, 3], \
            f"Expected fraud alerts for [0, 2, 3], got {alerted}"

    def test_rescale_down_correctness(self):
        """Savepoint at p=3, restore at p=2: fraud detection must work."""
        events = self._make_events()

        pipeline = FraudDetectionPipeline(events, parallelism=3)
        pipeline.run(checkpoint_interval=4)

        savepoint = create_savepoint(pipeline)

        new_pipeline = restore_pipeline_from_savepoint(
            savepoint, events, new_parallelism=2
        )
        new_pipeline.resume()

        alerted = sorted(a.account_id for a in new_pipeline.alerts)
        assert alerted == [0, 2, 3], \
            f"Expected fraud alerts for [0, 2, 3], got {alerted}"

    def test_no_duplicate_alerts(self):
        """Rescaling must not produce duplicate alerts."""
        events = self._make_events()

        pipeline = FraudDetectionPipeline(events, parallelism=2)
        pipeline.run(checkpoint_interval=4)

        savepoint = create_savepoint(pipeline)
        new_pipeline = restore_pipeline_from_savepoint(
            savepoint, events, new_parallelism=3
        )
        new_pipeline.resume()

        event_id_sets = [tuple(sorted(a.event_ids)) for a in new_pipeline.alerts]
        assert len(event_id_sets) == len(set(event_id_sets)), \
            "Duplicate alerts detected — exactly-once violation"

    def test_extreme_rescale_1_to_4(self):
        """Extreme rescale: 1->4 parallelism."""
        events = self._make_events()

        pipeline = FraudDetectionPipeline(events, parallelism=1)
        pipeline.run(checkpoint_interval=4)

        savepoint = create_savepoint(pipeline)
        new_pipeline = restore_pipeline_from_savepoint(
            savepoint, events, new_parallelism=4
        )
        new_pipeline.resume()

        alerted = sorted(a.account_id for a in new_pipeline.alerts)
        assert alerted == [0, 2, 3]

    def test_preserves_phase1_alerts(self):
        """Alerts from before the savepoint must be preserved after rescale."""
        events = [
            Transaction(10, 0.50, 1000, "x0"),
            Transaction(10, 600.00, 2000, "x1"),
            Transaction(20, 0.90, 3000, "x2"),
            # checkpoint after 3 events
            Transaction(20, 700.00, 4000, "x3"),
        ]

        pipeline = FraudDetectionPipeline(events, parallelism=2)
        pipeline.run(checkpoint_interval=3)

        assert len(pipeline.alerts) >= 1
        assert any(a.account_id == 10 for a in pipeline.alerts)

        savepoint = create_savepoint(pipeline)
        new_pipeline = restore_pipeline_from_savepoint(
            savepoint, events, new_parallelism=3
        )
        new_pipeline.resume()

        alerted = sorted(a.account_id for a in new_pipeline.alerts)
        assert alerted == [10, 20], \
            f"Expected [10, 20], got {alerted}"

    def test_rescale_4_to_1(self):
        """Scale down from 4 to 1: all state merges into single operator."""
        events = self._make_events()

        pipeline = FraudDetectionPipeline(events, parallelism=4)
        pipeline.run(checkpoint_interval=4)

        savepoint = create_savepoint(pipeline)
        new_pipeline = restore_pipeline_from_savepoint(
            savepoint, events, new_parallelism=1
        )
        new_pipeline.resume()

        alerted = sorted(a.account_id for a in new_pipeline.alerts)
        assert alerted == [0, 2, 3]
