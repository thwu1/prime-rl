
import sys
import os

sys.path.insert(0, '/app')

from affinity_engine.topology import Topology
from affinity_engine.placement import place_compact, place_scatter, PlacementResult
from affinity_engine.affinity import generate_mask, mask_to_list, generate_rank_masks
from affinity_engine.env_generator import compute_pin_domain_size
from affinity_engine.diagnostics import check_numa_locality

CONFIGS_DIR = '/app/configs'


class TestCompactPlacementNUMALocality:
    """Compact placement must keep each rank within a single NUMA node,
    even on topologies with interleaved physical core IDs across NUMA
    nodes (e.g. AMD EPYC NPS2 mode)."""

    def test_compact_nps2_each_rank_single_numa(self):
        topo = Topology.from_json(f'{CONFIGS_DIR}/dual_epyc_nps2.json')
        result = place_compact(topo, num_ranks=4, cores_per_rank=4)

        for rank in range(4):
            cores = result.get_rank_cores(rank)
            numa_nodes = set(c.numa_node_id for c in cores)
            assert len(numa_nodes) == 1, (
                f"Rank {rank} spans NUMA nodes {sorted(numa_nodes)}, "
                f"cores: {[c.physical_id for c in cores]}"
            )

    def test_compact_nps2_fills_numa_nodes_in_order(self):
        topo = Topology.from_json(f'{CONFIGS_DIR}/dual_epyc_nps2.json')
        result = place_compact(topo, num_ranks=4, cores_per_rank=4)

        for rank in range(4):
            cores = result.get_rank_cores(rank)
            numa_node = cores[0].numa_node_id
            assert numa_node == rank, (
                f"Rank {rank} placed in NUMA node {numa_node}, expected {rank}"
            )

    def test_compact_simple_topology_unchanged(self):
        """Compact placement on a topology with contiguous core IDs
        should still work correctly."""
        topo = Topology.from_json(f'{CONFIGS_DIR}/dual_xeon_nps1.json')
        result = place_compact(topo, num_ranks=2, cores_per_rank=8)

        for rank in range(2):
            cores = result.get_rank_cores(rank)
            assert len(cores) == 8
            numa_nodes = set(c.numa_node_id for c in cores)
            assert len(numa_nodes) == 1


class TestScatterPlacement:
    """Scatter placement must distribute ranks round-robin across sockets."""

    def test_scatter_does_not_raise(self):
        topo = Topology.from_json(f'{CONFIGS_DIR}/dual_epyc_nps2.json')
        result = place_scatter(topo, num_ranks=4, cores_per_rank=4)
        assert result.num_ranks == 4

    def test_scatter_alternates_sockets(self):
        topo = Topology.from_json(f'{CONFIGS_DIR}/dual_epyc_nps2.json')
        result = place_scatter(topo, num_ranks=4, cores_per_rank=4)

        for rank in range(4):
            cores = result.get_rank_cores(rank)
            sockets = set(c.socket_id for c in cores)
            assert len(sockets) == 1, (
                f"Rank {rank} spans sockets {sorted(sockets)}"
            )

            expected_socket = rank % 2
            actual_socket = cores[0].socket_id
            assert actual_socket == expected_socket, (
                f"Rank {rank} on socket {actual_socket}, "
                f"expected socket {expected_socket}"
            )

    def test_scatter_maintains_numa_locality(self):
        topo = Topology.from_json(f'{CONFIGS_DIR}/dual_epyc_nps2.json')
        result = place_scatter(topo, num_ranks=4, cores_per_rank=4)

        for rank in range(4):
            cores = result.get_rank_cores(rank)
            numa_nodes = set(c.numa_node_id for c in cores)
            assert len(numa_nodes) == 1, (
                f"Rank {rank} spans NUMA nodes {sorted(numa_nodes)}"
            )

    def test_scatter_no_ht_topology(self):
        topo = Topology.from_json(f'{CONFIGS_DIR}/dual_xeon_nps1.json')
        result = place_scatter(topo, num_ranks=2, cores_per_rank=8)

        for rank in range(2):
            cores = result.get_rank_cores(rank)
            assert len(cores) == 8
            sockets = set(c.socket_id for c in cores)
            assert len(sockets) == 1


class TestAffinityMaskHyperThreading:
    """Affinity masks must include HyperThread sibling logical CPUs
    when include_ht_siblings is True."""

    def test_mask_includes_ht_siblings(self):
        topo = Topology.from_json(f'{CONFIGS_DIR}/single_xeon_ht.json')
        # Core 0: logical [0, 8], Core 1: logical [1, 9]
        cores = topo.sockets[0].numa_nodes[0].cores[:2]

        mask = generate_mask(cores, include_ht_siblings=True)
        cpu_list = mask_to_list(mask)

        assert 0 in cpu_list, "Missing logical CPU 0"
        assert 8 in cpu_list, "Missing HT sibling logical CPU 8"
        assert 1 in cpu_list, "Missing logical CPU 1"
        assert 9 in cpu_list, "Missing HT sibling logical CPU 9"
        assert len(cpu_list) == 4, (
            f"Expected 4 CPUs in mask, got {len(cpu_list)}: {cpu_list}"
        )

    def test_mask_excludes_ht_when_disabled(self):
        topo = Topology.from_json(f'{CONFIGS_DIR}/single_xeon_ht.json')
        cores = topo.sockets[0].numa_nodes[0].cores[:2]

        mask = generate_mask(cores, include_ht_siblings=False)
        cpu_list = mask_to_list(mask)

        assert 0 in cpu_list
        assert 1 in cpu_list
        assert 8 not in cpu_list
        assert 9 not in cpu_list
        assert len(cpu_list) == 2

    def test_full_rank_masks_with_ht(self):
        topo = Topology.from_json(f'{CONFIGS_DIR}/single_xeon_ht.json')
        # 4 ranks x 2 cores each on 8-core HT system
        result = place_compact(topo, num_ranks=4, cores_per_rank=2)
        masks = generate_rank_masks(result, include_ht=True)

        for rank in range(4):
            cpu_list = masks[rank]['cpu_list']
            # Each rank has 2 cores x 2 HT = 4 logical CPUs
            assert len(cpu_list) == 4, (
                f"Rank {rank} mask has {len(cpu_list)} CPUs, expected 4: "
                f"{cpu_list}"
            )


class TestPinDomainAutoMode:
    """I_MPI_PIN_DOMAIN auto mode must use physical core count,
    not logical CPU count, to compute domain size."""

    def test_auto_domain_ht_system(self):
        topo = Topology.from_json(f'{CONFIGS_DIR}/dual_epyc_nps2.json')
        # 16 physical cores, 32 logical CPUs, 4 ranks
        domain_size = compute_pin_domain_size(topo, num_ranks=4, mode='auto')
        # Must be 16/4 = 4, not 32/4 = 8
        assert domain_size == 4, (
            f"Auto domain size should be 4 "
            f"(16 physical cores / 4 ranks), got {domain_size}"
        )

    def test_auto_domain_single_socket_ht(self):
        topo = Topology.from_json(f'{CONFIGS_DIR}/single_xeon_ht.json')
        # 8 physical cores, 16 logical CPUs, 2 ranks
        domain_size = compute_pin_domain_size(topo, num_ranks=2, mode='auto')
        assert domain_size == 4, (
            f"Auto domain size should be 4 "
            f"(8 physical cores / 2 ranks), got {domain_size}"
        )

    def test_auto_domain_no_ht(self):
        topo = Topology.from_json(f'{CONFIGS_DIR}/dual_xeon_nps1.json')
        # 16 physical cores = 16 logical CPUs (no HT), 4 ranks
        domain_size = compute_pin_domain_size(topo, num_ranks=4, mode='auto')
        # Without HT, physical == logical, so either formula gives 4
        assert domain_size == 4


class TestNUMALocalityDiagnostic:
    """NUMA locality checker must detect cross-NUMA placements even when
    both NUMA nodes are within the same physical socket (multi-NPS systems)."""

    def test_detects_cross_numa_within_same_socket(self):
        topo = Topology.from_json(f'{CONFIGS_DIR}/dual_epyc_nps2.json')

        # Manually create a placement with cores from NUMA 0 and NUMA 1
        # (both in socket 0, but different NUMA domains)
        cores_numa0 = topo.sockets[0].numa_nodes[0].cores[:2]
        cores_numa1 = topo.sockets[0].numa_nodes[1].cores[:2]

        placement = PlacementResult()
        placement.rank_cores[0] = cores_numa0 + cores_numa1

        warnings = check_numa_locality(topo, placement)

        assert len(warnings) > 0, (
            "Must warn about cross-NUMA placement within same socket "
            "(NUMA 0 + NUMA 1 are different memory domains)"
        )
        assert warnings[0]['type'] == 'cross_numa'

    def test_no_warning_for_single_numa_node(self):
        topo = Topology.from_json(f'{CONFIGS_DIR}/dual_epyc_nps2.json')

        cores = topo.sockets[0].numa_nodes[0].cores[:4]

        placement = PlacementResult()
        placement.rank_cores[0] = cores

        warnings = check_numa_locality(topo, placement)
        assert len(warnings) == 0, (
            f"Should not warn for single-NUMA placement, got: {warnings}"
        )

    def test_detects_cross_socket_numa(self):
        topo = Topology.from_json(f'{CONFIGS_DIR}/dual_xeon_nps1.json')

        # Cores from both sockets
        cores_s0 = topo.sockets[0].numa_nodes[0].cores[:4]
        cores_s1 = topo.sockets[1].numa_nodes[0].cores[:4]

        placement = PlacementResult()
        placement.rank_cores[0] = cores_s0 + cores_s1

        warnings = check_numa_locality(topo, placement)
        assert len(warnings) > 0
        assert warnings[0]['type'] == 'cross_numa'
