#!/usr/bin/env python3
"""Tests for MOESI cache coherence simulator bug fixes and NUMA extension.

"""

import json
import os
import sqlite3 as sqlite3_mod
import subprocess
import sys
sys.path.insert(0, '/app')


class TestBaseSimulatorFix:
    """Base moesi_sim.py must be fixed to pass coherence checks."""

    def test_diagnostic_trace_no_violations(self):
        """Run diagnostic trace through the fixed simulator."""
        result = subprocess.run(
            ['python3', '/app/moesi_sim.py', '/app/diagnostic.trace',
             '--cores', '4', '--capacity', '8'],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, f"Simulator crashed: {result.stderr}"
        assert 'COHERENCE VIOLATIONS' not in result.stdout, \
            f"Base simulator still has coherence bugs:\n{result.stdout}"

    def test_exclusive_sharing_tracks_all_sharers(self):
        """E->S transition must track both old and new sharers."""
        trace = "0 READ 0x0100\n1 READ 0x0100\n2 WRITE 0x0100 0xBEEF\n0 READ 0x0100\n"
        with open('/tmp/test_share.trace', 'w') as f:
            f.write(trace)
        result = subprocess.run(
            ['python3', '/app/moesi_sim.py', '/tmp/test_share.trace',
             '--cores', '4'],
            capture_output=True, text=True, timeout=30
        )
        assert 'COHERENCE VIOLATIONS' not in result.stdout, \
            f"Sharing bug not fixed:\n{result.stdout}"
        # Core 0's last read must return 0xBEEF, not stale data
        lines = result.stdout.strip().split('\n')
        last_core0_read = [l for l in lines if 'core 0' in l and 'READ' in l]
        assert last_core0_read, "No core 0 read output found"
        assert '0x0000beef' in last_core0_read[-1].lower(), \
            f"Core 0 read stale data after E->S fix:\n{result.stdout}"

    def test_eviction_preserves_silently_upgraded_data(self):
        """Silently upgraded E->M line must writeback on eviction."""
        lines = [
            "0 READ 0x0100", "0 WRITE 0x0100 0xCAFE",
            "0 WRITE 0x0080 0x01", "0 WRITE 0x00C0 0x02",
            "0 WRITE 0x0140 0x03", "0 WRITE 0x0180 0x04",
            "1 READ 0x0100"
        ]
        with open('/tmp/test_evict.trace', 'w') as f:
            f.write('\n'.join(lines) + '\n')
        result = subprocess.run(
            ['python3', '/app/moesi_sim.py', '/tmp/test_evict.trace',
             '--cores', '4', '--capacity', '4'],
            capture_output=True, text=True, timeout=30
        )
        assert '0x0000cafe' in result.stdout.lower(), \
            f"Data lost after eviction of silently upgraded line:\n{result.stdout}"


class TestNUMAInterface:
    """NUMACoherenceSimulator must expose the correct interface."""

    def test_import_and_instantiate(self):
        from numa_coherence import NUMACoherenceSimulator
        sim = NUMACoherenceSimulator(num_cores=8, l1_capacity=8)
        assert sim is not None

    def test_has_required_methods(self):
        from numa_coherence import NUMACoherenceSimulator
        sim = NUMACoherenceSimulator(num_cores=8, l1_capacity=8)
        assert callable(getattr(sim, 'read', None))
        assert callable(getattr(sim, 'write', None))
        assert callable(getattr(sim, 'verify_coherence', None))

    def test_has_required_stats(self):
        from numa_coherence import NUMACoherenceSimulator
        sim = NUMACoherenceSimulator(num_cores=8, l1_capacity=8)
        required_keys = [
            'total_cycles', 'inter_chiplet_messages', 'memory_writebacks',
            'chiplet_cache_hits', 'owner_transitions',
            'reads', 'writes', 'hits', 'misses', 'invalidations',
        ]
        for key in required_keys:
            assert key in sim.stats, f"Missing required stat key: {key}"

    def test_configurable_options(self):
        from numa_coherence import NUMACoherenceSimulator
        sim = NUMACoherenceSimulator(
            num_cores=8, l1_capacity=8, cores_per_chiplet=4,
            enable_owner_opt=True, enable_chiplet_cache=True,
            chiplet_cache_capacity=16,
        )
        assert sim is not None

    def test_both_opts_disabled(self):
        from numa_coherence import NUMACoherenceSimulator
        sim = NUMACoherenceSimulator(
            num_cores=8, l1_capacity=8,
            enable_owner_opt=False, enable_chiplet_cache=False,
        )
        sim.write(0, 0x0000, 0x42)
        assert sim.read(0, 0x0000) == 0x42


class TestCrossChipletCorrectness:
    """Data coherence must be maintained across chiplet boundaries."""

    def test_write_read_cross_chiplet(self):
        from numa_coherence import NUMACoherenceSimulator
        sim = NUMACoherenceSimulator(num_cores=8, l1_capacity=8)
        sim.write(0, 0x0000, 0xAABB)
        result = sim.read(4, 0x0000)
        assert result == 0xAABB, (
            f"Cross-chiplet read got {result:#x}, expected 0xAABB")

    def test_sequential_writes_cross_chiplet(self):
        from numa_coherence import NUMACoherenceSimulator
        sim = NUMACoherenceSimulator(num_cores=8, l1_capacity=8)
        sim.write(0, 0x0000, 0x100)
        sim.write(4, 0x0000, 0x200)
        result = sim.read(0, 0x0000)
        assert result == 0x200, (
            f"Expected 0x200 after cross-chiplet overwrite, got {result:#x}")

    def test_multiple_addresses_cross_chiplet(self):
        from numa_coherence import NUMACoherenceSimulator
        sim = NUMACoherenceSimulator(num_cores=8, l1_capacity=8)
        # 0x0000 homes on chip 0, 0x0040 homes on chip 1
        sim.write(0, 0x0000, 0x1111)
        sim.write(4, 0x0040, 0x2222)
        r1 = sim.read(4, 0x0000)
        r2 = sim.read(0, 0x0040)
        assert r1 == 0x1111, f"Expected 0x1111, got {r1:#x}"
        assert r2 == 0x2222, f"Expected 0x2222, got {r2:#x}"

    def test_all_cores_write_read(self):
        from numa_coherence import NUMACoherenceSimulator
        sim = NUMACoherenceSimulator(num_cores=8, l1_capacity=16)
        for i in range(8):
            sim.write(i, 0x0000, 0x1000 + i)
        result = sim.read(0, 0x0000)
        assert result == 0x1007, (
            f"Expected 0x1007 (last writer wins), got {result:#x}")

    def test_coherence_invariants_cross_chiplet(self):
        from numa_coherence import NUMACoherenceSimulator
        sim = NUMACoherenceSimulator(num_cores=8, l1_capacity=16)
        for addr_idx in range(4):
            addr = addr_idx * 0x40
            for cid in range(8):
                sim.write(cid, addr, addr + cid)
                sim.read((cid + 3) % 8, addr)
        violations = sim.verify_coherence()
        assert violations == [], f"Coherence violations: {violations}"

    def test_readback_after_write_same_core(self):
        from numa_coherence import NUMACoherenceSimulator
        sim = NUMACoherenceSimulator(num_cores=8, l1_capacity=8)
        for i in range(8):
            sim.write(i, 0x0000, 0x100 * (i + 1))
            result = sim.read(i, 0x0000)
            assert result == 0x100 * (i + 1), (
                f"Core {i}: write-then-read expected {0x100 * (i + 1):#x}, "
                f"got {result:#x}")

    def test_eviction_preserves_data_cross_chiplet(self):
        """Dirty data must survive eviction even across chiplets."""
        from numa_coherence import NUMACoherenceSimulator
        sim = NUMACoherenceSimulator(num_cores=8, l1_capacity=4)
        sim.write(4, 0x0000, 0xDEAD)
        # Fill core 4's cache to force eviction of 0x0000
        for i in range(1, 5):
            sim.write(4, i * 0x40, 0xFF00 + i)
        # Read from a core on the other chiplet
        result = sim.read(0, 0x0000)
        assert result == 0xDEAD, (
            f"Expected 0xDEAD after eviction+cross-chiplet read, "
            f"got {result:#x}")


class TestCycleModel:
    """Cycle costs must reflect NUMA topology."""

    def test_local_miss_cheaper_than_remote(self):
        from numa_coherence import NUMACoherenceSimulator
        # Local: core 0 writes addr 0x0000 (home chip 0), core 1 reads
        sim_local = NUMACoherenceSimulator(
            num_cores=8, l1_capacity=8,
            enable_owner_opt=False, enable_chiplet_cache=False)
        sim_local.write(0, 0x0000, 0x100)
        local_before = sim_local.stats['total_cycles']
        sim_local.read(1, 0x0000)
        local_read_cost = sim_local.stats['total_cycles'] - local_before

        # Remote: core 0 writes addr 0x0000 (home chip 0), core 4 reads
        sim_remote = NUMACoherenceSimulator(
            num_cores=8, l1_capacity=8,
            enable_owner_opt=False, enable_chiplet_cache=False)
        sim_remote.write(0, 0x0000, 0x100)
        remote_before = sim_remote.stats['total_cycles']
        sim_remote.read(4, 0x0000)
        remote_read_cost = sim_remote.stats['total_cycles'] - remote_before

        assert remote_read_cost > local_read_cost, (
            f"Remote read ({remote_read_cost} cycles) should cost more than "
            f"local read ({local_read_cost} cycles)")

    def test_cycles_increase_monotonically(self):
        from numa_coherence import NUMACoherenceSimulator
        sim = NUMACoherenceSimulator(num_cores=8, l1_capacity=8)
        prev_cycles = 0
        for i in range(8):
            sim.write(i, i * 0x40, 0x100 + i)
            assert sim.stats['total_cycles'] >= prev_cycles
            prev_cycles = sim.stats['total_cycles']
        assert sim.stats['total_cycles'] > 0

    def test_hit_costs_less_than_miss(self):
        from numa_coherence import NUMACoherenceSimulator
        sim = NUMACoherenceSimulator(num_cores=8, l1_capacity=8)
        sim.write(0, 0x0000, 0x100)
        cycles_after_write = sim.stats['total_cycles']
        sim.read(0, 0x0000)  # L1 hit
        hit_cost = sim.stats['total_cycles'] - cycles_after_write

        sim.read(1, 0x0000)  # L1 miss
        miss_cost = sim.stats['total_cycles'] - cycles_after_write - hit_cost

        assert hit_cost < miss_cost, (
            f"Hit cost ({hit_cost}) should be less than "
            f"miss cost ({miss_cost})")

    def test_inter_chiplet_messages_tracked(self):
        from numa_coherence import NUMACoherenceSimulator
        sim = NUMACoherenceSimulator(
            num_cores=8, l1_capacity=8, enable_chiplet_cache=False)
        assert sim.stats['inter_chiplet_messages'] == 0
        sim.write(0, 0x0000, 0x100)
        # Local write — no inter-chiplet messages
        local_msgs = sim.stats['inter_chiplet_messages']
        sim.read(4, 0x0000)
        # Remote read — should generate inter-chiplet messages
        remote_msgs = sim.stats['inter_chiplet_messages']
        assert remote_msgs > local_msgs, (
            "Remote read should generate inter-chiplet messages")


class TestOwnerOptimization:
    """Owner state must avoid unnecessary memory writebacks."""

    def test_owner_opt_reduces_writebacks(self):
        from numa_coherence import NUMACoherenceSimulator
        # Without owner opt
        sim_base = NUMACoherenceSimulator(
            num_cores=8, l1_capacity=8,
            enable_owner_opt=False, enable_chiplet_cache=False)
        sim_base.write(0, 0x0000, 0x100)
        sim_base.read(1, 0x0000)
        sim_base.write(2, 0x0000, 0x200)
        sim_base.read(3, 0x0000)
        base_writebacks = sim_base.stats['memory_writebacks']

        # With owner opt
        sim_opt = NUMACoherenceSimulator(
            num_cores=8, l1_capacity=8,
            enable_owner_opt=True, enable_chiplet_cache=False)
        sim_opt.write(0, 0x0000, 0x100)
        sim_opt.read(1, 0x0000)
        sim_opt.write(2, 0x0000, 0x200)
        sim_opt.read(3, 0x0000)
        opt_writebacks = sim_opt.stats['memory_writebacks']

        assert opt_writebacks < base_writebacks, (
            f"Owner opt writebacks ({opt_writebacks}) should be less than "
            f"baseline ({base_writebacks})")

    def test_owner_opt_maintains_correctness(self):
        from numa_coherence import NUMACoherenceSimulator
        sim = NUMACoherenceSimulator(
            num_cores=8, l1_capacity=8, enable_owner_opt=True)
        sim.write(0, 0x0000, 0x100)
        assert sim.read(1, 0x0000) == 0x100
        sim.write(2, 0x0000, 0x200)
        assert sim.read(3, 0x0000) == 0x200
        assert sim.read(0, 0x0000) == 0x200
        violations = sim.verify_coherence()
        assert violations == []

    def test_owner_transitions_counted(self):
        from numa_coherence import NUMACoherenceSimulator
        sim = NUMACoherenceSimulator(
            num_cores=8, l1_capacity=8, enable_owner_opt=True)
        sim.write(0, 0x0000, 0x100)
        sim.read(1, 0x0000)  # M -> O transition
        assert sim.stats['owner_transitions'] >= 1, (
            "Owner optimization should count M->O transitions")

    def test_owner_opt_reduces_cycles(self):
        from numa_coherence import NUMACoherenceSimulator
        ops = [(0, 'W', 0x0000, 0x100), (1, 'R', 0x0000, None),
               (2, 'W', 0x0000, 0x200), (3, 'R', 0x0000, None),
               (4, 'W', 0x0000, 0x300), (5, 'R', 0x0000, None)]

        sim_base = NUMACoherenceSimulator(
            num_cores=8, l1_capacity=8,
            enable_owner_opt=False, enable_chiplet_cache=False)
        sim_opt = NUMACoherenceSimulator(
            num_cores=8, l1_capacity=8,
            enable_owner_opt=True, enable_chiplet_cache=False)

        for cid, op, addr, data in ops:
            if op == 'W':
                sim_base.write(cid, addr, data)
                sim_opt.write(cid, addr, data)
            else:
                sim_base.read(cid, addr)
                sim_opt.read(cid, addr)

        assert sim_opt.stats['total_cycles'] < sim_base.stats['total_cycles'], (
            f"Owner opt cycles ({sim_opt.stats['total_cycles']}) should be "
            f"less than baseline ({sim_base.stats['total_cycles']})")

    def test_owner_cross_chiplet_correctness(self):
        """Owner optimization must work correctly across chiplet boundaries."""
        from numa_coherence import NUMACoherenceSimulator
        sim = NUMACoherenceSimulator(
            num_cores=8, l1_capacity=8, enable_owner_opt=True)
        sim.write(0, 0x0000, 0xAA)
        assert sim.read(4, 0x0000) == 0xAA
        assert sim.read(5, 0x0000) == 0xAA
        sim.write(6, 0x0000, 0xBB)
        assert sim.read(0, 0x0000) == 0xBB
        assert sim.read(7, 0x0000) == 0xBB
        violations = sim.verify_coherence()
        assert violations == []


class TestChipletCache:
    """Per-chiplet shared cache must reduce cross-chiplet traffic."""

    def test_chiplet_cache_reduces_inter_messages(self):
        from numa_coherence import NUMACoherenceSimulator
        # Without chiplet cache
        sim_base = NUMACoherenceSimulator(
            num_cores=8, l1_capacity=8,
            enable_owner_opt=True, enable_chiplet_cache=False)
        sim_base.write(0, 0x0000, 0x100)
        for c in [4, 5, 6, 7]:
            sim_base.read(c, 0x0000)
        base_inter = sim_base.stats['inter_chiplet_messages']

        # With chiplet cache
        sim_opt = NUMACoherenceSimulator(
            num_cores=8, l1_capacity=8,
            enable_owner_opt=True, enable_chiplet_cache=True)
        sim_opt.write(0, 0x0000, 0x100)
        for c in [4, 5, 6, 7]:
            sim_opt.read(c, 0x0000)
        opt_inter = sim_opt.stats['inter_chiplet_messages']

        assert opt_inter < base_inter, (
            f"Chiplet cache inter-chiplet messages ({opt_inter}) should be "
            f"less than baseline ({base_inter})")

    def test_chiplet_cache_hits_counted(self):
        from numa_coherence import NUMACoherenceSimulator
        sim = NUMACoherenceSimulator(
            num_cores=8, l1_capacity=8, enable_chiplet_cache=True)
        sim.write(0, 0x0000, 0x100)
        sim.read(4, 0x0000)  # Remote miss, populates chiplet cache
        sim.read(5, 0x0000)  # Should hit in chiplet cache
        assert sim.stats['chiplet_cache_hits'] >= 1, (
            "Second remote read to same address should hit chiplet cache")

    def test_chiplet_cache_invalidated_on_write(self):
        from numa_coherence import NUMACoherenceSimulator
        sim = NUMACoherenceSimulator(
            num_cores=8, l1_capacity=8, enable_chiplet_cache=True)
        sim.write(0, 0x0000, 0x100)
        sim.read(4, 0x0000)   # Populates chiplet cache on chip 1
        sim.write(0, 0x0000, 0x200)  # Must invalidate chiplet cache
        result = sim.read(5, 0x0000)  # Must get new value, not stale cache
        assert result == 0x200, (
            f"Expected 0x200 after write invalidation, got {result:#x}. "
            f"Chiplet cache was not properly invalidated on write.")

    def test_chiplet_cache_maintains_correctness(self):
        from numa_coherence import NUMACoherenceSimulator
        sim = NUMACoherenceSimulator(
            num_cores=8, l1_capacity=8, enable_chiplet_cache=True)
        for i in range(10):
            writer = i % 8
            sim.write(writer, 0x0000, 0x1000 + i)
            reader = (writer + 4) % 8  # Different chiplet
            result = sim.read(reader, 0x0000)
            assert result == 0x1000 + i, (
                f"Iteration {i}: expected {0x1000 + i:#x}, got {result:#x}")

    def test_chiplet_cache_only_for_remote(self):
        """Chiplet cache should only cache remotely-homed addresses."""
        from numa_coherence import NUMACoherenceSimulator
        sim = NUMACoherenceSimulator(
            num_cores=8, l1_capacity=8, enable_chiplet_cache=True)
        # 0x0000 homes on chip 0; core 0 is on chip 0 -> local
        sim.write(0, 0x0000, 0x100)
        sim.read(1, 0x0000)  # Local read — should NOT use chiplet cache
        sim.read(2, 0x0000)  # Local read
        assert sim.stats['chiplet_cache_hits'] == 0, (
            "Local reads should not produce chiplet cache hits")


class TestCLIIntegration:
    """Extended simulator must support CLI mode and comparison script."""

    def test_comparison_script_exists(self):
        assert os.path.isfile('/app/run_comparison.sh'), \
            "/app/run_comparison.sh not found"

    def test_comparison_script_executable(self):
        assert os.access('/app/run_comparison.sh', os.X_OK), \
            "/app/run_comparison.sh is not executable"

    def test_numa_cli_json_stats(self):
        """numa_coherence.py must support --json-stats CLI output."""
        result = subprocess.run(
            ['python3', '/app/numa_coherence.py',
             '/app/traces/producer_consumer.trace', '--json-stats'],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        stats = json.loads(result.stdout)
        for key in ['total_cycles', 'inter_chiplet_messages',
                     'memory_writebacks']:
            assert key in stats, f"Missing key '{key}' in CLI JSON output"

    def test_numa_cli_baseline_config(self):
        """CLI must support --no-owner-opt and --no-chiplet-cache flags."""
        result = subprocess.run(
            ['python3', '/app/numa_coherence.py',
             '/app/traces/producer_consumer.trace', '--json-stats',
             '--no-owner-opt', '--no-chiplet-cache'],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, f"CLI baseline failed: {result.stderr}"
        stats = json.loads(result.stdout)
        assert isinstance(stats['total_cycles'], (int, float))


class TestDatabaseAnalysis:
    """SQLite database must exist with correct schema and data."""

    def test_database_exists(self):
        assert os.path.exists('/app/coherence_analysis.db'), \
            "/app/coherence_analysis.db not found"

    def test_trace_stats_table_schema(self):
        conn = sqlite3_mod.connect('/app/coherence_analysis.db')
        cursor = conn.execute("PRAGMA table_info(trace_stats)")
        columns = {row[1]: row[2].upper() for row in cursor.fetchall()}
        conn.close()
        assert 'trace' in columns, "Missing 'trace' column in trace_stats"
        assert 'config' in columns, "Missing 'config' column in trace_stats"
        assert 'total_cycles' in columns, "Missing 'total_cycles' column"
        assert 'inter_chiplet_messages' in columns, \
            "Missing 'inter_chiplet_messages' column"
        assert 'memory_writebacks' in columns, \
            "Missing 'memory_writebacks' column"

    def test_trace_stats_has_both_configs(self):
        conn = sqlite3_mod.connect('/app/coherence_analysis.db')
        configs = conn.execute(
            "SELECT DISTINCT config FROM trace_stats ORDER BY config"
        ).fetchall()
        conn.close()
        config_set = {r[0] for r in configs}
        assert 'baseline' in config_set, "Missing 'baseline' config rows"
        assert 'optimized' in config_set, "Missing 'optimized' config rows"

    def test_trace_stats_has_all_traces(self):
        trace_files = [f for f in os.listdir('/app/traces')
                       if f.endswith('.trace')]
        conn = sqlite3_mod.connect('/app/coherence_analysis.db')
        db_traces = conn.execute(
            "SELECT DISTINCT trace FROM trace_stats"
        ).fetchall()
        conn.close()
        db_trace_set = {r[0] for r in db_traces}
        for tf in trace_files:
            assert tf in db_trace_set, (
                f"Trace '{tf}' missing from trace_stats table")

    def test_trace_stats_values_positive(self):
        conn = sqlite3_mod.connect('/app/coherence_analysis.db')
        rows = conn.execute(
            "SELECT trace, config, total_cycles FROM trace_stats"
        ).fetchall()
        conn.close()
        assert len(rows) > 0, "trace_stats table is empty"
        for trace, config, cycles in rows:
            assert cycles > 0, (
                f"total_cycles must be positive for {trace}/{config}, "
                f"got {cycles}")

    def test_optimization_impact_view_exists(self):
        conn = sqlite3_mod.connect('/app/coherence_analysis.db')
        views = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='view' AND name='optimization_impact'"
        ).fetchall()
        conn.close()
        assert len(views) == 1, "Missing 'optimization_impact' view"

    def test_optimization_impact_view_columns(self):
        conn = sqlite3_mod.connect('/app/coherence_analysis.db')
        cursor = conn.execute("SELECT * FROM optimization_impact LIMIT 1")
        col_names = [desc[0] for desc in cursor.description]
        conn.close()
        required = ['cycle_reduction_pct', 'writeback_reduction_pct',
                     'inter_chiplet_reduction_pct']
        for col in required:
            assert col in col_names, (
                f"Missing column '{col}' in optimization_impact view. "
                f"Found: {col_names}")

    def test_optimization_impact_shows_improvement(self):
        conn = sqlite3_mod.connect('/app/coherence_analysis.db')
        rows = conn.execute(
            "SELECT trace, cycle_reduction_pct FROM optimization_impact"
        ).fetchall()
        conn.close()
        improved = sum(1 for _, pct in rows if pct > 0)
        assert improved >= 3, (
            f"At least 3 traces must show cycle improvement, "
            f"but only {improved} do")

    def test_database_matches_results_json(self):
        """Data in the database must be consistent with results.json."""
        conn = sqlite3_mod.connect('/app/coherence_analysis.db')
        db_rows = conn.execute(
            "SELECT trace, config, total_cycles, inter_chiplet_messages, "
            "memory_writebacks FROM trace_stats ORDER BY trace, config"
        ).fetchall()
        conn.close()

        with open('/app/results.json') as f:
            results = json.load(f)

        for trace, config, cycles, inter, wb in db_rows:
            assert trace in results['traces'], \
                f"Trace '{trace}' in DB but not in results.json"
            json_stats = results['traces'][trace][config]
            assert json_stats['total_cycles'] == cycles, (
                f"Cycle mismatch for {trace}/{config}: "
                f"DB={cycles}, JSON={json_stats['total_cycles']}")
            assert json_stats['inter_chiplet_messages'] == inter, (
                f"inter_chiplet mismatch for {trace}/{config}: "
                f"DB={inter}, JSON={json_stats['inter_chiplet_messages']}")
            assert json_stats['memory_writebacks'] == wb, (
                f"writebacks mismatch for {trace}/{config}: "
                f"DB={wb}, JSON={json_stats['memory_writebacks']}")


class TestVisualization:
    """Gnuplot chart must exist and be valid SVG."""

    def test_chart_exists(self):
        assert os.path.exists('/app/comparison_chart.svg'), \
            "/app/comparison_chart.svg not found"

    def test_chart_is_valid_svg(self):
        with open('/app/comparison_chart.svg') as f:
            content = f.read()
        assert '<svg' in content.lower(), "Chart file is not valid SVG"
        assert '</svg>' in content.lower(), "SVG file is incomplete"

    def test_chart_contains_bar_elements(self):
        """Chart should contain visual elements (rectangles for bars)."""
        with open('/app/comparison_chart.svg') as f:
            content = f.read()
        assert '<rect' in content.lower(), (
            "SVG chart has no rect elements (missing bar chart data)")

    def test_chart_has_legend(self):
        """Chart should contain legend labels for baseline and optimized."""
        with open('/app/comparison_chart.svg') as f:
            content = f.read()
        content_lower = content.lower()
        assert 'baseline' in content_lower, \
            "Chart missing 'Baseline' in legend"
        assert 'optimized' in content_lower, \
            "Chart missing 'Optimized' in legend"

    def test_chart_file_size(self):
        """SVG chart should have non-trivial content (not empty/stub)."""
        size = os.path.getsize('/app/comparison_chart.svg')
        assert size > 1000, (
            f"SVG chart file is only {size} bytes — likely empty or stub")


class TestResultsFile:
    """results.json must exist with correct schema and show improvement."""

    def test_results_file_exists(self):
        assert os.path.exists('/app/results.json'), \
            "/app/results.json not found"

    def test_results_schema(self):
        with open('/app/results.json') as f:
            results = json.load(f)

        assert 'traces' in results, "Missing 'traces' key in results"
        assert len(results['traces']) >= 3, \
            f"Need results for at least 3 traces, got {len(results['traces'])}"

        for trace_name, trace_data in results['traces'].items():
            assert 'baseline' in trace_data, \
                f"Missing 'baseline' for {trace_name}"
            assert 'optimized' in trace_data, \
                f"Missing 'optimized' for {trace_name}"
            for mode in ['baseline', 'optimized']:
                stats = trace_data[mode]
                for key in ['total_cycles', 'inter_chiplet_messages',
                            'memory_writebacks']:
                    assert key in stats, \
                        f"Missing '{key}' in {trace_name}/{mode}"
                    assert isinstance(stats[key], (int, float)), \
                        f"{key} in {trace_name}/{mode} must be numeric"

    def test_optimization_improvement(self):
        with open('/app/results.json') as f:
            results = json.load(f)

        improved_count = 0
        for trace_name, trace_data in results['traces'].items():
            base_cycles = trace_data['baseline']['total_cycles']
            opt_cycles = trace_data['optimized']['total_cycles']
            if opt_cycles < base_cycles:
                improved_count += 1

        assert improved_count >= 3, (
            f"Optimization must improve at least 3 traces, "
            f"but only improved {improved_count}")

    def test_summary_present(self):
        with open('/app/results.json') as f:
            results = json.load(f)
        assert 'summary' in results, "Missing 'summary' key in results"
        summary = results['summary']
        for key in ['avg_cycle_reduction_pct', 'avg_writeback_reduction_pct',
                     'avg_inter_chiplet_reduction_pct']:
            assert key in summary, f"Missing '{key}' in summary"
            assert isinstance(summary[key], (int, float)), \
                f"summary['{key}'] must be numeric"

    def test_writebacks_reduced(self):
        """Optimized config should reduce memory writebacks overall."""
        with open('/app/results.json') as f:
            results = json.load(f)
        total_base_wb = sum(
            t['baseline']['memory_writebacks']
            for t in results['traces'].values())
        total_opt_wb = sum(
            t['optimized']['memory_writebacks']
            for t in results['traces'].values())
        assert total_opt_wb <= total_base_wb, (
            f"Total optimized writebacks ({total_opt_wb}) should not exceed "
            f"baseline ({total_base_wb})")
