"""
Tests for the deterministic consensus simulation framework.

"""
import sys
import math
import pytest

sys.path.insert(0, '/app')


# ===== Reference SplitMix64 for cross-checking =====

class _ReferenceSplitMix64:
    MASK = (1 << 64) - 1

    def __init__(self, seed):
        self.state = seed & self.MASK

    def next_u64(self):
        self.state = (self.state + 0x9e3779b97f4a7c15) & self.MASK
        z = self.state
        z = ((z ^ (z >> 30)) * 0xbf58476d1ce4e5b9) & self.MASK
        z = ((z ^ (z >> 27)) * 0x94d049bb133111eb) & self.MASK
        z = z ^ (z >> 31)
        return z


# ===================== Quorum Tests =====================

class TestQuorums:
    """Verify Flexible Paxos quorum calculations."""

    def test_exact_values_r1_to_r6(self):
        from dsim.quorums import compute_quorums

        expected = {
            1: {'replication': 1, 'view_change': 1, 'nack_prepare': 1,
                'majority': 1, 'upgrade': 1},
            2: {'replication': 2, 'view_change': 2, 'nack_prepare': 1,
                'majority': 2, 'upgrade': 2},
            3: {'replication': 2, 'view_change': 2, 'nack_prepare': 2,
                'majority': 2, 'upgrade': 3},
            4: {'replication': 2, 'view_change': 3, 'nack_prepare': 3,
                'majority': 3, 'upgrade': 4},
            5: {'replication': 3, 'view_change': 3, 'nack_prepare': 3,
                'majority': 3, 'upgrade': 5},
            6: {'replication': 3, 'view_change': 4, 'nack_prepare': 4,
                'majority': 4, 'upgrade': 6},
        }
        for r in range(1, 7):
            result = compute_quorums(r)
            for key in expected[r]:
                assert result[key] == expected[r][key], (
                    f"R={r}: {key} expected {expected[r][key]}, got {result[key]}"
                )

    def test_flexible_paxos_invariants(self):
        from dsim.quorums import compute_quorums

        for r in range(1, 13):
            q = compute_quorums(r)
            assert q['replication'] + q['view_change'] > r, (
                f"R={r}: Flexible Paxos intersection violated"
            )
            assert q['nack_prepare'] + q['replication'] > r, (
                f"R={r}: nack+rep must exceed R"
            )
            assert q['majority'] > r // 2, (
                f"R={r}: majority {q['majority']} not > {r // 2}"
            )
            assert q['view_change'] >= r // 2 + 1, (
                f"R={r}: view_change {q['view_change']} < {r // 2 + 1}"
            )
            assert q['upgrade'] == r

    def test_custom_replication_max(self):
        from dsim.quorums import compute_quorums

        q = compute_quorums(5, quorum_replication_max=2)
        assert q['replication'] == 2
        assert q['view_change'] == 4
        assert q['replication'] + q['view_change'] > 5

        q2 = compute_quorums(6, quorum_replication_max=5)
        assert q2['replication'] == 3
        assert q2['view_change'] == 4


# ===================== PRNG Tests =====================

class TestPRNG:
    """Verify SplitMix64 PRNG implementation."""

    def test_matches_reference(self):
        from dsim.prng import DeterministicPRNG

        for seed in [0, 1, 42, 2**32, 2**63 - 1]:
            prng = DeterministicPRNG(seed)
            ref = _ReferenceSplitMix64(seed)
            for _ in range(200):
                assert prng.next_u64() == ref.next_u64(), (
                    f"PRNG diverged from reference at seed={seed}"
                )

    def test_determinism(self):
        from dsim.prng import DeterministicPRNG

        prng1 = DeterministicPRNG(12345)
        prng2 = DeterministicPRNG(12345)
        for _ in range(1000):
            assert prng1.next_u64() == prng2.next_u64()

    def test_different_seeds_differ(self):
        from dsim.prng import DeterministicPRNG

        vals0 = [DeterministicPRNG(0).next_u64() for _ in range(5)]
        vals1 = [DeterministicPRNG(1).next_u64() for _ in range(5)]
        assert vals0 != vals1

    def test_chance_boundaries(self):
        from dsim.prng import DeterministicPRNG

        for seed in range(100):
            p = DeterministicPRNG(seed)
            assert not p.chance(0, 100), "0/100 must be False"
        for seed in range(100):
            p = DeterministicPRNG(seed)
            assert p.chance(100, 100), "100/100 must be True"

    def test_range_inclusive_bounds(self):
        from dsim.prng import DeterministicPRNG

        prng = DeterministicPRNG(42)
        for _ in range(2000):
            v = prng.range_inclusive(5, 10)
            assert 5 <= v <= 10

    def test_range_inclusive_coverage(self):
        """All values in the specified range must be reachable."""
        from dsim.prng import DeterministicPRNG

        prng = DeterministicPRNG(42)
        seen = set()
        for _ in range(10000):
            v = prng.range_inclusive(0, 3)
            seen.add(v)
        assert seen == {0, 1, 2, 3}, (
            f"Expected all values {{0,1,2,3}} reachable, got {seen}"
        )

    def test_shuffle_is_permutation(self):
        from dsim.prng import DeterministicPRNG

        prng = DeterministicPRNG(42)
        original = list(range(20))
        shuffled = prng.shuffle(original)
        assert sorted(shuffled) == original, "Shuffle must be a permutation"
        assert original == list(range(20)), "Shuffle must not mutate input"

    def test_shuffle_determinism(self):
        from dsim.prng import DeterministicPRNG

        lst = list(range(20))
        s1 = DeterministicPRNG(99).shuffle(lst)
        s2 = DeterministicPRNG(99).shuffle(lst)
        assert s1 == s2

    def test_exponential_non_negative(self):
        from dsim.prng import DeterministicPRNG

        prng = DeterministicPRNG(42)
        for _ in range(2000):
            assert prng.exponential(10.0) >= 0.0
        assert DeterministicPRNG(0).exponential(0.0) == 0.0


# ===================== Packet Simulator Tests =====================

class TestPacketSimulator:
    """Verify deterministic packet simulator behavior."""

    def test_determinism(self):
        from dsim.packet_simulator import PacketSimulator, PacketSimulatorOptions

        opts = PacketSimulatorOptions(
            node_count=3,
            one_way_delay_mean=10.0,
            one_way_delay_min=1.0,
            packet_loss_probability=(10, 100),
            packet_replay_probability=(5, 100),
        )

        def run(seed):
            sim = PacketSimulator(opts, seed)
            delivered = []
            for i in range(10):
                sim.submit_packet(f"msg_{i}", i % 3, (i + 1) % 3)
            for _ in range(100):
                sim.tick()
                delivered.extend(sim.step())
            return [(p, s, t) for p, s, t in delivered]

        r1 = run(42)
        r2 = run(42)
        assert len(r1) == len(r2), "Different delivery count"
        for i, (a, b) in enumerate(zip(r1, r2)):
            assert a == b, f"Delivery {i} differs: {a} vs {b}"

    def test_no_loss_delivery(self):
        from dsim.packet_simulator import PacketSimulator, PacketSimulatorOptions

        opts = PacketSimulatorOptions(
            node_count=2,
            one_way_delay_mean=1.0,
            one_way_delay_min=0.0,
            packet_loss_probability=(0, 100),
            packet_replay_probability=(0, 100),
            path_clog_probability=(0, 100),
        )
        sim = PacketSimulator(opts, 42)
        sim.submit_packet("hello", 0, 1)

        delivered = []
        for _ in range(100):
            sim.tick()
            delivered.extend(sim.step())

        packets = [p for p, _, _ in delivered]
        assert "hello" in packets, "Packet must be delivered with 0% loss"

    def test_total_loss(self):
        from dsim.packet_simulator import PacketSimulator, PacketSimulatorOptions

        opts = PacketSimulatorOptions(
            node_count=2,
            one_way_delay_mean=1.0,
            one_way_delay_min=0.0,
            packet_loss_probability=(100, 100),
            packet_replay_probability=(0, 100),
            path_clog_probability=(0, 100),
        )
        sim = PacketSimulator(opts, 42)
        for i in range(10):
            sim.submit_packet(f"msg_{i}", 0, 1)

        delivered = []
        for _ in range(200):
            sim.tick()
            delivered.extend(sim.step())

        assert len(delivered) == 0, "No packets should survive 100% loss"

    def test_capacity_limit(self):
        from dsim.packet_simulator import PacketSimulator, PacketSimulatorOptions

        opts = PacketSimulatorOptions(
            node_count=2,
            one_way_delay_mean=1.0,
            one_way_delay_min=1.0,
            path_maximum_capacity=3,
            packet_loss_probability=(0, 100),
            packet_replay_probability=(0, 100),
            path_clog_probability=(0, 100),
        )
        sim = PacketSimulator(opts, 42)
        for i in range(10):
            sim.submit_packet(f"msg_{i}", 0, 1)

        delivered = []
        for _ in range(100):
            sim.tick()
            delivered.extend(sim.step())

        assert len(delivered) == 3, (
            f"Expected exactly {opts.path_maximum_capacity} deliveries, got {len(delivered)}"
        )

    def test_partition_isolate_single(self):
        from dsim.packet_simulator import PacketSimulator, PacketSimulatorOptions

        for seed in range(50):
            opts = PacketSimulatorOptions(
                node_count=5,
                one_way_delay_mean=10.0,
                one_way_delay_min=1.0,
                partition_mode="isolate_single",
                partition_probability=(100, 100),
                unpartition_probability=(0, 100),
            )
            sim = PacketSimulator(opts, seed)
            sim.tick()

            partition = sim.get_partition()
            assert sim.is_partitioned()
            assert sum(partition) == 1, (
                f"isolate_single must isolate exactly 1 node, got {partition}"
            )

    def test_partition_uniform_size(self):
        from dsim.packet_simulator import PacketSimulator, PacketSimulatorOptions

        for seed in range(50):
            opts = PacketSimulatorOptions(
                node_count=5,
                one_way_delay_mean=10.0,
                one_way_delay_min=1.0,
                partition_mode="uniform_size",
                partition_probability=(100, 100),
                unpartition_probability=(0, 100),
            )
            sim = PacketSimulator(opts, seed)
            sim.tick()

            partition = sim.get_partition()
            true_ct = sum(partition)
            false_ct = len(partition) - true_ct
            assert true_ct >= 1 and false_ct >= 1, (
                f"uniform_size must create two non-empty groups, got {partition}"
            )


# ===================== State Checker Tests =====================

class TestStateChecker:
    """Verify consensus safety checking."""

    def test_valid_sequential_commits(self):
        from dsim.state_checker import StateChecker

        sc = StateChecker(3)
        for r in range(3):
            sc.on_commit(r, 1, checksum=100, parent_checksum=0)
        for r in range(3):
            sc.on_commit(r, 2, checksum=200, parent_checksum=100)

        assert sc.get_commit_count() == 3
        assert sc.check_convergence({0, 1, 2})

    def test_divergence_detected(self):
        from dsim.state_checker import StateChecker, SafetyViolation

        sc = StateChecker(3)
        sc.on_commit(0, 1, checksum=100, parent_checksum=0)

        with pytest.raises(SafetyViolation):
            sc.on_commit(1, 1, checksum=999, parent_checksum=0)

    def test_skip_detected(self):
        from dsim.state_checker import StateChecker, SafetyViolation

        sc = StateChecker(2)
        with pytest.raises(SafetyViolation):
            sc.on_commit(0, 3, checksum=300, parent_checksum=200)

    def test_parent_chain_violation(self):
        from dsim.state_checker import StateChecker, SafetyViolation

        sc = StateChecker(2)
        sc.on_commit(0, 1, checksum=100, parent_checksum=0)

        with pytest.raises(SafetyViolation):
            sc.on_commit(0, 2, checksum=200, parent_checksum=777)

    def test_convergence_partial(self):
        from dsim.state_checker import StateChecker

        sc = StateChecker(3)
        sc.on_commit(0, 1, checksum=100, parent_checksum=0)
        sc.on_commit(1, 1, checksum=100, parent_checksum=0)

        assert sc.check_convergence({0, 1}), "Core {0,1} should converge"
        assert not sc.check_convergence({0, 1, 2}), "Replica 2 is lagging"

    def test_idempotent_recommit(self):
        from dsim.state_checker import StateChecker

        sc = StateChecker(2)
        sc.on_commit(0, 1, checksum=100, parent_checksum=0)
        sc.on_commit(0, 1, checksum=100, parent_checksum=0)
        assert sc.get_replica_commit_min(0) == 1

    def test_divergent_recommit(self):
        """A replica recommitting an op with a different checksum is a safety violation."""
        from dsim.state_checker import StateChecker, SafetyViolation

        sc = StateChecker(2)
        sc.on_commit(0, 1, checksum=100, parent_checksum=0)
        # Simulate restart: replica 0 replays op 1 with corrupted state
        with pytest.raises(SafetyViolation):
            sc.on_commit(0, 1, checksum=999, parent_checksum=0)


# ===================== Liveness Tests =====================

class TestLiveness:
    """Verify liveness mode and resonance bug detection."""

    def test_core_selection_meets_quorum(self):
        from dsim.prng import DeterministicPRNG
        from dsim.quorums import compute_quorums
        from dsim.liveness import select_random_core

        for seed in range(100):
            for r in range(1, 7):
                q = compute_quorums(r)
                prng = DeterministicPRNG(seed * 1000 + r)
                core = select_random_core(prng, r, 0, q['view_change'])
                replica_core = {i for i in core if i < r}
                assert len(replica_core) >= q['view_change'], (
                    f"R={r}, seed={seed}: core has {len(replica_core)} replicas, "
                    f"need {q['view_change']}"
                )

    def test_core_with_standbys(self):
        from dsim.prng import DeterministicPRNG
        from dsim.liveness import select_random_core

        prng = DeterministicPRNG(42)
        core = select_random_core(prng, 3, 2, 2)
        replicas_in_core = {i for i in core if i < 3}
        assert len(replicas_in_core) >= 2

    def test_resonance_deadlock_detected(self):
        from dsim.liveness import detect_repair_deadlock

        available = {
            0: set(),
            1: {6},
            2: {5},
        }
        all_ops = {5, 6}

        stuck = detect_repair_deadlock(available, all_ops)
        assert len(stuck) > 0, "Must detect round-robin deadlock"
        assert 0 in stuck, "Replica 0 must be identified as stuck"

    def test_no_deadlock_when_ops_available(self):
        from dsim.liveness import detect_repair_deadlock

        available = {
            0: {5},
            1: {6},
            2: {5, 6},
        }
        all_ops = {5, 6}

        stuck = detect_repair_deadlock(available, all_ops)
        assert len(stuck) == 0, f"No deadlock when all ops reachable, got stuck={stuck}"

    def test_no_deadlock_fully_available(self):
        from dsim.liveness import detect_repair_deadlock

        available = {
            0: {5, 6},
            1: {5, 6},
            2: {5, 6},
        }
        stuck = detect_repair_deadlock(available, {5, 6})
        assert len(stuck) == 0


# ===================== Integration Test =====================

class TestIntegration:
    """End-to-end integration of components."""

    def test_simulation_determinism_end_to_end(self):
        """Full simulation pipeline: PRNG -> quorums -> packet sim -> state checker."""
        from dsim.prng import DeterministicPRNG
        from dsim.quorums import compute_quorums
        from dsim.packet_simulator import PacketSimulator, PacketSimulatorOptions
        from dsim.state_checker import StateChecker

        def run_simulation(seed):
            prng = DeterministicPRNG(seed)
            replica_count = 3
            q = compute_quorums(replica_count)

            opts = PacketSimulatorOptions(
                node_count=replica_count,
                one_way_delay_mean=5.0,
                one_way_delay_min=1.0,
                packet_loss_probability=(5, 100),
                packet_replay_probability=(2, 100),
                path_clog_probability=(0, 100),
            )
            sim = PacketSimulator(opts, prng.next_u64())
            sc = StateChecker(replica_count)

            checksum = 0
            for op in range(1, 11):
                parent = checksum
                checksum = prng.next_u64()
                for r in range(replica_count):
                    sc.on_commit(r, op, checksum, parent)

            assert sc.check_convergence({0, 1, 2})
            assert sc.get_commit_count() == 11
            return (q, sc.get_commit_count())

        r1 = run_simulation(42)
        r2 = run_simulation(42)
        assert r1 == r2, "End-to-end simulation must be deterministic"
