
import subprocess
import os
import glob


def parse_gr(text):
    """Parse a PACE .gr format graph. Returns (n, edges)."""
    n = 0
    edges = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("c"):
            continue
        if line.startswith("p"):
            parts = line.split()
            n = int(parts[2])
        else:
            parts = line.split()
            u, v = int(parts[0]), int(parts[1])
            edges.append((u, v))
    return n, edges


def verify_contraction_sequence(n, edges, sequence):
    """
    Simulate the contraction sequence on the trigraph and return
    (is_valid, width, error_message).

    Contraction of (x, y): y is removed, x inherits merged adjacencies.
    For each remaining z:
      - adjacent to both x and y: x-z keeps current color
      - adjacent to exactly one: x-z becomes/stays red
      - adjacent to neither: no edge
    """
    vertices = set(range(1, n + 1))
    black_adj = {v: set() for v in vertices}
    red_adj = {v: set() for v in vertices}
    for u, v in edges:
        black_adj[u].add(v)
        black_adj[v].add(u)

    max_red_deg = 0

    for step_idx, (x, y) in enumerate(sequence):
        if x not in vertices:
            return False, -1, f"Step {step_idx}: vertex {x} not present"
        if y not in vertices:
            return False, -1, f"Step {step_idx}: vertex {y} not present"
        if x == y:
            return False, -1, f"Step {step_idx}: self-contraction"

        x_neigh = (black_adj[x] | red_adj[x]) - {y}
        y_neigh = (black_adj[y] | red_adj[y]) - {x}

        new_black = set()
        new_red = set()

        for z in x_neigh:
            if z in y_neigh:
                # Adjacent to both: keep x's current color
                if z in black_adj[x]:
                    new_black.add(z)
                else:
                    new_red.add(z)
            else:
                # Adjacent to x only: red
                new_red.add(z)

        for z in y_neigh:
            if z not in x_neigh:
                # Adjacent to y only: new red
                new_red.add(z)

        # Remove y
        vertices.discard(y)
        del black_adj[y]
        del red_adj[y]
        for v in vertices:
            black_adj[v].discard(y)
            red_adj[v].discard(y)

        # Update x adjacencies
        black_adj[x] = new_black
        red_adj[x] = new_red

        for z in vertices:
            if z == x:
                continue
            black_adj[z].discard(x)
            red_adj[z].discard(x)
            if z in new_black:
                black_adj[z].add(x)
            elif z in new_red:
                red_adj[z].add(x)

        # Track maximum red degree
        for v in vertices:
            rd = len(red_adj[v])
            if rd > max_red_deg:
                max_red_deg = rd

    if len(vertices) != 1:
        return False, -1, f"Did not reduce to single vertex ({len(vertices)} remain)"

    return True, max_red_deg, ""


def parse_sequence(text, n):
    """Parse contraction sequence output."""
    seq = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("c"):
            continue
        parts = line.split()
        seq.append((int(parts[0]), int(parts[1])))
    assert len(seq) == n - 1, f"Expected {n - 1} contractions, got {len(seq)}"
    return seq


def run_solver(gr_text):
    """Run /app/solver on the given .gr text and return stdout."""
    result = subprocess.run(
        ["/app/solver"],
        input=gr_text,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"Solver exited with code {result.returncode}: {result.stderr[:500]}"
    )
    return result.stdout


def _check(gr_text, expected_tw, label):
    n, edges = parse_gr(gr_text)
    output = run_solver(gr_text)
    seq = parse_sequence(output, n)
    valid, width, err = verify_contraction_sequence(n, edges, seq)
    assert valid, f"{label}: invalid contraction sequence — {err}"
    assert width == expected_tw, (
        f"{label}: width {width} != expected optimal {expected_tw}"
    )


# Known optimal twinwidths for provided instances (opaque filenames)
INSTANCE_EXPECTED = {
    "instance_001": 0,   # K6 — complete graph
    "instance_002": 1,   # P10 — path
    "instance_003": 2,   # C9 — cycle
    "instance_004": 4,   # Petersen graph
    "instance_005": 2,   # 3x3 grid
    "instance_006": 2,   # triangular prism
    "instance_007": 1,   # P20 — path
    "instance_008": 2,   # C18 — cycle
}


class TestSolverExists:
    def test_solver_present(self):
        assert os.path.exists("/app/solver"), "/app/solver not found"

    def test_solver_executable(self):
        assert os.access("/app/solver", os.X_OK), "/app/solver is not executable"


class TestProvidedInstances:
    """Test solver on all provided benchmark instances."""

    def test_instance_001(self):
        with open("/app/instances/instance_001.gr") as f:
            _check(f.read(), INSTANCE_EXPECTED["instance_001"], "instance_001")

    def test_instance_002(self):
        with open("/app/instances/instance_002.gr") as f:
            _check(f.read(), INSTANCE_EXPECTED["instance_002"], "instance_002")

    def test_instance_003(self):
        with open("/app/instances/instance_003.gr") as f:
            _check(f.read(), INSTANCE_EXPECTED["instance_003"], "instance_003")

    def test_instance_004(self):
        with open("/app/instances/instance_004.gr") as f:
            _check(f.read(), INSTANCE_EXPECTED["instance_004"], "instance_004")

    def test_instance_005(self):
        with open("/app/instances/instance_005.gr") as f:
            _check(f.read(), INSTANCE_EXPECTED["instance_005"], "instance_005")

    def test_instance_006(self):
        with open("/app/instances/instance_006.gr") as f:
            _check(f.read(), INSTANCE_EXPECTED["instance_006"], "instance_006")

    def test_instance_007(self):
        with open("/app/instances/instance_007.gr") as f:
            _check(f.read(), INSTANCE_EXPECTED["instance_007"], "instance_007")

    def test_instance_008(self):
        with open("/app/instances/instance_008.gr") as f:
            _check(f.read(), INSTANCE_EXPECTED["instance_008"], "instance_008")


class TestGeneratedInstances:
    """Test solver on dynamically generated graphs not visible during development."""

    def test_triangle(self):
        gr = "p tww 3 3\n1 2\n2 3\n1 3\n"
        _check(gr, 0, "generated K3")

    def test_path_5(self):
        gr = "p tww 5 4\n1 2\n2 3\n3 4\n4 5\n"
        _check(gr, 1, "generated P5")

    def test_cycle_5(self):
        gr = "p tww 5 5\n1 2\n2 3\n3 4\n4 5\n5 1\n"
        _check(gr, 2, "generated C5")

    def test_single_edge(self):
        gr = "p tww 2 1\n1 2\n"
        _check(gr, 0, "generated single edge")

    def test_star_4(self):
        gr = "p tww 5 4\n1 2\n1 3\n1 4\n1 5\n"
        _check(gr, 0, "generated star K1,4")

    def test_bull_graph(self):
        gr = "p tww 5 5\n1 2\n2 3\n1 3\n1 4\n2 5\n"
        _check(gr, 1, "generated bull")

    def test_k4(self):
        gr = "p tww 4 6\n1 2\n1 3\n1 4\n2 3\n2 4\n3 4\n"
        _check(gr, 0, "generated K4")

    def test_cycle_6(self):
        gr = "p tww 6 6\n1 2\n2 3\n3 4\n4 5\n5 6\n6 1\n"
        _check(gr, 2, "generated C6")

    def test_path_7(self):
        gr = "p tww 7 6\n1 2\n2 3\n3 4\n4 5\n5 6\n6 7\n"
        _check(gr, 1, "generated P7")

    def test_complete_bipartite_k33(self):
        gr = "p tww 6 9\n1 4\n1 5\n1 6\n2 4\n2 5\n2 6\n3 4\n3 5\n3 6\n"
        _check(gr, 0, "generated K3,3")
