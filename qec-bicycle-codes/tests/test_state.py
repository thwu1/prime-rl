
"""
Tests for Bivariate Bicycle Code Analysis and Circuit Synthesis task.
Independently constructs codes and verifies reported parameters,
circuit files, detector error models, and matching decoder properties.
"""

import json
import os
import numpy as np
import pytest
import stim
import pymatching


# Known parameters from Bravyi et al., Nature 627, 778-782 (2024)
EXPECTED = {
    "BB_72": {"n": 72, "k": 12, "d": 6, "l": 6, "m": 6},
    "BB_90": {"n": 90, "k": 8, "d": 10, "l": 15, "m": 3},
}


# --------------- GF(2) helpers (independent of solution) ---------------

def _perm_matrix(l, m, a, b):
    N = l * m
    mat = np.zeros((N, N), dtype=np.uint8)
    for i in range(l):
        for j in range(m):
            src = i * m + j
            dst = ((i + a) % l) * m + ((j + b) % m)
            mat[dst, src] = 1
    return mat


def _group_element(l, m, terms):
    N = l * m
    mat = np.zeros((N, N), dtype=np.uint8)
    for a, b in terms:
        mat = (mat + _perm_matrix(l, m, a, b)) % 2
    return mat


def _gf2_rank(M):
    M = np.array(M, dtype=np.int32).copy() % 2
    rows, cols = M.shape
    rank = 0
    for col in range(cols):
        pivot = None
        for r in range(rank, rows):
            if M[r, col] == 1:
                pivot = r
                break
        if pivot is None:
            continue
        M[[rank, pivot]] = M[[pivot, rank]]
        for r in range(rows):
            if r != rank and M[r, col] == 1:
                M[r] = (M[r] + M[rank]) % 2
        rank += 1
    return rank


def _build_code(spec):
    l, m = spec["l"], spec["m"]
    A = _group_element(l, m, spec["A_terms"])
    B = _group_element(l, m, spec["B_terms"])
    Hx = np.hstack([A, B]).astype(np.uint8)
    Hz = np.hstack([B.T, A.T]).astype(np.uint8)
    return Hx, Hz


# --------------- Load data ---------------

def _load_results():
    with open("/app/results.json") as f:
        return json.load(f)


def _load_codes():
    with open("/app/codes.json") as f:
        return json.load(f)


def _get_spec(name):
    codes = _load_codes()
    for c in codes["codes"]:
        if c["name"] == name:
            return c
    return None


# --------------- Structural tests ---------------

class TestResultsFileStructure:
    def test_results_file_exists(self):
        assert os.path.isfile("/app/results.json"), "results.json not found"

    def test_results_valid_json(self):
        results = _load_results()
        assert isinstance(results, dict)

    def test_all_codes_present(self):
        results = _load_results()
        for name in EXPECTED:
            assert name in results, f"Missing code entry: {name}"

    def test_best_encoding_rate_key(self):
        results = _load_results()
        assert "best_encoding_rate" in results, "Missing best_encoding_rate"

    def test_required_fields(self):
        results = _load_results()
        required = [
            "n", "k", "d", "css_valid", "hx_rank", "hz_rank",
            "rank_symmetric", "encoding_rate", "check_weight",
            "matching_nodes", "matching_edges",
        ]
        for name in EXPECTED:
            for field in required:
                assert field in results[name], f"{name} missing field: {field}"


# --------------- BB_72 [[72, 12, 6]] ---------------

class TestBB72Parameters:
    def test_n(self):
        r = _load_results()["BB_72"]
        assert r["n"] == 72, f"Expected n=72, got {r['n']}"

    def test_k(self):
        r = _load_results()["BB_72"]
        assert r["k"] == 12, f"Expected k=12, got {r['k']}"

    def test_d(self):
        r = _load_results()["BB_72"]
        assert r["d"] == 6, f"Expected d=6, got {r['d']}"

    def test_css_valid(self):
        r = _load_results()["BB_72"]
        assert r["css_valid"] is True, "CSS condition must be True"

    def test_rank_consistency(self):
        r = _load_results()["BB_72"]
        assert r["hx_rank"] + r["hz_rank"] + r["k"] == r["n"], (
            f"Rank consistency failed: {r['hx_rank']}+{r['hz_rank']}+{r['k']} != {r['n']}"
        )

    def test_encoding_rate(self):
        r = _load_results()["BB_72"]
        expected_rate = 12.0 / 72.0
        assert abs(r["encoding_rate"] - expected_rate) < 1e-4, (
            f"Expected rate ~{expected_rate:.4f}, got {r['encoding_rate']}"
        )

    def test_rank_symmetric(self):
        r = _load_results()["BB_72"]
        assert r["rank_symmetric"] is True, "BB code ranks should be equal"
        assert r["hx_rank"] == r["hz_rank"], (
            f"Ranks not equal: {r['hx_rank']} != {r['hz_rank']}"
        )

    def test_check_weight(self):
        r = _load_results()["BB_72"]
        assert r["check_weight"] == 6, f"Expected check_weight=6, got {r['check_weight']}"


# --------------- BB_90 [[90, 8, 10]] ---------------

class TestBB90Parameters:
    def test_n(self):
        r = _load_results()["BB_90"]
        assert r["n"] == 90, f"Expected n=90, got {r['n']}"

    def test_k(self):
        r = _load_results()["BB_90"]
        assert r["k"] == 8, f"Expected k=8, got {r['k']}"

    def test_d(self):
        r = _load_results()["BB_90"]
        assert r["d"] == 10, f"Expected d=10, got {r['d']}"

    def test_css_valid(self):
        r = _load_results()["BB_90"]
        assert r["css_valid"] is True, "CSS condition must be True"

    def test_rank_consistency(self):
        r = _load_results()["BB_90"]
        assert r["hx_rank"] + r["hz_rank"] + r["k"] == r["n"], (
            f"Rank consistency failed: {r['hx_rank']}+{r['hz_rank']}+{r['k']} != {r['n']}"
        )

    def test_encoding_rate(self):
        r = _load_results()["BB_90"]
        expected_rate = 8.0 / 90.0
        assert abs(r["encoding_rate"] - expected_rate) < 1e-4, (
            f"Expected rate ~{expected_rate:.4f}, got {r['encoding_rate']}"
        )

    def test_rank_symmetric(self):
        r = _load_results()["BB_90"]
        assert r["rank_symmetric"] is True, "BB code ranks should be equal"
        assert r["hx_rank"] == r["hz_rank"], (
            f"Ranks not equal: {r['hx_rank']} != {r['hz_rank']}"
        )

    def test_check_weight(self):
        r = _load_results()["BB_90"]
        assert r["check_weight"] == 6, f"Expected check_weight=6, got {r['check_weight']}"


# --------------- Independent verification ---------------

class TestIndependentConstruction:
    """Build codes from scratch and verify n, k, CSS condition."""

    def test_bb72_n_independent(self):
        spec = _get_spec("BB_72")
        Hx, Hz = _build_code(spec)
        assert Hx.shape[1] == 72

    def test_bb72_css_independent(self):
        spec = _get_spec("BB_72")
        Hx, Hz = _build_code(spec)
        product = (Hx.astype(np.int32) @ Hz.T.astype(np.int32)) % 2
        assert np.all(product == 0), "CSS condition failed for BB_72"

    def test_bb72_k_independent(self):
        spec = _get_spec("BB_72")
        Hx, Hz = _build_code(spec)
        n = Hx.shape[1]
        rx = _gf2_rank(Hx)
        rz = _gf2_rank(Hz)
        k = n - rx - rz
        assert k == 12, f"Independent k computation: expected 12, got {k}"

    def test_bb90_n_independent(self):
        spec = _get_spec("BB_90")
        Hx, Hz = _build_code(spec)
        assert Hx.shape[1] == 90

    def test_bb90_css_independent(self):
        spec = _get_spec("BB_90")
        Hx, Hz = _build_code(spec)
        product = (Hx.astype(np.int32) @ Hz.T.astype(np.int32)) % 2
        assert np.all(product == 0), "CSS condition failed for BB_90"

    def test_bb90_k_independent(self):
        spec = _get_spec("BB_90")
        Hx, Hz = _build_code(spec)
        n = Hx.shape[1]
        rx = _gf2_rank(Hx)
        rz = _gf2_rank(Hz)
        k = n - rx - rz
        assert k == 8, f"Independent k computation: expected 8, got {k}"

    def test_bb72_matrix_dimensions(self):
        spec = _get_spec("BB_72")
        Hx, Hz = _build_code(spec)
        l, m = spec["l"], spec["m"]
        N = l * m
        assert Hx.shape == (N, 2 * N), f"Hx shape: expected ({N},{2*N}), got {Hx.shape}"
        assert Hz.shape == (N, 2 * N), f"Hz shape: expected ({N},{2*N}), got {Hz.shape}"

    def test_bb90_matrix_dimensions(self):
        spec = _get_spec("BB_90")
        Hx, Hz = _build_code(spec)
        l, m = spec["l"], spec["m"]
        N = l * m
        assert Hx.shape == (N, 2 * N), f"Hx shape: expected ({N},{2*N}), got {Hx.shape}"
        assert Hz.shape == (N, 2 * N), f"Hz shape: expected ({N},{2*N}), got {Hz.shape}"

    def test_bb72_row_weights(self):
        """Each row of Hx should have weight 6 (3 from A + 3 from B)."""
        spec = _get_spec("BB_72")
        Hx, _ = _build_code(spec)
        row_weights = np.sum(Hx, axis=1)
        assert np.all(row_weights == 6), (
            f"BB_72 Hx row weights should all be 6, got unique: {np.unique(row_weights)}"
        )

    def test_bb90_row_weights(self):
        """Each row of Hx should have weight 6 (3 from A + 3 from B)."""
        spec = _get_spec("BB_90")
        Hx, _ = _build_code(spec)
        row_weights = np.sum(Hx, axis=1)
        assert np.all(row_weights == 6), (
            f"BB_90 Hx row weights should all be 6, got unique: {np.unique(row_weights)}"
        )


# --------------- Best encoding rate ---------------

class TestBestEncodingRate:
    def test_correct_best(self):
        results = _load_results()
        rates = {}
        for name in EXPECTED:
            rates[name] = results[name]["encoding_rate"]
        expected_best = max(rates, key=rates.get)
        assert results["best_encoding_rate"] == expected_best, (
            f"Expected best={expected_best}, got {results['best_encoding_rate']}"
        )

    def test_bb72_has_higher_rate(self):
        """BB_72 (k/n=12/72=1/6) should beat BB_90 (k/n=8/90~0.089)."""
        results = _load_results()
        assert results["BB_72"]["encoding_rate"] > results["BB_90"]["encoding_rate"]


# --------------- Circuit files ---------------

class TestCircuitFiles:
    def test_bb72_circuit_exists(self):
        assert os.path.isfile("/app/circuits/BB_72.stim"), "BB_72 circuit file missing"

    def test_bb90_circuit_exists(self):
        assert os.path.isfile("/app/circuits/BB_90.stim"), "BB_90 circuit file missing"

    def test_bb72_circuit_parseable(self):
        with open("/app/circuits/BB_72.stim") as f:
            circuit = stim.Circuit(f.read())
        assert circuit.num_qubits > 0, "Circuit has no qubits"

    def test_bb90_circuit_parseable(self):
        with open("/app/circuits/BB_90.stim") as f:
            circuit = stim.Circuit(f.read())
        assert circuit.num_qubits > 0, "Circuit has no qubits"

    def test_bb72_circuit_has_detectors(self):
        with open("/app/circuits/BB_72.stim") as f:
            circuit = stim.Circuit(f.read())
        assert circuit.num_detectors > 0, "Circuit has no DETECTOR annotations"

    def test_bb90_circuit_has_detectors(self):
        with open("/app/circuits/BB_90.stim") as f:
            circuit = stim.Circuit(f.read())
        assert circuit.num_detectors > 0, "Circuit has no DETECTOR annotations"

    def test_bb72_circuit_has_observables(self):
        with open("/app/circuits/BB_72.stim") as f:
            circuit = stim.Circuit(f.read())
        assert circuit.num_observables > 0, "Circuit has no OBSERVABLE_INCLUDE"

    def test_bb90_circuit_has_observables(self):
        with open("/app/circuits/BB_90.stim") as f:
            circuit = stim.Circuit(f.read())
        assert circuit.num_observables > 0, "Circuit has no OBSERVABLE_INCLUDE"

    def test_bb72_circuit_has_noise(self):
        with open("/app/circuits/BB_72.stim") as f:
            content = f.read()
        has_noise = any(kw in content for kw in [
            "DEPOLARIZE", "X_ERROR", "Z_ERROR", "Y_ERROR", "PAULI_CHANNEL"
        ])
        assert has_noise, "Circuit has no noise operations"

    def test_bb90_circuit_has_noise(self):
        with open("/app/circuits/BB_90.stim") as f:
            content = f.read()
        has_noise = any(kw in content for kw in [
            "DEPOLARIZE", "X_ERROR", "Z_ERROR", "Y_ERROR", "PAULI_CHANNEL"
        ])
        assert has_noise, "Circuit has no noise operations"


# --------------- Detector error model files ---------------

class TestDEMFiles:
    def test_bb72_dem_exists(self):
        assert os.path.isfile("/app/dem/BB_72.dem"), "BB_72 DEM file missing"

    def test_bb90_dem_exists(self):
        assert os.path.isfile("/app/dem/BB_90.dem"), "BB_90 DEM file missing"

    def test_bb72_dem_parseable(self):
        with open("/app/dem/BB_72.dem") as f:
            dem = stim.DetectorErrorModel(f.read())
        assert dem.num_detectors > 0, "DEM has no detectors"

    def test_bb90_dem_parseable(self):
        with open("/app/dem/BB_90.dem") as f:
            dem = stim.DetectorErrorModel(f.read())
        assert dem.num_detectors > 0, "DEM has no detectors"

    def test_bb72_dem_has_errors(self):
        with open("/app/dem/BB_72.dem") as f:
            dem = stim.DetectorErrorModel(f.read())
        assert dem.num_errors > 0, "DEM has no error mechanisms"

    def test_bb90_dem_has_errors(self):
        with open("/app/dem/BB_90.dem") as f:
            dem = stim.DetectorErrorModel(f.read())
        assert dem.num_errors > 0, "DEM has no error mechanisms"


# --------------- Matching decoder ---------------

class TestMatchingDecoder:
    def test_bb72_matching_nodes_positive(self):
        r = _load_results()["BB_72"]
        assert isinstance(r["matching_nodes"], int)
        assert r["matching_nodes"] > 0, "matching_nodes must be positive"

    def test_bb90_matching_nodes_positive(self):
        r = _load_results()["BB_90"]
        assert isinstance(r["matching_nodes"], int)
        assert r["matching_nodes"] > 0, "matching_nodes must be positive"

    def test_bb72_matching_edges_positive(self):
        r = _load_results()["BB_72"]
        assert isinstance(r["matching_edges"], int)
        assert r["matching_edges"] > 0, "matching_edges must be positive"

    def test_bb90_matching_edges_positive(self):
        r = _load_results()["BB_90"]
        assert isinstance(r["matching_edges"], int)
        assert r["matching_edges"] > 0, "matching_edges must be positive"

    def test_bb72_matching_consistency(self):
        """Independently construct matching from saved DEM and verify properties match."""
        with open("/app/dem/BB_72.dem") as f:
            dem = stim.DetectorErrorModel(f.read())
        matching = pymatching.Matching.from_detector_error_model(dem)
        r = _load_results()["BB_72"]
        assert r["matching_nodes"] == matching.num_nodes, (
            f"matching_nodes mismatch: reported {r['matching_nodes']}, computed {matching.num_nodes}"
        )
        assert r["matching_edges"] == matching.num_edges, (
            f"matching_edges mismatch: reported {r['matching_edges']}, computed {matching.num_edges}"
        )

    def test_bb90_matching_consistency(self):
        """Independently construct matching from saved DEM and verify properties match."""
        with open("/app/dem/BB_90.dem") as f:
            dem = stim.DetectorErrorModel(f.read())
        matching = pymatching.Matching.from_detector_error_model(dem)
        r = _load_results()["BB_90"]
        assert r["matching_nodes"] == matching.num_nodes, (
            f"matching_nodes mismatch: reported {r['matching_nodes']}, computed {matching.num_nodes}"
        )
        assert r["matching_edges"] == matching.num_edges, (
            f"matching_edges mismatch: reported {r['matching_edges']}, computed {matching.num_edges}"
        )
