
import json
import os
import subprocess
import pytest

PROGRAMS_DIR = "/app/programs"
RESULTS_DIR = "/app/results"
GRAPHS_DIR = "/app/graphs"
ANALYZER = "/app/analyzer.py"

ALL_PROGRAMS = [
    "simple_fork_join", "nested_finish", "diamond_pattern",
    "phaser_sync", "multi_phase",
]


@pytest.fixture(scope="session", autouse=True)
def ensure_results():
    """Run the analyzer if result files are missing."""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    os.makedirs(GRAPHS_DIR, exist_ok=True)
    missing = [p for p in ALL_PROGRAMS if not os.path.exists(f"{RESULTS_DIR}/{p}.json")]
    if missing:
        cmd = ["python3", ANALYZER] + [f"{PROGRAMS_DIR}/{p}.json" for p in missing]
        subprocess.run(cmd, check=True, cwd="/app", timeout=120)


def load_result(name):
    path = f"{RESULTS_DIR}/{name}.json"
    assert os.path.exists(path), f"Result file {path} not found. Did the analyzer run?"
    with open(path) as f:
        return json.load(f)


def race_set(result):
    return {
        (r["access1"], r["access2"], r["variable"])
        for r in result["data_races"]
    }


# ===================== simple_fork_join =====================

class TestSimpleForkJoinWork:
    def test_work(self):
        r = load_result("simple_fork_join")
        assert r["work"] == 32, f"Expected work=32, got {r['work']}"


class TestSimpleForkJoinSpan:
    def test_span(self):
        r = load_result("simple_fork_join")
        assert r["span"] == 20, f"Expected span=20, got {r['span']}"


class TestSimpleForkJoinParallelism:
    def test_parallelism(self):
        r = load_result("simple_fork_join")
        assert abs(r["ideal_parallelism"] - 1.6) < 0.01


class TestSimpleForkJoinRaces:
    def test_race_count(self):
        r = load_result("simple_fork_join")
        assert len(r["data_races"]) == 1

    def test_race_r1_w1_x(self):
        races = race_set(load_result("simple_fork_join"))
        assert ("r1", "w1", "x") in races

    def test_no_race_on_y(self):
        races = race_set(load_result("simple_fork_join"))
        y_races = {r for r in races if r[2] == "y"}
        assert len(y_races) == 0


# ===================== nested_finish =====================

class TestNestedFinishWork:
    def test_work(self):
        r = load_result("nested_finish")
        assert r["work"] == 36, f"Expected work=36, got {r['work']}"


class TestNestedFinishSpan:
    def test_span(self):
        r = load_result("nested_finish")
        assert r["span"] == 20, f"Expected span=20, got {r['span']}"


class TestNestedFinishParallelism:
    def test_parallelism(self):
        r = load_result("nested_finish")
        assert abs(r["ideal_parallelism"] - 1.8) < 0.01


class TestNestedFinishRaces:
    def test_race_count(self):
        r = load_result("nested_finish")
        assert len(r["data_races"]) == 3

    def test_race_r1_w1_a(self):
        races = race_set(load_result("nested_finish"))
        assert ("r1", "w1", "a") in races

    def test_race_r2_w1_a(self):
        races = race_set(load_result("nested_finish"))
        assert ("r2", "w1", "a") in races

    def test_race_w2_w3_b(self):
        races = race_set(load_result("nested_finish"))
        assert ("w2", "w3", "b") in races


# ===================== diamond_pattern =====================

class TestDiamondPatternWork:
    def test_work(self):
        r = load_result("diamond_pattern")
        assert r["work"] == 45, f"Expected work=45, got {r['work']}"


class TestDiamondPatternSpan:
    def test_span(self):
        r = load_result("diamond_pattern")
        assert r["span"] == 21, f"Expected span=21, got {r['span']}"


class TestDiamondPatternParallelism:
    def test_parallelism(self):
        r = load_result("diamond_pattern")
        expected = round(45 / 21, 4)
        assert abs(r["ideal_parallelism"] - expected) < 0.01


class TestDiamondPatternRaces:
    def test_race_count(self):
        r = load_result("diamond_pattern")
        assert len(r["data_races"]) == 3

    def test_race_r1_w1_x(self):
        races = race_set(load_result("diamond_pattern"))
        assert ("r1", "w1", "x") in races

    def test_race_r3_w4_z(self):
        races = race_set(load_result("diamond_pattern"))
        assert ("r3", "w4", "z") in races

    def test_race_w2_w3_y(self):
        races = race_set(load_result("diamond_pattern"))
        assert ("w2", "w3", "y") in races

    def test_no_race_on_w(self):
        races = race_set(load_result("diamond_pattern"))
        w_races = {r for r in races if r[2] == "w"}
        assert len(w_races) == 0

    def test_no_false_race_w1_r4_x(self):
        """w1 happens-before r4 via continuation, so no race."""
        races = race_set(load_result("diamond_pattern"))
        assert ("r4", "w1", "x") not in races


# ===================== phaser_sync =====================

class TestPhaserSyncWork:
    def test_work(self):
        r = load_result("phaser_sync")
        assert r["work"] == 24, f"Expected work=24, got {r['work']}"


class TestPhaserSyncSpan:
    def test_span(self):
        r = load_result("phaser_sync")
        assert r["span"] == 14, f"Expected span=14, got {r['span']}"


class TestPhaserSyncParallelism:
    def test_parallelism(self):
        r = load_result("phaser_sync")
        expected = round(24 / 14, 4)
        assert abs(r["ideal_parallelism"] - expected) < 0.01


class TestPhaserSyncRaces:
    def test_race_count(self):
        r = load_result("phaser_sync")
        assert len(r["data_races"]) == 1, (
            f"Expected 1 race, got {len(r['data_races'])}: {r['data_races']}"
        )

    def test_race_r3_w3_z(self):
        """w3 and r3 are post-wait in different tasks — not ordered."""
        races = race_set(load_result("phaser_sync"))
        assert ("r3", "w3", "z") in races, (
            f"Expected race (r3, w3, z); found: {races}"
        )

    def test_no_race_on_x(self):
        """Phaser P1 synchronization: w1 HB r2 via signal/wait."""
        races = race_set(load_result("phaser_sync"))
        x_races = {r for r in races if r[2] == "x"}
        assert len(x_races) == 0, f"False positive race(s) on x: {x_races}"

    def test_no_race_on_y(self):
        """Phaser P1 synchronization: w2 HB r1 via signal/wait."""
        races = race_set(load_result("phaser_sync"))
        y_races = {r for r in races if r[2] == "y"}
        assert len(y_races) == 0, f"False positive race(s) on y: {y_races}"


# ===================== multi_phase =====================

class TestMultiPhaseWork:
    def test_work(self):
        r = load_result("multi_phase")
        assert r["work"] == 33, f"Expected work=33, got {r['work']}"


class TestMultiPhaseSpan:
    def test_span(self):
        r = load_result("multi_phase")
        assert r["span"] == 13, f"Expected span=13, got {r['span']}"


class TestMultiPhaseParallelism:
    def test_parallelism(self):
        r = load_result("multi_phase")
        expected = round(33 / 13, 4)
        assert abs(r["ideal_parallelism"] - expected) < 0.01


class TestMultiPhaseRaces:
    def test_race_count(self):
        r = load_result("multi_phase")
        assert len(r["data_races"]) == 3, (
            f"Expected 3 races, got {len(r['data_races'])}: {r['data_races']}"
        )

    def test_race_r2_w4_a(self):
        """r2 and w4 are between P1 phase-0 wait and phase-1 signal — unsynchronized."""
        races = race_set(load_result("multi_phase"))
        assert ("r2", "w4", "a") in races

    def test_race_r3_w4_a(self):
        """T3 syncs on P2 only; w4 in T1 is post-P1-phase-0-wait — no ordering."""
        races = race_set(load_result("multi_phase"))
        assert ("r3", "w4", "a") in races

    def test_race_r6_w3_d(self):
        """Main continuation r6 and T3's w3 are not ordered."""
        races = race_set(load_result("multi_phase"))
        assert ("r6", "w3", "d") in races

    def test_no_race_on_b(self):
        """P1 phase-0: w2 HB r1 via signal/wait."""
        races = race_set(load_result("multi_phase"))
        b_races = {r for r in races if r[2] == "b"}
        assert len(b_races) == 0, f"False positive race(s) on b: {b_races}"

    def test_no_race_on_c(self):
        """P1 phase-1: w5 HB r4 via signal/wait."""
        races = race_set(load_result("multi_phase"))
        c_races = {r for r in races if r[2] == "c"}
        assert len(c_races) == 0, f"False positive race(s) on c: {c_races}"

    def test_w1_not_racing_r2(self):
        """w1 HB r2 via P1 phase-0 signal/wait chain."""
        races = race_set(load_result("multi_phase"))
        assert ("r2", "w1", "a") not in races

    def test_w1_not_racing_r3(self):
        """w1 HB r3 via P1-signal -> P2-signal -> P2-wait chain."""
        races = race_set(load_result("multi_phase"))
        assert ("r3", "w1", "a") not in races


# ===================== Graphviz DOT output =====================

class TestDotOutput:
    @pytest.mark.parametrize("name", ALL_PROGRAMS)
    def test_dot_file_exists(self, name):
        path = f"{GRAPHS_DIR}/{name}.dot"
        assert os.path.exists(path), f"DOT file {path} not found"

    @pytest.mark.parametrize("name", ALL_PROGRAMS)
    def test_dot_is_valid_digraph(self, name):
        with open(f"{GRAPHS_DIR}/{name}.dot") as f:
            content = f.read()
        assert content.strip().startswith("digraph"), (
            "DOT file must begin with 'digraph'"
        )
        assert content.strip().endswith("}"), "DOT file must end with '}'"

    def test_phaser_sync_dot_has_phaser_edges(self):
        with open(f"{GRAPHS_DIR}/phaser_sync.dot") as f:
            content = f.read().lower()
        assert "red" in content or "phaser" in content, (
            "Phaser program DOT should visually distinguish phaser edges"
        )


# ===================== SVG rendering =====================

class TestSvgOutput:
    @pytest.mark.parametrize("name", ALL_PROGRAMS)
    def test_svg_file_exists(self, name):
        path = f"{GRAPHS_DIR}/{name}.svg"
        assert os.path.exists(path), (
            f"SVG file {path} not found — was 'dot -Tsvg' used to render?"
        )


# ===================== Makefile =====================

class TestMakefile:
    def test_makefile_exists(self):
        assert os.path.exists("/app/Makefile"), "Makefile not found at /app/Makefile"

    def test_make_validate_succeeds(self):
        result = subprocess.run(
            ["make", "-C", "/app", "validate"],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, (
            f"make validate failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
