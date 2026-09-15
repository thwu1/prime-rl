
import subprocess
import os
import re
import pytest

PARSER_EXE = "/app/_build/default/bin/main.exe"
PARSER_MLY = "/app/lib/parser.mly"
MESSAGES_FILE = "/app/lib/errors.messages"
MAIN_ML = "/app/bin/main.ml"


def run_parser(input_text):
    """Run the parser on input text and return (stdout, stderr, returncode)."""
    result = subprocess.run(
        [PARSER_EXE],
        input=input_text,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout.strip(), result.stderr.strip(), result.returncode


class TestBuild:
    def test_dune_build_succeeds(self):
        """The project must build with zero grammar conflicts."""
        result = subprocess.run(
            ["dune", "build"],
            cwd="/app",
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, (
            f"dune build failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_parser_executable_exists(self):
        """The parser executable must be produced."""
        assert os.path.isfile(PARSER_EXE), f"Parser executable not found at {PARSER_EXE}"


class TestIncrementalAPI:
    def test_uses_incremental_api(self):
        """The driver must use Menhir's incremental API."""
        with open(MAIN_ML) as f:
            content = f.read()
        has_incremental = (
            "MenhirInterpreter" in content or "Incremental" in content
        )
        assert has_incremental, (
            "main.ml must use the incremental API "
            "(MenhirInterpreter/Incremental not found)"
        )

    def test_no_monolithic_api(self):
        """The driver must not use the monolithic API pattern."""
        with open(MAIN_ML) as f:
            content = f.read()
        # The monolithic API pattern: Parser.program Lexer.token lexbuf
        uses_monolithic = bool(
            re.search(r"Parser\.program\s+.*Lexer\.token", content)
        )
        assert not uses_monolithic, (
            "main.ml still uses the monolithic API pattern"
        )


PARSE_CASES = [
    ("42", "42"),
    ("true", "true"),
    ("false", "false"),
    ("x", "x"),
    ("1 + 2 * 3", "(+ 1 (* 2 3))"),
    ("(1 + 2) * 3", "(* (+ 1 2) 3)"),
    ("-1", "(- 1)"),
    ("1 + -2", "(+ 1 (- 2))"),
    ("1 < 2", "(< 1 2)"),
    ("true && false || true", "(|| (&& true false) true)"),
    ("let x = 1 in x", "(let x 1 x)"),
    ("let rec f x = f x in f 1", "(letrec f x (app f x) (app f 1))"),
    ("if true then 1 else 2", "(if true 1 2)"),
    ("fun x -> x", "(fun x x)"),
    ("f x", "(app f x)"),
    ("f x y", "(app (app f x) y)"),
    ("f x + 1", "(+ (app f x) 1)"),
    ("(1, 2, 3)", "(tuple 1 2 3)"),
    ("[1; 2; 3]", "(list 1 2 3)"),
    ("1 :: 2 :: []", "(:: 1 (:: 2 (list)))"),
    ("match x with 0 -> true | _ -> false", "(match x (-> 0 true) (-> _ false))"),
    ("1; 2", "(seq 1 2)"),
    ("let x = 1 in x; 2", "(let x 1 (seq x 2))"),
    ("not true", "(not true)"),
    ("[]", "(list)"),
    ("fun f -> fun x -> f (x + 1)", "(fun f (fun x (app f (+ x 1))))"),
    ("1 + 2 + 3", "(+ (+ 1 2) 3)"),
    (
        "match x with 0 -> match y with 1 -> true | 2 -> false",
        "(match x (-> 0 (match y (-> 1 true) (-> 2 false))))",
    ),
    (
        "match xs with x :: rest -> x | _ -> 0",
        "(match xs (-> (:: x rest) x) (-> _ 0))",
    ),
    ("(1; 2)", "(seq 1 2)"),
    (
        "if 1 < 2 then 3 + 4 else 5 * 6",
        "(if (< 1 2) (+ 3 4) (* 5 6))",
    ),
    (
        "let f = fun x -> x + 1 in f 2",
        "(let f (fun x (+ x 1)) (app f 2))",
    ),
    (
        "let rec map f = fun xs -> match xs with [] -> [] | x :: rest -> f x :: map f rest in map",
        "(letrec map f (fun xs (match xs (-> (list) (list)) (-> (:: x rest) (:: (app f x) (app (app map f) rest))))) map)",
    ),
]


class TestParsing:
    @pytest.mark.parametrize("input_text,expected", PARSE_CASES)
    def test_parse(self, input_text, expected):
        stdout, stderr, rc = run_parser(input_text)
        assert rc == 0, f"Parser failed on '{input_text}':\nstderr: {stderr}"
        assert stdout == expected, (
            f"Wrong AST for '{input_text}':\n"
            f"  expected: {expected}\n"
            f"  got:      {stdout}"
        )


class TestErrorReporting:
    def test_error_on_invalid_input(self):
        """Parser must exit 1 on invalid input."""
        _, _, rc = run_parser("1 + ")
        assert rc == 1, "Parser should exit 1 on invalid input"

    def test_error_message_has_position(self):
        """Error output must include line and column information."""
        _, stderr, rc = run_parser("1 + + 2")
        assert rc == 1
        stderr_lower = stderr.lower()
        assert "line" in stderr_lower or "column" in stderr_lower or (
            re.search(r"\d+.*\d+", stderr)
        ), f"Error message should include position info, got: {stderr}"

    def test_error_on_unmatched_paren(self):
        """Parser must reject unmatched parentheses."""
        _, _, rc = run_parser("(1 + 2")
        assert rc == 1

    def test_error_on_missing_in(self):
        """Parser must reject let without in."""
        _, _, rc = run_parser("let x = 1")
        assert rc == 1


class TestMessagesFile:
    def test_messages_file_exists(self):
        """The .messages file must exist."""
        assert os.path.isfile(MESSAGES_FILE), (
            f"Messages file not found at {MESSAGES_FILE}"
        )

    def test_messages_file_complete(self):
        """The .messages file must cover all error states."""
        # Generate the complete set of error sentences
        list_result = subprocess.run(
            ["menhir", "--list-errors", PARSER_MLY],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert list_result.returncode == 0, (
            f"menhir --list-errors failed: {list_result.stderr}"
        )

        # Write complete messages to a temp file
        complete_file = "/tmp/complete_errors.messages"
        with open(complete_file, "w") as f:
            f.write(list_result.stdout)

        # Check that the complete set is a subset of the user's file
        compare_result = subprocess.run(
            [
                "menhir",
                "--compare-errors", complete_file,
                "--compare-errors", MESSAGES_FILE,
                PARSER_MLY,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert compare_result.returncode == 0, (
            f"Messages file is incomplete:\n{compare_result.stderr}"
        )

    def test_messages_not_placeholder(self):
        """No message should be the default placeholder."""
        with open(MESSAGES_FILE) as f:
            content = f.read()
        assert "<YOUR MESSAGE HERE>" not in content, (
            "Messages file still contains placeholder text"
        )

    def test_messages_not_empty(self):
        """Messages should not be empty strings."""
        with open(MESSAGES_FILE) as f:
            content = f.read()
        # Check for entries with empty messages (two blank lines with nothing between)
        # Each entry ends with a message. A blank line after message starts new entry.
        # An empty message would be just blank lines after the sentence.
        lines = content.split("\n")
        in_sentence = False
        saw_blank = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if stripped == "":
                if in_sentence:
                    saw_blank = True
                continue
            if stripped.endswith(":") or ":" in stripped.split()[0] if stripped.split() else False:
                # Could be a sentence line like "program: INT PLUS"
                in_sentence = True
                saw_blank = False
            elif saw_blank and in_sentence:
                # This is a message line
                assert len(stripped) > 0, "Found empty error message"
                in_sentence = False
                saw_blank = False
