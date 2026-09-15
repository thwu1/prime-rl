
import pytest
import sys
import os
import json

sys.path.insert(0, "/app")


def _import_sim():
    """Import the simulator module; fail clearly if missing."""
    try:
        import importlib
        if "simulator" in sys.modules:
            importlib.reload(sys.modules["simulator"])
            return sys.modules["simulator"]
        import simulator
        return simulator
    except ImportError:
        pytest.fail("Could not import /app/simulator.py")


# ---------------------------------------------------------------------------
# Halo size computation
# ---------------------------------------------------------------------------

class TestHaloSizes:

    def test_face_sizes(self):
        sim = _import_sim()
        sizes = sim.compute_halo_sizes(60, 72, 80, 1, 8)
        assert sizes["x_face"] == 72 * 80 * 1 * 8   # 46080
        assert sizes["y_face"] == 60 * 80 * 1 * 8    # 38400
        assert sizes["z_face"] == 60 * 72 * 1 * 8    # 34560

    def test_edge_sizes(self):
        """xy_edge runs along z, xz_edge along y, yz_edge along x."""
        sim = _import_sim()
        sizes = sim.compute_halo_sizes(60, 72, 80, 1, 8)
        assert sizes["xy_edge"] == 80 * 1 * 8   # nz * h^2 * e = 640
        assert sizes["xz_edge"] == 72 * 1 * 8   # ny * h^2 * e = 576
        assert sizes["yz_edge"] == 60 * 1 * 8   # nx * h^2 * e = 480

    def test_edge_sizes_halo2(self):
        sim = _import_sim()
        sizes = sim.compute_halo_sizes(100, 80, 60, 2, 8)
        assert sizes["xy_edge"] == 60 * 4 * 8    # 1920
        assert sizes["xz_edge"] == 80 * 4 * 8    # 2560
        assert sizes["yz_edge"] == 100 * 4 * 8   # 3200
        assert sizes["corner"] == 8 * 8           # 64


# ---------------------------------------------------------------------------
# Per-process volume
# ---------------------------------------------------------------------------

class TestPerProcessVolume:

    def test_26stencil(self):
        sim = _import_sim()
        vol = sim.compute_per_process_volume(60, 72, 80, 26, 1, 8)
        assert vol == 244928

    def test_18stencil_excludes_corners(self):
        """18-stencil includes face+edge but NOT corner contributions."""
        sim = _import_sim()
        vol = sim.compute_per_process_volume(60, 72, 80, 18, 1, 8)
        # face=238080 + edge=6784, no corners
        assert vol == 244864

    def test_6stencil_faces_only(self):
        sim = _import_sim()
        vol = sim.compute_per_process_volume(60, 72, 80, 6, 1, 8)
        assert vol == 238080

    def test_scenario_c_subdomain(self):
        """Volume for 18-stencil with halo_depth=2."""
        sim = _import_sim()
        vol = sim.compute_per_process_volume(80, 60, 80, 18, 2, 8)
        assert vol == 540160


# ---------------------------------------------------------------------------
# Decomposition optimization
# ---------------------------------------------------------------------------

class TestDecomposition:

    def test_scenario_a(self):
        """72 procs on 360x288x240 with 26-stencil: must find global optimum."""
        sim = _import_sim()
        result = sim.find_optimal_decomposition(72, 360, 288, 240, 26, 1, 8)
        assert result["Px"] * result["Py"] * result["Pz"] == 72
        assert 360 % result["Px"] == 0
        assert 288 % result["Py"] == 0
        assert 240 % result["Pz"] == 0
        assert result["volume"] == 244928

    def test_scenario_b(self):
        sim = _import_sim()
        result = sim.find_optimal_decomposition(24, 240, 120, 96, 6, 1, 8)
        assert result["Px"] * result["Py"] * result["Pz"] == 24
        assert result["volume"] == 115200

    def test_scenario_c(self):
        """48 procs on 480x240x160 with 18-stencil, h=2."""
        sim = _import_sim()
        result = sim.find_optimal_decomposition(48, 480, 240, 160, 18, 2, 8)
        assert result["Px"] * result["Py"] * result["Pz"] == 48
        assert result["volume"] == 540160

    def test_divisibility_enforced(self):
        sim = _import_sim()
        result = sim.find_optimal_decomposition(12, 100, 60, 40, 26, 1, 8)
        assert result["Px"] * result["Py"] * result["Pz"] == 12
        assert 100 % result["Px"] == 0
        assert 60 % result["Py"] == 0
        assert 40 % result["Pz"] == 0


# ---------------------------------------------------------------------------
# Neighbor graph
# ---------------------------------------------------------------------------

class TestNeighborGraph:

    def test_periodic_3x3x3_complete(self):
        """3x3x3 periodic with 26-stencil: complete graph."""
        sim = _import_sim()
        graph = sim.build_neighbor_graph(3, 3, 3, (True, True, True), 26)
        assert len(graph) == 27
        for rank in range(27):
            assert len(graph[rank]) == 26

    def test_periodic_4x4x4_6stencil(self):
        sim = _import_sim()
        graph = sim.build_neighbor_graph(4, 4, 4, (True, True, True), 6)
        for rank in range(64):
            assert len(graph[rank]) == 6

    def test_nonperiodic_corner(self):
        """4x4x4 non-periodic, 26-stencil: corner process has 7 neighbors."""
        sim = _import_sim()
        graph = sim.build_neighbor_graph(4, 4, 4, (False, False, False), 26)
        assert len(graph[0]) == 7
        expected = sorted([1, 4, 5, 16, 17, 20, 21])
        assert graph[0] == expected

    def test_nonperiodic_upper_corner(self):
        """4x4x4 non-periodic, 26-stencil: upper corner (3,3,3) also has 7."""
        sim = _import_sim()
        graph = sim.build_neighbor_graph(4, 4, 4, (False, False, False), 26)
        rank_333 = 3 + 3 * 4 + 3 * 16  # 63
        assert len(graph[rank_333]) == 7

    def test_graph_symmetry(self):
        """If A neighbors B then B neighbors A."""
        sim = _import_sim()
        graph = sim.build_neighbor_graph(6, 4, 3, (True, True, True), 26)
        for rank, neighbors in graph.items():
            for nb in neighbors:
                assert rank in graph[nb], (
                    f"Rank {rank} has neighbor {nb} but {nb} doesn't have {rank}")

    def test_nonperiodic_symmetry(self):
        """Symmetry must hold for non-periodic grids too."""
        sim = _import_sim()
        graph = sim.build_neighbor_graph(4, 3, 2, (False, False, False), 6)
        for rank, neighbors in graph.items():
            for nb in neighbors:
                assert rank in graph[nb]

    def test_all_ranks_valid(self):
        """All neighbor ranks must be in [0, num_procs)."""
        sim = _import_sim()
        N = 4 * 3 * 2
        graph = sim.build_neighbor_graph(4, 3, 2, (False, False, False), 26)
        for rank, neighbors in graph.items():
            for nb in neighbors:
                assert 0 <= nb < N, (
                    f"Rank {rank} has invalid neighbor {nb} (num_procs={N})")

    def test_mixed_periodic_rank0(self):
        """6x4x2, periodic-x only, 18-stencil: corner (0,0,0) has 9 neighbors."""
        sim = _import_sim()
        graph = sim.build_neighbor_graph(6, 4, 2, (True, False, False), 18)
        assert len(graph[0]) == 9


# ---------------------------------------------------------------------------
# Exchange time estimation
# ---------------------------------------------------------------------------

class TestExchangeTime:

    def test_scenario_a_time(self):
        sim = _import_sim()
        t = sim.estimate_exchange_time(60, 72, 80, 26, 1, 8, 1.5, 12.0)
        assert t == pytest.approx(29.7053, rel=1e-3)

    def test_scenario_b_time(self):
        sim = _import_sim()
        t = sim.estimate_exchange_time(60, 40, 48, 6, 1, 8, 2.0, 10.0)
        assert t == pytest.approx(11.76, rel=1e-3)

    def test_scenario_c_time(self):
        sim = _import_sim()
        t = sim.estimate_exchange_time(80, 60, 80, 18, 2, 8, 1.0, 25.0)
        assert t == pytest.approx(19.8032, rel=1e-3)

    def test_bandwidth_is_GB_not_GiB(self):
        """Bandwidth uses GB/s (10^9), not GiB/s (2^30)."""
        sim = _import_sim()
        # 6-stencil on 50x50x1, h=1, e=4, zero latency, bw=1.0 GB/s
        # x_face=200, y_face=200, z_face=10000
        # time = (200+200+10000)/1000 = 10.4 us
        t = sim.estimate_exchange_time(50, 50, 1, 6, 1, 4, 0.0, 1.0)
        assert t == pytest.approx(10.4, rel=1e-4)


# ---------------------------------------------------------------------------
# Output file correctness
# ---------------------------------------------------------------------------

class TestOutputFiles:

    def test_scenario_a_exists(self):
        assert os.path.isfile("/app/output/scenario_a.json")

    def test_scenario_b_exists(self):
        assert os.path.isfile("/app/output/scenario_b.json")

    def test_scenario_c_exists(self):
        assert os.path.isfile("/app/output/scenario_c.json")

    def test_scenario_a_values(self):
        with open("/app/output/scenario_a.json") as f:
            d = json.load(f)
        assert d["per_process_volume_bytes"] == 244928
        assert d["total_volume_bytes"] == 72 * 244928
        assert d["num_neighbor_pairs"] == 936
        assert d["estimated_time_us"] == pytest.approx(29.7053, rel=1e-3)

    def test_scenario_b_values(self):
        with open("/app/output/scenario_b.json") as f:
            d = json.load(f)
        assert d["per_process_volume_bytes"] == 115200
        assert d["total_volume_bytes"] == 24 * 115200
        assert d["num_neighbor_pairs"] == 46
        assert d["estimated_time_us"] == pytest.approx(11.76, rel=1e-3)

    def test_scenario_c_values(self):
        with open("/app/output/scenario_c.json") as f:
            d = json.load(f)
        assert d["per_process_volume_bytes"] == 540160
        assert d["total_volume_bytes"] == 48 * 540160
        assert d["num_neighbor_pairs"] == 264
        assert d["estimated_time_us"] == pytest.approx(19.8032, rel=1e-3)


# ---------------------------------------------------------------------------
# Cross-consistency
# ---------------------------------------------------------------------------

class TestConsistency:

    def test_volume_matches_decomposition(self):
        sim = _import_sim()
        result = sim.find_optimal_decomposition(72, 360, 288, 240, 26, 1, 8)
        nx = 360 // result["Px"]
        ny = 288 // result["Py"]
        nz = 240 // result["Pz"]
        vol = sim.compute_per_process_volume(nx, ny, nz, 26, 1, 8)
        assert result["volume"] == vol

    def test_neighbor_graph_total_edges(self):
        """Total directed edges for all-periodic 6x4x3 26-stencil = 1872."""
        sim = _import_sim()
        graph = sim.build_neighbor_graph(6, 4, 3, (True, True, True), 26)
        total = sum(len(v) for v in graph.values())
        assert total == 1872
        assert total // 2 == 936
