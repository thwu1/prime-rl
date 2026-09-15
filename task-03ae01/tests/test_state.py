
import sys
import os
import json
import subprocess
import pytest
import tempfile

sys.path.insert(0, '/app')
sys.path.insert(0, '/opt/cool_task')

import cool_parser


def check(path):
    """Parse a Cool file and run the type checker on it."""
    import type_checker
    ast = cool_parser.parse_file(path)
    return type_checker.check_program(ast)


def find_node(ast, kind, **kwargs):
    """DFS to find first AST node matching kind and all kwargs."""
    if isinstance(ast, dict):
        if ast.get('kind') == kind:
            if all(ast.get(k) == v for k, v in kwargs.items()):
                return ast
        for v in ast.values():
            result = find_node(v, kind, **kwargs)
            if result is not None:
                return result
    elif isinstance(ast, list):
        for item in ast:
            result = find_node(item, kind, **kwargs)
            if result is not None:
                return result
    return None


def run_lexer(source_text):
    """Write source to a temp file, run cool_lexer, return parsed JSON tokens."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.cl', delete=False) as f:
        f.write(source_text)
        f.flush()
        tmp = f.name
    try:
        result = subprocess.run(
            ['/app/cool_lexer', tmp],
            capture_output=True, text=True, timeout=10
        )
        tokens = []
        for line in result.stdout.strip().split('\n'):
            line = line.strip()
            if line:
                tokens.append(json.loads(line))
        return tokens
    finally:
        os.unlink(tmp)


# ====== Lexer Build Tests ======

class TestLexerBuild:
    def test_cool_lexer_binary_exists(self):
        """The Makefile must produce a cool_lexer binary."""
        assert os.path.exists('/app/cool_lexer'), \
            "cool_lexer binary not found. Makefile must build it."

    def test_lexer_runs_on_hello(self):
        """cool_lexer must tokenize a simple program without crashing."""
        result = subprocess.run(
            ['/app/cool_lexer', '/app/programs/valid_hello.cl'],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, f"Lexer crashed: {result.stderr}"
        lines = [l for l in result.stdout.strip().split('\n') if l.strip()]
        assert len(lines) > 5, "Too few tokens produced"


# ====== Lexer Token Tests ======

class TestLexerTokens:
    def test_keywords(self):
        """All Cool keywords must be recognized case-insensitively."""
        tokens = run_lexer('CLASS Main { main() : Object { IF true THEN 0 ELSE 1 FI }; };')
        types = [t['type'] for t in tokens]
        assert 'CLASS' in types
        assert 'IF' in types
        assert 'THEN' in types
        assert 'ELSE' in types
        assert 'FI' in types

    def test_keywords_case_insensitive(self):
        """Keywords like 'cLaSs' must be recognized."""
        tokens = run_lexer('cLaSs Main { main() : Object { 0 }; };')
        types = [t['type'] for t in tokens]
        assert types[0] == 'CLASS'

    def test_identifiers(self):
        """TYPEID starts uppercase, OBJECTID starts lowercase."""
        tokens = run_lexer('Main foo SELF_TYPE self')
        assert tokens[0]['type'] == 'TYPEID'
        assert tokens[0]['value'] == 'Main'
        assert tokens[1]['type'] == 'OBJECTID'
        assert tokens[1]['value'] == 'foo'
        assert tokens[2]['type'] == 'TYPEID'
        assert tokens[2]['value'] == 'SELF_TYPE'
        assert tokens[3]['type'] == 'OBJECTID'
        assert tokens[3]['value'] == 'self'

    def test_integer_constants(self):
        """Integer constants must be recognized."""
        tokens = run_lexer('42 0 12345')
        for t in tokens:
            assert t['type'] == 'INT_CONST'
        assert tokens[0]['value'] == '42'

    def test_bool_constants(self):
        """true/false must start with lowercase."""
        tokens = run_lexer('true false tRuE fAlSe')
        for t in tokens:
            assert t['type'] == 'BOOL_CONST'
        assert tokens[0]['value'] is True
        assert tokens[1]['value'] is False

    def test_bool_uppercase_is_typeid(self):
        """True/False starting with uppercase must NOT be BOOL_CONST."""
        tokens = run_lexer('True False')
        assert tokens[0]['type'] == 'TYPEID'
        assert tokens[1]['type'] == 'TYPEID'

    def test_multi_char_operators(self):
        """=>, <-, <= must be recognized."""
        tokens = run_lexer('=> <- <=')
        assert tokens[0]['type'] == 'DARROW'
        assert tokens[1]['type'] == 'ASSIGN'
        assert tokens[2]['type'] == 'LE'

    def test_single_char_tokens(self):
        """All single-char tokens must be recognized."""
        tokens = run_lexer('{ } ( ) ; : . , @ ~ + - * / < =')
        types = [t['type'] for t in tokens]
        assert '{' in types
        assert '}' in types
        assert '(' in types
        assert ')' in types
        assert '+' in types
        assert '-' in types

    def test_string_basic(self):
        """Basic string constants."""
        tokens = run_lexer('"hello"')
        assert tokens[0]['type'] == 'STR_CONST'
        assert tokens[0]['value'] == 'hello'

    def test_string_escapes(self):
        r"""String escape sequences \n, \t, \\, \" must work."""
        tokens = run_lexer(r'"hello\nworld"')
        assert tokens[0]['type'] == 'STR_CONST'
        assert tokens[0]['value'] == 'hello\nworld'

    def test_string_tab_escape(self):
        r"""String \t escape."""
        tokens = run_lexer(r'"a\tb"')
        assert tokens[0]['type'] == 'STR_CONST'
        assert tokens[0]['value'] == 'a\tb'

    def test_string_backslash_escape(self):
        r"""String \\ escape."""
        tokens = run_lexer(r'"a\\b"')
        assert tokens[0]['type'] == 'STR_CONST'
        assert tokens[0]['value'] == 'a\\b'

    def test_nested_comments(self):
        """Nested block comments must be handled."""
        tokens = run_lexer('(* outer (* inner *) still_comment *) class')
        types = [t['type'] for t in tokens]
        # Only 'class' should survive the comment
        assert types == ['CLASS']

    def test_single_line_comment(self):
        """-- comment to end of line."""
        tokens = run_lexer('class -- this is a comment\nMain')
        types = [t['type'] for t in tokens]
        assert types == ['CLASS', 'TYPEID']

    def test_unmatched_close_comment(self):
        """Unmatched *) must produce an ERROR token."""
        tokens = run_lexer('*) class')
        types = [t['type'] for t in tokens]
        assert 'ERROR' in types


# ====== Valid Program Type Checks ======

class TestValidPrograms:
    def test_hello(self):
        result = check('/app/programs/valid_hello.cl')
        assert result['status'] == 'ok'

    def test_self_type(self):
        result = check('/app/programs/valid_self_type.cl')
        assert result['status'] == 'ok'

    def test_self_type_chain(self):
        result = check('/app/programs/valid_self_type_chain.cl')
        assert result['status'] == 'ok'

    def test_case(self):
        result = check('/app/programs/valid_case.cl')
        assert result['status'] == 'ok'

    def test_let_scope(self):
        result = check('/app/programs/valid_let_scope.cl')
        assert result['status'] == 'ok'

    def test_static_dispatch(self):
        result = check('/app/programs/valid_static_dispatch.cl')
        assert result['status'] == 'ok'

    def test_cond_lub(self):
        result = check('/app/programs/valid_cond_lub.cl')
        assert result['status'] == 'ok'


# ====== Error Program Type Checks ======

class TestErrorPrograms:
    def test_cycle(self):
        result = check('/app/programs/error_cycle.cl')
        assert result['status'] == 'error'
        errors = ' '.join(e['message'].lower() for e in result['errors'])
        assert 'cycle' in errors or 'inherit' in errors or 'circular' in errors

    def test_override(self):
        result = check('/app/programs/error_override.cl')
        assert result['status'] == 'error'

    def test_no_main(self):
        result = check('/app/programs/error_no_main.cl')
        assert result['status'] == 'error'
        errors = ' '.join(e['message'].lower() for e in result['errors'])
        assert 'main' in errors

    def test_arith(self):
        result = check('/app/programs/error_arith.cl')
        assert result['status'] == 'error'

    def test_undef_type(self):
        result = check('/app/programs/error_undef_type.cl')
        assert result['status'] == 'error'

    def test_redefine_basic(self):
        result = check('/app/programs/error_redefine_basic.cl')
        assert result['status'] == 'error'

    def test_attr_redefine(self):
        result = check('/app/programs/error_attr_redefine.cl')
        assert result['status'] == 'error'

    def test_conform(self):
        result = check('/app/programs/error_conform.cl')
        assert result['status'] == 'error'

    def test_self_assign(self):
        result = check('/app/programs/error_self_assign.cl')
        assert result['status'] == 'error'
        errors = ' '.join(e['message'].lower() for e in result['errors'])
        assert 'self' in errors

    def test_self_type_formal(self):
        result = check('/app/programs/error_self_type_formal.cl')
        assert result['status'] == 'error'


# ====== Type Annotation Tests ======

class TestTypeAnnotations:
    """Verify that the annotated AST has correct static_type on key nodes."""

    def test_self_type_dispatch_resolves_to_concrete(self):
        """Dispatching a SELF_TYPE method on (new Dog) must yield static_type Dog."""
        result = check('/app/programs/valid_self_type.cl')
        assert result['status'] == 'ok'
        ast = result['annotated_ast']
        dispatch = find_node(ast, 'dispatch', method='copy_self')
        assert dispatch is not None, "dispatch node for copy_self not found"
        assert dispatch.get('static_type') == 'Dog', (
            f"Expected Dog, got {dispatch.get('static_type')}"
        )

    def test_self_type_chain_preserves_type(self):
        """Chained SELF_TYPE dispatch on AdvBuilder must keep AdvBuilder type."""
        result = check('/app/programs/valid_self_type_chain.cl')
        assert result['status'] == 'ok'
        ast = result['annotated_ast']
        set_name = find_node(ast, 'dispatch', method='set_name')
        assert set_name is not None
        assert set_name.get('static_type') == 'AdvBuilder', (
            f"Expected AdvBuilder, got {set_name.get('static_type')}"
        )
        set_extra = find_node(ast, 'dispatch', method='set_extra')
        assert set_extra is not None
        assert set_extra.get('static_type') == 'AdvBuilder', (
            f"Expected AdvBuilder, got {set_extra.get('static_type')}"
        )

    def test_cond_lub_is_common_ancestor(self):
        """if-then-else with Cat/Dog branches must have static_type Animal."""
        result = check('/app/programs/valid_cond_lub.cl')
        assert result['status'] == 'ok'
        ast = result['annotated_ast']
        cond = find_node(ast, 'cond')
        assert cond is not None
        assert cond.get('static_type') == 'Animal', (
            f"Expected Animal, got {cond.get('static_type')}"
        )

    def test_case_type_is_lub(self):
        """Case with two String branches must have static_type String."""
        result = check('/app/programs/valid_case.cl')
        assert result['status'] == 'ok'
        ast = result['annotated_ast']
        case = find_node(ast, 'case')
        assert case is not None
        assert case.get('static_type') == 'String', (
            f"Expected String, got {case.get('static_type')}"
        )

    def test_static_dispatch_type(self):
        """(new B)@A.foo() should have static_type String."""
        result = check('/app/programs/valid_static_dispatch.cl')
        assert result['status'] == 'ok'
        ast = result['annotated_ast']
        sd = find_node(ast, 'static_dispatch')
        assert sd is not None
        assert sd.get('static_type') == 'String', (
            f"Expected String, got {sd.get('static_type')}"
        )

    def test_let_arithmetic_type(self):
        """x + y where both are Int should have static_type Int."""
        result = check('/app/programs/valid_let_scope.cl')
        assert result['status'] == 'ok'
        ast = result['annotated_ast']
        plus = find_node(ast, 'plus')
        assert plus is not None
        assert plus.get('static_type') == 'Int', (
            f"Expected Int, got {plus.get('static_type')}"
        )
