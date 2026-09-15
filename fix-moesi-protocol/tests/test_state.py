"""
Tests for the MOESI Cache Coherence Protocol Simulator.

Verifies that all five issues have been resolved:
1. Directory entry double-deallocation in L2 controller
2. L2 bank address interleaving mask + per-bank set aliasing
3. Memory range overlap in dual-memory configuration
4. L2 inclusion enforcement with dirty data collection
5. Protocol traffic instrumentation
"""

import json
import struct
import sys
import os

sys.path.insert(0, '/app')

from coherence_sim import (
    CoherenceSimulator, BankedL2Cache, MemorySystem,
    CacheState, L2State, BLOCK_SIZE,
)


def check_inclusion(sim):
    """Check L2 inclusion: every non-invalid L1 line must exist in L2."""
    violations = []
    for core_id, l1 in enumerate(sim.l1_controllers):
        for set_idx in range(l1.num_sets):
            for line in l1.sets[set_idx]:
                if line.state != CacheState.I:
                    bank_idx = sim.l2_cache.get_bank_index(line.addr)
                    l2_bank = sim.l2_cache.banks[bank_idx]
                    l2_line = l2_bank._find_line(line.addr)
                    if l2_line is None:
                        violations.append(
                            f"L1[{core_id}] addr=0x{line.addr:x} "
                            f"state={line.state.name} not in L2 bank {bank_idx}"
                        )
    return violations


class TestDirectoryEntryBug:
    """Test Bug 1: L2 controller directory entry double-deallocation."""

    def test_writeback_storm_no_assertion(self):
        """
        Run writeback-storm pattern with 4 cores.
        This MUST NOT raise AssertionError from _remove_from_dir.
        """
        sim = CoherenceSimulator(num_cores=4, num_l2_banks=4)
        base_addrs = list(range(0, 8192, BLOCK_SIZE))

        for round_num in range(50):
            for line_idx in range(0, len(base_addrs), 2):
                addr = base_addrs[line_idx % len(base_addrs)]
                data = struct.pack('<QQ', round_num, line_idx) + b'\x00' * 48

                sim.store(0, addr, data)
                sim.run_until_idle(100)

                data2 = struct.pack('<QQ', round_num + 1000, line_idx) + b'\x00' * 48
                sim.store(1, addr, data2)
                sim.run_until_idle(100)

                evict_addr = base_addrs[(line_idx + 1) % len(base_addrs)]
                data3 = struct.pack('<QQ', round_num + 2000, line_idx) + b'\x00' * 48
                sim.store(2, evict_addr, data3)
                sim.run_until_idle(100)

                sim.load(3, addr)
                sim.run_until_idle(100)

                data4 = struct.pack('<QQ', round_num + 3000, line_idx) + b'\x00' * 48
                sim.store(0, addr, data4)
                sim.run_until_idle(100)

        # Force eviction cascade
        for i in range(256):
            addr = (i * BLOCK_SIZE + 16384)
            data = struct.pack('<Q', 0xDEAD0000 + i) + b'\x00' * 56
            sim.store(i % sim.num_cores, addr, data)
            sim.run_until_idle(100)

        assert len(sim.assertion_errors) == 0, \
            f"Assertion errors occurred: {sim.assertion_errors}"

    def test_ilxw_transition_no_double_free(self):
        """
        Specifically test the ILXW->M->MI->I transition path.
        Directory entry must not be double-freed.
        """
        sim = CoherenceSimulator(num_cores=2, num_l2_banks=2)

        addr = 0x1000
        data1 = struct.pack('<Q', 0xAAAA) + b'\x00' * 56

        sim.store(0, addr, data1)
        sim.run_until_idle(100)

        data2 = struct.pack('<Q', 0xBBBB) + b'\x00' * 56
        sim.store(1, addr, data2)
        sim.run_until_idle(100)

        for i in range(64):
            evict_addr = (i + 100) * BLOCK_SIZE
            data = struct.pack('<Q', i) + b'\x00' * 56
            sim.store(0, evict_addr, data)
            sim.run_until_idle(100)

        assert len(sim.assertion_errors) == 0, \
            f"Double-free detected: {sim.assertion_errors}"


class TestBankInterleavingBug:
    """Test Bug 2a: L2 bank address interleaving mask error."""

    def test_bank_distribution_balanced(self):
        """
        Sequential addresses must be evenly distributed across banks.
        With correct interleaving, each bank should get ~25% of accesses.
        """
        banked_l2 = BankedL2Cache(num_banks=4)

        num_accesses = 1000
        for i in range(num_accesses):
            addr = i * BLOCK_SIZE
            banked_l2.get_bank_index(addr)

        dist = banked_l2.get_bank_distribution()
        total = sum(info['accesses'] for info in dist.values())
        expected = total / 4

        variance = sum((info['accesses'] - expected) ** 2
                       for info in dist.values()) / 4
        stddev = variance ** 0.5
        cv = stddev / expected if expected > 0 else float('inf')

        assert cv < 0.1, (
            f"Bank distribution is imbalanced (CV={cv:.3f}, max 0.1). "
            f"Distribution: {dist}"
        )

    def test_consecutive_lines_different_banks(self):
        """Consecutive cache lines must map to different banks."""
        banked_l2 = BankedL2Cache(num_banks=4)

        banks_seen = set()
        for i in range(4):
            addr = i * BLOCK_SIZE
            bank = banked_l2.get_bank_index(addr)
            banks_seen.add(bank)

        assert len(banks_seen) == 4, (
            f"4 consecutive cache lines should map to 4 different banks, "
            f"but only {len(banks_seen)} unique banks seen: {banks_seen}"
        )

    def test_mask_is_proper_bitmask(self):
        """The interleave mask must be (1 << bits) - 1, not (1 << bits)."""
        banked_l2 = BankedL2Cache(num_banks=4)

        expected_mask = (1 << banked_l2.intlv_bits) - 1
        assert banked_l2.intlv_mask == expected_mask, (
            f"Interleave mask is {banked_l2.intlv_mask} "
            f"(binary: {bin(banked_l2.intlv_mask)}), "
            f"expected {expected_mask} (binary: {bin(expected_mask)}). "
            f"Mask should be (1 << {banked_l2.intlv_bits}) - 1"
        )

    def test_bank_index_never_exceeds_num_banks(self):
        """Bank index must always be in [0, num_banks)."""
        banked_l2 = BankedL2Cache(num_banks=4)

        for i in range(10000):
            addr = i * BLOCK_SIZE
            raw_bank = (addr >> banked_l2.intlv_low_bit) & banked_l2.intlv_mask
            assert raw_bank < banked_l2.num_banks, (
                f"Raw bank index {raw_bank} >= num_banks {banked_l2.num_banks} "
                f"for addr 0x{addr:x}. Mask is wrong."
            )


class TestBankSetDistribution:
    """Test Bug 2b: Per-bank set index must not alias due to bank bits."""

    def test_no_set_aliasing_within_bank(self):
        """
        Addresses mapping to the same bank should distribute across
        all cache sets within that bank, not cluster into a few sets.
        """
        banked_l2 = BankedL2Cache(num_banks=4)
        bank0 = banked_l2.banks[0]

        bank0_sets = set()
        for i in range(1024):
            addr = i * BLOCK_SIZE
            if banked_l2.get_bank_index(addr) == 0:
                set_idx = bank0._get_set_index(addr)
                bank0_sets.add(set_idx)

        num_sets = bank0.num_sets
        assert len(bank0_sets) > num_sets * 0.5, (
            f"Bank 0: only {len(bank0_sets)}/{num_sets} sets used for its "
            f"assigned addresses. The set index likely includes the bank "
            f"interleave bits, causing aliasing."
        )

    def test_all_banks_use_all_sets(self):
        """Every bank should utilize the majority of its cache sets."""
        banked_l2 = BankedL2Cache(num_banks=4)

        sets_per_bank = {i: set() for i in range(4)}
        for i in range(4096):
            addr = i * BLOCK_SIZE
            bank = banked_l2.get_bank_index(addr)
            set_idx = banked_l2.banks[bank]._get_set_index(addr)
            sets_per_bank[bank].add(set_idx)

        for bank_id, sets_used in sets_per_bank.items():
            num_sets = banked_l2.banks[bank_id].num_sets
            assert len(sets_used) >= num_sets * 0.75, (
                f"Bank {bank_id}: only {len(sets_used)}/{num_sets} sets used. "
                f"Set index calculation likely overlaps with bank selection bits."
            )


class TestMemoryRangeOverlapBug:
    """Test Bug 3: DRAM/HBM address range overlap."""

    def test_no_range_overlap(self):
        """Memory ranges must not overlap in dual-memory mode."""
        mem = MemorySystem(dual_memory=True)
        overlaps = mem.check_ranges()
        assert len(overlaps) == 0, (
            f"Memory ranges overlap: {overlaps}. "
            f"Ranges: {mem.ranges}"
        )

    def test_boundary_address_single_controller(self):
        """
        Each address at the DRAM/HBM boundary must be served by
        exactly one controller.
        """
        mem = MemorySystem(dual_memory=True)

        dram_size = 512 * 1024 * 1024
        test_addrs = [
            dram_size - BLOCK_SIZE,
            dram_size,
            dram_size + BLOCK_SIZE,
        ]

        for addr in test_addrs:
            controllers = mem.get_all_matching_controllers(addr)
            assert len(controllers) == 1, (
                f"Address 0x{addr:x} is served by {len(controllers)} "
                f"controllers, expected exactly 1. "
                f"Ranges: {mem.ranges}"
            )

    def test_dram_range_end_exclusive(self):
        """DRAM range end must be exclusive (not overlap with HBM start)."""
        mem = MemorySystem(dual_memory=True)

        dram_range = mem.ranges[0]
        hbm_range = mem.ranges[1]

        assert dram_range.end <= hbm_range.start, (
            f"DRAM end (0x{dram_range.end:x}) must be <= "
            f"HBM start (0x{hbm_range.start:x})"
        )

    def test_dual_memory_no_duplicate_services(self):
        """
        Full simulation in dual-memory mode must not produce
        duplicate memory services.
        """
        sim = CoherenceSimulator(
            num_cores=2, num_l2_banks=2, dual_memory=True
        )

        dram_size = 512 * 1024 * 1024
        boundary_addrs = [
            dram_size - 2 * BLOCK_SIZE,
            dram_size - BLOCK_SIZE,
            dram_size,
            dram_size + BLOCK_SIZE,
        ]

        for addr in boundary_addrs:
            baddr = addr & ~(BLOCK_SIZE - 1)
            controllers = sim.mem_system.get_all_matching_controllers(baddr)
            assert len(controllers) <= 1, (
                f"Address 0x{baddr:x} served by {len(controllers)} "
                f"controllers"
            )


class TestL2InclusionEnforcement:
    """Test Bug 4: L2 must enforce inclusion property."""

    def test_inclusion_after_eviction_pressure(self):
        """
        After heavy eviction pressure, every non-invalid L1 line must
        have a corresponding entry in L2 (inclusion property).
        """
        sim = CoherenceSimulator(num_cores=4, num_l2_banks=4)

        # L2 total capacity: 4 banks * 2KB = 8KB = 128 lines
        # Write 512 unique lines to force many L2 evictions
        for i in range(512):
            addr = i * BLOCK_SIZE
            data = struct.pack('<Q', i) + b'\x00' * 56
            sim.store(i % 4, addr, data)
            sim.run_until_idle(200)

        violations = check_inclusion(sim)
        assert len(violations) == 0, (
            f"L2 inclusion violated ({len(violations)} violations):\n" +
            "\n".join(violations[:10])
        )

    def test_inclusion_with_sharing(self):
        """
        Inclusion must hold even when lines are shared across
        multiple L1 caches before L2 eviction.
        """
        sim = CoherenceSimulator(num_cores=4, num_l2_banks=4)

        # Create sharing: all 4 cores access the same lines
        for i in range(32):
            addr = i * BLOCK_SIZE
            data = struct.pack('<Q', i) + b'\x00' * 56
            sim.store(0, addr, data)
            sim.run_until_idle(200)
            for core in range(1, 4):
                sim.load(core, addr)
                sim.run_until_idle(200)

        # Force L2 evictions
        for i in range(256):
            addr = (i + 1000) * BLOCK_SIZE
            data = struct.pack('<Q', i) + b'\x00' * 56
            sim.store(i % 4, addr, data)
            sim.run_until_idle(200)

        violations = check_inclusion(sim)
        assert len(violations) == 0, (
            f"L2 inclusion violated with sharing:\n" +
            "\n".join(violations[:10])
        )

    def test_dirty_data_preserved_through_eviction(self):
        """
        When L2 evicts a line whose L1 copy is in M state, the
        dirty data must be collected and written back to memory.
        """
        sim = CoherenceSimulator(num_cores=2, num_l2_banks=2)

        # Write distinctive values (store twice: first miss, then hit)
        test_values = {}
        for i in range(16):
            addr = i * BLOCK_SIZE
            val = 0xA000_0000_0000_0000 | (i << 16)
            data = struct.pack('<Q', val) + b'\x00' * 56
            # First store: miss -> GETX
            sim.store(0, addr, data)
            sim.run_until_idle(200)
            # Second store: hit -> actually writes data
            sim.store(0, addr, data)
            sim.run_until_idle(200)
            test_values[addr] = val

        # Force L2 evictions (L2 = 2 banks * 2KB = 4KB = 64 lines)
        for i in range(256):
            addr = (i + 500) * BLOCK_SIZE
            data = struct.pack('<Q', 0xB000 | i) + b'\x00' * 56
            sim.store(i % 2, addr, data)
            sim.run_until_idle(200)

        # Verify dirty data made it to backing memory via recall
        errors = []
        for addr, expected_val in test_values.items():
            baddr = addr & ~(BLOCK_SIZE - 1)
            ctrl = sim.mem_system.get_controller(baddr)
            if baddr in ctrl.memory:
                stored = struct.unpack('<Q', ctrl.memory[baddr][:8])[0]
                if stored != expected_val:
                    errors.append(
                        f"0x{addr:x}: expected 0x{expected_val:x}, "
                        f"got 0x{stored:x}"
                    )

        assert len(errors) == 0, (
            f"Dirty data lost during L2 eviction "
            f"(inclusion enforcement failed to collect M-state data):\n" +
            "\n".join(errors[:5])
        )
        assert len(sim.assertion_errors) == 0


class TestProtocolInvariants:
    """Test that MOESI protocol invariants hold after all fixes."""

    def test_basic_load_store(self):
        """Basic load/store functionality works after fixes."""
        sim = CoherenceSimulator(num_cores=2, num_l2_banks=2)

        addr = 0x2000
        data = struct.pack('<Q', 42) + b'\x00' * 56
        sim.store(0, addr, data)
        sim.run_until_idle(200)

        result = sim.load(0, addr)
        sim.run_until_idle(200)

        assert len(sim.assertion_errors) == 0

    def test_multicore_sharing(self):
        """Multiple cores can share a cache line."""
        sim = CoherenceSimulator(num_cores=4, num_l2_banks=4)

        addr = 0x3000
        data = struct.pack('<Q', 99) + b'\x00' * 56
        sim.store(0, addr, data)
        sim.run_until_idle(200)

        for core in range(1, 4):
            sim.load(core, addr)
            sim.run_until_idle(200)

        assert len(sim.assertion_errors) == 0

    def test_no_dual_m_state(self):
        """No two L1 caches should simultaneously hold the same line in M state."""
        sim = CoherenceSimulator(num_cores=4, num_l2_banks=4)

        for i in range(300):
            addr = (i * BLOCK_SIZE) % (64 * 1024)
            core = i % 4
            data = struct.pack('<Q', i) + b'\x00' * 56

            if i % 3 == 0:
                sim.load(core, addr)
            else:
                sim.store(core, addr, data)
            sim.run_until_idle(50)

            # Check M-state uniqueness
            m_holders = {}
            for c_id, l1 in enumerate(sim.l1_controllers):
                for s_idx in range(l1.num_sets):
                    for line in l1.sets[s_idx]:
                        if line.state == CacheState.M:
                            if line.addr in m_holders:
                                assert False, (
                                    f"Dual M-state at addr 0x{line.addr:x}: "
                                    f"cores {m_holders[line.addr]} and {c_id}"
                                )
                            m_holders[line.addr] = c_id

    def test_sustained_workload(self):
        """Sustained mixed workload completes without errors."""
        sim = CoherenceSimulator(num_cores=4, num_l2_banks=4)

        for i in range(500):
            addr = (i * BLOCK_SIZE) % (64 * 1024)
            core = i % 4
            data = struct.pack('<Q', i) + b'\x00' * 56

            if i % 3 == 0:
                sim.load(core, addr)
            else:
                sim.store(core, addr, data)
            sim.run_until_idle(50)

        assert len(sim.assertion_errors) == 0
        stats = sim.get_stats()
        assert stats['cycles'] > 0


class TestProtocolInstrumentation:
    """Test 5: Protocol traffic instrumentation design and implementation."""

    def test_traffic_report_method_exists(self):
        """Simulator must have get_protocol_traffic_report() method."""
        sim = CoherenceSimulator(num_cores=2, num_l2_banks=2)
        assert hasattr(sim, 'get_protocol_traffic_report'), \
            "CoherenceSimulator must have get_protocol_traffic_report() method"
        report = sim.get_protocol_traffic_report()
        assert isinstance(report, dict), \
            "get_protocol_traffic_report() must return a dict"

    def test_traffic_report_required_keys(self):
        """Report must contain all required keys with correct types."""
        sim = CoherenceSimulator(num_cores=2, num_l2_banks=2)
        report = sim.get_protocol_traffic_report()
        required_keys = [
            'total_messages', 'messages_by_type',
            'recall_events', 'dirty_collections',
        ]
        for key in required_keys:
            assert key in report, f"Missing required key: {key}"
        assert isinstance(report['total_messages'], int)
        assert isinstance(report['messages_by_type'], dict)
        assert isinstance(report['recall_events'], int)
        assert isinstance(report['dirty_collections'], int)

    def test_message_counting_after_workload(self):
        """Message counters must increment during simulation."""
        sim = CoherenceSimulator(num_cores=4, num_l2_banks=4)
        for i in range(50):
            addr = i * BLOCK_SIZE
            data = struct.pack('<Q', i) + b'\x00' * 56
            sim.store(i % 4, addr, data)
            sim.run_until_idle(100)

        report = sim.get_protocol_traffic_report()
        assert report['total_messages'] > 0, \
            "No messages counted during simulation"

    def test_messages_by_type_populated(self):
        """Message type breakdown must contain expected protocol messages."""
        sim = CoherenceSimulator(num_cores=2, num_l2_banks=2)
        for i in range(20):
            addr = i * BLOCK_SIZE
            data = struct.pack('<Q', i) + b'\x00' * 56
            sim.store(0, addr, data)
            sim.run_until_idle(100)
            sim.load(1, addr)
            sim.run_until_idle(100)

        report = sim.get_protocol_traffic_report()
        by_type = report['messages_by_type']
        assert isinstance(by_type, dict), "messages_by_type must be a dict"
        assert len(by_type) > 0, "messages_by_type must have entries"
        type_names = set(by_type.keys())
        assert 'GETX' in type_names or 'GETS' in type_names, (
            f"Expected GETX or GETS in message types, got: {type_names}"
        )

    def test_recall_events_counted(self):
        """Recall events must be counted when inclusion enforcement triggers."""
        sim = CoherenceSimulator(num_cores=2, num_l2_banks=2)

        # Write distinctive values to force M-state in L1
        for i in range(16):
            addr = i * BLOCK_SIZE
            data = struct.pack('<Q', 0xA000 + i) + b'\x00' * 56
            sim.store(0, addr, data)
            sim.run_until_idle(200)
            sim.store(0, addr, data)  # hit -> M state with data
            sim.run_until_idle(200)

        # Force L2 evictions to trigger recalls
        for i in range(256):
            addr = (i + 500) * BLOCK_SIZE
            data = struct.pack('<Q', 0xF000 + i) + b'\x00' * 56
            sim.store(i % 2, addr, data)
            sim.run_until_idle(200)

        report = sim.get_protocol_traffic_report()
        assert report['recall_events'] > 0, \
            "No recall events counted during L2 eviction with L1 M-state lines"
        assert report['dirty_collections'] > 0, \
            "No dirty data collections counted during recalls"

    def test_traffic_report_file(self):
        """Solver must produce /app/traffic_report.json with valid data."""
        assert os.path.exists('/app/traffic_report.json'), \
            "Missing /app/traffic_report.json"
        with open('/app/traffic_report.json') as f:
            data = json.load(f)
        assert data['total_messages'] > 0, \
            "traffic_report.json has zero total_messages"
        assert isinstance(data['messages_by_type'], dict), \
            "traffic_report.json messages_by_type must be a dict"
