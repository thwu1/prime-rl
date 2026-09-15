
import json
import os
import re
import pytest

RESULTS_DIR = "/app/results"

# ---------------------------------------------------------------------------
# Reference spectrum values (exhaustively computed at orders 1-3)
# ---------------------------------------------------------------------------
EXPECTED_SPECTRUM = {
    "E0": [1, 4, 729],
    "E1": [1, 8, 729],
    "E2": [1, 8, 113],
    "E3": [1, 4, 64],
    "E4": [1, 4, 64],
    "E5": [1, 2, 3],
    "E6": [1, 9, 224],
    "E7": [1, 9, 224],
    "E8": [1, 10, 137],
    "E9": [1, 10, 369],
}

# ---------------------------------------------------------------------------
# Reference implications (over magmas of order <= 4)
# E5 implies E1, E3, E4 at order <= 3 but Z3 finds order-4
# counterexamples, so E5 only implies E5 and E9 at order <= 4.
# ---------------------------------------------------------------------------
EXPECTED_IMPLICATIONS = {
    "E0": ["E0"],
    "E1": ["E1"],
    "E2": ["E2", "E8"],
    "E3": ["E3"],
    "E4": ["E4"],
    "E5": ["E5", "E9"],
    "E6": ["E6"],
    "E7": ["E7"],
    "E8": ["E8"],
    "E9": ["E9"],
}

# ---------------------------------------------------------------------------
# Reference Hasse diagram (transitive reduction, no self-loops)
# ---------------------------------------------------------------------------
EXPECTED_HASSE = {
    "E0": [],
    "E1": [],
    "E2": ["E8"],
    "E3": [],
    "E4": [],
    "E5": ["E9"],
    "E6": [],
    "E7": [],
    "E8": [],
    "E9": [],
}

# ---------------------------------------------------------------------------
# Reference joint spectrum at order 3 (selected entries)
# ---------------------------------------------------------------------------
EXPECTED_JOINT_SPOT = {
    ("E0", "E1"): 27,
    ("E0", "E2"): 35,
    ("E1", "E2"): 63,
    ("E2", "E5"): 0,
    ("E5", "E1"): 3,
    ("E5", "E3"): 3,
    ("E5", "E4"): 3,
    ("E5", "E9"): 3,
    ("E6", "E7"): 81,
    ("E6", "E6"): 224,
    ("E8", "E2"): 113,
    ("E9", "E1"): 105,
    ("E0", "E9"): 48,
    ("E3", "E4"): 3,
}

# ---------------------------------------------------------------------------
# Smallest counterexample orders for selected non-implications
# E5->E1, E5->E3, E5->E4 hold at order <= 3 but fail at order 4.
# ---------------------------------------------------------------------------
EXPECTED_CE_ORDERS = {
    "E0->E1": 2,
    "E0->E2": 3,
    "E0->E3": 2,
    "E1->E0": 2,
    "E1->E2": 2,
    "E2->E1": 2,
    "E2->E9": 3,
    "E5->E0": 2,
    "E5->E1": 4,
    "E5->E2": 3,
    "E5->E3": 4,
    "E5->E4": 4,
}

# ---------------------------------------------------------------------------
# Expected duality relationships
# ---------------------------------------------------------------------------
EXPECTED_DUALITY = {
    "E0": {"dual_id": "E0", "self_dual": True},
    "E1": {"dual_id": "E1", "self_dual": True},
    "E2": {"dual_id": "E2", "self_dual": True},
    "E3": {"dual_id": "E4", "self_dual": False},
    "E4": {"dual_id": "E3", "self_dual": False},
    "E5": {"dual_id": None, "self_dual": False},
    "E6": {"dual_id": "E7", "self_dual": False},
    "E7": {"dual_id": "E6", "self_dual": False},
    "E8": {"dual_id": "E8", "self_dual": True},
    "E9": {"dual_id": "E9", "self_dual": True},
}

# ---------------------------------------------------------------------------
# Expected lattice properties
# With only two Hasse edges (E2->E8, E5->E9), there are 8 connected
# components (6 isolated nodes + 2 two-node chains).  Width = 8
# (maximum antichain excludes one node from each chain).
# ---------------------------------------------------------------------------
EXPECTED_LATTICE = {
    "width": 8,
    "height": 1,
    "num_maximal": 8,
    "num_minimal": 8,
    "num_connected_components": 8,
}

# ---------------------------------------------------------------------------
# Per-equation checkers (hardcoded, NOT a general parser)
# ---------------------------------------------------------------------------
EQ_IDS = ["E0", "E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8", "E9"]


def _check(M, eq_idx):
    """Check whether magma table M satisfies equation eq_idx."""
    n = len(M)
    e = range(n)
    if eq_idx == 0:
        return all(M[x][x] == x for x in e)
    if eq_idx == 1:
        return all(M[x][y] == M[y][x] for x in e for y in e)
    if eq_idx == 2:
        return all(M[M[x][y]][z] == M[x][M[y][z]] for x in e for y in e for z in e)
    if eq_idx == 3:
        return all(M[x][M[x][y]] == y for x in e for y in e)
    if eq_idx == 4:
        return all(M[M[x][y]][y] == x for x in e for y in e)
    if eq_idx == 5:
        return all(M[M[x][y]][x] == y for x in e for y in e)
    if eq_idx == 6:
        return all(M[x][M[y][z]] == M[M[x][y]][M[x][z]] for x in e for y in e for z in e)
    if eq_idx == 7:
        return all(M[M[x][y]][z] == M[M[x][z]][M[y][z]] for x in e for y in e for z in e)
    if eq_idx == 8:
        return all(
            M[w][M[x][M[y][z]]] == M[M[M[w][x]][y]][z]
            for w in e for x in e for y in e for z in e
        )
    if eq_idx == 9:
        return all(
            M[M[x][y]][M[z][w]] == M[M[x][z]][M[y][w]]
            for x in e for y in e for z in e for w in e
        )
    raise ValueError(f"unknown eq {eq_idx}")


# ===================================================================
# Tests — Output file existence
# ===================================================================

class TestOutputFilesExist:
    @pytest.mark.parametrize("fname", [
        "spectrum.json", "joint_spectrum.json", "implications.json",
        "counterexamples.json", "hasse.json",
        "duality.json", "hasse.dot", "hasse.svg",
        "lattice_properties.json",
    ])
    def test_file_exists(self, fname):
        path = os.path.join(RESULTS_DIR, fname)
        assert os.path.isfile(path), f"{path} does not exist"


# ===================================================================
# Tests — Spectrum
# ===================================================================

class TestSpectrum:
    @pytest.fixture(autouse=True)
    def load(self):
        with open(f"{RESULTS_DIR}/spectrum.json") as f:
            self.data = json.load(f)

    def test_all_keys_present(self):
        for eid in EQ_IDS:
            assert eid in self.data, f"Missing key {eid}"

    def test_each_list_length_3(self):
        for eid in EQ_IDS:
            assert len(self.data[eid]) == 3, f"{eid} should have 3 entries"

    def test_order1_all_ones(self):
        for eid in EQ_IDS:
            assert self.data[eid][0] == 1, f"{eid} order-1 count must be 1"

    def test_spectrum_values(self):
        for eid, expected in EXPECTED_SPECTRUM.items():
            assert self.data[eid] == expected, (
                f"Spectrum {eid}: got {self.data[eid]}, expected {expected}"
            )


# ===================================================================
# Tests — Implications
# ===================================================================

class TestImplications:
    @pytest.fixture(autouse=True)
    def load(self):
        with open(f"{RESULTS_DIR}/implications.json") as f:
            self.data = json.load(f)

    def test_all_keys_present(self):
        for eid in EQ_IDS:
            assert eid in self.data

    def test_self_implication(self):
        for eid in EQ_IDS:
            assert eid in self.data[eid], f"{eid} must imply itself"

    def test_implications_match(self):
        for eid, expected in EXPECTED_IMPLICATIONS.items():
            assert sorted(self.data[eid]) == sorted(expected), (
                f"Implications of {eid}: got {sorted(self.data[eid])}, "
                f"expected {sorted(expected)}"
            )

    def test_e2_implies_e8(self):
        assert "E8" in self.data["E2"], "Associativity must imply generalized associativity"

    def test_e5_implies_medial(self):
        assert "E9" in self.data["E5"], "E5 must imply mediality"

    def test_e5_does_not_imply_commutative(self):
        assert "E1" not in self.data["E5"], (
            "E5 does NOT imply commutativity (order-4 counterexample exists)"
        )

    def test_e5_does_not_imply_left_involution(self):
        assert "E3" not in self.data["E5"], (
            "E5 does NOT imply left involution (order-4 counterexample exists)"
        )

    def test_e5_does_not_imply_right_involution(self):
        assert "E4" not in self.data["E5"], (
            "E5 does NOT imply right involution (order-4 counterexample exists)"
        )

    def test_e0_does_not_imply_e1(self):
        assert "E1" not in self.data["E0"]

    def test_e8_does_not_imply_e2(self):
        assert "E2" not in self.data["E8"]


# ===================================================================
# Tests — Joint Spectrum
# ===================================================================

class TestJointSpectrum:
    @pytest.fixture(autouse=True)
    def load(self):
        with open(f"{RESULTS_DIR}/joint_spectrum.json") as f:
            self.data = json.load(f)

    def test_all_keys_present(self):
        for ei in EQ_IDS:
            assert ei in self.data, f"Missing outer key {ei}"
            for ej in EQ_IDS:
                assert ej in self.data[ei], f"Missing inner key {ei}.{ej}"

    def test_symmetry(self):
        for ei in EQ_IDS:
            for ej in EQ_IDS:
                assert self.data[ei][ej] == self.data[ej][ei], (
                    f"Joint not symmetric: [{ei}][{ej}]={self.data[ei][ej]} "
                    f"vs [{ej}][{ei}]={self.data[ej][ei]}"
                )

    def test_diagonal_matches_order3_spectrum(self):
        with open(f"{RESULTS_DIR}/spectrum.json") as f:
            spec = json.load(f)
        for eid in EQ_IDS:
            assert self.data[eid][eid] == spec[eid][2], (
                f"Diagonal [{eid}][{eid}] must equal order-3 spectrum"
            )

    def test_spot_values(self):
        for (ei, ej), expected in EXPECTED_JOINT_SPOT.items():
            actual = self.data[ei][ej]
            assert actual == expected, (
                f"Joint[{ei}][{ej}]: got {actual}, expected {expected}"
            )

    def test_no_magma_satisfies_e2_and_e5(self):
        assert self.data["E2"]["E5"] == 0

    def test_all_e5_magmas_satisfy_e9(self):
        with open(f"{RESULTS_DIR}/spectrum.json") as f:
            spec = json.load(f)
        assert self.data["E5"]["E9"] == spec["E5"][2]


# ===================================================================
# Tests — Counterexamples
# ===================================================================

class TestCounterexamples:
    @pytest.fixture(autouse=True)
    def load(self):
        with open(f"{RESULTS_DIR}/counterexamples.json") as f:
            self.data = json.load(f)

    def test_no_counterexample_for_true_implications(self):
        for ei, targets in EXPECTED_IMPLICATIONS.items():
            for ej in targets:
                if ei != ej:
                    key = f"{ei}->{ej}"
                    assert key not in self.data, (
                        f"{key} should not appear (implication holds)"
                    )

    def test_counterexample_count(self):
        # 10 equations, 90 non-self pairs, 2 true non-self implications
        # (E2->E8, E5->E9), so 90 - 2 = 88 counterexamples
        assert len(self.data) == 88, (
            f"Expected 88 counterexamples, got {len(self.data)}"
        )

    def test_counterexamples_are_valid(self):
        """Each CE table must satisfy the source equation and violate the target."""
        for key, val in self.data.items():
            src_str, tgt_str = key.split("->")
            src_idx = int(src_str[1:])
            tgt_idx = int(tgt_str[1:])
            table = val["table"]
            order = val["order"]
            assert len(table) == order, f"{key}: table size mismatch"
            assert all(len(row) == order for row in table), f"{key}: row length mismatch"
            assert all(
                0 <= table[r][c] < order
                for r in range(order) for c in range(order)
            ), f"{key}: element out of range"
            assert _check(table, src_idx), (
                f"{key}: table does not satisfy {src_str}"
            )
            assert not _check(table, tgt_idx), (
                f"{key}: table should NOT satisfy {tgt_str}"
            )

    def test_selected_smallest_orders(self):
        for key, expected_order in EXPECTED_CE_ORDERS.items():
            assert key in self.data, f"Missing counterexample {key}"
            assert self.data[key]["order"] == expected_order, (
                f"{key}: expected smallest order {expected_order}, "
                f"got {self.data[key]['order']}"
            )


# ===================================================================
# Tests — Hasse (data)
# ===================================================================

class TestHasse:
    @pytest.fixture(autouse=True)
    def load(self):
        with open(f"{RESULTS_DIR}/hasse.json") as f:
            self.data = json.load(f)

    def test_all_keys_present(self):
        for eid in EQ_IDS:
            assert eid in self.data

    def test_hasse_correct(self):
        for eid, expected in EXPECTED_HASSE.items():
            assert sorted(self.data[eid]) == sorted(expected), (
                f"Hasse {eid}: got {sorted(self.data[eid])}, "
                f"expected {sorted(expected)}"
            )

    def test_hasse_subset_of_implications(self):
        with open(f"{RESULTS_DIR}/implications.json") as f:
            impl = json.load(f)
        for eid in EQ_IDS:
            for target in self.data[eid]:
                assert target in impl[eid], (
                    f"Hasse edge {eid}->{target} not in implications"
                )

    def test_no_self_loops(self):
        for eid in EQ_IDS:
            assert eid not in self.data[eid], f"Hasse should have no self-loop for {eid}"

    def test_e2_directly_implies_e8(self):
        assert "E8" in self.data["E2"]

    def test_e5_has_one_direct_target(self):
        assert len(self.data["E5"]) == 1, (
            f"E5 should have exactly 1 direct Hasse target (E9), "
            f"got {self.data['E5']}"
        )


# ===================================================================
# Tests — Duality
# ===================================================================

class TestDuality:
    @pytest.fixture(autouse=True)
    def load(self):
        with open(f"{RESULTS_DIR}/duality.json") as f:
            self.data = json.load(f)

    def test_all_keys_present(self):
        for eid in EQ_IDS:
            assert eid in self.data, f"Missing duality entry for {eid}"

    def test_has_required_fields(self):
        for eid in EQ_IDS:
            assert "dual_id" in self.data[eid], f"{eid} missing dual_id"
            assert "self_dual" in self.data[eid], f"{eid} missing self_dual"

    def test_self_dual_equations(self):
        for eid in ["E0", "E1", "E2", "E8", "E9"]:
            assert self.data[eid]["self_dual"] is True, (
                f"{eid} should be self-dual"
            )
            assert self.data[eid]["dual_id"] == eid, (
                f"{eid} self-dual but dual_id is {self.data[eid]['dual_id']}"
            )

    def test_non_self_dual_equations(self):
        for eid in ["E3", "E4", "E5", "E6", "E7"]:
            assert self.data[eid]["self_dual"] is False, (
                f"{eid} should NOT be self-dual"
            )

    def test_e3_e4_are_duals(self):
        assert self.data["E3"]["dual_id"] == "E4"
        assert self.data["E4"]["dual_id"] == "E3"

    def test_e6_e7_are_duals(self):
        assert self.data["E6"]["dual_id"] == "E7"
        assert self.data["E7"]["dual_id"] == "E6"

    def test_e5_dual_not_in_set(self):
        assert self.data["E5"]["dual_id"] is None, (
            f"E5's dual should not match any equation in the set, "
            f"got dual_id={self.data['E5']['dual_id']}"
        )

    def test_duality_is_involutive(self):
        """If dual_id is not null, applying duality twice returns to the original."""
        for eid in EQ_IDS:
            did = self.data[eid]["dual_id"]
            if did is not None:
                assert self.data[did]["dual_id"] == eid, (
                    f"Duality not involutive: dual({eid})={did}, "
                    f"dual({did})={self.data[did]['dual_id']}"
                )

    def test_dual_pairs_have_same_spectrum(self):
        """Dual equations have the same spectrum (dual magmas biject)."""
        with open(f"{RESULTS_DIR}/spectrum.json") as f:
            spec = json.load(f)
        for eid in EQ_IDS:
            did = self.data[eid]["dual_id"]
            if did is not None and did != eid:
                assert spec[eid] == spec[did], (
                    f"Dual pair ({eid}, {did}) should have equal spectra: "
                    f"{spec[eid]} vs {spec[did]}"
                )


# ===================================================================
# Tests — Hasse DOT file
# ===================================================================

class TestHasseDot:
    @pytest.fixture(autouse=True)
    def load(self):
        with open(f"{RESULTS_DIR}/hasse.dot") as f:
            self.content = f.read()

    def test_is_digraph(self):
        assert "digraph" in self.content.lower(), "DOT file must define a digraph"

    def test_all_equation_ids_present(self):
        for eid in EQ_IDS:
            assert eid in self.content, f"Node {eid} not found in DOT file"

    def test_expected_edges_present(self):
        for src, tgts in EXPECTED_HASSE.items():
            for tgt in tgts:
                patterns = [
                    f"{src} -> {tgt}",
                    f'"{src}" -> "{tgt}"',
                    f"{src}->{tgt}",
                    f'"{src}"->"{tgt}"',
                ]
                found = any(p in self.content for p in patterns)
                assert found, f"Edge {src} -> {tgt} not found in DOT file"

    def test_edge_count(self):
        edge_lines = [
            line.strip() for line in self.content.split('\n')
            if '->' in line and 'digraph' not in line.lower()
            and not line.strip().startswith('//')
            and not line.strip().startswith('#')
        ]
        assert len(edge_lines) == 2, (
            f"Expected 2 Hasse edges in DOT file, found {len(edge_lines)}"
        )

    def test_no_self_loop_edges(self):
        for eid in EQ_IDS:
            patterns = [
                f"{eid} -> {eid}",
                f'"{eid}" -> "{eid}"',
                f"{eid}->{eid}",
            ]
            for p in patterns:
                assert p not in self.content, (
                    f"Self-loop edge for {eid} found in DOT file"
                )


# ===================================================================
# Tests — Hasse SVG
# ===================================================================

class TestHasseSvg:
    def test_svg_exists_and_nonempty(self):
        path = os.path.join(RESULTS_DIR, "hasse.svg")
        assert os.path.isfile(path), "hasse.svg does not exist"
        size = os.path.getsize(path)
        assert size > 200, f"hasse.svg too small ({size} bytes), likely invalid"

    def test_svg_contains_svg_tag(self):
        with open(f"{RESULTS_DIR}/hasse.svg") as f:
            content = f.read()
        assert "<svg" in content.lower(), "hasse.svg does not contain <svg> tag"

    def test_svg_contains_equation_labels(self):
        with open(f"{RESULTS_DIR}/hasse.svg") as f:
            content = f.read()
        for eid in EQ_IDS:
            assert eid in content, (
                f"Equation {eid} label not found in rendered SVG"
            )


# ===================================================================
# Tests — Lattice Properties
# ===================================================================

class TestLatticeProperties:
    @pytest.fixture(autouse=True)
    def load(self):
        with open(f"{RESULTS_DIR}/lattice_properties.json") as f:
            self.data = json.load(f)

    def test_has_required_fields(self):
        for field in ["width", "height", "num_maximal", "num_minimal",
                      "num_connected_components"]:
            assert field in self.data, f"Missing field: {field}"

    def test_width(self):
        assert self.data["width"] == EXPECTED_LATTICE["width"], (
            f"Width: got {self.data['width']}, expected {EXPECTED_LATTICE['width']}"
        )

    def test_height(self):
        assert self.data["height"] == EXPECTED_LATTICE["height"], (
            f"Height: got {self.data['height']}, expected {EXPECTED_LATTICE['height']}"
        )

    def test_num_maximal(self):
        assert self.data["num_maximal"] == EXPECTED_LATTICE["num_maximal"], (
            f"Maximal: got {self.data['num_maximal']}, "
            f"expected {EXPECTED_LATTICE['num_maximal']}"
        )

    def test_num_minimal(self):
        assert self.data["num_minimal"] == EXPECTED_LATTICE["num_minimal"], (
            f"Minimal: got {self.data['num_minimal']}, "
            f"expected {EXPECTED_LATTICE['num_minimal']}"
        )

    def test_num_connected_components(self):
        assert self.data["num_connected_components"] == \
            EXPECTED_LATTICE["num_connected_components"], (
            f"Components: got {self.data['num_connected_components']}, "
            f"expected {EXPECTED_LATTICE['num_connected_components']}"
        )

    def test_width_geq_height_plus_one(self):
        """Sanity: width >= 1 and height >= 0."""
        assert self.data["width"] >= 1
        assert self.data["height"] >= 0

    def test_maximal_plus_minimal_consistency(self):
        """Isolated nodes are both maximal and minimal."""
        n = len(EQ_IDS)
        assert self.data["num_maximal"] <= n
        assert self.data["num_minimal"] <= n
