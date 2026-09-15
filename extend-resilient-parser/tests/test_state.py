"""
Tests for the extended resilient LL parser (L2 grammar).
Verifies array literals, index expressions, ternary conditionals,
for-in loops, and their interactions with the existing parser features.
"""

import subprocess
import pytest

# ---------------------------------------------------------------------------
# Build fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def build_parser():
    result = subprocess.run(
        ["cargo", "build", "--release"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, f"cargo build failed:\n{result.stderr}"

PARSE_BIN = "/app/target/release/parse"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_parser(input_text: str):
    """Run the parser binary and return (stdout, stderr, returncode)."""
    result = subprocess.run(
        [PARSE_BIN],
        input=input_text,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout, result.stderr, result.returncode


def parse_tree(text: str):
    """Parse CST debug output into a nested dict tree."""
    lines = text.rstrip().split("\n")
    root = {"name": "ROOT", "children": [], "indent": -2}
    stack = [root]
    for line in lines:
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        name = line.strip()
        node = {"name": name, "children": [], "indent": indent}
        while stack[-1]["indent"] >= indent:
            stack.pop()
        stack[-1]["children"].append(node)
        if not name.startswith("'"):
            stack.append(node)
    return root["children"][0] if root["children"] else None


def find_all(tree, kind):
    """Find all nodes whose name matches *kind*, depth-first."""
    results = []
    if tree["name"] == kind:
        results.append(tree)
    for child in tree["children"]:
        results.extend(find_all(child, kind))
    return results


def child_names(tree):
    """Return a list of direct-child names."""
    return [c["name"] for c in tree["children"]]


# ---------------------------------------------------------------------------
# Tests: Regression — existing features must still work
# ---------------------------------------------------------------------------

class TestRegression:
    def test_base_arithmetic(self):
        stdout, _, rc = run_parser("fn f() { let x = 1 + 2 * 3; }")
        assert rc == 0
        tree = parse_tree(stdout)
        assert tree["name"] == "File"
        assert len(find_all(tree, "Fn")) == 1
        binaries = find_all(tree, "ExprBinary")
        assert len(binaries) == 2

    def test_function_call(self):
        stdout, _, rc = run_parser("fn f() { g(1, 2); }")
        assert rc == 0
        tree = parse_tree(stdout)
        assert len(find_all(tree, "ExprCall")) == 1

    def test_if_else(self):
        stdout, _, rc = run_parser(
            "fn f() { let z = if a { 1; } else { 2; }; }"
        )
        assert rc == 0
        tree = parse_tree(stdout)
        ifs = find_all(tree, "ExprIf")
        assert len(ifs) == 1
        blocks = [c for c in ifs[0]["children"] if c["name"] == "Block"]
        assert len(blocks) == 2

    def test_while_no_semicolon(self):
        stdout, _, rc = run_parser(
            "fn f() { while x { let a = 1; } let b = 2; }"
        )
        assert rc == 0
        tree = parse_tree(stdout)
        assert len(find_all(tree, "ExprWhile")) == 1
        assert len(find_all(tree, "StmtLet")) == 2

    def test_unary_precedence(self):
        stdout, _, rc = run_parser("fn f() { let x = -a + b; }")
        assert rc == 0
        tree = parse_tree(stdout)
        stmt_let = find_all(tree, "StmtLet")[0]
        top = [c for c in stmt_let["children"] if c["name"] == "ExprBinary"]
        assert len(top) == 1
        assert "ExprUnary" in child_names(top[0])

    def test_logical_precedence(self):
        """a || b && c => a || (b && c)."""
        stdout, _, rc = run_parser("fn f() { let x = a || b && c; }")
        assert rc == 0
        tree = parse_tree(stdout)
        stmt_let = find_all(tree, "StmtLet")[0]
        top = [c for c in stmt_let["children"] if c["name"] == "ExprBinary"]
        assert len(top) == 1
        assert "'||'" in child_names(top[0])


# ---------------------------------------------------------------------------
# Tests: Array literals
# ---------------------------------------------------------------------------

class TestArrayLiteral:
    def test_array_basic(self):
        stdout, _, rc = run_parser("fn f() { let x = [1, 2, 3]; }")
        assert rc == 0
        tree = parse_tree(stdout)
        arrays = find_all(tree, "ExprArray")
        assert len(arrays) == 1
        cn = child_names(arrays[0])
        assert "'['" in cn
        assert "']'" in cn
        lits = [c for c in arrays[0]["children"] if c["name"] == "ExprLiteral"]
        assert len(lits) == 3

    def test_array_empty(self):
        stdout, _, rc = run_parser("fn f() { let x = []; }")
        assert rc == 0
        tree = parse_tree(stdout)
        arrays = find_all(tree, "ExprArray")
        assert len(arrays) == 1
        lits = [c for c in arrays[0]["children"] if c["name"] == "ExprLiteral"]
        assert len(lits) == 0

    def test_array_single_element(self):
        stdout, _, rc = run_parser("fn f() { let x = [42]; }")
        assert rc == 0
        tree = parse_tree(stdout)
        arrays = find_all(tree, "ExprArray")
        assert len(arrays) == 1
        lits = [c for c in arrays[0]["children"] if c["name"] == "ExprLiteral"]
        assert len(lits) == 1

    def test_array_nested(self):
        stdout, _, rc = run_parser("fn f() { let x = [[1, 2], [3]]; }")
        assert rc == 0
        tree = parse_tree(stdout)
        arrays = find_all(tree, "ExprArray")
        assert len(arrays) == 3  # outer + two inner

    def test_array_with_expressions(self):
        stdout, _, rc = run_parser("fn f() { let x = [a + b, c * d]; }")
        assert rc == 0
        tree = parse_tree(stdout)
        arrays = find_all(tree, "ExprArray")
        assert len(arrays) == 1
        bins = [c for c in arrays[0]["children"] if c["name"] == "ExprBinary"]
        assert len(bins) == 2

    def test_array_trailing_comma(self):
        stdout, _, rc = run_parser("fn f() { let x = [1, 2,]; }")
        assert rc == 0
        tree = parse_tree(stdout)
        arrays = find_all(tree, "ExprArray")
        assert len(arrays) == 1
        lits = [c for c in arrays[0]["children"] if c["name"] == "ExprLiteral"]
        assert len(lits) == 2


# ---------------------------------------------------------------------------
# Tests: Index expressions
# ---------------------------------------------------------------------------

class TestIndexExpression:
    def test_index_basic(self):
        stdout, _, rc = run_parser("fn f() { let x = a[0]; }")
        assert rc == 0
        tree = parse_tree(stdout)
        indices = find_all(tree, "ExprIndex")
        assert len(indices) == 1
        cn = child_names(indices[0])
        assert "ExprName" in cn
        assert "'['" in cn
        assert "']'" in cn

    def test_index_chained(self):
        """a[0][1] => ExprIndex(ExprIndex(a, 0), 1)"""
        stdout, _, rc = run_parser("fn f() { let x = a[0][1]; }")
        assert rc == 0
        tree = parse_tree(stdout)
        indices = find_all(tree, "ExprIndex")
        assert len(indices) == 2
        # Outer index should contain inner index as direct child
        stmt_let = find_all(tree, "StmtLet")[0]
        top = [c for c in stmt_let["children"] if c["name"] == "ExprIndex"]
        assert len(top) == 1
        inner = [c for c in top[0]["children"] if c["name"] == "ExprIndex"]
        assert len(inner) == 1

    def test_index_on_array_literal(self):
        """[1, 2, 3][0] => ExprIndex(ExprArray(...), 0)"""
        stdout, _, rc = run_parser("fn f() { let x = [1, 2, 3][0]; }")
        assert rc == 0
        tree = parse_tree(stdout)
        indices = find_all(tree, "ExprIndex")
        assert len(indices) == 1
        assert "ExprArray" in child_names(indices[0])

    def test_index_on_function_call(self):
        """f()[0] => ExprIndex(ExprCall(...), 0)"""
        stdout, _, rc = run_parser("fn f() { let x = g()[0]; }")
        assert rc == 0
        tree = parse_tree(stdout)
        indices = find_all(tree, "ExprIndex")
        assert len(indices) == 1
        assert "ExprCall" in child_names(indices[0])

    def test_call_on_index(self):
        """a[0](x) => ExprCall(ExprIndex(a, 0), ArgList(x))"""
        stdout, _, rc = run_parser("fn f() { let x = a[0](1); }")
        assert rc == 0
        tree = parse_tree(stdout)
        calls = find_all(tree, "ExprCall")
        assert len(calls) == 1
        assert "ExprIndex" in child_names(calls[0])

    def test_index_higher_than_binary(self):
        """a + b[0] => a + (b[0])"""
        stdout, _, rc = run_parser("fn f() { let x = a + b[0]; }")
        assert rc == 0
        tree = parse_tree(stdout)
        stmt_let = find_all(tree, "StmtLet")[0]
        top = [c for c in stmt_let["children"] if c["name"] == "ExprBinary"]
        assert len(top) == 1
        assert "'+'" in child_names(top[0])
        # ExprIndex should be inside ExprBinary, not outside
        idx_in_bin = [c for c in top[0]["children"] if c["name"] == "ExprIndex"]
        assert len(idx_in_bin) == 1

    def test_index_with_complex_subscript(self):
        """a[b + c] => ExprIndex with ExprBinary inside brackets"""
        stdout, _, rc = run_parser("fn f() { let x = a[b + c]; }")
        assert rc == 0
        tree = parse_tree(stdout)
        indices = find_all(tree, "ExprIndex")
        assert len(indices) == 1
        bins = find_all(indices[0], "ExprBinary")
        assert len(bins) == 1


# ---------------------------------------------------------------------------
# Tests: Ternary conditional expression
# ---------------------------------------------------------------------------

class TestTernaryExpression:
    def test_ternary_basic(self):
        stdout, _, rc = run_parser("fn f() { let x = a ? b : c; }")
        assert rc == 0
        tree = parse_tree(stdout)
        terns = find_all(tree, "ExprTernary")
        assert len(terns) == 1
        cn = child_names(terns[0])
        assert "'?'" in cn
        assert "':'" in cn
        names = [c for c in terns[0]["children"] if c["name"] == "ExprName"]
        assert len(names) == 3

    def test_ternary_right_associative(self):
        """a ? b : c ? d : e => a ? b : (c ? d : e)"""
        stdout, _, rc = run_parser("fn f() { let x = a ? b : c ? d : e; }")
        assert rc == 0
        tree = parse_tree(stdout)
        terns = find_all(tree, "ExprTernary")
        assert len(terns) == 2

        stmt_let = find_all(tree, "StmtLet")[0]
        top = [c for c in stmt_let["children"] if c["name"] == "ExprTernary"]
        assert len(top) == 1
        outer = top[0]

        cn = child_names(outer)
        # Right-associative: condition=ExprName, ?, then=ExprName, :, else=ExprTernary
        assert cn[0] == "ExprName"       # a (condition)
        assert cn[1] == "'?'"
        assert cn[2] == "ExprName"       # b (then)
        assert cn[3] == "':'"
        assert cn[4] == "ExprTernary"    # c ? d : e (else — RIGHT-assoc)

    def test_ternary_nested_in_then(self):
        """a ? b ? c : d : e => a ? (b ? c : d) : e"""
        stdout, _, rc = run_parser("fn f() { let x = a ? b ? c : d : e; }")
        assert rc == 0
        tree = parse_tree(stdout)
        terns = find_all(tree, "ExprTernary")
        assert len(terns) == 2

        stmt_let = find_all(tree, "StmtLet")[0]
        top = [c for c in stmt_let["children"] if c["name"] == "ExprTernary"]
        assert len(top) == 1
        outer = top[0]

        cn = child_names(outer)
        # The "then" branch contains the inner ternary
        assert cn[0] == "ExprName"       # a
        assert cn[1] == "'?'"
        assert cn[2] == "ExprTernary"    # b ? c : d (nested in then)
        assert cn[3] == "':'"
        assert cn[4] == "ExprName"       # e

    def test_ternary_lower_than_or(self):
        """a || b ? c : d => (a || b) ? c : d"""
        stdout, _, rc = run_parser("fn f() { let x = a || b ? c : d; }")
        assert rc == 0
        tree = parse_tree(stdout)
        stmt_let = find_all(tree, "StmtLet")[0]
        top = [c for c in stmt_let["children"] if c["name"] == "ExprTernary"]
        assert len(top) == 1
        tern = top[0]
        # The condition should be an ExprBinary with ||
        cond_bins = [c for c in tern["children"] if c["name"] == "ExprBinary"]
        assert len(cond_bins) == 1
        assert "'||'" in child_names(cond_bins[0])

    def test_ternary_with_arithmetic(self):
        """a + b ? c * d : e - f"""
        stdout, _, rc = run_parser("fn f() { let x = a + b ? c * d : e - f; }")
        assert rc == 0
        tree = parse_tree(stdout)
        terns = find_all(tree, "ExprTernary")
        assert len(terns) == 1
        # All three operands of ternary should be ExprBinary
        bins = [c for c in terns[0]["children"] if c["name"] == "ExprBinary"]
        assert len(bins) == 3

    def test_ternary_in_function_call(self):
        """f(a ? b : c)"""
        stdout, _, rc = run_parser("fn f() { g(a ? b : c); }")
        assert rc == 0
        tree = parse_tree(stdout)
        calls = find_all(tree, "ExprCall")
        assert len(calls) == 1
        terns = find_all(tree, "ExprTernary")
        assert len(terns) == 1

    def test_ternary_in_array(self):
        """[a ? 1 : 2, b ? 3 : 4]"""
        stdout, _, rc = run_parser("fn f() { let x = [a ? 1 : 2, b ? 3 : 4]; }")
        assert rc == 0
        tree = parse_tree(stdout)
        arrays = find_all(tree, "ExprArray")
        assert len(arrays) == 1
        terns = find_all(tree, "ExprTernary")
        assert len(terns) == 2

    def test_ternary_in_index(self):
        """a[x ? 0 : 1]"""
        stdout, _, rc = run_parser("fn f() { let x = a[x ? 0 : 1]; }")
        assert rc == 0
        tree = parse_tree(stdout)
        indices = find_all(tree, "ExprIndex")
        assert len(indices) == 1
        terns = find_all(indices[0], "ExprTernary")
        assert len(terns) == 1


# ---------------------------------------------------------------------------
# Tests: For-in expression
# ---------------------------------------------------------------------------

class TestForInExpression:
    def test_for_basic(self):
        stdout, _, rc = run_parser(
            "fn f() { for x in items { let y = 1; } }"
        )
        assert rc == 0
        tree = parse_tree(stdout)
        fors = find_all(tree, "ExprFor")
        assert len(fors) == 1
        cn = child_names(fors[0])
        assert "'for'" in cn
        assert "'x'" in cn
        assert "'in'" in cn
        assert "ExprName" in cn
        assert "Block" in cn

    def test_for_no_semicolon(self):
        """for as statement should not require trailing semicolon."""
        stdout, _, rc = run_parser(
            "fn f() { for x in items { let a = 1; } let b = 2; }"
        )
        assert rc == 0
        tree = parse_tree(stdout)
        assert len(find_all(tree, "ExprFor")) == 1
        assert len(find_all(tree, "StmtLet")) == 2

    def test_for_with_call_iterable(self):
        stdout, _, rc = run_parser(
            "fn f() { for x in get_items() { g(x); } }"
        )
        assert rc == 0
        tree = parse_tree(stdout)
        fors = find_all(tree, "ExprFor")
        assert len(fors) == 1
        # The iterable should be an ExprCall
        calls = [c for c in fors[0]["children"] if c["name"] == "ExprCall"]
        assert len(calls) == 1

    def test_for_with_array_iterable(self):
        stdout, _, rc = run_parser(
            "fn f() { for x in [1, 2, 3] { g(x); } }"
        )
        assert rc == 0
        tree = parse_tree(stdout)
        fors = find_all(tree, "ExprFor")
        assert len(fors) == 1
        arrays = [c for c in fors[0]["children"] if c["name"] == "ExprArray"]
        assert len(arrays) == 1

    def test_for_with_index_iterable(self):
        stdout, _, rc = run_parser(
            "fn f() { for x in items[0] { g(x); } }"
        )
        assert rc == 0
        tree = parse_tree(stdout)
        fors = find_all(tree, "ExprFor")
        assert len(fors) == 1
        indices = [c for c in fors[0]["children"] if c["name"] == "ExprIndex"]
        assert len(indices) == 1

    def test_for_nested(self):
        stdout, _, rc = run_parser(
            "fn f() { for x in a { for y in b { g(x, y); } } }"
        )
        assert rc == 0
        tree = parse_tree(stdout)
        fors = find_all(tree, "ExprFor")
        assert len(fors) == 2


# ---------------------------------------------------------------------------
# Tests: Complex interactions between new features
# ---------------------------------------------------------------------------

class TestComplexInteractions:
    def test_array_of_ternaries(self):
        """Array containing ternary expressions."""
        code = "fn f() { let x = [a ? 1 : 0, b ? 2 : 0, c ? 3 : 0]; }"
        stdout, _, rc = run_parser(code)
        assert rc == 0
        tree = parse_tree(stdout)
        arrays = find_all(tree, "ExprArray")
        assert len(arrays) == 1
        terns = find_all(arrays[0], "ExprTernary")
        assert len(terns) == 3

    def test_index_with_ternary_and_binary(self):
        """a[x + 1] ? b[0] : c[1]"""
        code = "fn f() { let r = a[x + 1] ? b[0] : c[1]; }"
        stdout, _, rc = run_parser(code)
        assert rc == 0
        tree = parse_tree(stdout)
        terns = find_all(tree, "ExprTernary")
        assert len(terns) == 1
        indices = find_all(tree, "ExprIndex")
        assert len(indices) == 3

    def test_for_with_ternary_body(self):
        """for loop containing ternary in body."""
        code = "fn f() { for x in items { let y = x ? 1 : 0; } }"
        stdout, _, rc = run_parser(code)
        assert rc == 0
        tree = parse_tree(stdout)
        assert len(find_all(tree, "ExprFor")) == 1
        assert len(find_all(tree, "ExprTernary")) == 1

    def test_for_if_while_mixed(self):
        """All three block-carrying expressions together."""
        code = "fn f() { for x in items { if x { while y { g(); } } } }"
        stdout, _, rc = run_parser(code)
        assert rc == 0
        tree = parse_tree(stdout)
        assert len(find_all(tree, "ExprFor")) == 1
        assert len(find_all(tree, "ExprIf")) == 1
        assert len(find_all(tree, "ExprWhile")) == 1

    def test_all_new_features_combined(self):
        """A program using arrays, indexing, ternary, and for-in together."""
        code = (
            'fn f() { '
            'let arr = [1, 2, 3]; '
            'for i in arr { '
            'let v = arr[i] ? arr[i] + 1 : 0; '
            'g(v); '
            '} '
            '}'
        )
        stdout, _, rc = run_parser(code)
        assert rc == 0
        tree = parse_tree(stdout)
        assert tree["name"] == "File"
        assert len(find_all(tree, "ExprArray")) == 1
        assert len(find_all(tree, "ExprFor")) == 1
        assert len(find_all(tree, "ExprTernary")) == 1
        assert len(find_all(tree, "ExprIndex")) == 2
        assert len(find_all(tree, "StmtLet")) == 2

    def test_unary_on_indexed(self):
        """-a[0] => -(a[0]), not (-a)[0]"""
        code = "fn f() { let x = -a[0]; }"
        stdout, _, rc = run_parser(code)
        assert rc == 0
        tree = parse_tree(stdout)
        unaries = find_all(tree, "ExprUnary")
        assert len(unaries) == 1
        # ExprIndex should be inside ExprUnary
        indices_in_unary = find_all(unaries[0], "ExprIndex")
        assert len(indices_in_unary) == 1


# ---------------------------------------------------------------------------
# Tests: Error recovery for new constructs
# ---------------------------------------------------------------------------

class TestErrorRecoveryNew:
    def test_malformed_array_no_close(self):
        """[1, 2  without ] should not crash."""
        stdout, _, rc = run_parser("fn f() { let x = [1, 2; }")
        assert rc == 0
        tree = parse_tree(stdout)
        assert tree["name"] == "File"

    def test_malformed_ternary_no_colon(self):
        """a ? b without : should not crash."""
        stdout, _, rc = run_parser("fn f() { let x = a ? b; }")
        assert rc == 0
        tree = parse_tree(stdout)
        assert tree["name"] == "File"

    def test_malformed_for_no_in(self):
        """for x { } without in should not crash."""
        stdout, _, rc = run_parser("fn f() { for x { let y = 1; } }")
        assert rc == 0
        tree = parse_tree(stdout)
        assert tree["name"] == "File"

    def test_malformed_index_no_close(self):
        """a[ without ] should not crash."""
        stdout, _, rc = run_parser("fn f() { let x = a[0; }")
        assert rc == 0
        tree = parse_tree(stdout)
        assert tree["name"] == "File"
