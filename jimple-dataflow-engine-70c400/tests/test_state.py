"""
Tests for intraprocedural dataflow analysis engine.
Verifies reaching definitions, live variables, and available expressions
across five TAC programs with different control flow patterns.
Also verifies JAR packaging, DOT CFG output, and SVG generation.
"""

import subprocess
import json
import os
import re
import pytest


# Hidden test program: nested loops with complex dataflow
NESTED_TAC = """\
method nested()
  a = 1
  b = 2
  n = a + b
  i = 0
outer:
  if i >= n goto end
  j = 0
  s = a + b
inner:
  if j >= n goto skip
  t = s + j
  s = t
  v = a + b
  j = v
  goto inner
skip:
  w = s + i
  i = w
  goto outer
end:
  x = a + b
  return x
"""


# ==================== Fixtures ====================

@pytest.fixture(scope="module")
def compiled():
    result = subprocess.run(
        ["make", "compile"],
        capture_output=True, text=True, cwd="/app"
    )
    assert result.returncode == 0, f"make compile failed:\n{result.stderr}"
    return True


@pytest.fixture(scope="module")
def batch_results(compiled):
    """Run analyze.sh and return batch results; also ensures JAR and SVGs are created."""
    result = subprocess.run(
        ["/app/analyze.sh", "/app/tac"],
        capture_output=True, text=True, cwd="/app", timeout=120
    )
    assert result.returncode == 0, f"analyze.sh failed:\n{result.stderr}"
    data = json.loads(result.stdout)
    return data


def run_tac(name, compiled, path_prefix="/app/tac"):
    result = subprocess.run(
        ["java", "-cp", "/app/build", "Main", f"{path_prefix}/{name}.tac"],
        capture_output=True, text=True, cwd="/app", timeout=60
    )
    assert result.returncode == 0, f"Runtime error on {name}.tac:\n{result.stderr}"
    data = json.loads(result.stdout)
    assert "reaching_definitions" in data, "Missing reaching_definitions in output"
    assert "live_variables" in data, "Missing live_variables in output"
    assert "available_expressions" in data, "Missing available_expressions in output"
    return data


def run_dot_mode(name, compiled, path_prefix="/app/tac"):
    """Run the engine in DOT mode and return the DOT string."""
    result = subprocess.run(
        ["java", "-cp", "/app/build", "Main", "--dot", f"{path_prefix}/{name}.tac"],
        capture_output=True, text=True, cwd="/app", timeout=60
    )
    assert result.returncode == 0, f"DOT mode error on {name}.tac:\n{result.stderr}"
    return result.stdout


def parse_dot(dot_str):
    """Parse DOT string and extract graph name, node ids, edges."""
    name_match = re.search(r'digraph\s+(\w+)', dot_str)
    graph_name = name_match.group(1) if name_match else None
    nodes = set()
    for m in re.finditer(r'(\d+)\s*\[label=', dot_str):
        nodes.add(int(m.group(1)))
    edges = set()
    for m in re.finditer(r'(\d+)\s*->\s*(\d+)', dot_str):
        edges.add((int(m.group(1)), int(m.group(2))))
    return graph_name, nodes, edges


@pytest.fixture(scope="module")
def straight(compiled):
    return run_tac("straight", compiled)


@pytest.fixture(scope="module")
def branch(compiled):
    return run_tac("branch", compiled)


@pytest.fixture(scope="module")
def loop(compiled):
    return run_tac("loop", compiled)


@pytest.fixture(scope="module")
def diamond(compiled):
    return run_tac("diamond", compiled)


@pytest.fixture(scope="module")
def nested(compiled):
    tac_path = "/tmp/test_nested.tac"
    with open(tac_path, "w") as f:
        f.write(NESTED_TAC)
    result = subprocess.run(
        ["java", "-cp", "/app/build", "Main", tac_path],
        capture_output=True, text=True, cwd="/app", timeout=60
    )
    assert result.returncode == 0, f"Runtime error on nested.tac:\n{result.stderr}"
    data = json.loads(result.stdout)
    return data


@pytest.fixture(scope="module")
def straight_dot(compiled):
    return run_dot_mode("straight", compiled)


@pytest.fixture(scope="module")
def branch_dot(compiled):
    return run_dot_mode("branch", compiled)


@pytest.fixture(scope="module")
def loop_dot(compiled):
    return run_dot_mode("loop", compiled)


@pytest.fixture(scope="module")
def nested_dot(compiled):
    tac_path = "/tmp/test_nested.tac"
    with open(tac_path, "w") as f:
        f.write(NESTED_TAC)
    result = subprocess.run(
        ["java", "-cp", "/app/build", "Main", "--dot", tac_path],
        capture_output=True, text=True, cwd="/app", timeout=60
    )
    assert result.returncode == 0, f"DOT mode error on nested.tac:\n{result.stderr}"
    return result.stdout


# ==================== Helper functions ====================

def rd_has(result, io, idx, var, def_idx):
    """Check if reaching definitions in/out set at stmt idx contains [var, def_idx]."""
    return [var, def_idx] in result["reaching_definitions"][io][idx]


def lv_has(result, io, idx, var):
    """Check if live variables in/out set at stmt idx contains var."""
    return var in result["live_variables"][io][idx]


def ae_has(result, io, idx, expr):
    """Check if available expressions in/out set at stmt idx contains expr."""
    return expr in result["available_expressions"][io][idx]


# ==================== BUILD SYSTEM TESTS ====================

class TestBuildSystem:
    def test_makefile_exists(self):
        assert os.path.isfile("/app/Makefile"), "Makefile not found at /app/Makefile"

    def test_make_compile_produces_classes(self, compiled):
        assert compiled
        class_files = []
        for root, _, files in os.walk("/app/build"):
            for f in files:
                if f.endswith(".class"):
                    class_files.append(f)
        assert len(class_files) >= 2, "Expected at least 2 .class files from compilation"

    def test_make_run(self, compiled):
        result = subprocess.run(
            ["make", "run", "FILE=/app/tac/straight.tac"],
            capture_output=True, text=True, cwd="/app", timeout=60
        )
        assert result.returncode == 0, f"make run failed:\n{result.stderr}"
        data = json.loads(result.stdout)
        assert data["method"] == "straight"


# ==================== JAR PACKAGING TESTS ====================

class TestJarPackaging:
    def test_jar_exists(self, batch_results):
        assert os.path.isfile("/app/analyzer.jar"), "analyzer.jar not found at /app/analyzer.jar"

    def test_jar_analysis_output(self, batch_results):
        result = subprocess.run(
            ["java", "-jar", "/app/analyzer.jar", "/app/tac/straight.tac"],
            capture_output=True, text=True, cwd="/app", timeout=60
        )
        assert result.returncode == 0, f"JAR analysis failed:\n{result.stderr}"
        data = json.loads(result.stdout)
        assert data["method"] == "straight"
        assert len(data["statements"]) == 6
        assert "reaching_definitions" in data
        assert "live_variables" in data
        assert "available_expressions" in data

    def test_jar_dot_mode(self, batch_results):
        result = subprocess.run(
            ["java", "-jar", "/app/analyzer.jar", "--dot", "/app/tac/loop.tac"],
            capture_output=True, text=True, cwd="/app", timeout=60
        )
        assert result.returncode == 0, f"JAR DOT mode failed:\n{result.stderr}"
        assert "digraph" in result.stdout
        name, nodes, edges = parse_dot(result.stdout)
        assert name == "loop"
        assert len(nodes) == 10

    def test_jar_consistent_with_classpath(self, batch_results, straight):
        result = subprocess.run(
            ["java", "-jar", "/app/analyzer.jar", "/app/tac/straight.tac"],
            capture_output=True, text=True, cwd="/app", timeout=60
        )
        jar_data = json.loads(result.stdout)
        assert jar_data == straight, "JAR output must match classpath execution output"


# ==================== DOT OUTPUT TESTS ====================

class TestDotStraight:
    def test_graph_name(self, straight_dot):
        name, _, _ = parse_dot(straight_dot)
        assert name == "straight"

    def test_node_count(self, straight_dot):
        _, nodes, _ = parse_dot(straight_dot)
        assert len(nodes) == 6

    def test_linear_edges(self, straight_dot):
        _, _, edges = parse_dot(straight_dot)
        for i in range(5):
            assert (i, i + 1) in edges, f"Missing edge {i} -> {i + 1}"

    def test_no_return_successor(self, straight_dot):
        _, _, edges = parse_dot(straight_dot)
        assert not any(e[0] == 5 for e in edges), "Return stmt should have no successors"

    def test_total_edges(self, straight_dot):
        _, _, edges = parse_dot(straight_dot)
        assert len(edges) == 5

    def test_graphviz_compatible(self, straight_dot):
        result = subprocess.run(
            ["dot", "-Tsvg"],
            input=straight_dot,
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, f"Graphviz failed to parse DOT:\n{result.stderr}"
        assert "<svg" in result.stdout


class TestDotBranch:
    def test_graph_name(self, branch_dot):
        name, _, _ = parse_dot(branch_dot)
        assert name == "branch"

    def test_branch_has_two_successors(self, branch_dot):
        _, _, edges = parse_dot(branch_dot)
        # stmt 3 is the conditional: fall-through to 4, branch to 7
        assert (3, 4) in edges, "Missing fall-through edge from conditional"
        assert (3, 7) in edges, "Missing branch edge from conditional"

    def test_goto_edge(self, branch_dot):
        _, _, edges = parse_dot(branch_dot)
        assert (6, 8) in edges, "Missing goto merge edge"

    def test_merge_convergence(self, branch_dot):
        _, _, edges = parse_dot(branch_dot)
        assert (7, 8) in edges, "Missing fall-through to merge from right branch"

    def test_total_edges(self, branch_dot):
        _, _, edges = parse_dot(branch_dot)
        assert len(edges) == 10


class TestDotLoop:
    def test_back_edge(self, loop_dot):
        _, _, edges = parse_dot(loop_dot)
        assert (8, 3) in edges, "Missing back edge in loop"

    def test_loop_header_two_successors(self, loop_dot):
        _, _, edges = parse_dot(loop_dot)
        assert (3, 4) in edges, "Missing fall-through from loop header"
        assert (3, 9) in edges, "Missing exit edge from loop header"

    def test_total_edges(self, loop_dot):
        _, _, edges = parse_dot(loop_dot)
        assert len(edges) == 10


class TestDotNested:
    def test_node_count(self, nested_dot):
        _, nodes, _ = parse_dot(nested_dot)
        assert len(nodes) == 18

    def test_outer_back_edge(self, nested_dot):
        _, _, edges = parse_dot(nested_dot)
        assert (15, 4) in edges, "Missing outer loop back edge"

    def test_inner_back_edge(self, nested_dot):
        _, _, edges = parse_dot(nested_dot)
        assert (12, 7) in edges, "Missing inner loop back edge"

    def test_outer_header_successors(self, nested_dot):
        _, _, edges = parse_dot(nested_dot)
        assert (4, 5) in edges, "Missing outer header fall-through"
        assert (4, 16) in edges, "Missing outer header exit edge"

    def test_inner_header_successors(self, nested_dot):
        _, _, edges = parse_dot(nested_dot)
        assert (7, 8) in edges, "Missing inner header fall-through"
        assert (7, 13) in edges, "Missing inner header skip edge"

    def test_total_edges(self, nested_dot):
        _, _, edges = parse_dot(nested_dot)
        assert len(edges) == 19

    def test_graphviz_compatible(self, nested_dot):
        result = subprocess.run(
            ["dot", "-Tsvg"],
            input=nested_dot,
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, f"Graphviz failed to parse DOT:\n{result.stderr}"
        assert "<svg" in result.stdout


# ==================== SVG GENERATION TESTS ====================

class TestSvgGeneration:
    def test_result_dir_exists(self, batch_results):
        assert os.path.isdir("/app/results"), "/app/results directory not found"

    def test_svg_files_produced(self, batch_results):
        for method in ["straight", "branch", "loop", "diamond"]:
            path = f"/app/results/{method}_cfg.svg"
            assert os.path.isfile(path), f"SVG not found: {path}"

    def test_svg_valid_content(self, batch_results):
        for method in ["straight", "branch", "loop", "diamond"]:
            with open(f"/app/results/{method}_cfg.svg") as f:
                content = f.read()
            assert "<svg" in content, f"{method}_cfg.svg is not valid SVG"
            assert len(content) > 100, f"{method}_cfg.svg is too small"

    def test_json_files_produced(self, batch_results):
        for method in ["straight", "branch", "loop", "diamond"]:
            path = f"/app/results/{method}.json"
            assert os.path.isfile(path), f"JSON not found: {path}"

    def test_json_files_valid(self, batch_results):
        for method in ["straight", "branch", "loop", "diamond"]:
            with open(f"/app/results/{method}.json") as f:
                data = json.load(f)
            assert data["method"] == method


# ==================== ANALYZE SCRIPT TESTS ====================

class TestAnalyzeScript:
    def test_script_exists(self, batch_results):
        assert os.path.isfile("/app/analyze.sh"), "analyze.sh not found at /app/analyze.sh"
        assert os.access("/app/analyze.sh", os.X_OK), "analyze.sh must be executable"

    def test_batch_output_is_json_array(self, batch_results):
        assert isinstance(batch_results, list), "Output must be a JSON array"
        methods = sorted([d["method"] for d in batch_results])
        assert "branch" in methods
        assert "diamond" in methods
        assert "loop" in methods
        assert "straight" in methods

    def test_batch_results_structurally_valid(self, batch_results):
        for entry in batch_results:
            assert "method" in entry
            assert "statements" in entry
            assert "reaching_definitions" in entry
            assert "live_variables" in entry
            assert "available_expressions" in entry
            n = len(entry["statements"])
            assert len(entry["reaching_definitions"]["in"]) == n
            assert len(entry["reaching_definitions"]["out"]) == n
            assert len(entry["live_variables"]["in"]) == n
            assert len(entry["live_variables"]["out"]) == n
            assert len(entry["available_expressions"]["in"]) == n
            assert len(entry["available_expressions"]["out"]) == n


# ==================== STRAIGHT-LINE TESTS ====================

class TestStraightStructure:
    def test_num_statements(self, straight):
        assert len(straight["statements"]) == 6

    def test_method_name(self, straight):
        assert straight["method"] == "straight"

    def test_rd_in_out_lengths(self, straight):
        assert len(straight["reaching_definitions"]["in"]) == 6
        assert len(straight["reaching_definitions"]["out"]) == 6

    def test_lv_in_out_lengths(self, straight):
        assert len(straight["live_variables"]["in"]) == 6
        assert len(straight["live_variables"]["out"]) == 6

    def test_ae_in_out_lengths(self, straight):
        assert len(straight["available_expressions"]["in"]) == 6
        assert len(straight["available_expressions"]["out"]) == 6


class TestStraightReachingDefs:
    def test_a_defined_at_0_reaches_stmt1(self, straight):
        assert rd_has(straight, "out", 0, "a", 0)
        assert rd_has(straight, "in", 1, "a", 0)

    def test_a_killed_at_3(self, straight):
        assert not rd_has(straight, "out", 3, "a", 0)
        assert rd_has(straight, "out", 3, "a", 3)

    def test_b_killed_at_4(self, straight):
        assert not rd_has(straight, "out", 4, "b", 1)
        assert rd_has(straight, "out", 4, "b", 4)

    def test_c_defined_at_2_reaches_end(self, straight):
        assert rd_has(straight, "in", 5, "c", 2)

    def test_entry_has_no_reaching_defs(self, straight):
        assert straight["reaching_definitions"]["in"][0] == []


class TestStraightLiveVars:
    def test_nothing_live_before_start(self, straight):
        assert straight["live_variables"]["in"][0] == []

    def test_a_b_live_before_their_use(self, straight):
        assert lv_has(straight, "in", 2, "a")
        assert lv_has(straight, "in", 2, "b")

    def test_c_live_before_redef_a(self, straight):
        assert lv_has(straight, "in", 3, "c")
        assert not lv_has(straight, "in", 3, "a")
        assert not lv_has(straight, "in", 3, "b")

    def test_b_live_before_return(self, straight):
        assert lv_has(straight, "in", 5, "b")

    def test_nothing_live_after_return(self, straight):
        assert straight["live_variables"]["out"][5] == []


class TestStraightAvailExprs:
    def test_ab_available_after_compute(self, straight):
        assert ae_has(straight, "out", 2, "a + b")

    def test_ab_killed_by_redef_a(self, straight):
        assert not ae_has(straight, "out", 3, "a + b")

    def test_ac_available_after_compute(self, straight):
        assert ae_has(straight, "out", 4, "a + c")

    def test_nothing_available_at_entry(self, straight):
        assert straight["available_expressions"]["in"][0] == []


# ==================== BRANCH TESTS ====================

class TestBranchStructure:
    def test_num_statements(self, branch):
        assert len(branch["statements"]) == 10

    def test_method_name(self, branch):
        assert branch["method"] == "branch"


class TestBranchReachingDefs:
    def test_both_a_defs_at_merge(self, branch):
        assert rd_has(branch, "in", 8, "a", 0)
        assert rd_has(branch, "in", 8, "a", 4)

    def test_both_d_defs_at_merge(self, branch):
        assert rd_has(branch, "in", 8, "d", 5)
        assert rd_has(branch, "in", 8, "d", 7)

    def test_b_reaches_merge(self, branch):
        assert rd_has(branch, "in", 8, "b", 1)

    def test_c_reaches_merge(self, branch):
        assert rd_has(branch, "in", 8, "c", 2)


class TestBranchLiveVars:
    def test_a_b_live_before_merge_expr(self, branch):
        assert lv_has(branch, "in", 8, "a")
        assert lv_has(branch, "in", 8, "b")

    def test_e_live_before_return(self, branch):
        assert lv_has(branch, "in", 9, "e")


class TestBranchAvailExprs:
    def test_empty_at_merge(self, branch):
        assert branch["available_expressions"]["in"][8] == []

    def test_ab_regenerated_at_merge(self, branch):
        assert ae_has(branch, "out", 8, "a + b")

    def test_ab_available_after_initial_compute(self, branch):
        assert ae_has(branch, "out", 2, "a + b")


# ==================== LOOP TESTS ====================

class TestLoopStructure:
    def test_num_statements(self, loop):
        assert len(loop["statements"]) == 10

    def test_method_name(self, loop):
        assert loop["method"] == "loop"


class TestLoopReachingDefs:
    def test_both_i_defs_at_header(self, loop):
        assert rd_has(loop, "in", 3, "i", 1)
        assert rd_has(loop, "in", 3, "i", 7)

    def test_both_s_defs_at_header(self, loop):
        assert rd_has(loop, "in", 3, "s", 2)
        assert rd_has(loop, "in", 3, "s", 5)

    def test_n_only_from_entry(self, loop):
        assert rd_has(loop, "in", 3, "n", 0)

    def test_t_from_loop_body(self, loop):
        assert rd_has(loop, "in", 3, "t", 4)

    def test_u_from_loop_body(self, loop):
        assert rd_has(loop, "in", 3, "u", 6)


class TestLoopLiveVars:
    def test_i_n_s_live_at_header(self, loop):
        assert lv_has(loop, "in", 3, "i")
        assert lv_has(loop, "in", 3, "n")
        assert lv_has(loop, "in", 3, "s")

    def test_nothing_live_at_entry(self, loop):
        assert loop["live_variables"]["in"][0] == []

    def test_s_live_before_return(self, loop):
        assert lv_has(loop, "in", 9, "s")

    def test_t_live_before_s_assign(self, loop):
        assert lv_has(loop, "in", 5, "t")


class TestLoopAvailExprs:
    def test_empty_at_header(self, loop):
        assert loop["available_expressions"]["in"][3] == []

    def test_si_after_compute(self, loop):
        assert ae_has(loop, "out", 4, "s + i")

    def test_in_after_compute(self, loop):
        assert ae_has(loop, "out", 6, "i + n")


# ==================== DIAMOND TESTS ====================

class TestDiamondStructure:
    def test_num_statements(self, diamond):
        assert len(diamond["statements"]) == 13

    def test_method_name(self, diamond):
        assert diamond["method"] == "diamond"


class TestDiamondAvailExprs:
    def test_ab_and_amulb_at_merge(self, diamond):
        assert ae_has(diamond, "in", 10, "a + b")
        assert ae_has(diamond, "in", 10, "a * b")

    def test_cplusd_not_at_merge(self, diamond):
        assert not ae_has(diamond, "in", 10, "c + d")

    def test_cminusd_not_at_merge(self, diamond):
        assert not ae_has(diamond, "in", 10, "c - d")

    def test_eplusf_generated_at_merge(self, diamond):
        assert ae_has(diamond, "out", 10, "e + f")

    def test_ab_available_at_end(self, diamond):
        assert ae_has(diamond, "out", 11, "a + b")


class TestDiamondReachingDefs:
    def test_both_e_defs_at_merge(self, diamond):
        assert rd_has(diamond, "in", 10, "e", 5)
        assert rd_has(diamond, "in", 10, "e", 8)

    def test_both_f_defs_at_merge(self, diamond):
        assert rd_has(diamond, "in", 10, "f", 6)
        assert rd_has(diamond, "in", 10, "f", 9)

    def test_abcd_reach_merge(self, diamond):
        assert rd_has(diamond, "in", 10, "a", 0)
        assert rd_has(diamond, "in", 10, "b", 1)
        assert rd_has(diamond, "in", 10, "c", 2)
        assert rd_has(diamond, "in", 10, "d", 3)


class TestDiamondLiveVars:
    def test_h_live_before_return(self, diamond):
        assert lv_has(diamond, "in", 12, "h")

    def test_ef_live_before_merge_expr(self, diamond):
        assert lv_has(diamond, "in", 10, "e")
        assert lv_has(diamond, "in", 10, "f")

    def test_ab_live_before_branch(self, diamond):
        assert lv_has(diamond, "in", 4, "a")
        assert lv_has(diamond, "in", 4, "b")


# ==================== NESTED LOOP TESTS (hidden program) ====================
# 18 statements, two nested loops, tests complex fixed-point convergence

class TestNestedStructure:
    def test_num_statements(self, nested):
        assert len(nested["statements"]) == 18

    def test_method_name(self, nested):
        assert nested["method"] == "nested"

    def test_all_analysis_lengths(self, nested):
        n = 18
        for analysis in ["reaching_definitions", "live_variables", "available_expressions"]:
            assert len(nested[analysis]["in"]) == n, f"{analysis} in length mismatch"
            assert len(nested[analysis]["out"]) == n, f"{analysis} out length mismatch"


class TestNestedReachingDefs:
    def test_entry_empty(self, nested):
        assert nested["reaching_definitions"]["in"][0] == []

    def test_both_i_defs_at_outer_header(self, nested):
        # i defined at stmt 3 (i=0) and stmt 14 (i=w)
        assert rd_has(nested, "in", 4, "i", 3)
        assert rd_has(nested, "in", 4, "i", 14)

    def test_both_j_defs_at_inner_header(self, nested):
        # j defined at stmt 5 (j=0) and stmt 11 (j=v)
        assert rd_has(nested, "in", 7, "j", 5)
        assert rd_has(nested, "in", 7, "j", 11)

    def test_both_s_defs_at_inner_header(self, nested):
        # s defined at stmt 6 (s=a+b) and stmt 9 (s=t)
        assert rd_has(nested, "in", 7, "s", 6)
        assert rd_has(nested, "in", 7, "s", 9)

    def test_inner_body_defs_reach_outer_header(self, nested):
        # t (stmt 8) and v (stmt 10) reach outer header via back edges
        assert rd_has(nested, "in", 4, "t", 8)
        assert rd_has(nested, "in", 4, "v", 10)

    def test_a_b_reach_end(self, nested):
        assert rd_has(nested, "in", 17, "a", 0)
        assert rd_has(nested, "in", 17, "b", 1)


class TestNestedLiveVars:
    def test_nothing_live_at_entry(self, nested):
        assert nested["live_variables"]["in"][0] == []

    def test_x_live_before_return(self, nested):
        assert nested["live_variables"]["in"][17] == ["x"]

    def test_ab_live_before_end_block(self, nested):
        # stmt 16: x = a + b needs a and b
        assert lv_has(nested, "in", 16, "a")
        assert lv_has(nested, "in", 16, "b")
        assert not lv_has(nested, "in", 16, "x")

    def test_outer_header_live_vars(self, nested):
        # stmt 4: outer header needs i, n for condition; a, b for body
        assert lv_has(nested, "in", 4, "i")
        assert lv_has(nested, "in", 4, "n")
        assert lv_has(nested, "in", 4, "a")
        assert lv_has(nested, "in", 4, "b")

    def test_j_killed_at_assignment(self, nested):
        # stmt 5: j = 0 kills j
        assert not lv_has(nested, "in", 5, "j")

    def test_inner_header_has_many_live(self, nested):
        # stmt 7: inner header - many variables needed downstream
        for v in ["a", "b", "i", "j", "n", "s"]:
            assert lv_has(nested, "in", 7, v), f"{v} should be live at inner header"


class TestNestedAvailExprs:
    def test_nothing_at_entry(self, nested):
        assert nested["available_expressions"]["in"][0] == []

    def test_ab_available_after_first_compute(self, nested):
        # stmt 2: n = a + b generates a + b
        assert ae_has(nested, "out", 2, "a + b")

    def test_ab_persists_everywhere(self, nested):
        # a and b are never redefined so a + b is available at all points after stmt 2
        for i in range(3, 18):
            assert ae_has(nested, "in", i, "a + b"), f"a + b should be in IN[{i}]"

    def test_sj_generated_and_killed(self, nested):
        # s + j generated at stmt 8 (t = s + j), killed at stmt 9 (s = t redefines s)
        assert ae_has(nested, "out", 8, "s + j")
        assert not ae_has(nested, "out", 9, "s + j")

    def test_si_generated_and_killed(self, nested):
        # s + i generated at stmt 13 (w = s + i), killed at stmt 14 (i = w redefines i)
        assert ae_has(nested, "out", 13, "s + i")
        assert not ae_has(nested, "out", 14, "s + i")

    def test_outer_header_only_ab(self, nested):
        # Only a + b survives intersection at outer header
        assert nested["available_expressions"]["in"][4] == ["a + b"]

    def test_inner_header_only_ab(self, nested):
        # Only a + b survives intersection at inner header
        assert nested["available_expressions"]["in"][7] == ["a + b"]
