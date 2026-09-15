
import json
import os
import shutil
import subprocess
import tempfile

import pytest

RESULTS_PATH = "/app/results.json"
SCORER_PATH = "/app/scorer.py"

REQUIRED_CASES = {
    "case_identical", "case_unchanged", "case_partial",
    "case_over_patched", "case_with_macros",
}
SCORE_FIELDS = [
    "ast_similarity", "function_accuracy", "call_accuracy",
    "node_accuracy", "variable_accuracy", "composite_score",
]
ALL_REQUIRED_FIELDS = SCORE_FIELDS + [
    "migration_type", "changed_symbols", "node_type_details",
]
VALID_MIGRATION_TYPES = {"rename", "api_migration", "deprecation", "structural", "refactor"}


@pytest.fixture(scope="session")
def results():
    assert os.path.exists(RESULTS_PATH), f"Results file not found at {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        return json.load(f)


# -- Structure ----------------------------------------------------------------


class TestStructure:
    def test_results_file_exists(self):
        assert os.path.exists(RESULTS_PATH)

    def test_has_cases_key(self, results):
        assert "cases" in results

    def test_all_required_cases_present(self, results):
        assert REQUIRED_CASES.issubset(set(results["cases"].keys())), (
            f"Missing cases: {REQUIRED_CASES - set(results['cases'].keys())}"
        )

    def test_each_case_has_required_fields(self, results):
        for name, case in results["cases"].items():
            for field in ALL_REQUIRED_FIELDS:
                assert field in case, f"Missing '{field}' in case '{name}'"


# -- Score bounds -------------------------------------------------------------


class TestScoreBounds:
    def test_all_scores_between_zero_and_one(self, results):
        for name, case in results["cases"].items():
            for field in SCORE_FIELDS:
                val = case[field]
                assert isinstance(val, (int, float)), (
                    f"{field} in {name} is not numeric: {type(val)}"
                )
                assert 0.0 <= val <= 1.0, (
                    f"{field}={val} out of [0,1] in case '{name}'"
                )


# -- Perfect case -------------------------------------------------------------


class TestPerfectCase:
    def test_composite_score_is_one(self, results):
        case = results["cases"]["case_identical"]
        assert case["composite_score"] == pytest.approx(1.0, abs=1e-6)

    def test_all_sub_metrics_are_one(self, results):
        case = results["cases"]["case_identical"]
        for field in SCORE_FIELDS[:-1]:  # exclude composite_score
            assert case[field] == pytest.approx(1.0, abs=1e-6), (
                f"case_identical: {field}={case[field]}, expected 1.0"
            )


# -- Unchanged case -----------------------------------------------------------


class TestUnchangedCase:
    def test_composite_below_half(self, results):
        case = results["cases"]["case_unchanged"]
        assert case["composite_score"] < 0.5, (
            f"Unchanged candidate should score < 0.5, got {case['composite_score']}"
        )

    def test_ast_similarity_below_one(self, results):
        case = results["cases"]["case_unchanged"]
        assert case["ast_similarity"] < 1.0


# -- Partial case -------------------------------------------------------------


class TestPartialCase:
    def test_above_unchanged(self, results):
        partial = results["cases"]["case_partial"]["composite_score"]
        unchanged = results["cases"]["case_unchanged"]["composite_score"]
        assert partial > unchanged, (
            f"Partial ({partial}) should exceed unchanged ({unchanged})"
        )

    def test_below_perfect(self, results):
        assert results["cases"]["case_partial"]["composite_score"] < 1.0


# -- Over-patched case --------------------------------------------------------


class TestOverPatchedCase:
    def test_below_perfect(self, results):
        case = results["cases"]["case_over_patched"]
        assert case["composite_score"] < 1.0

    def test_above_zero(self, results):
        case = results["cases"]["case_over_patched"]
        assert case["composite_score"] > 0.0


# -- Composite formula --------------------------------------------------------


class TestCompositeFormula:
    WEIGHTS = [0.30, 0.25, 0.20, 0.15, 0.10]

    def test_weighted_sum_matches(self, results):
        metrics = SCORE_FIELDS[:-1]  # the five sub-metrics
        for name, case in results["cases"].items():
            expected = sum(
                w * case[m] for w, m in zip(self.WEIGHTS, metrics)
            )
            assert case["composite_score"] == pytest.approx(expected, abs=1e-4), (
                f"Composite mismatch in '{name}': "
                f"got {case['composite_score']}, expected {expected}"
            )


# -- Migration type -----------------------------------------------------------


class TestMigrationType:
    def test_valid_types(self, results):
        for name, case in results["cases"].items():
            assert case["migration_type"] in VALID_MIGRATION_TYPES, (
                f"Invalid migration type '{case['migration_type']}' in '{name}'"
            )


# -- Changed symbols ----------------------------------------------------------


class TestChangedSymbols:
    def test_structure(self, results):
        for name, case in results["cases"].items():
            syms = case["changed_symbols"]
            for key in ("added", "removed", "modified"):
                assert key in syms, f"Missing '{key}' in changed_symbols of '{name}'"
                assert isinstance(syms[key], list), (
                    f"changed_symbols['{key}'] should be list in '{name}'"
                )

    def test_identical_case_detects_changes(self, results):
        syms = results["cases"]["case_identical"]["changed_symbols"]
        total = len(syms["added"]) + len(syms["removed"]) + len(syms["modified"])
        assert total > 0, "case_identical should detect symbol changes between base and reference"

    def test_removed_symbols_in_identical(self, results):
        removed = set(results["cases"]["case_identical"]["changed_symbols"]["removed"])
        assert "old_register" in removed or "old_unregister" in removed, (
            "Should detect removal of old_register or old_unregister"
        )

    def test_added_symbols_in_identical(self, results):
        added = set(results["cases"]["case_identical"]["changed_symbols"]["added"])
        assert "validate_device" in added or "new_register" in added, (
            "Should detect addition of validate_device or new_register"
        )


# -- Node type details --------------------------------------------------------


class TestNodeTypeDetails:
    def test_structure(self, results):
        for name, case in results["cases"].items():
            details = case["node_type_details"]
            assert isinstance(details, dict), (
                f"node_type_details should be dict in '{name}'"
            )
            for type_name, info in details.items():
                for key in ("delta_ref", "delta_gen", "similarity"):
                    assert key in info, (
                        f"Missing '{key}' in node_type_details['{type_name}'] of '{name}'"
                    )

    def test_perfect_case_deltas_match(self, results):
        details = results["cases"]["case_identical"]["node_type_details"]
        for type_name, info in details.items():
            assert info["delta_ref"] == info["delta_gen"], (
                f"Perfect case: deltas should match for '{type_name}', "
                f"got ref={info['delta_ref']} gen={info['delta_gen']}"
            )
            assert info["similarity"] == pytest.approx(1.0, abs=1e-6), (
                f"Perfect case: similarity should be 1.0 for '{type_name}'"
            )

    def test_unchanged_has_low_similarity(self, results):
        details = results["cases"]["case_unchanged"]["node_type_details"]
        assert len(details) > 0, "Unchanged case should have node type details"
        sims = [info["similarity"] for info in details.values()]
        assert min(sims) < 0.5, (
            f"Unchanged case should have some low similarities, got min={min(sims)}"
        )


# -- Scorer implementation ----------------------------------------------------


class TestScorerImplementation:
    def test_scorer_file_exists(self):
        assert os.path.exists(SCORER_PATH), "Scorer not found at /app/scorer.py"

    def test_scorer_uses_parser(self):
        with open(SCORER_PATH) as f:
            source = f.read()
        parser_keywords = [
            "pycparser", "tree_sitter", "tree-sitter", "clang",
            "CParser", "Parser", "parse",
        ]
        assert any(kw in source for kw in parser_keywords), (
            "Scorer should use a C parser library"
        )

    def test_scorer_has_delta_logic(self):
        with open(SCORER_PATH) as f:
            source = f.read().lower()
        assert "delta" in source or "count" in source, (
            "Scorer should compute node count deltas"
        )


# -- Macros case --------------------------------------------------------------


class TestMacrosCase:
    def test_macros_valid_scores(self, results):
        case = results["cases"]["case_with_macros"]
        for field in SCORE_FIELDS:
            assert 0.0 <= case[field] <= 1.0

    def test_macros_below_perfect(self, results):
        case = results["cases"]["case_with_macros"]
        assert case["composite_score"] < 1.0, (
            "Macros case candidate differs from reference, should score < 1.0"
        )

    def test_macros_above_zero(self, results):
        case = results["cases"]["case_with_macros"]
        assert case["composite_score"] > 0.0


# -- Dynamic cases (anti-hardcode) --------------------------------------------


class TestDynamicCase:
    """Verify scorer generalizes to unseen cases generated at test time."""

    def _run_scorer(self, case_dir):
        result = subprocess.run(
            ["python3", SCORER_PATH, case_dir],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"Scorer failed on dynamic case: {result.stderr}"
        return json.loads(result.stdout)

    def _make_case(self, base_code, ref_code, cand_code):
        case_dir = tempfile.mkdtemp(prefix="tbench_dynamic_")
        for name, code in [
            ("base.c", base_code),
            ("reference.c", ref_code),
            ("candidate.c", cand_code),
        ]:
            with open(os.path.join(case_dir, name), "w") as f:
                f.write(code)
        with open(os.path.join(case_dir, "metadata.json"), "w") as f:
            json.dump({"description": "dynamic test case"}, f)
        return case_dir

    def test_perfect_match_dynamic(self):
        base = "int foo(int x) { return x + 1; }\nint main(void) { return foo(0); }\n"
        ref = "int bar(int x, int y) { return x + y; }\nint main(void) { return bar(0, 1); }\n"
        case_dir = self._make_case(base, ref, ref)
        try:
            out = self._run_scorer(case_dir)
            assert out["composite_score"] == pytest.approx(1.0, abs=1e-6), (
                f"Dynamic perfect match should score 1.0, got {out['composite_score']}"
            )
            for field in SCORE_FIELDS[:-1]:
                assert out[field] == pytest.approx(1.0, abs=1e-6), (
                    f"Dynamic perfect match: {field}={out[field]}, expected 1.0"
                )
        finally:
            shutil.rmtree(case_dir, ignore_errors=True)

    def test_no_change_dynamic(self):
        base = "int compute(int a, int b) { return a * b; }\n"
        ref = (
            "int compute_v2(int a, int b, int c) {\n"
            "    if (c > 0) return a * b + c;\n"
            "    return a * b;\n"
            "}\n"
        )
        case_dir = self._make_case(base, ref, base)
        try:
            out = self._run_scorer(case_dir)
            assert out["composite_score"] < 0.5, (
                f"Dynamic no-change should score < 0.5, got {out['composite_score']}"
            )
        finally:
            shutil.rmtree(case_dir, ignore_errors=True)

    def test_output_structure_dynamic(self):
        base = "void init(void) { }\n"
        ref = "int init(int flags) { if (flags < 0) return -1; return 0; }\n"
        cand = "int init(int flags) { return 0; }\n"
        case_dir = self._make_case(base, ref, cand)
        try:
            out = self._run_scorer(case_dir)
            for field in ALL_REQUIRED_FIELDS:
                assert field in out, f"Dynamic case missing field '{field}'"
            for field in SCORE_FIELDS:
                assert 0.0 <= out[field] <= 1.0, (
                    f"Dynamic case: {field}={out[field]} out of bounds"
                )
            assert out["migration_type"] in VALID_MIGRATION_TYPES
            syms = out["changed_symbols"]
            for key in ("added", "removed", "modified"):
                assert isinstance(syms[key], list)
        finally:
            shutil.rmtree(case_dir, ignore_errors=True)

    def test_partial_score_ordering_dynamic(self):
        """Verify partial changes score between no-change and perfect."""
        base = (
            "int old_api(int x) { return x; }\n"
            "int process(int val) { return old_api(val) + 1; }\n"
        )
        ref = (
            "int new_api(int x, int y) { return x + y; }\n"
            "int validate(int x) { if (x < 0) return 0; return 1; }\n"
            "int process(int val) {\n"
            "    if (!validate(val)) return -1;\n"
            "    return new_api(val, 0) + 1;\n"
            "}\n"
        )
        # Partial candidate: has the new function but not the validation
        cand = (
            "int new_api(int x, int y) { return x + y; }\n"
            "int process(int val) { return new_api(val, 0) + 1; }\n"
        )
        case_dir_nochange = self._make_case(base, ref, base)
        case_dir_partial = self._make_case(base, ref, cand)
        case_dir_perfect = self._make_case(base, ref, ref)
        try:
            nochange = self._run_scorer(case_dir_nochange)["composite_score"]
            partial = self._run_scorer(case_dir_partial)["composite_score"]
            perfect = self._run_scorer(case_dir_perfect)["composite_score"]
            assert nochange < partial < perfect, (
                f"Expected nochange ({nochange}) < partial ({partial}) < perfect ({perfect})"
            )
        finally:
            shutil.rmtree(case_dir_nochange, ignore_errors=True)
            shutil.rmtree(case_dir_partial, ignore_errors=True)
            shutil.rmtree(case_dir_perfect, ignore_errors=True)
