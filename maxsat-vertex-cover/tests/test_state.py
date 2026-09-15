
import json
import os
import pytest

# ---- Known optimal values ----

GRAPH_OPTIMAL = {
    "graph_a": 13,
    "graph_b": 21,
    "graph_c": 75,
}

MYSTERY_OPTIMAL = {
    "mystery_alpha": 10,
    "mystery_beta": 31,
}

INSTANCE_OPTIMAL = {
    "set_cover": 11,
    "graph_color": 3,
}

MYSTERY_GRAPHS = {
    "mystery_alpha": {
        "num_vertices": 8,
        "edges": sorted([[0,1],[0,3],[1,2],[1,4],[2,5],[3,4],[3,6],[4,5],[4,7],[5,7],[6,7]]),
        "weights": [6, 2, 8, 3, 5, 4, 7, 1],
    },
    "mystery_beta": {
        "num_vertices": 12,
        "edges": sorted([
            [0,1],[0,4],[0,8],[1,2],[1,5],[2,3],[2,6],[3,7],[3,11],
            [4,5],[4,8],[5,6],[5,9],[6,7],[6,10],[7,11],
            [8,9],[9,10],[10,11],[0,11],[1,9],[2,10],[3,8]
        ]),
        "weights": [5, 3, 8, 2, 7, 4, 6, 9, 1, 5, 3, 7],
    },
}


def load_graph(name):
    with open(f"/app/graphs/{name}.json") as f:
        return json.load(f)


def load_solution(name):
    with open(f"/app/solutions/{name}.json") as f:
        return json.load(f)


def is_valid_vertex_cover(vertices, edges):
    vc_set = set(vertices)
    for u, v in edges:
        if u not in vc_set and v not in vc_set:
            return False
    return True


def parse_wcnf(filepath):
    with open(filepath) as f:
        content = f.read()
    num_vars = 0
    num_clauses = 0
    top = 0
    hard_clauses = []
    soft_clauses = []
    for line in content.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("c"):
            continue
        if line.startswith("p"):
            parts = line.split()
            num_vars = int(parts[2])
            num_clauses = int(parts[3])
            top = int(parts[4])
            continue
        tokens = list(map(int, line.split()))
        weight = tokens[0]
        lits = tokens[1:-1]
        if weight >= top:
            hard_clauses.append(lits)
        else:
            soft_clauses.append((weight, lits))
    return num_vars, num_clauses, top, hard_clauses, soft_clauses


def clause_satisfied(clause, assignment):
    """Check if a clause is satisfied by a given truth assignment dict."""
    for lit in clause:
        var = abs(lit)
        val = assignment.get(var, False)
        if (lit > 0 and val) or (lit < 0 and not val):
            return True
    return False


# ========== Graph Encoding Tests ==========

class TestGraphEncodings:
    @pytest.mark.parametrize("name", ["graph_a", "graph_b", "graph_c"])
    def test_encoding_exists(self, name):
        assert os.path.exists(f"/app/encodings/{name}.wcnf"), (
            f"Encoding /app/encodings/{name}.wcnf not found"
        )

    @pytest.mark.parametrize("name", ["graph_a", "graph_b", "graph_c"])
    def test_wcnf_valid_format(self, name):
        num_vars, num_clauses, top, hard, soft = parse_wcnf(
            f"/app/encodings/{name}.wcnf"
        )
        assert num_vars > 0
        total = len(hard) + len(soft)
        assert num_clauses == total, (
            f"Header claims {num_clauses} clauses but found {total}"
        )
        assert top > 0
        sum_soft = sum(w for w, _ in soft)
        assert top > sum_soft, (
            f"Top weight {top} must exceed sum of soft weights {sum_soft}"
        )

    @pytest.mark.parametrize("name", ["graph_a", "graph_b", "graph_c"])
    def test_wcnf_variable_count_matches_graph(self, name):
        graph = load_graph(name)
        num_vars, _, _, _, _ = parse_wcnf(f"/app/encodings/{name}.wcnf")
        assert num_vars == graph["num_vertices"], (
            f"WCNF has {num_vars} vars but graph has {graph['num_vertices']} vertices"
        )

    @pytest.mark.parametrize("name", ["graph_a", "graph_b", "graph_c"])
    def test_wcnf_hard_clause_count_matches_edges(self, name):
        graph = load_graph(name)
        _, _, _, hard, _ = parse_wcnf(f"/app/encodings/{name}.wcnf")
        assert len(hard) == len(graph["edges"]), (
            f"Expected {len(graph['edges'])} hard clauses for edges, got {len(hard)}"
        )

    @pytest.mark.parametrize("name", ["graph_a", "graph_b", "graph_c"])
    def test_wcnf_soft_clause_count_matches_vertices(self, name):
        graph = load_graph(name)
        _, _, _, _, soft = parse_wcnf(f"/app/encodings/{name}.wcnf")
        assert len(soft) == graph["num_vertices"], (
            f"Expected {graph['num_vertices']} soft clauses for vertices, got {len(soft)}"
        )

    @pytest.mark.parametrize("name", ["graph_a", "graph_b", "graph_c"])
    def test_wcnf_variable_range(self, name):
        num_vars, _, _, hard, soft = parse_wcnf(f"/app/encodings/{name}.wcnf")
        for clause in hard:
            for lit in clause:
                assert 1 <= abs(lit) <= num_vars, f"Literal {lit} out of range"
        for _, clause in soft:
            for lit in clause:
                assert 1 <= abs(lit) <= num_vars, f"Literal {lit} out of range"


# ========== Graph Solution Tests ==========

class TestGraphSolutions:
    @pytest.mark.parametrize("name", ["graph_a", "graph_b", "graph_c"])
    def test_solution_exists(self, name):
        assert os.path.exists(f"/app/solutions/{name}.json"), (
            f"Solution /app/solutions/{name}.json not found"
        )

    @pytest.mark.parametrize("name", ["graph_a", "graph_b", "graph_c"])
    def test_vertices_no_duplicates(self, name):
        sol = load_solution(name)
        verts = sol["vertices"]
        assert len(verts) == len(set(verts)), "Duplicate vertices"

    @pytest.mark.parametrize("name", ["graph_a", "graph_b", "graph_c"])
    def test_vertices_in_range(self, name):
        graph = load_graph(name)
        sol = load_solution(name)
        assert all(0 <= v < graph["num_vertices"] for v in sol["vertices"]), (
            "Vertex index out of range"
        )

    @pytest.mark.parametrize("name", ["graph_a", "graph_b", "graph_c"])
    def test_valid_vertex_cover(self, name):
        graph = load_graph(name)
        sol = load_solution(name)
        assert is_valid_vertex_cover(sol["vertices"], graph["edges"]), (
            f"Solution for {name} is not a valid vertex cover"
        )

    @pytest.mark.parametrize("name", ["graph_a", "graph_b", "graph_c"])
    def test_weight_consistent(self, name):
        graph = load_graph(name)
        sol = load_solution(name)
        computed = sum(graph["weights"][v] for v in sol["vertices"])
        assert sol["weight"] == computed, (
            f"Reported weight {sol['weight']} != computed {computed}"
        )

    @pytest.mark.parametrize("name", ["graph_a", "graph_b", "graph_c"])
    def test_weight_optimal(self, name):
        sol = load_solution(name)
        assert sol["weight"] == GRAPH_OPTIMAL[name], (
            f"Weight {sol['weight']} != optimal {GRAPH_OPTIMAL[name]}"
        )


# ========== Mystery Instance Tests ==========

class TestMysterySolutions:
    @pytest.mark.parametrize("name", ["mystery_alpha", "mystery_beta"])
    def test_solution_exists(self, name):
        assert os.path.exists(f"/app/solutions/{name}.json"), (
            f"Solution /app/solutions/{name}.json not found"
        )

    @pytest.mark.parametrize("name", ["mystery_alpha", "mystery_beta"])
    def test_has_graph_field(self, name):
        sol = load_solution(name)
        assert "graph" in sol, "Missing 'graph' field"
        for key in ("num_vertices", "edges", "weights"):
            assert key in sol["graph"], f"Missing 'graph.{key}'"

    @pytest.mark.parametrize("name", ["mystery_alpha", "mystery_beta"])
    def test_num_vertices(self, name):
        sol = load_solution(name)
        expected = MYSTERY_GRAPHS[name]
        assert sol["graph"]["num_vertices"] == expected["num_vertices"]

    @pytest.mark.parametrize("name", ["mystery_alpha", "mystery_beta"])
    def test_edges_reconstruction(self, name):
        sol = load_solution(name)
        expected = MYSTERY_GRAPHS[name]
        reconstructed = sorted([sorted(e) for e in sol["graph"]["edges"]])
        assert reconstructed == expected["edges"], (
            "Reconstructed edges do not match"
        )

    @pytest.mark.parametrize("name", ["mystery_alpha", "mystery_beta"])
    def test_weights_reconstruction(self, name):
        sol = load_solution(name)
        expected = MYSTERY_GRAPHS[name]
        assert sol["graph"]["weights"] == expected["weights"], (
            f"Weights {sol['graph']['weights']} != expected {expected['weights']}"
        )

    @pytest.mark.parametrize("name", ["mystery_alpha", "mystery_beta"])
    def test_vertices_valid(self, name):
        sol = load_solution(name)
        n = MYSTERY_GRAPHS[name]["num_vertices"]
        verts = sol["vertices"]
        assert len(verts) == len(set(verts)), "Duplicate vertices"
        assert all(0 <= v < n for v in verts), "Vertex out of range"

    @pytest.mark.parametrize("name", ["mystery_alpha", "mystery_beta"])
    def test_valid_cover(self, name):
        sol = load_solution(name)
        expected = MYSTERY_GRAPHS[name]
        assert is_valid_vertex_cover(sol["vertices"], expected["edges"])

    @pytest.mark.parametrize("name", ["mystery_alpha", "mystery_beta"])
    def test_weight_consistent(self, name):
        sol = load_solution(name)
        expected = MYSTERY_GRAPHS[name]
        computed = sum(expected["weights"][v] for v in sol["vertices"])
        assert sol["weight"] == computed

    @pytest.mark.parametrize("name", ["mystery_alpha", "mystery_beta"])
    def test_weight_optimal(self, name):
        sol = load_solution(name)
        assert sol["weight"] == MYSTERY_OPTIMAL[name], (
            f"Weight {sol['weight']} != optimal {MYSTERY_OPTIMAL[name]}"
        )


# ========== Opaque Instance Tests ==========

class TestOpaqueSolutions:
    @pytest.mark.parametrize("name", ["set_cover", "graph_color"])
    def test_solution_exists(self, name):
        assert os.path.exists(f"/app/solutions/{name}.json"), (
            f"Solution /app/solutions/{name}.json not found"
        )

    @pytest.mark.parametrize("name", ["set_cover", "graph_color"])
    def test_has_required_fields(self, name):
        sol = load_solution(name)
        assert "cost" in sol, "Missing 'cost' field"
        assert "assignment" in sol, "Missing 'assignment' field"

    @pytest.mark.parametrize("name", ["set_cover", "graph_color"])
    def test_assignment_covers_all_variables(self, name):
        sol = load_solution(name)
        num_vars, _, _, _, _ = parse_wcnf(f"/app/instances/{name}.wcnf")
        assigned_vars = set(abs(x) for x in sol["assignment"])
        expected_vars = set(range(1, num_vars + 1))
        assert assigned_vars == expected_vars, (
            f"Assignment must cover all {num_vars} variables"
        )

    @pytest.mark.parametrize("name", ["set_cover", "graph_color"])
    def test_hard_clauses_satisfied(self, name):
        sol = load_solution(name)
        num_vars, _, _, hard, _ = parse_wcnf(f"/app/instances/{name}.wcnf")
        assignment = {}
        for lit in sol["assignment"]:
            var = abs(lit)
            assignment[var] = (lit > 0)
        for i, clause in enumerate(hard):
            assert clause_satisfied(clause, assignment), (
                f"Hard clause {i} unsatisfied: {clause}"
            )

    @pytest.mark.parametrize("name", ["set_cover", "graph_color"])
    def test_cost_consistent(self, name):
        sol = load_solution(name)
        _, _, _, _, soft = parse_wcnf(f"/app/instances/{name}.wcnf")
        assignment = {}
        for lit in sol["assignment"]:
            var = abs(lit)
            assignment[var] = (lit > 0)
        computed_cost = 0
        for weight, clause in soft:
            if not clause_satisfied(clause, assignment):
                computed_cost += weight
        assert sol["cost"] == computed_cost, (
            f"Reported cost {sol['cost']} != computed {computed_cost}"
        )

    @pytest.mark.parametrize("name", ["set_cover", "graph_color"])
    def test_cost_optimal(self, name):
        sol = load_solution(name)
        assert sol["cost"] == INSTANCE_OPTIMAL[name], (
            f"Cost {sol['cost']} != optimal {INSTANCE_OPTIMAL[name]}"
        )
