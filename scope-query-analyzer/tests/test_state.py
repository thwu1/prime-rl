"""
Tests for the Cursorless scope query compiler.

Validates compiled_scopes.json output: query validation via tree-sitter,
static scope analysis, predicate classification, cross-language matrix,
and query execution results against sample code.

"""

import json
import pytest
from pathlib import Path

REPORT_PATH = Path("/app/compiled_scopes.json")


@pytest.fixture(scope="module")
def report():
    assert REPORT_PATH.exists(), (
        f"Compiled scopes report not found at {REPORT_PATH}. "
        "Did you run the compiler?"
    )
    with open(REPORT_PATH) as f:
        data = json.load(f)
    return data


@pytest.fixture(scope="module")
def validation(report):
    return report["query_validation"]


@pytest.fixture(scope="module")
def imports(report):
    return report["imports"]


@pytest.fixture(scope="module")
def scope_types(report):
    return report["scope_types"]


@pytest.fixture(scope="module")
def facets(report):
    return report["facets"]


@pytest.fixture(scope="module")
def predicates(report):
    return report["predicates"]


@pytest.fixture(scope="module")
def node_types(report):
    return report["node_types"]


@pytest.fixture(scope="module")
def matrix(report):
    return report["cross_language_matrix"]


@pytest.fixture(scope="module")
def execution(report):
    return report["execution_results"]


# ============================================================
# Structure tests
# ============================================================

class TestReportStructure:
    def test_top_level_keys(self, report):
        required = {
            "query_validation", "imports", "scope_types", "facets",
            "predicates", "node_types", "cross_language_matrix",
            "execution_results",
        }
        assert required.issubset(set(report.keys())), (
            f"Missing top-level keys: {required - set(report.keys())}"
        )

    def test_all_files_present_in_validation(self, validation):
        expected = {"java.scm", "javascript.scm", "python.scm", "typescript.scm"}
        assert set(validation.keys()) == expected

    def test_all_files_present_in_scope_types(self, scope_types):
        expected = {"java.scm", "javascript.scm", "python.scm", "typescript.scm"}
        assert set(scope_types.keys()) == expected

    def test_all_files_present_in_node_types(self, node_types):
        expected = {"java.scm", "javascript.scm", "python.scm", "typescript.scm"}
        assert set(node_types.keys()) == expected


# ============================================================
# Query validation tests (tree-sitter)
# ============================================================

class TestQueryValidation:
    def test_python_valid(self, validation):
        assert validation["python.scm"]["valid"] is True

    def test_python_pattern_count(self, validation):
        assert validation["python.scm"]["pattern_count"] == 85

    def test_python_capture_count(self, validation):
        assert validation["python.scm"]["capture_count"] == 83

    def test_java_valid(self, validation):
        assert validation["java.scm"]["valid"] is True

    def test_java_pattern_count(self, validation):
        assert validation["java.scm"]["pattern_count"] == 77

    def test_java_capture_count(self, validation):
        assert validation["java.scm"]["capture_count"] == 83

    def test_javascript_valid(self, validation):
        assert validation["javascript.scm"]["valid"] is True

    def test_javascript_pattern_count(self, validation):
        assert validation["javascript.scm"]["pattern_count"] == 9

    def test_javascript_capture_count(self, validation):
        assert validation["javascript.scm"]["capture_count"] == 26

    def test_typescript_valid(self, validation):
        assert validation["typescript.scm"]["valid"] is True

    def test_typescript_pattern_count(self, validation):
        assert validation["typescript.scm"]["pattern_count"] == 1

    def test_typescript_capture_count(self, validation):
        assert validation["typescript.scm"]["capture_count"] == 3


# ============================================================
# Import tests
# ============================================================

class TestImports:
    def test_java_no_imports(self, imports):
        assert imports["java.scm"] == []

    def test_javascript_imports(self, imports):
        assert sorted(imports["javascript.scm"]) == [
            "javascript.core.scm",
            "javascript.jsx.scm",
        ]

    def test_python_imports(self, imports):
        assert imports["python.scm"] == ["python.fieldAccess.scm"]

    def test_typescript_imports(self, imports):
        assert imports["typescript.scm"] == ["typescript.core.scm"]


# ============================================================
# Scope type tests
# ============================================================

class TestScopeTypes:
    def test_python_scope_count(self, scope_types):
        assert len(scope_types["python.scm"]) == 24

    def test_python_scope_types_exact(self, scope_types):
        expected = [
            "anonymousFunction", "argumentList", "argumentOrParameter",
            "branch", "class", "collectionItem", "collectionKey",
            "comment", "condition", "disqualifyDelimiter",
            "functionCall", "functionCallee", "ifStatement",
            "interior", "list", "map", "name", "namedFunction",
            "pairDelimiter", "statement", "string", "textFragment",
            "type", "value",
        ]
        assert scope_types["python.scm"] == expected

    def test_java_scope_count(self, scope_types):
        assert len(scope_types["java.scm"]) == 22

    def test_java_scope_types_exact(self, scope_types):
        expected = [
            "anonymousFunction", "argumentList", "argumentOrParameter",
            "branch", "class", "collectionItem", "comment", "condition",
            "disqualifyDelimiter", "functionCall", "functionCallee",
            "ifStatement", "interior", "list", "map", "name",
            "namedFunction", "statement", "string", "textFragment",
            "type", "value",
        ]
        assert scope_types["java.scm"] == expected

    def test_javascript_scope_types(self, scope_types):
        expected = sorted([
            "argumentList", "argumentOrParameter", "name",
            "namedFunction", "statement", "value",
        ])
        assert scope_types["javascript.scm"] == expected

    def test_typescript_scope_types(self, scope_types):
        assert scope_types["typescript.scm"] == ["type"]

    def test_no_private_scopes(self, scope_types):
        for fname, scopes in scope_types.items():
            for scope in scopes:
                assert not scope.startswith("_"), (
                    f"Private scope '{scope}' found in {fname}"
                )

    def test_all_sorted(self, scope_types):
        for fname, scopes in scope_types.items():
            assert scopes == sorted(scopes), (
                f"Scope types not sorted in {fname}"
            )


# ============================================================
# Facet tests
# ============================================================

class TestFacets:
    def test_python_name_facets(self, facets):
        assert sorted(facets["python.scm"]["name"]) == [
            "domain", "iteration", "removal", "trailing",
        ]

    def test_python_branch_facets(self, facets):
        assert sorted(facets["python.scm"]["branch"]) == [
            "end", "iteration", "removal", "start",
        ]

    def test_python_value_facets(self, facets):
        assert sorted(facets["python.scm"]["value"]) == [
            "domain", "iteration", "leading",
        ]

    def test_python_interior_facets(self, facets):
        assert sorted(facets["python.scm"]["interior"]) == ["end", "start"]

    def test_python_statement_facets(self, facets):
        assert facets["python.scm"]["statement"] == ["iteration"]

    def test_java_branch_facets(self, facets):
        assert sorted(facets["java.scm"]["branch"]) == [
            "end", "iteration", "removal", "start",
        ]

    def test_java_condition_facets(self, facets):
        assert sorted(facets["java.scm"]["condition"]) == [
            "domain", "end", "iteration", "start",
        ]

    def test_java_type_facets(self, facets):
        assert sorted(facets["java.scm"]["type"]) == ["iteration", "removal"]

    def test_javascript_argumentList_facets(self, facets):
        assert sorted(facets["javascript.scm"]["argumentList"]) == [
            "domain", "removal",
        ]

    def test_typescript_no_facets(self, facets):
        assert facets["typescript.scm"] == {}

    def test_facets_all_sorted(self, facets):
        for fname, scope_facets in facets.items():
            for scope, flist in scope_facets.items():
                assert flist == sorted(flist), (
                    f"Facets for {scope} in {fname} not sorted"
                )


# ============================================================
# Predicate classification tests
# ============================================================

class TestPredicates:
    def test_has_filters_and_directives(self, predicates):
        assert "filters" in predicates
        assert "directives" in predicates

    def test_filter_count(self, predicates):
        assert len(predicates["filters"]) == 4

    def test_directive_count(self, predicates):
        assert len(predicates["directives"]) == 6

    def test_not_parent_type_is_filter(self, predicates):
        assert predicates["filters"].get("#not-parent-type?") == 8

    def test_not_type_is_filter(self, predicates):
        assert predicates["filters"].get("#not-type?") == 8

    def test_type_is_filter(self, predicates):
        assert predicates["filters"].get("#type?") == 2

    def test_match_is_filter(self, predicates):
        assert predicates["filters"].get("#match?") == 1

    def test_child_range_is_directive(self, predicates):
        assert predicates["directives"].get("#child-range!") == 13

    def test_document_range_is_directive(self, predicates):
        assert predicates["directives"].get("#document-range!") == 4

    def test_insertion_delimiter_is_directive(self, predicates):
        assert predicates["directives"].get("#insertion-delimiter!") == 7

    def test_empty_single_multi_is_directive(self, predicates):
        assert predicates["directives"].get("#empty-single-multi-delimiter!") == 7

    def test_single_or_multi_is_directive(self, predicates):
        assert predicates["directives"].get("#single-or-multi-line-delimiter!") == 8

    def test_character_range_is_directive(self, predicates):
        assert predicates["directives"].get("#character-range!") == 1

    def test_total_filter_occurrences(self, predicates):
        total = sum(predicates["filters"].values())
        assert total == 19

    def test_total_directive_occurrences(self, predicates):
        total = sum(predicates["directives"].values())
        assert total == 40

    def test_no_filter_in_directives(self, predicates):
        for key in predicates["directives"]:
            assert key.endswith("!"), f"Non-directive {key} in directives"

    def test_no_directive_in_filters(self, predicates):
        for key in predicates["filters"]:
            assert key.endswith("?"), f"Non-filter {key} in filters"


# ============================================================
# Node type tests
# ============================================================

class TestNodeTypes:
    def test_python_node_type_count(self, node_types):
        assert len(node_types["python.scm"]) == 63

    def test_python_has_key_node_types(self, node_types):
        required = {
            "function_definition", "class_definition", "assignment",
            "augmented_assignment", "for_statement", "while_statement",
            "if_statement", "try_statement", "return_statement",
            "call", "lambda", "dictionary", "list",
            "module", "block", "comment", "string",
            "conditional_expression", "match_statement", "case_clause",
        }
        assert required.issubset(set(node_types["python.scm"]))

    def test_python_no_except_group_clause(self, node_types):
        assert "except_group_clause" not in node_types["python.scm"]

    def test_java_node_type_count(self, node_types):
        assert len(node_types["java.scm"]) == 66

    def test_java_has_key_node_types(self, node_types):
        required = {
            "class_declaration", "method_declaration",
            "constructor_declaration", "enum_declaration",
            "interface_declaration", "if_statement",
            "for_statement", "while_statement", "try_statement",
            "lambda_expression", "program",
        }
        assert required.issubset(set(node_types["java.scm"]))

    def test_javascript_node_types(self, node_types):
        expected = sorted([
            "arrow_function", "assignment_pattern", "catch_clause",
            "field_definition", "formal_parameters",
            "function_expression", "generator_function",
            "identifier", "rest_pattern",
        ])
        assert node_types["javascript.scm"] == expected

    def test_typescript_node_types(self, node_types):
        assert sorted(node_types["typescript.scm"]) == [
            "type_arguments", "type_assertion",
        ]

    def test_no_wildcard_in_node_types(self, node_types):
        for fname, ntypes in node_types.items():
            assert "_" not in ntypes, f"Wildcard _ found in {fname}"

    def test_no_predicates_in_node_types(self, node_types):
        for fname, ntypes in node_types.items():
            for nt in ntypes:
                assert not nt.startswith("#"), (
                    f"Predicate {nt} found in node_types of {fname}"
                )

    def test_all_node_types_sorted(self, node_types):
        for fname, ntypes in node_types.items():
            assert ntypes == sorted(ntypes), (
                f"Node types not sorted in {fname}"
            )


# ============================================================
# Cross-language matrix tests
# ============================================================

class TestCrossLanguageMatrix:
    def test_statement_languages(self, matrix):
        assert sorted(matrix["statement"]) == [
            "java.scm", "javascript.scm", "python.scm",
        ]

    def test_type_languages(self, matrix):
        assert sorted(matrix["type"]) == [
            "java.scm", "python.scm", "typescript.scm",
        ]

    def test_collectionKey_only_python(self, matrix):
        assert matrix["collectionKey"] == ["python.scm"]

    def test_pairDelimiter_only_python(self, matrix):
        assert matrix["pairDelimiter"] == ["python.scm"]

    def test_anonymousFunction_languages(self, matrix):
        assert sorted(matrix["anonymousFunction"]) == [
            "java.scm", "python.scm",
        ]

    def test_name_languages(self, matrix):
        assert sorted(matrix["name"]) == [
            "java.scm", "javascript.scm", "python.scm",
        ]

    def test_namedFunction_languages(self, matrix):
        assert sorted(matrix["namedFunction"]) == [
            "java.scm", "javascript.scm", "python.scm",
        ]

    def test_value_languages(self, matrix):
        assert sorted(matrix["value"]) == [
            "java.scm", "javascript.scm", "python.scm",
        ]

    def test_total_scope_types_in_matrix(self, matrix):
        assert len(matrix) == 24

    def test_all_matrix_lists_sorted(self, matrix):
        for scope, langs in matrix.items():
            assert langs == sorted(langs), (
                f"Languages for {scope} not sorted in matrix"
            )


# ============================================================
# Execution results tests
# ============================================================

class TestExecutionResults:
    def test_all_files_present(self, execution):
        expected = {"java.scm", "javascript.scm", "python.scm", "typescript.scm"}
        assert set(execution.keys()) == expected

    def test_python_total_hits(self, execution):
        assert execution["python.scm"]["total_capture_hits"] == 103

    def test_python_unique_captures(self, execution):
        assert execution["python.scm"]["unique_captures_matched"] == 45

    def test_python_scope_types_matched(self, execution):
        expected = [
            "argumentList", "argumentOrParameter", "branch", "class",
            "condition", "disqualifyDelimiter", "ifStatement", "interior",
            "name", "namedFunction", "statement", "type", "value",
        ]
        assert execution["python.scm"]["scope_types_matched"] == expected

    def test_java_total_hits(self, execution):
        assert execution["java.scm"]["total_capture_hits"] == 61

    def test_java_unique_captures(self, execution):
        assert execution["java.scm"]["unique_captures_matched"] == 37

    def test_java_scope_types_matched(self, execution):
        expected = [
            "argumentList", "argumentOrParameter", "class", "interior",
            "name", "namedFunction", "statement", "type", "value",
        ]
        assert execution["java.scm"]["scope_types_matched"] == expected

    def test_javascript_total_hits(self, execution):
        assert execution["javascript.scm"]["total_capture_hits"] == 49

    def test_javascript_unique_captures(self, execution):
        assert execution["javascript.scm"]["unique_captures_matched"] == 24

    def test_javascript_scope_types_matched(self, execution):
        expected = [
            "argumentList", "argumentOrParameter", "name",
            "namedFunction", "statement", "value",
        ]
        assert execution["javascript.scm"]["scope_types_matched"] == expected

    def test_typescript_total_hits(self, execution):
        assert execution["typescript.scm"]["total_capture_hits"] == 3

    def test_typescript_unique_captures(self, execution):
        assert execution["typescript.scm"]["unique_captures_matched"] == 3

    def test_typescript_scope_types_matched(self, execution):
        assert execution["typescript.scm"]["scope_types_matched"] == ["type"]
