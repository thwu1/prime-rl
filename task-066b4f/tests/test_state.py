"""
Verification tests for the TornadoAsyncTransformer implementation.

"""
import ast
import os
import sys

import pytest
import libcst

# Make sure /app is on sys.path so we can import the transformer
sys.path.insert(0, "/app")

from tornado_async_transformer import TornadoAsyncTransformer, TransformError


# ---------------------------------------------------------------------------
# Helpers to collect test data from /app/tests/
# ---------------------------------------------------------------------------

def _collect_test_cases():
    """Walk /app/tests/test_cases/ for before/after pairs."""
    root_dir = "/app/tests/test_cases"
    cases = []
    for entry in sorted(os.listdir(root_dir)):
        case_dir = os.path.join(root_dir, entry)
        before_path = os.path.join(case_dir, "before.py")
        after_path = os.path.join(case_dir, "after.py")
        if os.path.isfile(before_path) and os.path.isfile(after_path):
            with open(before_path) as f:
                before = f.read()
            with open(after_path) as f:
                after = f.read()
            cases.append(pytest.param(before, after, id=entry))
    return cases


def _collect_exception_cases():
    """Walk /app/tests/exception_cases/ for files that should raise TransformError."""
    root_dir = "/app/tests/exception_cases"
    cases = []
    for entry in sorted(os.listdir(root_dir)):
        if not entry.endswith(".py"):
            continue
        filepath = os.path.join(root_dir, entry)
        with open(filepath) as f:
            source = f.read()
        # The module docstring is the expected error message
        tree = ast.parse(source)
        docstring = ast.get_docstring(tree)
        expected_msg = docstring.replace("\n", " ")
        cases.append(pytest.param(source, expected_msg, id=entry))
    return cases


# ---------------------------------------------------------------------------
# Parametrized transformation tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("before,after", _collect_test_cases())
def test_transformation(before, after):
    """Parse before code, transform it, verify it matches after code exactly."""
    source_tree = libcst.parse_module(before)
    transformer = TornadoAsyncTransformer()
    visited_tree = source_tree.visit(transformer)
    assert visited_tree.code == after, (
        f"Transformed code does not match expected output.\n"
        f"--- GOT ---\n{visited_tree.code}\n"
        f"--- EXPECTED ---\n{after}"
    )


@pytest.mark.parametrize("source,expected_msg", _collect_exception_cases())
def test_exception_cases(source, expected_msg):
    """Verify unsupported patterns raise TransformError with expected message."""
    source_tree = libcst.parse_module(source)
    with pytest.raises(TransformError) as exc_info:
        source_tree.visit(TornadoAsyncTransformer())
    assert expected_msg in str(exc_info.value), (
        f"Expected error message substring not found.\n"
        f"Expected substring: {expected_msg!r}\n"
        f"Actual message: {str(exc_info.value)!r}"
    )


# ---------------------------------------------------------------------------
# Structural tests: verify the transformer is properly implemented
# ---------------------------------------------------------------------------

class TestTransformerStructure:
    """Verify the transformer class is properly set up."""

    def test_is_cst_transformer(self):
        """TornadoAsyncTransformer must be a subclass of libcst.CSTTransformer."""
        assert issubclass(TornadoAsyncTransformer, libcst.CSTTransformer)

    def test_transform_error_is_exception(self):
        """TransformError must be an Exception subclass."""
        assert issubclass(TransformError, Exception)

    def test_transformer_instantiation(self):
        """Transformer must be instantiable without arguments."""
        t = TornadoAsyncTransformer()
        assert t is not None

    def test_identity_on_non_coroutine(self):
        """Non-coroutine code should pass through unchanged."""
        code = "def hello():\n    return 42\n"
        tree = libcst.parse_module(code)
        result = tree.visit(TornadoAsyncTransformer())
        assert result.code == code

    def test_multiple_invocations_independent(self):
        """Each transformer instance should be independent (no shared state)."""
        before = '''\
"""
Test.
"""
from tornado import gen


@gen.coroutine
def f():
    yield gen.sleep(1)
'''
        for _ in range(3):
            tree = libcst.parse_module(before)
            result = tree.visit(TornadoAsyncTransformer())
            assert "async def f():" in result.code
            assert "asyncio.sleep" in result.code
