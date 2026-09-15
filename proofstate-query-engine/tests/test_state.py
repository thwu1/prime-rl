
import json
import os
import subprocess

ARITH_PATH = "/app/data/arith_proof.json"
LIST_PATH = "/app/data/list_proof.json"
BOOL_PATH = "/app/data/bool_proof.json"


def run_query(path_str, json_file):
    result = subprocess.run(
        ["python3", "/app/proofquery.py", "query", path_str, json_file],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, (
        f"Query failed (rc={result.returncode}):\n"
        f"  path: {path_str}\n"
        f"  file: {json_file}\n"
        f"  stderr: {result.stderr}")
    return json.loads(result.stdout)


def run_cmd(args):
    result = subprocess.run(
        ["python3", "/app/proofquery.py"] + args,
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, (
        f"Command failed (rc={result.returncode}):\n"
        f"  args: {args}\n"
        f"  stderr: {result.stderr}")
    return result


def run_dag(json_file):
    result = subprocess.run(
        ["python3", "/app/proofquery.py", "dag", json_file],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, (
        f"DAG failed (rc={result.returncode}):\n"
        f"  file: {json_file}\n"
        f"  stderr: {result.stderr}")
    return json.loads(result.stdout)


# ===== Data file sanity =====

def test_data_files_exist():
    """Verify all required data files and tool exist."""
    assert os.path.isfile("/app/proofquery.py"), "/app/proofquery.py missing"
    for p in [ARITH_PATH, LIST_PATH, BOOL_PATH]:
        assert os.path.isfile(p), f"{p} missing"
        with open(p) as f:
            data = json.load(f)
        assert isinstance(data, list), f"{p} is not a JSON array"
        assert len(data) >= 1, f"{p} has no fragments"


# ===== Sentence matching =====

def test_sentence_literal_match():
    """Match sentences containing 'induction'."""
    results = run_query(".s(induction)", ARITH_PATH)
    assert len(results) == 1
    assert "induction n" in results[0]["sentence"]


def test_sentence_fnmatch():
    """Match sentences with fnmatch pattern 'Theorem*'."""
    results = run_query(".s{Theorem*}", ARITH_PATH)
    assert len(results) == 1
    assert results[0]["sentence"].startswith("Theorem")


def test_sentence_multiple_matches():
    """Multiple sentences can match a pattern."""
    results = run_query(".s(reflexivity)", ARITH_PATH)
    assert len(results) == 2
    for r in results:
        assert "reflexivity" in r["sentence"]


def test_sentence_no_match():
    """Non-matching pattern returns empty list."""
    results = run_query(".s(nonexistent_pattern_xyz)", ARITH_PATH)
    assert len(results) == 0


# ===== Goal matching =====

def test_goal_by_position():
    """Match goal by 1-based position."""
    results = run_query(".s(induction).g#1", ARITH_PATH)
    assert len(results) == 1
    assert "0 + m" in results[0]["conclusion"]


def test_goal_by_position_2():
    """Match second goal by position."""
    results = run_query(".s(induction).g#2", ARITH_PATH)
    assert len(results) == 1
    assert "S n'" in results[0]["conclusion"]


def test_goal_content_match():
    """Match goal by conclusion content."""
    results = run_query(".s(simpl).g(m + 0)", ARITH_PATH)
    assert len(results) == 1
    assert "m + 0" in results[0]["conclusion"]


def test_goal_no_goals():
    """Position match on sentence with no goals returns empty."""
    results = run_query(".s(reflexivity).g#1", ARITH_PATH)
    assert len(results) == 0


# ===== Hypothesis matching =====

def test_hypothesis_by_name():
    """Match hypothesis by name."""
    results = run_query(".s(induction).g#2.h#IHn'", ARITH_PATH)
    assert len(results) == 1
    assert results[0]["name"] == "IHn'"
    assert "forall m" in results[0]["type"]


def test_hypothesis_type_leaf():
    """Extract hypothesis type via leaf selector."""
    results = run_query(".s(induction).g#2.h#IHn'.type", ARITH_PATH)
    assert len(results) == 1
    assert results[0] == "forall m : nat, n' + m = m + n'"


def test_hypothesis_content_match():
    """Match hypotheses by type content (substring)."""
    results = run_query(".s(intros).h(list)", LIST_PATH)
    assert len(results) == 2
    for r in results:
        assert "list" in r["type"]


def test_hypothesis_fnmatch():
    """Match hypotheses with fnmatch on type."""
    results = run_query(".s(intros).h{list*}", LIST_PATH)
    assert len(results) == 2


def test_hypothesis_name_leaf():
    """Extract hypothesis name via leaf selector."""
    results = run_query(".s(induction).g#2.h#n'.name", ARITH_PATH)
    assert len(results) == 1
    assert results[0] == "n'"


# ===== Implicit goal default =====

def test_implicit_goal_default_hyp():
    """Hypothesis selector without explicit .g defaults to first goal."""
    results = run_query(".s(Base case).h#m", ARITH_PATH)
    assert len(results) == 1
    assert results[0]["name"] == "m"
    assert results[0]["type"] == "nat"


def test_implicit_goal_default_ccl():
    """Conclusion leaf without explicit .g defaults to first goal."""
    results = run_query(".s(Base case).ccl", ARITH_PATH)
    assert len(results) == 1
    assert results[0] == "0 + m = m + 0"


# ===== Message matching =====

def test_message_bare():
    """Match all messages from a sentence."""
    results = run_query(".s(Print).msg", ARITH_PATH)
    assert len(results) == 1
    assert "forall n m : nat" in results[0]


def test_message_content_match():
    """Match messages with content filter."""
    results = run_query(".s(Check).msg(forall)", ARITH_PATH)
    assert len(results) == 1


def test_message_from_compute():
    """Match messages from Compute sentences."""
    results = run_query(".s(Compute).msg", LIST_PATH)
    assert len(results) == 1
    assert "3" in results[0]


# ===== Input leaf =====

def test_input_leaf():
    """Extract sentence text via .in selector."""
    results = run_query(".s{Qed.}.in", ARITH_PATH)
    assert len(results) == 1
    assert results[0] == "Qed."


# ===== Cross-file queries =====

def test_list_proof_induction_goal():
    """Query induction goal in list proof."""
    results = run_query(".s(induction l1).g#2.h#IHl1'.type", LIST_PATH)
    assert len(results) == 1
    assert "length" in results[0]


def test_list_proof_lemma_match():
    """Match Lemma sentence in list proof."""
    results = run_query(".s{Lemma*}", LIST_PATH)
    assert len(results) == 1
    assert "length_app" in results[0]["sentence"]


# ===== Bool proof queries =====

def test_bool_destruct_sentences():
    """Query destruct sentences across bool proof file."""
    results = run_query(".s(destruct)", BOOL_PATH)
    sents = [r["sentence"] for r in results]
    assert len(results) == 4, (
        f"Expected 4 sentences containing 'destruct', got {len(results)}: {sents}")


def test_bool_reflexivity_count():
    """Count reflexivity sentences in bool proof."""
    results = run_query(".s(reflexivity)", BOOL_PATH)
    sents = [r["sentence"] for r in results]
    assert len(results) == 6, (
        f"Expected 6 reflexivity sentences, got {len(results)}: {sents}")


def test_bool_goal_position_after_destruct():
    """Query second goal after destruct in bool proof."""
    results = run_query(".s(destruct a).g#2", BOOL_PATH)
    assert len(results) == 1, (
        f"Expected 1 result for .s(destruct a).g#2, got {len(results)}")
    assert "false" in results[0]["conclusion"], (
        f"Expected 'false' in conclusion, got: {results[0]['conclusion']}")


# ===== Minification =====

def test_minify_roundtrip_arith():
    """Minify then expand should produce the original document."""
    with open(ARITH_PATH) as f:
        original = json.load(f)

    run_cmd(["minify", ARITH_PATH, "-o", "/tmp/arith_minified.json"])
    run_cmd(["expand", "/tmp/arith_minified.json", "-o", "/tmp/arith_expanded.json"])

    with open("/tmp/arith_expanded.json") as f:
        expanded = json.load(f)

    assert original == expanded, "Roundtrip failed: expanded differs from original"


def test_minify_roundtrip_list():
    """Minify then expand should produce the original list proof document."""
    with open(LIST_PATH) as f:
        original = json.load(f)

    run_cmd(["minify", LIST_PATH, "-o", "/tmp/list_minified.json"])
    run_cmd(["expand", "/tmp/list_minified.json", "-o", "/tmp/list_expanded.json"])

    with open("/tmp/list_expanded.json") as f:
        expanded = json.load(f)

    assert original == expanded, "Roundtrip failed: expanded differs from original"


def test_minify_has_refs():
    """Minified arith proof should have at least one ref (duplicated hypotheses)."""
    run_cmd(["minify", ARITH_PATH, "-o", "/tmp/arith_minified.json"])
    with open("/tmp/arith_minified.json") as f:
        minified = json.load(f)

    assert "_refs" in minified
    assert "data" in minified
    assert len(minified["_refs"]) > 0


def test_minify_size_reduction():
    """Minified file should be smaller than original."""
    run_cmd(["minify", ARITH_PATH, "-o", "/tmp/arith_minified.json"])

    orig_size = os.path.getsize(ARITH_PATH)
    mini_size = os.path.getsize("/tmp/arith_minified.json")

    assert mini_size < orig_size * 0.9, (
        f"Minified ({mini_size}) not significantly smaller than original ({orig_size})")


def test_query_on_minified():
    """Query on minified document produces same results as original."""
    run_cmd(["minify", ARITH_PATH, "-o", "/tmp/arith_minified.json"])

    orig = run_query(".s(induction).g#2.h#IHn'.type", ARITH_PATH)
    mini = run_query(".s(induction).g#2.h#IHn'.type", "/tmp/arith_minified.json")

    assert orig == mini, f"Query mismatch: {orig} vs {mini}"


def test_minify_deterministic():
    """Running minification twice produces identical output."""
    run_cmd(["minify", ARITH_PATH, "-o", "/tmp/arith_min1.json"])
    run_cmd(["minify", ARITH_PATH, "-o", "/tmp/arith_min2.json"])

    with open("/tmp/arith_min1.json") as f:
        m1 = json.load(f)
    with open("/tmp/arith_min2.json") as f:
        m2 = json.load(f)

    assert m1 == m2, "Minification is not deterministic"


def test_minify_complex_queries_roundtrip():
    """Multiple complex queries on minified docs produce same results as on originals."""
    run_cmd(["minify", ARITH_PATH, "-o", "/tmp/arith_minified.json"])
    run_cmd(["minify", LIST_PATH, "-o", "/tmp/list_minified.json"])
    cases = [
        (".s(induction).g#2.h#IHn'.type", ARITH_PATH, "/tmp/arith_minified.json"),
        (".s(Base case).ccl", ARITH_PATH, "/tmp/arith_minified.json"),
        (".s(Print).msg", ARITH_PATH, "/tmp/arith_minified.json"),
        (".s(induction).g#1", ARITH_PATH, "/tmp/arith_minified.json"),
        (".s(intros).h(list)", LIST_PATH, "/tmp/list_minified.json"),
        (".s(induction l1).g#2.h#IHl1'.type", LIST_PATH, "/tmp/list_minified.json"),
    ]
    for path, orig_file, min_file in cases:
        orig = run_query(path, orig_file)
        mini = run_query(path, min_file)
        assert orig == mini, f"Query mismatch for '{path}': {orig} vs {mini}"


# ===== jq filter generation =====

def run_jqgen(path_str, json_file):
    """Run jqgen to get the jq filter expression."""
    result = subprocess.run(
        ["python3", "/app/proofquery.py", "jqgen", path_str, json_file],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, f"jqgen failed (rc={result.returncode}): {result.stderr}"
    return result.stdout.strip()


def run_jq(filter_expr, json_file):
    """Run the system jq command with the given filter."""
    result = subprocess.run(
        ["jq", filter_expr, json_file],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, (
        f"jq failed (rc={result.returncode}):\n"
        f"  filter: {filter_expr}\n"
        f"  stderr: {result.stderr}"
    )
    return json.loads(result.stdout)


def assert_jq_equiv(path_str, json_file):
    """Assert jqgen filter produces same results as query when run through jq."""
    py_result = run_query(path_str, json_file)
    jq_filter = run_jqgen(path_str, json_file)
    jq_result = run_jq(jq_filter, json_file)
    assert py_result == jq_result, (
        f"jq/query mismatch for '{path_str}':\n"
        f"  Python query: {json.dumps(py_result, indent=2)}\n"
        f"  jq filter: {jq_filter}\n"
        f"  jq result: {json.dumps(jq_result, indent=2)}"
    )


def test_jq_sentence_literal():
    """jq filter for literal sentence match produces same result as query."""
    assert_jq_equiv(".s(induction)", ARITH_PATH)


def test_jq_sentence_fnmatch():
    """jq filter for fnmatch sentence match produces same result as query."""
    assert_jq_equiv(".s{Theorem*}", ARITH_PATH)


def test_jq_goal_by_position():
    """jq filter for goal selection by position produces same result."""
    assert_jq_equiv(".s(induction).g#2", ARITH_PATH)


def test_jq_hyp_by_name():
    """jq filter for hypothesis selection by name (with special char)."""
    assert_jq_equiv(".s(induction).g#2.h#IHn'", ARITH_PATH)


def test_jq_leaf_type():
    """jq filter for leaf type extraction through full path."""
    assert_jq_equiv(".s(induction).g#2.h#IHn'.type", ARITH_PATH)


def test_jq_implicit_goal_ccl():
    """jq filter with implicit goal default for conclusion leaf."""
    assert_jq_equiv(".s(Base case).ccl", ARITH_PATH)


def test_jq_message():
    """jq filter for message extraction from sentence responses."""
    assert_jq_equiv(".s(Print).msg", ARITH_PATH)


def test_jq_hyp_content():
    """jq filter for hypothesis content matching across files."""
    assert_jq_equiv(".s(intros).h(list)", LIST_PATH)


def test_jq_empty_result():
    """jq filter produces empty array for non-matching path."""
    assert_jq_equiv(".s(nonexistent_xyz)", ARITH_PATH)


def test_jq_goal_content():
    """jq filter for goal content matching with substring."""
    assert_jq_equiv(".s(simpl).g(m + 0)", ARITH_PATH)


def test_jq_input_leaf():
    """jq filter for .in leaf selector with fnmatch dot-escaping."""
    assert_jq_equiv(".s{Qed.}.in", ARITH_PATH)


def test_jq_list_proof_lemma():
    """jq filter for Lemma fnmatch in list proof."""
    assert_jq_equiv(".s{Lemma*}", LIST_PATH)


def test_jq_hyp_fnmatch_cross_file():
    """jq filter for fnmatch hypothesis matching in list proof."""
    assert_jq_equiv(".s(intros).h{list*}", LIST_PATH)


def test_jq_goal_position_beyond_range():
    """jq filter for goal position beyond range returns empty array."""
    assert_jq_equiv(".s(induction).g#99", ARITH_PATH)


# ===== Proof obligation DAG =====

def test_dag_arith_proof_count():
    """Arith file has 1 proof and 2 commands (Print, Check)."""
    dag = run_dag(ARITH_PATH)
    assert len(dag["proofs"]) == 1
    assert len(dag["commands"]) == 2
    assert dag["commands"][0]["effect"] == "info"
    assert dag["commands"][1]["effect"] == "info"


def test_dag_arith_goal_count():
    """Arith proof has 3 goals: root + 2 branches."""
    dag = run_dag(ARITH_PATH)
    proof = dag["proofs"][0]
    assert len(proof["goals"]) == 3


def test_dag_arith_step_count():
    """Arith proof has 13 tactic steps."""
    dag = run_dag(ARITH_PATH)
    proof = dag["proofs"][0]
    assert len(proof["steps"]) == 13


def test_dag_arith_tree_structure():
    """Arith proof tree: g0 branches into g1 and g2 (both leaves)."""
    dag = run_dag(ARITH_PATH)
    proof = dag["proofs"][0]
    goals = {g["id"]: g for g in proof["goals"]}

    # Root
    assert goals["g0"]["parent"] is None
    assert goals["g0"]["children"] == ["g1", "g2"]
    assert goals["g0"]["resolution"] == "branch"

    # Leaves
    assert goals["g1"]["parent"] == "g0"
    assert goals["g1"]["children"] == []
    assert goals["g1"]["resolution"] == "discharge"

    assert goals["g2"]["parent"] == "g0"
    assert goals["g2"]["children"] == []
    assert goals["g2"]["resolution"] == "discharge"


def test_dag_arith_effects():
    """Arith proof effects match expected sequence."""
    dag = run_dag(ARITH_PATH)
    effects = [s["effect"] for s in dag["proofs"][0]["steps"]]
    expected = [
        "declare",    # Theorem
        "noop",       # Proof.
        "branch",     # induction
        "intro",      # intro m (base)
        "transform",  # simpl
        "transform",  # rewrite
        "discharge",  # reflexivity
        "intro",      # intro m (inductive)
        "transform",  # simpl
        "transform",  # rewrite IHn'
        "transform",  # rewrite plus_n_Sm
        "discharge",  # reflexivity
        "close",      # Qed.
    ]
    assert effects == expected, f"Effects mismatch:\n  got:    {effects}\n  expect: {expected}"


def test_dag_arith_discharge_points():
    """Arith proof: g1 discharged at step 6, g2 at step 11."""
    dag = run_dag(ARITH_PATH)
    goals = {g["id"]: g for g in dag["proofs"][0]["goals"]}

    assert goals["g1"]["spawned_by"] == 2
    assert goals["g1"]["resolved_by"] == 6

    assert goals["g2"]["spawned_by"] == 2
    assert goals["g2"]["resolved_by"] == 11


def test_dag_arith_proof_name():
    """Arith proof name extracted correctly."""
    dag = run_dag(ARITH_PATH)
    assert dag["proofs"][0]["name"] == "add_comm"


def test_dag_list_structure():
    """List proof has 3 goals with correct tree structure."""
    dag = run_dag(LIST_PATH)
    assert len(dag["proofs"]) == 1
    assert len(dag["commands"]) == 5  # Check, Compute, Definition, Check, Eval

    proof = dag["proofs"][0]
    assert proof["name"] == "length_app"
    assert len(proof["goals"]) == 3

    goals = {g["id"]: g for g in proof["goals"]}
    assert goals["g0"]["children"] == ["g1", "g2"]
    assert goals["g0"]["resolution"] == "branch"
    assert goals["g1"]["resolution"] == "discharge"
    assert goals["g2"]["resolution"] == "discharge"


def test_dag_list_effects():
    """List proof effects match expected sequence."""
    dag = run_dag(LIST_PATH)
    effects = [s["effect"] for s in dag["proofs"][0]["steps"]]
    expected = [
        "declare",    # Lemma
        "noop",       # Proof.
        "intro",      # intros A l1 l2
        "branch",     # induction l1
        "transform",  # simpl (nil case)
        "discharge",  # reflexivity
        "transform",  # simpl (cons case)
        "transform",  # f_equal
        "discharge",  # exact IHl1'
        "close",      # Qed.
    ]
    assert effects == expected, f"Effects mismatch:\n  got:    {effects}\n  expect: {expected}"


def test_dag_bool_proof_count():
    """Bool file has 2 proofs and 0 commands."""
    dag = run_dag(BOOL_PATH)
    assert len(dag["proofs"]) == 2
    assert len(dag["commands"]) == 0


def test_dag_bool_proof_names():
    """Bool proof names extracted correctly."""
    dag = run_dag(BOOL_PATH)
    assert dag["proofs"][0]["name"] == "double_neg"
    assert dag["proofs"][1]["name"] == "andb_comm"


def test_dag_bool_double_neg_structure():
    """double_neg has 3 goals: 1 root branching into 2 leaves."""
    dag = run_dag(BOOL_PATH)
    proof = dag["proofs"][0]
    assert len(proof["goals"]) == 3

    goals = {g["id"]: g for g in proof["goals"]}
    assert goals["g0"]["children"] == ["g1", "g2"]
    assert goals["g0"]["resolution"] == "branch"
    assert goals["g1"]["resolution"] == "discharge"
    assert goals["g2"]["resolution"] == "discharge"


def test_dag_bool_andb_comm_goal_count():
    """andb_comm has 7 goals (nested branching, depth 2)."""
    dag = run_dag(BOOL_PATH)
    proof = dag["proofs"][1]
    assert len(proof["goals"]) == 7


def test_dag_bool_nested_tree():
    """andb_comm tree: g0->{g1,g2}, g1->{g3,g4}, g2->{g5,g6}."""
    dag = run_dag(BOOL_PATH)
    proof = dag["proofs"][1]
    goals = {g["id"]: g for g in proof["goals"]}

    # Root
    assert goals["g0"]["parent"] is None
    assert goals["g0"]["children"] == ["g1", "g2"]
    assert goals["g0"]["resolution"] == "branch"

    # Level 1
    assert goals["g1"]["parent"] == "g0"
    assert goals["g1"]["children"] == ["g3", "g4"]
    assert goals["g1"]["resolution"] == "branch"

    assert goals["g2"]["parent"] == "g0"
    assert goals["g2"]["children"] == ["g5", "g6"]
    assert goals["g2"]["resolution"] == "branch"

    # Level 2 (leaves)
    for gid in ["g3", "g4", "g5", "g6"]:
        assert goals[gid]["children"] == []
        assert goals[gid]["resolution"] == "discharge"

    assert goals["g3"]["parent"] == "g1"
    assert goals["g4"]["parent"] == "g1"
    assert goals["g5"]["parent"] == "g2"
    assert goals["g6"]["parent"] == "g2"


def test_dag_bool_andb_comm_effects():
    """andb_comm effects include nested branching and consecutive discharges."""
    dag = run_dag(BOOL_PATH)
    effects = [s["effect"] for s in dag["proofs"][1]["steps"]]
    expected = [
        "declare",    # Theorem andb_comm
        "noop",       # Proof.
        "branch",     # destruct a -> g1, g2
        "branch",     # destruct b -> g3, g4 (branch of g1)
        "discharge",  # reflexivity (g3)
        "transform",  # simpl (g4)
        "discharge",  # reflexivity (g4)
        "branch",     # destruct b -> g5, g6 (branch of g2)
        "transform",  # simpl (g5)
        "discharge",  # reflexivity (g5)
        "discharge",  # reflexivity (g6) -- consecutive discharge
        "close",      # Qed.
    ]
    assert effects == expected, f"Effects mismatch:\n  got:    {effects}\n  expect: {expected}"


def test_dag_bool_consecutive_discharge():
    """andb_comm has consecutive discharges at steps 9 and 10."""
    dag = run_dag(BOOL_PATH)
    steps = dag["proofs"][1]["steps"]
    assert steps[9]["effect"] == "discharge"
    assert steps[10]["effect"] == "discharge"


def test_dag_bool_andb_comm_spawned_resolved():
    """andb_comm: verify spawned_by and resolved_by for nested goals."""
    dag = run_dag(BOOL_PATH)
    goals = {g["id"]: g for g in dag["proofs"][1]["goals"]}

    # g0: spawned by declare (0), resolved by first destruct (2)
    assert goals["g0"]["spawned_by"] == 0
    assert goals["g0"]["resolved_by"] == 2

    # g1, g2: spawned by first destruct (2)
    assert goals["g1"]["spawned_by"] == 2
    assert goals["g2"]["spawned_by"] == 2

    # g1 resolved by nested destruct b (3)
    assert goals["g1"]["resolved_by"] == 3

    # g3, g4: spawned by nested destruct b (3)
    assert goals["g3"]["spawned_by"] == 3
    assert goals["g4"]["spawned_by"] == 3

    # g3 discharged at step 4, g4 discharged at step 6
    assert goals["g3"]["resolved_by"] == 4
    assert goals["g4"]["resolved_by"] == 6

    # g2 resolved by second destruct b (7)
    assert goals["g2"]["resolved_by"] == 7

    # g5, g6: spawned by second destruct b (7)
    assert goals["g5"]["spawned_by"] == 7
    assert goals["g6"]["spawned_by"] == 7

    # g5 discharged at step 9, g6 at step 10
    assert goals["g5"]["resolved_by"] == 9
    assert goals["g6"]["resolved_by"] == 10


def test_dag_on_minified():
    """DAG analysis works correctly on minified documents."""
    run_cmd(["minify", ARITH_PATH, "-o", "/tmp/arith_minified.json"])

    dag_orig = run_dag(ARITH_PATH)
    dag_mini = run_dag("/tmp/arith_minified.json")

    assert dag_orig == dag_mini, "DAG differs between original and minified input"


def test_dag_goal_conclusions():
    """DAG records correct initial conclusions for each goal."""
    dag = run_dag(ARITH_PATH)
    goals = {g["id"]: g for g in dag["proofs"][0]["goals"]}

    assert "n + m = m + n" in goals["g0"]["conclusion"]
    assert "0 + m = m + 0" in goals["g1"]["conclusion"]
    assert "S n'" in goals["g2"]["conclusion"]


def test_dag_invariants_arith():
    """Verify DAG invariants on arith proof."""
    dag = run_dag(ARITH_PATH)
    proof = dag["proofs"][0]
    goals = {g["id"]: g for g in proof["goals"]}

    for g in proof["goals"]:
        # resolved_by > spawned_by
        assert g["resolved_by"] > g["spawned_by"], (
            f"{g['id']}: resolved_by ({g['resolved_by']}) <= spawned_by ({g['spawned_by']})")

        # parent/children consistency
        if g["parent"] is not None:
            parent = goals[g["parent"]]
            assert g["id"] in parent["children"], (
                f"{g['id']} claims parent {g['parent']} but parent's children = {parent['children']}")

        for child_id in g["children"]:
            child = goals[child_id]
            assert child["parent"] == g["id"], (
                f"{g['id']} lists child {child_id} but child's parent = {child['parent']}")

        # leaf vs branch resolution
        if len(g["children"]) == 0:
            assert g["resolution"] == "discharge"
        else:
            assert g["resolution"] == "branch"

    # Root check
    assert goals["g0"]["parent"] is None


def test_dag_invariants_andb_comm():
    """Verify DAG invariants on andb_comm (nested branching) proof."""
    dag = run_dag(BOOL_PATH)
    proof = dag["proofs"][1]
    goals = {g["id"]: g for g in proof["goals"]}

    for g in proof["goals"]:
        assert g["resolved_by"] > g["spawned_by"]

        if g["parent"] is not None:
            parent = goals[g["parent"]]
            assert g["id"] in parent["children"]

        for child_id in g["children"]:
            child = goals[child_id]
            assert child["parent"] == g["id"]

        if len(g["children"]) == 0:
            assert g["resolution"] == "discharge"
        else:
            assert g["resolution"] == "branch"

    assert goals["g0"]["parent"] is None
