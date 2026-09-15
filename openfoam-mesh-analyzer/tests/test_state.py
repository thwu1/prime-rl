"""

Tests for the OpenFOAM mesh analysis pipeline output.
Verifies /app/mesh_report.json against independently computed expected values.
"""
import json
import math
import os

import pytest


def compute_first_last_cell(L, N, R):
    """Compute first and last cell sizes for geometric grading.

    For N cells spanning length L with expansion ratio R (= last/first):
      common ratio r = R^(1/(N-1))
      first cell d1 = L * (r - 1) / (r^N - 1)
      last cell  dN = d1 * R
    """
    if N == 1:
        return L, L
    if abs(R - 1.0) < 1e-10:
        d = L / N
        return d, d
    r = R ** (1.0 / (N - 1))
    d_first = L * (r - 1.0) / (r ** N - 1.0)
    d_last = d_first * R
    return d_first, d_last


def compute_multi_grading_first_last(L, N, segments):
    """Compute first cell of first segment and last cell of last segment
    for multi-grading: ((lenFrac cellFrac expansion) ...).
    """
    f_seg = segments[0]
    L1 = f_seg[0] * L
    N1 = round(f_seg[1] * N)
    R1 = f_seg[2]
    d_first, _ = compute_first_last_cell(L1, N1, R1)

    l_seg = segments[-1]
    L_last = l_seg[0] * L
    N_last = round(l_seg[1] * N)
    R_last = l_seg[2]
    _, d_last = compute_first_last_cell(L_last, N_last, R_last)

    return d_first, d_last


@pytest.fixture
def report():
    path = "/app/mesh_report.json"
    assert os.path.exists(path), "mesh_report.json not found at /app/mesh_report.json"
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Basic mesh information
# ---------------------------------------------------------------------------
class TestBasicMeshInfo:
    def test_num_vertices(self, report):
        assert report["num_vertices"] == 24

    def test_num_blocks(self, report):
        assert report["num_blocks"] == 6

    def test_total_cells(self, report):
        assert report["total_cells"] == 2560


# ---------------------------------------------------------------------------
# Per-block cell counts
# ---------------------------------------------------------------------------
class TestBlockCells:
    EXPECTED = {0: 256, 1: 768, 2: 128, 3: 384, 4: 256, 5: 768}

    @pytest.mark.parametrize("block_id,expected", EXPECTED.items(),
                             ids=[f"block{k}" for k in EXPECTED])
    def test_block_total_cells(self, report, block_id, expected):
        block = next(b for b in report["blocks"] if b["id"] == block_id)
        assert block["total_cells"] == expected, (
            f"Block {block_id}: expected {expected} cells, got {block['total_cells']}"
        )


# ---------------------------------------------------------------------------
# Vertex indices extracted from hex definitions
# ---------------------------------------------------------------------------
class TestBlockVertices:
    EXPECTED_VERTS = {
        0: [0, 1, 5, 4, 12, 13, 17, 16],
        1: [4, 5, 9, 8, 16, 17, 21, 20],
        2: [1, 2, 6, 5, 13, 14, 18, 17],
        3: [5, 6, 10, 9, 17, 18, 22, 21],
        4: [2, 3, 7, 6, 14, 15, 19, 18],
        5: [6, 7, 11, 10, 18, 19, 23, 22],
    }

    @pytest.mark.parametrize("block_id,expected", EXPECTED_VERTS.items(),
                             ids=[f"block{k}" for k in EXPECTED_VERTS])
    def test_block_vertices(self, report, block_id, expected):
        block = next(b for b in report["blocks"] if b["id"] == block_id)
        assert block["vertices"] == expected


# ---------------------------------------------------------------------------
# Region classification
# ---------------------------------------------------------------------------
class TestRegionClassification:
    def test_solid_block(self, report):
        block = next(b for b in report["blocks"] if b["id"] == 2)
        assert block["region"] == "solid"

    @pytest.mark.parametrize("block_id", [0, 1, 3, 4, 5])
    def test_fluid_blocks(self, report, block_id):
        block = next(b for b in report["blocks"] if b["id"] == block_id)
        assert block["region"] == "fluid"


# ---------------------------------------------------------------------------
# Block adjacency
# ---------------------------------------------------------------------------
class TestAdjacency:
    EXPECTED_PAIRS = [[0, 1], [0, 2], [1, 3], [2, 3], [2, 4], [3, 5], [4, 5]]

    def test_num_adjacencies(self, report):
        assert len(report["adjacency"]) == 7

    def test_all_expected_pairs_present(self, report):
        actual = [sorted(pair) for pair in report["adjacency"]]
        for expected in self.EXPECTED_PAIRS:
            assert sorted(expected) in actual, f"Missing adjacency pair {expected}"

    def test_no_extra_pairs(self, report):
        actual = [tuple(sorted(pair)) for pair in report["adjacency"]]
        expected_set = {tuple(p) for p in self.EXPECTED_PAIRS}
        extra = set(actual) - expected_set
        assert len(extra) == 0, f"Unexpected adjacency pairs: {extra}"


# ---------------------------------------------------------------------------
# Cell sizes from grading (the core parsing + computation challenge)
# ---------------------------------------------------------------------------
class TestCellSizes:
    REL_TOL = 0.01  # 1% relative tolerance

    def _check_close(self, actual, expected, label=""):
        assert abs(actual - expected) / expected < self.REL_TOL, (
            f"{label}: expected {expected:.6e}, got {actual:.6e}"
        )

    # Block 0: simpleGrading y=0.25, L=0.01, N=8
    def test_block0_first_cell_y(self, report):
        block = next(b for b in report["blocks"] if b["id"] == 0)
        exp_first, _ = compute_first_last_cell(0.01, 8, 0.25)
        self._check_close(block["first_cell_height_y"], exp_first, "Block0 first_y")

    def test_block0_last_cell_y(self, report):
        block = next(b for b in report["blocks"] if b["id"] == 0)
        _, exp_last = compute_first_last_cell(0.01, 8, 0.25)
        self._check_close(block["last_cell_height_y"], exp_last, "Block0 last_y")

    # Block 2: uniform grading (R=1), L=0.01, N=8
    def test_block2_uniform_first(self, report):
        block = next(b for b in report["blocks"] if b["id"] == 2)
        expected = 0.01 / 8.0
        assert abs(block["first_cell_height_y"] - expected) < 1e-8

    def test_block2_uniform_last(self, report):
        block = next(b for b in report["blocks"] if b["id"] == 2)
        expected = 0.01 / 8.0
        assert abs(block["last_cell_height_y"] - expected) < 1e-8

    # Block 3: simpleGrading y=4.0, L=0.03, N=24
    def test_block3_first_cell_y(self, report):
        block = next(b for b in report["blocks"] if b["id"] == 3)
        exp_first, _ = compute_first_last_cell(0.03, 24, 4.0)
        self._check_close(block["first_cell_height_y"], exp_first, "Block3 first_y")

    def test_block3_last_cell_y(self, report):
        block = next(b for b in report["blocks"] if b["id"] == 3)
        _, exp_last = compute_first_last_cell(0.03, 24, 4.0)
        self._check_close(block["last_cell_height_y"], exp_last, "Block3 last_y")

    # Block 1: multi-grading y=((0.4 0.5 5.0)(0.6 0.5 0.2)), L=0.03, N=24
    def test_block1_multigrading_first(self, report):
        block = next(b for b in report["blocks"] if b["id"] == 1)
        segs = [(0.4, 0.5, 5.0), (0.6, 0.5, 0.2)]
        exp_first, _ = compute_multi_grading_first_last(0.03, 24, segs)
        self._check_close(block["first_cell_height_y"], exp_first, "Block1 mg first")

    def test_block1_multigrading_last(self, report):
        block = next(b for b in report["blocks"] if b["id"] == 1)
        segs = [(0.4, 0.5, 5.0), (0.6, 0.5, 0.2)]
        _, exp_last = compute_multi_grading_first_last(0.03, 24, segs)
        self._check_close(block["last_cell_height_y"], exp_last, "Block1 mg last")

    # Block 4: same grading as Block 0
    def test_block4_first_cell_y(self, report):
        block = next(b for b in report["blocks"] if b["id"] == 4)
        exp_first, _ = compute_first_last_cell(0.01, 8, 0.25)
        self._check_close(block["first_cell_height_y"], exp_first, "Block4 first_y")

    # Block 5: same multi-grading as Block 1
    def test_block5_multigrading_first(self, report):
        block = next(b for b in report["blocks"] if b["id"] == 5)
        segs = [(0.4, 0.5, 5.0), (0.6, 0.5, 0.2)]
        exp_first, _ = compute_multi_grading_first_last(0.03, 24, segs)
        self._check_close(block["first_cell_height_y"], exp_first, "Block5 mg first")


# ---------------------------------------------------------------------------
# Conjugate heat transfer analysis
# ---------------------------------------------------------------------------
class TestCHTAnalysis:
    # Problem parameters (must match cht_params.json)
    K_S = 50.0          # solid conductivity [W/(m*K)]
    Q_GEN = 5e5         # volumetric heat generation [W/m^3]
    T_F = 300.0         # fluid bulk temperature [K]
    H_CONV = 500.0      # convective HTC [W/(m^2*K)]
    H_SOLID = 0.01      # heater height [m]

    @property
    def q_flux(self):
        return self.Q_GEN * self.H_SOLID  # 5000 W/m^2

    @property
    def t_interface(self):
        return self.T_F + self.q_flux / self.H_CONV  # 310 K

    @property
    def t_max(self):
        return self.t_interface + self.Q_GEN / (2 * self.K_S) * self.H_SOLID ** 2  # 310.5 K

    def test_solid_block_id(self, report):
        assert report["cht"]["solid_block"] == 2

    def test_fluid_interface_block_id(self, report):
        assert report["cht"]["fluid_interface_block"] == 3

    def test_interface_temperature(self, report):
        T_int = report["cht"]["interface_temperature_K"]
        assert abs(T_int - self.t_interface) < 0.1, (
            f"Interface temp: expected {self.t_interface}, got {T_int}"
        )

    def test_max_heater_temperature(self, report):
        T_max = report["cht"]["max_heater_temperature_K"]
        assert abs(T_max - self.t_max) < 0.1, (
            f"Max heater temp: expected {self.t_max}, got {T_max}"
        )

    def test_interface_heat_flux(self, report):
        q = report["cht"]["interface_heat_flux_W_m2"]
        assert abs(q - self.q_flux) / self.q_flux < 0.01, (
            f"Interface heat flux: expected {self.q_flux}, got {q}"
        )
