"""Tests for the EC Transition Engine and crash dump recovery.

"""

import hashlib
import os
import sys

import pytest

sys.path.insert(0, '/opt/ec_libs')
sys.path.insert(0, '/app')

from cluster import Cluster  # noqa: E402
from storage import StorageEngine  # noqa: E402
from transition_engine import TransitionEngine  # noqa: E402


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_data(seed: int, size: int) -> bytes:
    """Deterministic test data from *seed* and *size*."""
    return bytes([(seed * 37 + j * 13) % 256 for j in range(size)])


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def cluster():
    """Fresh 15-node cluster with 10 test files under RS(4,2)."""
    c = Cluster(num_nodes=15)
    se = StorageEngine(c)
    store = {}
    for i in range(10):
        fid = f"test_{i:03d}"
        data = _make_data(i, 1024 * (i + 1))
        se.write_file(fid, data, k=4, m=2)
        store[fid] = data
    c._test_data = store
    return c


@pytest.fixture
def engine(cluster):
    return TransitionEngine(cluster)


# ===================================================================
# 0. crash dump recovery
# ===================================================================

class TestCrashDumpRecovery:

    EXPECTED_SHA256 = "d9bd473a763d3c7373365a21ecdfeb89b9bb53b654815c9ff7ef032ac29c73b9"
    EXPECTED_SIZE = 4500

    def test_recovered_file_exists(self):
        assert os.path.isfile('/app/recovered.bin'), \
            "/app/recovered.bin not found"

    def test_recovered_file_size(self):
        with open('/app/recovered.bin', 'rb') as f:
            data = f.read()
        assert len(data) == self.EXPECTED_SIZE, \
            f"expected {self.EXPECTED_SIZE} bytes, got {len(data)}"

    def test_recovered_file_checksum(self):
        with open('/app/recovered.bin', 'rb') as f:
            data = f.read()
        got = hashlib.sha256(data).hexdigest()
        assert got == self.EXPECTED_SHA256, \
            f"SHA-256 mismatch: {got}"


# ===================================================================
# 1. encode_file
# ===================================================================

class TestEncodeFile:

    def test_metadata_shape(self, engine):
        data = b"encode-test " * 120
        meta = engine.encode_file("enc_1", data, k=4, m=2)
        assert meta['k'] == 4
        assert meta['m'] == 2
        assert meta['original_size'] == len(data)
        assert meta['checksum'] == hashlib.sha256(data).hexdigest()
        assert len(meta['shard_locations']) == 6

    def test_distinct_nodes(self, engine):
        data = b"node-test " * 100
        meta = engine.encode_file("enc_2", data, k=5, m=3)
        nodes = list(meta['shard_locations'].values())
        assert len(set(nodes)) == 8  # all distinct

    def test_roundtrip(self, engine):
        data = _make_data(99, 7777)
        engine.encode_file("enc_3", data, k=4, m=2)
        assert engine.reconstruct_read("enc_3") == data

    def test_various_k_m(self, engine):
        for k, m in [(2, 1), (3, 3), (6, 2), (8, 4)]:
            data = _make_data(k + m, 2000)
            fid = f"enc_km_{k}_{m}"
            engine.encode_file(fid, data, k=k, m=m)
            assert engine.reconstruct_read(fid) == data


# ===================================================================
# 2. plan_transition  (efficiency is the key test)
# ===================================================================

class TestPlanTransition:

    def test_same_k_keeps_data(self, cluster, engine):
        """When k is unchanged, all data shards must be kept in place."""
        plan = engine.plan_transition("test_000", target_k=4, target_m=3)
        kept = {idx for idx, _ in plan['keep']}
        assert kept == {0, 1, 2, 3}

    def test_same_k_deletes_old_parity(self, cluster, engine):
        plan = engine.plan_transition("test_000", target_k=4, target_m=3)
        deleted = {idx for idx, _ in plan['delete']}
        assert deleted == {4, 5}  # old parity indices

    def test_same_k_creates_new_parity(self, cluster, engine):
        plan = engine.plan_transition("test_000", target_k=4, target_m=3)
        created = {idx for idx, _, _ in plan['create']}
        assert created == {4, 5, 6}  # new parity indices

    def test_same_k_movement_equals_created(self, cluster, engine):
        plan = engine.plan_transition("test_000", target_k=4, target_m=3)
        total = sum(len(d) for _, _, d in plan['create'])
        assert plan['data_movement_bytes'] == total

    def test_same_k_movement_less_than_full(self, cluster, engine):
        """Same-k transition movement must be strictly less than full re-encode."""
        meta = cluster.get_file_metadata("test_000")
        full = meta['original_size']
        plan = engine.plan_transition("test_000", target_k=4, target_m=3)
        assert plan['data_movement_bytes'] < full

    def test_different_k_creates_all(self, cluster, engine):
        plan = engine.plan_transition("test_000", target_k=6, target_m=3)
        created = {idx for idx, _, _ in plan['create']}
        assert created == set(range(9))  # 6 data + 3 parity

    def test_scheme_fields(self, cluster, engine):
        plan = engine.plan_transition("test_001", target_k=4, target_m=5)
        assert tuple(plan['current_scheme']) == (4, 2)
        assert tuple(plan['target_scheme']) == (4, 5)


# ===================================================================
# 3. execute_transition
# ===================================================================

class TestExecuteTransition:

    def test_same_k_integrity(self, cluster, engine):
        orig = cluster._test_data["test_001"]
        plan = engine.plan_transition("test_001", target_k=4, target_m=3)
        new = engine.execute_transition(plan)
        assert new['k'] == 4 and new['m'] == 3
        assert engine.reconstruct_read("test_001") == orig

    def test_different_k_integrity(self, cluster, engine):
        orig = cluster._test_data["test_002"]
        plan = engine.plan_transition("test_002", target_k=6, target_m=3)
        new = engine.execute_transition(plan)
        assert new['k'] == 6 and new['m'] == 3
        assert engine.reconstruct_read("test_002") == orig

    def test_reduce_redundancy(self, cluster, engine):
        orig = cluster._test_data["test_003"]
        plan = engine.plan_transition("test_003", target_k=4, target_m=1)
        new = engine.execute_transition(plan)
        assert new['m'] == 1
        assert engine.reconstruct_read("test_003") == orig

    def test_increase_redundancy(self, cluster, engine):
        orig = cluster._test_data["test_004"]
        plan = engine.plan_transition("test_004", target_k=4, target_m=5)
        new = engine.execute_transition(plan)
        assert new['m'] == 5
        assert len(new['shard_locations']) == 9
        assert engine.reconstruct_read("test_004") == orig

    def test_sequential_transitions(self, cluster, engine):
        """Two transitions in a row must preserve data."""
        orig = cluster._test_data["test_005"]
        p1 = engine.plan_transition("test_005", 4, 4)
        engine.execute_transition(p1)
        p2 = engine.plan_transition("test_005", 6, 3)
        engine.execute_transition(p2)
        assert engine.reconstruct_read("test_005") == orig

    def test_shards_exist_after_transition(self, cluster, engine):
        plan = engine.plan_transition("test_006", target_k=4, target_m=3)
        new = engine.execute_transition(plan)
        for idx_str, nid in new['shard_locations'].items():
            node = cluster.get_node(nid)
            assert node.has_shard("test_006", int(idx_str)), \
                f"shard {idx_str} missing on node {nid}"

    def test_does_not_corrupt_other_files(self, cluster, engine):
        plan = engine.plan_transition("test_000", 6, 3)
        engine.execute_transition(plan)
        for fid, orig in cluster._test_data.items():
            if fid == "test_000":
                continue
            assert engine.reconstruct_read(fid) == orig, \
                f"{fid} corrupted after transitioning test_000"


# ===================================================================
# 4. reconstruct_read
# ===================================================================

class TestReconstructRead:

    def test_no_failures(self, cluster, engine):
        for fid, orig in cluster._test_data.items():
            assert engine.reconstruct_read(fid) == orig

    def test_single_data_failure(self, cluster, engine):
        meta = cluster.get_file_metadata("test_000")
        nid = meta['shard_locations']['0']
        cluster.fail_node(nid)
        try:
            assert engine.reconstruct_read("test_000") == \
                cluster._test_data["test_000"]
        finally:
            cluster.recover_node(nid)

    def test_single_parity_failure(self, cluster, engine):
        meta = cluster.get_file_metadata("test_001")
        nid = meta['shard_locations'][str(meta['k'])]
        cluster.fail_node(nid)
        try:
            assert engine.reconstruct_read("test_001") == \
                cluster._test_data["test_001"]
        finally:
            cluster.recover_node(nid)

    def test_max_failures(self, cluster, engine):
        """m failures (the maximum tolerable) must still succeed."""
        meta = cluster.get_file_metadata("test_002")
        failed = []
        for i in range(meta['m']):
            nid = meta['shard_locations'][str(i)]
            if nid not in failed:
                cluster.fail_node(nid)
                failed.append(nid)
        try:
            assert engine.reconstruct_read("test_002") == \
                cluster._test_data["test_002"]
        finally:
            for n in failed:
                cluster.recover_node(n)

    def test_too_many_failures(self, cluster, engine):
        meta = cluster.get_file_metadata("test_003")
        failed = []
        seen = set()
        for i in range(meta['k'] + meta['m']):
            nid = meta['shard_locations'][str(i)]
            if nid not in seen:
                seen.add(nid)
                cluster.fail_node(nid)
                failed.append(nid)
            if len(failed) > meta['m']:
                break
        try:
            with pytest.raises((ValueError, Exception)):
                engine.reconstruct_read("test_003")
        finally:
            for n in failed:
                cluster.recover_node(n)

    def test_explicit_failed_nodes(self, cluster, engine):
        meta = cluster.get_file_metadata("test_004")
        nid = meta['shard_locations']['0']
        result = engine.reconstruct_read("test_004",
                                         failed_nodes=[nid])
        assert result == cluster._test_data["test_004"]

    def test_after_transition(self, cluster, engine):
        orig = cluster._test_data["test_007"]
        plan = engine.plan_transition("test_007", 4, 4)
        engine.execute_transition(plan)
        meta = cluster.get_file_metadata("test_007")
        failed = []
        seen = set()
        for idx in sorted(meta['shard_locations'], key=int):
            nid = meta['shard_locations'][idx]
            if nid not in seen and len(failed) < 3:
                cluster.fail_node(nid)
                failed.append(nid)
                seen.add(nid)
        try:
            assert engine.reconstruct_read("test_007") == orig
        finally:
            for n in failed:
                cluster.recover_node(n)


# ===================================================================
# 5. repair
# ===================================================================

class TestRepair:

    def test_basic_repair(self, cluster, engine):
        orig = cluster._test_data["test_000"]
        meta = cluster.get_file_metadata("test_000")
        bad = meta['shard_locations']['0']
        cluster.fail_node(bad)
        new_meta = engine.repair("test_000", [bad])
        assert new_meta['shard_locations']['0'] != bad
        assert engine.reconstruct_read("test_000") == orig
        cluster.recover_node(bad)

    def test_repair_parity_shard(self, cluster, engine):
        orig = cluster._test_data["test_001"]
        meta = cluster.get_file_metadata("test_001")
        k = meta['k']
        bad = meta['shard_locations'][str(k)]
        cluster.fail_node(bad)
        new_meta = engine.repair("test_001", [bad])
        assert new_meta['shard_locations'][str(k)] != bad
        assert engine.reconstruct_read("test_001") == orig
        cluster.recover_node(bad)

    def test_repair_multi_node(self, cluster, engine):
        data = _make_data(42, 3000)
        engine.encode_file("rep_multi", data, k=4, m=4)
        meta = cluster.get_file_metadata("rep_multi")
        bad = []
        seen = set()
        for i in range(8):
            nid = meta['shard_locations'][str(i)]
            if nid not in seen and len(bad) < 3:
                bad.append(nid)
                seen.add(nid)
        for nid in bad:
            cluster.fail_node(nid)
        new_meta = engine.repair("rep_multi", bad)
        for idx_str, nid in new_meta['shard_locations'].items():
            assert cluster.get_node(nid).is_alive
            assert cluster.get_node(nid).has_shard("rep_multi", int(idx_str))
        assert engine.reconstruct_read("rep_multi") == data
        for nid in bad:
            cluster.recover_node(nid)

    def test_repair_then_degrade(self, cluster, engine):
        """After repair, file should tolerate further failures."""
        orig = cluster._test_data["test_008"]
        meta = cluster.get_file_metadata("test_008")
        bad = meta['shard_locations']['0']
        cluster.fail_node(bad)
        new_meta = engine.repair("test_008", [bad])
        cluster.recover_node(bad)
        another = new_meta['shard_locations']['1']
        cluster.fail_node(another)
        try:
            assert engine.reconstruct_read("test_008") == orig
        finally:
            cluster.recover_node(another)

    def test_repair_insufficient_shards(self, cluster, engine):
        meta = cluster.get_file_metadata("test_009")
        bad = []
        seen = set()
        for i in range(meta['k'] + meta['m']):
            nid = meta['shard_locations'][str(i)]
            if nid not in seen:
                seen.add(nid)
                bad.append(nid)
            if len(bad) > meta['m']:
                break
        for nid in bad:
            cluster.fail_node(nid)
        try:
            with pytest.raises((ValueError, Exception)):
                engine.repair("test_009", bad)
        finally:
            for nid in bad:
                cluster.recover_node(nid)


# ===================================================================
# 6. end-to-end
# ===================================================================

class TestEndToEnd:

    def test_full_lifecycle(self, cluster, engine):
        data = _make_data(77, 6000)
        engine.encode_file("e2e", data, k=4, m=2)
        assert engine.reconstruct_read("e2e") == data

        # transition RS(4,2)->RS(4,4)
        p = engine.plan_transition("e2e", 4, 4)
        engine.execute_transition(p)
        assert engine.reconstruct_read("e2e") == data

        # degrade 3 nodes (within m=4)
        meta = cluster.get_file_metadata("e2e")
        failed = []
        seen = set()
        for idx in sorted(meta['shard_locations'], key=int):
            nid = meta['shard_locations'][idx]
            if nid not in seen and len(failed) < 3:
                cluster.fail_node(nid)
                failed.append(nid)
                seen.add(nid)
        try:
            assert engine.reconstruct_read("e2e") == data
        finally:
            for n in failed:
                cluster.recover_node(n)

        # repair
        cluster.fail_node(failed[0])
        engine.repair("e2e", [failed[0]])
        cluster.recover_node(failed[0])
        assert engine.reconstruct_read("e2e") == data

        # transition RS(4,4)->RS(6,3)
        p = engine.plan_transition("e2e", 6, 3)
        engine.execute_transition(p)
        assert engine.reconstruct_read("e2e") == data
