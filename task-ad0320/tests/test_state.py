"""Tests for the MOESI cache coherence protocol simulator.

Verifies bank distribution, coherence correctness, LR/SC atomicity,
Upgrade transaction optimization, SVG diagram generation, and trace
report analysis.
"""


import sys
sys.path.insert(0, "/app")

from moesi_sim.simulator import MOESISimulator


class TestBankDistribution:
    """Bank interleaving must distribute line-aligned accesses evenly."""

    def test_even_distribution(self):
        sim = MOESISimulator(num_cores=4, num_banks=4, block_size=64)
        for i in range(16):
            sim.load(0, i * 64)
        stats = sim.get_bank_stats()
        for bank_id in range(4):
            assert stats[bank_id]["gets"] > 0, (
                f"Bank {bank_id} received zero traffic; "
                f"bank interleaving is broken"
            )

    def test_balanced_distribution(self):
        sim = MOESISimulator(num_cores=4, num_banks=4, block_size=64)
        for i in range(16):
            sim.load(0, i * 64)
        stats = sim.get_bank_stats()
        for bank_id in range(4):
            assert stats[bank_id]["gets"] == 4, (
                f"Bank {bank_id}: expected 4 gets, got {stats[bank_id]['gets']}; "
                f"interleaving granularity is incorrect"
            )

    def test_same_line_same_bank(self):
        """Different cores accessing the same address must hit the same bank."""
        sim = MOESISimulator(num_cores=4, num_banks=4, block_size=64)
        addr = 0x140  # block 5
        sim.store(0, addr, 1)
        sim.load(1, addr)
        sim.load(2, addr)
        stats = sim.get_bank_stats()
        active = [b for b in range(4) if stats[b]["gets"] + stats[b]["getm"] > 0]
        assert len(active) == 1, (
            f"Address {hex(addr)} was served by multiple banks: {active}"
        )


class TestCoherenceSharing:
    """Read-sharing via directory forwarding must maintain coherence."""

    def test_stale_read_after_third_party_write(self):
        """After M->O sharing + third-core write, original owner must see new value."""
        sim = MOESISimulator(num_cores=4, num_banks=4, block_size=64)
        addr = 0x100

        sim.store(0, addr, 42)
        val = sim.load(1, addr)
        assert val == 42, f"Core 1 should read 42, got {val}"

        sim.store(2, addr, 99)
        val = sim.load(0, addr)
        assert val == 99, (
            f"Core 0 read stale value {val} instead of 99; "
            f"old owner was not invalidated on third-party write"
        )

    def test_multiple_sharers_invalidation(self):
        """All sharers must be invalidated when a new writer appears."""
        sim = MOESISimulator(num_cores=4, num_banks=4, block_size=64)
        addr = 0x100

        sim.store(0, addr, 10)
        for core in [1, 2, 3]:
            val = sim.load(core, addr)
            assert val == 10

        sim.store(3, addr, 77)
        for core in [0, 1, 2]:
            val = sim.load(core, addr)
            assert val == 77, (
                f"Core {core} read {val} instead of 77 after core 3's write"
            )


class TestLRSCAtomicity:
    """Load-reserved / store-conditional must guarantee atomicity."""

    def test_sc_fails_after_intervening_store(self):
        """SC must fail if another core wrote between LR and SC."""
        sim = MOESISimulator(num_cores=4, num_banks=4, block_size=64)
        addr = 0x200

        sim.store(0, addr, 10)
        val = sim.load_reserved(0, addr)
        assert val == 10

        sim.store(1, addr, 20)
        success = sim.store_conditional(0, addr, 30)
        assert not success, (
            "SC succeeded after another core's intervening store; "
            "reservation was not cleared on invalidation"
        )

        val = sim.load(0, addr)
        assert val == 20, f"Expected 20, got {val}"

    def test_sc_succeeds_without_contention(self):
        """SC should succeed when no intervening write occurred."""
        sim = MOESISimulator(num_cores=4, num_banks=4, block_size=64)
        addr = 0x300

        sim.store(0, addr, 50)
        sim.load_reserved(0, addr)
        success = sim.store_conditional(0, addr, 60)
        assert success, "SC should succeed without contention"

        val = sim.load(0, addr)
        assert val == 60


class TestMulticoreConsistency:
    """Integration test: complex access patterns must produce consistent state."""

    def test_write_after_sharing(self):
        sim = MOESISimulator(num_cores=4, num_banks=4, block_size=64)
        addrs = [i * 64 for i in range(8)]

        # Phase 1: core 0 initializes all lines
        for i, addr in enumerate(addrs):
            sim.store(0, addr, i * 10)

        # Phase 2: all cores read all lines (creates sharing)
        for i, addr in enumerate(addrs):
            for core in range(4):
                val = sim.load(core, addr)
                assert val == i * 10, (
                    f"Phase 2: core {core} addr {hex(addr)}: "
                    f"expected {i * 10}, got {val}"
                )

        # Phase 3: different cores overwrite different lines
        for i, addr in enumerate(addrs):
            writer = (i + 1) % 4
            sim.store(writer, addr, 1000 + i)

        # Phase 4: all cores must see latest values
        for i, addr in enumerate(addrs):
            expected = 1000 + i
            for core in range(4):
                val = sim.load(core, addr)
                assert val == expected, (
                    f"Phase 4: core {core} addr {hex(addr)}: "
                    f"expected {expected}, got {val}"
                )


class TestUpgradeTransaction:
    """Upgrade optimization: S/O->M without redundant data fetch."""

    def test_upgrade_from_shared(self):
        """A store to a Shared line must use Upgrade, not GetM."""
        sim = MOESISimulator(num_cores=4, num_banks=4, block_size=64)
        addr = 0x100

        sim.store(0, addr, 42)     # Core 0: GetM -> M
        sim.load(1, addr)          # Core 1: GetS -> S (Core 0: M->O)
        sim.store(1, addr, 99)     # Core 1: should Upgrade from S, not GetM

        stats = sim.get_bank_stats()
        bank = sim.interleaver.get_bank(addr)
        assert stats[bank]["upgrade"] >= 1, (
            f"Expected Upgrade transaction for S->M, but upgrade count is "
            f"{stats[bank]['upgrade']}; store path may be using GetM instead"
        )

    def test_upgrade_from_owned(self):
        """A store to an Owned line must use Upgrade, not GetM."""
        sim = MOESISimulator(num_cores=4, num_banks=4, block_size=64)
        addr = 0x100

        sim.store(0, addr, 10)     # Core 0: M
        sim.load(1, addr)          # Core 0: O, Core 1: S
        sim.store(0, addr, 20)     # Core 0: Upgrade from O to M

        val = sim.load(1, addr)
        assert val == 20, (
            f"Core 1 should see 20 after Owned->Modified upgrade, got {val}"
        )

        stats = sim.get_bank_stats()
        bank = sim.interleaver.get_bank(addr)
        assert stats[bank]["upgrade"] >= 1, (
            f"Expected Upgrade for O->M transition, got {stats[bank]['upgrade']}"
        )

    def test_upgrade_invalidates_all_sharers(self):
        """After Upgrade, all other sharers must be invalidated."""
        sim = MOESISimulator(num_cores=4, num_banks=4, block_size=64)
        addr = 0x100

        sim.store(0, addr, 10)
        for core in [1, 2, 3]:
            sim.load(core, addr)

        # Core 1 does Upgrade from Shared
        sim.store(1, addr, 50)

        # All other cores must see core 1's new value
        for core in [0, 2, 3]:
            val = sim.load(core, addr)
            assert val == 50, (
                f"Core {core} read {val} instead of 50 after Upgrade; "
                f"sharer invalidation is incomplete"
            )

    def test_upgrade_reduces_getm_count(self):
        """Upgrade should avoid a second GetM on already-Shared data."""
        sim = MOESISimulator(num_cores=4, num_banks=4, block_size=64)
        addr = 0x100

        sim.store(0, addr, 1)     # GetM #1
        sim.load(1, addr)         # GetS
        sim.store(1, addr, 2)     # Should be Upgrade (not GetM #2)

        stats = sim.get_bank_stats()
        bank = sim.interleaver.get_bank(addr)
        assert stats[bank]["getm"] == 1, (
            f"Expected exactly 1 GetM (initial store), got {stats[bank]['getm']}; "
            f"second store should use Upgrade, not GetM"
        )
        assert stats[bank]["upgrade"] == 1, (
            f"Expected exactly 1 Upgrade, got {stats[bank]['upgrade']}"
        )

    def test_upgrade_complex_multi_sharer_sequence(self):
        """Upgrade under complex sharing: write-share-upgrade-reshare-upgrade."""
        sim = MOESISimulator(num_cores=4, num_banks=4, block_size=64)
        addr = 0x400

        # Core 0 writes
        sim.store(0, addr, 100)

        # Cores 1, 2, 3 read (Core 0: O, others: S)
        for c in [1, 2, 3]:
            assert sim.load(c, addr) == 100

        # Core 2 upgrades (S -> M), invalidating others
        sim.store(2, addr, 200)
        assert sim.load(0, addr) == 200
        assert sim.load(3, addr) == 200

        # Now Core 0 and Core 3 have re-shared (S), Core 2 has O
        # Core 3 upgrades (S -> M)
        sim.store(3, addr, 300)

        # Everyone must see 300
        for c in range(4):
            val = sim.load(c, addr)
            assert val == 300, (
                f"Core {c} read {val} instead of 300 in multi-sharer "
                f"upgrade sequence"
            )

        stats = sim.get_bank_stats()
        bank = sim.interleaver.get_bank(addr)
        assert stats[bank]["upgrade"] >= 2, (
            f"Expected at least 2 Upgrade transactions in this sequence, "
            f"got {stats[bank]['upgrade']}"
        )


class TestDiagramGeneration:
    """Protocol state diagram must be a valid SVG with correct transitions."""

    def test_svg_file_exists(self):
        import os
        assert os.path.exists("/app/protocol.svg"), (
            "protocol.svg not found at /app/protocol.svg; "
            "run 'make diagram' to generate"
        )

    def test_svg_is_valid_format(self):
        with open("/app/protocol.svg", "rb") as f:
            raw = f.read(4000)
        assert b"<svg" in raw, (
            "protocol.svg does not contain valid SVG markup; "
            "check that Graphviz dot uses the correct output format flag"
        )

    def test_svg_contains_all_cache_states(self):
        with open("/app/protocol.svg", encoding="utf-8", errors="replace") as f:
            content = f.read()
        for state in ["Modified", "Owned", "Exclusive", "Shared", "Invalid"]:
            assert state in content, (
                f"SVG diagram missing cache state '{state}'"
            )

    def test_svg_contains_upgrade_transitions(self):
        with open("/app/protocol.svg", encoding="utf-8", errors="replace") as f:
            content = f.read()
        assert "Upgrade" in content, (
            "SVG diagram missing Upgrade transition label; "
            "gen_diagram.py must include Upgrade transitions"
        )


class TestTraceReport:
    """Trace analysis report must contain correct protocol statistics."""

    def test_report_file_exists(self):
        import os
        assert os.path.exists("/app/trace_report.json"), (
            "trace_report.json not found at /app/trace_report.json; "
            "run 'make trace-report' to generate"
        )

    def test_report_has_required_fields(self):
        import json
        with open("/app/trace_report.json") as f:
            report = json.load(f)
        for field in ["total_operations", "upgrade_transactions",
                      "getm_transactions", "bank_utilization"]:
            assert field in report, (
                f"Report missing required field '{field}'"
            )

    def test_report_statistics_correct(self):
        import json
        with open("/app/trace_report.json") as f:
            report = json.load(f)
        assert report["total_operations"] == 20, (
            f"Expected 20 total operations, got {report['total_operations']}"
        )
        assert report["upgrade_transactions"] == 3, (
            f"Expected 3 upgrade transactions, got {report['upgrade_transactions']}"
        )
        assert report["getm_transactions"] == 8, (
            f"Expected 8 GetM transactions, got {report['getm_transactions']}"
        )
        assert isinstance(report["bank_utilization"], dict), (
            "bank_utilization must be a dictionary"
        )
        assert len(report["bank_utilization"]) == 4, (
            f"Expected 4 banks in bank_utilization, "
            f"got {len(report['bank_utilization'])}"
        )
