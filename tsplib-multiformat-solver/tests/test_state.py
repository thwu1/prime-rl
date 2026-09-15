"""
Tests for TSPLIB95 benchmark verification.

"""
import json
import math
import os
import pytest


@pytest.fixture(scope="module")
def results():
    path = "/app/results.json"
    assert os.path.exists(path), "results.json not found at /app/results.json"
    with open(path) as f:
        data = json.load(f)
    return data


# ── br17 ATSP exact solve ──────────────────────────────────────────────

def _load_br17_matrix():
    """Independently load and parse the br17 distance matrix."""
    with open("/app/instances/br17.atsp") as f:
        lines = f.readlines()
    in_section = False
    values = []
    for line in lines:
        stripped = line.strip()
        if stripped == "EDGE_WEIGHT_SECTION":
            in_section = True
            continue
        if stripped == "EOF":
            break
        if in_section:
            values.extend(int(x) for x in stripped.split())
    n = 17
    matrix = []
    for i in range(n):
        row = values[i * n : (i + 1) * n]
        matrix.append(row)
    return matrix


def test_br17_optimal_cost(results):
    assert "br17_optimal_cost" in results, "Missing key: br17_optimal_cost"
    assert results["br17_optimal_cost"] == 39


def test_br17_optimal_tour_valid(results):
    assert "br17_optimal_tour" in results, "Missing key: br17_optimal_tour"
    tour = results["br17_optimal_tour"]
    assert isinstance(tour, list)
    assert sorted(tour) == list(range(1, 18)), \
        "br17_optimal_tour must be a permutation of [1..17]"


def test_br17_optimal_tour_cost(results):
    tour = results["br17_optimal_tour"]
    matrix = _load_br17_matrix()
    cost = 0
    for i in range(len(tour)):
        u = tour[i] - 1
        v = tour[(i + 1) % len(tour)] - 1
        cost += matrix[u][v]
    assert cost == 39, f"Tour cost is {cost}, expected 39"


# ── berlin52 tour validation ───────────────────────────────────────────

def test_berlin52_tour_cost(results):
    assert "berlin52_tour_cost" in results, "Missing key: berlin52_tour_cost"
    assert results["berlin52_tour_cost"] == 7542


# ── att48 ATT distance function ────────────────────────────────────────

def test_att48_distance_1_2(results):
    assert "att48_distance_1_2" in results
    assert results["att48_distance_1_2"] == 1495


def test_att48_distance_2_3(results):
    assert "att48_distance_2_3" in results
    assert results["att48_distance_2_3"] == 1135


def test_att48_distance_6_7(results):
    assert "att48_distance_6_7" in results
    assert results["att48_distance_6_7"] == 235


def test_att48_nn_cost(results):
    assert "att48_nn_cost" in results
    assert results["att48_nn_cost"] == 12861


# ── eil13 explicit distance matrix ────────────────────────────────────

def test_eil13_distance_1_2(results):
    assert "eil13_distance_1_2" in results
    assert results["eil13_distance_1_2"] == 9


def test_eil13_distance_1_13(results):
    assert "eil13_distance_1_13" in results
    assert results["eil13_distance_1_13"] == 52


def test_eil13_distance_6_7(results):
    assert "eil13_distance_6_7" in results
    assert results["eil13_distance_6_7"] == 9


def test_eil13_distance_7_8(results):
    assert "eil13_distance_7_8" in results
    assert results["eil13_distance_7_8"] == 7


# ── eil13 CVRP analysis ───────────────────────────────────────────────

def test_eil13_min_vehicles(results):
    assert "eil13_min_vehicles" in results
    assert results["eil13_min_vehicles"] == 4


def test_eil13_tsp_optimal(results):
    assert "eil13_tsp_optimal" in results
    assert results["eil13_tsp_optimal"] == 142
