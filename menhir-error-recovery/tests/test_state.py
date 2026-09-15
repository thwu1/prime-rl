
import subprocess
import json
import pytest

BINARY = "/app/_build/default/src/driver.exe"


def run_parser(input_text):
    """Run the parser executable on the given input and return parsed JSON."""
    result = subprocess.run(
        [BINARY],
        input=input_text,
        capture_output=True,
        text=True,
        timeout=10,
    )
    stdout = result.stdout.strip()
    if not stdout:
        pytest.fail(
            f"No output from parser.\nstderr: {result.stderr!r}\n"
            f"returncode: {result.returncode}"
        )
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        pytest.fail(f"Invalid JSON output: {stdout!r}\nstderr: {result.stderr!r}")


# ---------------------------------------------------------------------------
# Valid-input tests: verify correct AST JSON
# ---------------------------------------------------------------------------


class TestValidParsing:
    def test_integer(self):
        r = run_parser("42")
        assert r["status"] == "ok"
        assert r["ast"]["tag"] == "int"
        assert r["ast"]["value"] == 42

    def test_boolean_true(self):
        r = run_parser("true")
        assert r["status"] == "ok"
        assert r["ast"]["tag"] == "bool"
        assert r["ast"]["value"] is True

    def test_boolean_false(self):
        r = run_parser("false")
        assert r["status"] == "ok"
        assert r["ast"]["tag"] == "bool"
        assert r["ast"]["value"] is False

    def test_variable(self):
        r = run_parser("x")
        assert r["status"] == "ok"
        assert r["ast"]["tag"] == "var"
        assert r["ast"]["name"] == "x"

    def test_addition(self):
        r = run_parser("1 + 2")
        assert r["status"] == "ok"
        a = r["ast"]
        assert a["tag"] == "binop"
        assert a["op"] == "+"
        assert a["left"] == {"tag": "int", "value": 1}
        assert a["right"] == {"tag": "int", "value": 2}

    def test_precedence_mul_over_add(self):
        r = run_parser("1 + 2 * 3")
        assert r["status"] == "ok"
        a = r["ast"]
        assert a["tag"] == "binop"
        assert a["op"] == "+"
        assert a["left"]["value"] == 1
        assert a["right"]["tag"] == "binop"
        assert a["right"]["op"] == "*"
        assert a["right"]["left"]["value"] == 2
        assert a["right"]["right"]["value"] == 3

    def test_left_associativity(self):
        r = run_parser("1 - 2 - 3")
        assert r["status"] == "ok"
        a = r["ast"]
        # Should be (1 - 2) - 3
        assert a["tag"] == "binop"
        assert a["op"] == "-"
        assert a["left"]["tag"] == "binop"
        assert a["left"]["op"] == "-"
        assert a["left"]["left"]["value"] == 1
        assert a["left"]["right"]["value"] == 2
        assert a["right"]["value"] == 3

    def test_let_binding(self):
        r = run_parser("let x = 1 in x + 2")
        assert r["status"] == "ok"
        a = r["ast"]
        assert a["tag"] == "let"
        assert a["name"] == "x"
        assert a["bind"] == {"tag": "int", "value": 1}
        assert a["body"]["tag"] == "binop"
        assert a["body"]["op"] == "+"

    def test_if_then_else(self):
        r = run_parser("if true then 1 else 2")
        assert r["status"] == "ok"
        a = r["ast"]
        assert a["tag"] == "if"
        assert a["cond"] == {"tag": "bool", "value": True}
        assert a["then"] == {"tag": "int", "value": 1}
        assert a["else"] == {"tag": "int", "value": 2}

    def test_lambda(self):
        r = run_parser("fun x -> x")
        assert r["status"] == "ok"
        a = r["ast"]
        assert a["tag"] == "fun"
        assert a["param"] == "x"
        assert a["body"] == {"tag": "var", "name": "x"}

    def test_application(self):
        r = run_parser("f x")
        assert r["status"] == "ok"
        a = r["ast"]
        assert a["tag"] == "app"
        assert a["fn"] == {"tag": "var", "name": "f"}
        assert a["arg"] == {"tag": "var", "name": "x"}

    def test_multi_application_left_assoc(self):
        r = run_parser("f x y")
        assert r["status"] == "ok"
        a = r["ast"]
        # f x y = (f x) y
        assert a["tag"] == "app"
        assert a["fn"]["tag"] == "app"
        assert a["fn"]["fn"] == {"tag": "var", "name": "f"}
        assert a["fn"]["arg"] == {"tag": "var", "name": "x"}
        assert a["arg"] == {"tag": "var", "name": "y"}

    def test_sequence(self):
        r = run_parser("1 ; 2")
        assert r["status"] == "ok"
        a = r["ast"]
        assert a["tag"] == "seq"
        assert a["first"] == {"tag": "int", "value": 1}
        assert a["second"] == {"tag": "int", "value": 2}

    def test_unary_minus(self):
        r = run_parser("-42")
        assert r["status"] == "ok"
        a = r["ast"]
        assert a["tag"] == "neg"
        assert a["expr"] == {"tag": "int", "value": 42}

    def test_parenthesized_precedence(self):
        r = run_parser("(1 + 2) * 3")
        assert r["status"] == "ok"
        a = r["ast"]
        assert a["tag"] == "binop"
        assert a["op"] == "*"
        assert a["left"]["tag"] == "binop"
        assert a["left"]["op"] == "+"
        assert a["right"]["value"] == 3

    def test_complex_let_fun_app(self):
        r = run_parser("let f = fun x -> x * x in f 5")
        assert r["status"] == "ok"
        a = r["ast"]
        assert a["tag"] == "let"
        assert a["name"] == "f"
        assert a["bind"]["tag"] == "fun"
        assert a["bind"]["param"] == "x"
        assert a["bind"]["body"]["tag"] == "binop"
        assert a["bind"]["body"]["op"] == "*"
        assert a["body"]["tag"] == "app"
        assert a["body"]["fn"] == {"tag": "var", "name": "f"}
        assert a["body"]["arg"] == {"tag": "int", "value": 5}

    def test_comparison_eq(self):
        r = run_parser("x == y")
        assert r["status"] == "ok"
        a = r["ast"]
        assert a["tag"] == "binop"
        assert a["op"] == "=="

    def test_logical_and(self):
        r = run_parser("true && false")
        assert r["status"] == "ok"
        assert r["ast"]["tag"] == "binop"
        assert r["ast"]["op"] == "&&"

    def test_nested_let(self):
        r = run_parser("let x = 1 in let y = 2 in x + y")
        assert r["status"] == "ok"
        a = r["ast"]
        assert a["tag"] == "let"
        assert a["name"] == "x"
        assert a["body"]["tag"] == "let"
        assert a["body"]["name"] == "y"
        assert a["body"]["body"]["tag"] == "binop"


# ---------------------------------------------------------------------------
# Error-detection tests: verify error recovery, positions, and messages
# ---------------------------------------------------------------------------


class TestErrorDetection:
    def test_single_error_incomplete(self):
        """An incomplete expression should produce at least one error."""
        r = run_parser("1 +")
        assert r["status"] == "error"
        assert len(r["errors"]) >= 1

    def test_error_position_let_missing_ident(self):
        """Error position should point to the offending token."""
        r = run_parser("let = 1 in x")
        assert r["status"] == "error"
        e = r["errors"][0]
        assert e["line"] == 1
        # '=' is at column 5 (1-based)
        assert 4 <= e["col"] <= 6

    def test_context_sensitive_message(self):
        """Error message must be descriptive, not just 'syntax error'."""
        r = run_parser("1 + * 2")
        assert r["status"] == "error"
        msg = r["errors"][0]["message"]
        assert msg.lower() != "syntax error"
        assert len(msg) >= 16

    def test_multi_error_via_semicolons(self):
        """Multiple independent errors separated by ';' must all be detected."""
        r = run_parser("1 + ; 2 + ; 3")
        assert r["status"] == "error"
        assert len(r["errors"]) >= 2

    def test_multi_error_bad_starts(self):
        """Multiple invalid expression starts separated by ';'."""
        r = run_parser("+ ; *")
        assert r["status"] == "error"
        assert len(r["errors"]) >= 2

    def test_eof_error(self):
        """Unexpected EOF should produce an error."""
        r = run_parser("let x =")
        assert r["status"] == "error"
        assert len(r["errors"]) >= 1

    def test_unmatched_paren(self):
        """Unmatched parenthesis should produce an error."""
        r = run_parser("(1 + 2")
        assert r["status"] == "error"
        assert len(r["errors"]) >= 1

    def test_error_message_has_expected(self):
        """Error message should contain 'expected' or 'unexpected'."""
        r = run_parser("let = 1 in x")
        assert r["status"] == "error"
        msg = r["errors"][0]["message"].lower()
        assert "expect" in msg or "unexpected" in msg

    def test_error_message_if_missing_then(self):
        """Missing 'then' after condition should give informative message."""
        r = run_parser("if true 1 else 2")
        assert r["status"] == "error"
        msg = r["errors"][0]["message"]
        assert len(msg) >= 16
        assert msg.lower() != "syntax error"

    def test_error_json_structure(self):
        """Error JSON must contain line, col, and message fields."""
        r = run_parser("***")
        assert r["status"] == "error"
        for e in r["errors"]:
            assert "line" in e
            assert "col" in e
            assert "message" in e
            assert isinstance(e["line"], int)
            assert isinstance(e["col"], int)
            assert isinstance(e["message"], str)
