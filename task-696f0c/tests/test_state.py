"""
Tests for graph chromatic number certification with formal optimality proofs.
"""

import json
import os
import subprocess

import pytest

GRAPHS = {
    "graph_a": {"chi": 3, "n": 10, "m": 15},
    "graph_b": {"chi": 4, "n": 11, "m": 20},
    "graph_c": {"chi": 5, "n": 23, "m": 71},
}


def _read_graph(path):
    with open(path) as f:
        n, m = map(int, f.readline().split())
        edges = []
        for _ in range(m):
            parts = f.readline().split()
            edges.append((int(parts[0]), int(parts[1])))
    return n, m, edges


@pytest.fixture(params=list(GRAPHS.keys()))
def graph_info(request):
    name = request.param
    meta = GRAPHS[name]
    gpath = f"/app/instances/{name}.edgelist"
    rdir = f"/app/results/{name}"
    n, m, edges = _read_graph(gpath)
    assert n == meta["n"] and m == meta["m"]
    return {
        "name": name,
        "n": n,
        "m": m,
        "edges": edges,
        "result_dir": rdir,
        "chi": meta["chi"],
    }


# ---------------------------------------------------------------------------
# Chromatic number tests
# ---------------------------------------------------------------------------


class TestChromaticNumber:
    def test_file_exists(self, graph_info):
        p = os.path.join(graph_info["result_dir"], "chromatic_number.txt")
        assert os.path.isfile(p), f"Missing {p}"

    def test_value_correct(self, graph_info):
        p = os.path.join(graph_info["result_dir"], "chromatic_number.txt")
        chi = int(open(p).read().strip())
        assert chi == graph_info["chi"], (
            f"{graph_info['name']}: expected chi={graph_info['chi']}, got {chi}"
        )


# ---------------------------------------------------------------------------
# Coloring validity tests
# ---------------------------------------------------------------------------


class TestColoring:
    def _load(self, graph_info):
        p = os.path.join(graph_info["result_dir"], "coloring.json")
        assert os.path.isfile(p), f"Missing {p}"
        return json.load(open(p))

    def test_all_vertices_present(self, graph_info):
        col = self._load(graph_info)
        for v in range(graph_info["n"]):
            assert str(v) in col, f"Vertex {v} missing from coloring"

    def test_no_edge_conflicts(self, graph_info):
        col = self._load(graph_info)
        for u, v in graph_info["edges"]:
            assert col[str(u)] != col[str(v)], (
                f"Adjacent vertices {u} and {v} share color {col[str(u)]}"
            )

    def test_uses_at_most_chi_colors(self, graph_info):
        col = self._load(graph_info)
        k = len(set(col.values()))
        assert k <= graph_info["chi"], (
            f"Uses {k} colors, expected at most {graph_info['chi']}"
        )


# ---------------------------------------------------------------------------
# Unsatisfiability encoding tests
# ---------------------------------------------------------------------------


class TestUnsatEncoding:
    def test_file_exists(self, graph_info):
        p = os.path.join(graph_info["result_dir"], "unsat.cnf")
        assert os.path.isfile(p), f"Missing {p}"

    def test_valid_dimacs(self, graph_info):
        p = os.path.join(graph_info["result_dir"], "unsat.cnf")
        header = False
        nvars = 0
        nclauses_decl = 0
        nclauses_actual = 0
        with open(p) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("c"):
                    continue
                if line.startswith("p cnf"):
                    parts = line.split()
                    assert len(parts) == 4, f"Malformed header: {line}"
                    nvars = int(parts[2])
                    nclauses_decl = int(parts[3])
                    assert nvars > 0 and nclauses_decl > 0
                    header = True
                elif header:
                    lits = list(map(int, line.split()))
                    assert lits[-1] == 0, f"Clause not terminated by 0: {line}"
                    for lit in lits[:-1]:
                        assert 1 <= abs(lit) <= nvars, (
                            f"Variable {abs(lit)} out of range [1,{nvars}]"
                        )
                    nclauses_actual += 1
        assert header, "No 'p cnf' header found"
        assert nclauses_actual == nclauses_decl, (
            f"Declared {nclauses_decl} clauses, found {nclauses_actual}"
        )

    def test_variable_count_plausible(self, graph_info):
        """The encoding for (chi-1)-coloring needs at least n*(chi-1) variables."""
        p = os.path.join(graph_info["result_dir"], "unsat.cnf")
        n = graph_info["n"]
        k = graph_info["chi"] - 1
        with open(p) as f:
            for line in f:
                if line.startswith("p cnf"):
                    nvars = int(line.split()[2])
                    assert nvars >= n * k, (
                        f"Expected >= {n * k} vars for {k}-coloring "
                        f"of {n} vertices, got {nvars}"
                    )
                    return
        pytest.fail("No header found")


# ---------------------------------------------------------------------------
# Refutation certificate tests
# ---------------------------------------------------------------------------


class TestRefutationCertificate:
    def test_proof_file_exists(self, graph_info):
        p = os.path.join(graph_info["result_dir"], "proof.drat")
        assert os.path.isfile(p), f"Missing {p}"
        assert os.path.getsize(p) > 0, "Proof file is empty"

    def test_verified_status_file(self, graph_info):
        p = os.path.join(graph_info["result_dir"], "proof_verified.txt")
        assert os.path.isfile(p), f"Missing {p}"
        status = open(p).read().strip()
        assert status == "VERIFIED", f"Expected VERIFIED, got: {status}"

    def test_independent_verification(self, graph_info):
        """Run drat-trim independently to cross-check the refutation."""
        cnf = os.path.join(graph_info["result_dir"], "unsat.cnf")
        prf = os.path.join(graph_info["result_dir"], "proof.drat")
        if not os.path.isfile("/usr/local/bin/drat-trim"):
            pytest.skip("drat-trim not available for independent check")
        result = subprocess.run(
            ["/usr/local/bin/drat-trim", cnf, prf],
            capture_output=True,
            text=True,
            timeout=120,
        )
        combined = result.stdout + result.stderr
        assert "VERIFIED" in combined, (
            f"Independent verification failed:\n{combined[:800]}"
        )
