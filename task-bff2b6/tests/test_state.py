
import ast
import os
import sys

import pytest

sys.path.insert(0, "/app")

import libcst

from tornado_async_transformer import TornadoAsyncTransformer, TransformError


def transform(code: str) -> str:
    tree = libcst.parse_module(code)
    return tree.visit(TornadoAsyncTransformer()).code


def collect_test_cases():
    test_cases_dir = "/app/tests/test_cases"
    cases = []
    for name in sorted(os.listdir(test_cases_dir)):
        case_dir = os.path.join(test_cases_dir, name)
        before_path = os.path.join(case_dir, "before.py")
        after_path = os.path.join(case_dir, "after.py")
        if (
            os.path.isdir(case_dir)
            and os.path.isfile(before_path)
            and os.path.isfile(after_path)
        ):
            with open(before_path) as f:
                before = f.read()
            with open(after_path) as f:
                after = f.read()
            cases.append(pytest.param((before, after), id=name))
    return cases


def collect_exception_cases():
    ec_dir = "/app/tests/exception_cases"
    cases = []
    for filename in sorted(os.listdir(ec_dir)):
        if filename.endswith(".py"):
            filepath = os.path.join(ec_dir, filename)
            with open(filepath) as f:
                source = f.read()
            tree = ast.parse(source)
            docstring = ast.get_docstring(tree)
            expected_msg = docstring.replace("\n", " ")
            cases.append(pytest.param((source, expected_msg), id=filename))
    return cases


class TestTransformerStructure:
    def test_transformer_is_cst_transformer(self):
        assert issubclass(TornadoAsyncTransformer, libcst.CSTTransformer)

    def test_transform_error_is_exception(self):
        assert issubclass(TransformError, Exception)

    def test_transformer_instantiation(self):
        t = TornadoAsyncTransformer()
        assert t is not None


@pytest.mark.parametrize("case", collect_test_cases())
def test_transformation(case):
    before, after = case
    result = transform(before)
    assert result == after, (
        f"Transformation mismatch.\nExpected:\n{after}\nGot:\n{result}"
    )


@pytest.mark.parametrize("case", collect_exception_cases())
def test_exception_case(case):
    source, expected_msg = case
    with pytest.raises(TransformError) as exc_info:
        transform(source)
    assert expected_msg in str(exc_info.value), (
        f"Expected error message containing:\n{expected_msg}\nGot:\n{str(exc_info.value)}"
    )


class TestImportAgnosticMatching:
    """Verify the transformer handles different import styles correctly."""

    def test_from_tornado_import_gen_style(self):
        before = '''from tornado import gen

@gen.coroutine
def foo():
    result = yield bar()
    raise gen.Return(result)
'''
        result = transform(before)
        assert "async def foo():" in result
        assert "await bar()" in result
        assert "return result" in result
        assert "@gen.coroutine" not in result

    def test_import_tornado_style(self):
        before = '''import tornado

@tornado.gen.coroutine
def foo():
    result = yield bar()
    raise tornado.gen.Return(result)
'''
        result = transform(before)
        assert "async def foo():" in result
        assert "await bar()" in result
        assert "return result" in result
        assert "@tornado.gen.coroutine" not in result

    def test_non_coroutine_unchanged(self):
        code = '''def foo():
    return 42
'''
        result = transform(code)
        assert result == code


class TestCoroutineContextStack:
    """Verify nested function scoping works correctly."""

    def test_nested_non_coroutine_generator_preserved(self):
        """Yields inside nested non-coroutine generators must NOT become awaits."""
        before = '''from tornado import gen

@gen.coroutine
def outer():
    def inner():
        for x in items:
            yield x
    for item in inner():
        yield process(item)
'''
        result = transform(before)
        assert "await process(item)" in result
        assert "            yield x" in result

    def test_nested_coroutine_both_converted(self):
        before = '''from tornado import gen

@gen.coroutine
def outer():
    @gen.coroutine
    def inner():
        result = yield compute()
        raise gen.Return(result)
    val = yield inner()
    raise gen.Return(val)
'''
        result = transform(before)
        assert result.count("async def") == 2
        assert result.count("await") == 2
        assert "@gen.coroutine" not in result


class TestNewPatterns:
    """Verify extended transformation patterns."""

    def test_yield_tuple_to_gather(self):
        before = '''from tornado import gen

@gen.coroutine
def foo():
    a, b = yield (bar(), baz())
    raise gen.Return((a, b))
'''
        result = transform(before)
        assert "asyncio.gather" in result
        assert "import asyncio" in result

    def test_gen_moment_to_sleep_zero(self):
        before = '''from tornado import gen

@gen.coroutine
def foo():
    yield gen.moment
'''
        result = transform(before)
        assert "asyncio.sleep(0)" in result
        assert "import asyncio" in result

    def test_yield_set_raises_error(self):
        code = '''from tornado import gen

@gen.coroutine
def foo():
    result = yield {bar(), baz()}
'''
        with pytest.raises(TransformError):
            transform(code)

    def test_already_async_not_modified(self):
        code = '''import tornado

class Test(tornado.testing.AsyncHTTPTestCase):
    @tornado.testing.gen_test
    async def test_it(self):
        response = await self.fetch("/")
        expected = yield helper()
        assert response == expected
'''
        result = transform(code)
        assert result == code

    def test_asyncio_import_added_for_gather(self):
        before = '''from tornado import gen

@gen.coroutine
def foo():
    results = yield [bar(), baz()]
    raise gen.Return(results)
'''
        result = transform(before)
        assert "import asyncio" in result
        assert "asyncio.gather" in result

    def test_asyncio_import_added_for_sleep(self):
        before = '''from tornado import gen

@gen.coroutine
def foo():
    yield gen.sleep(1)
'''
        result = transform(before)
        assert "import asyncio" in result
        assert "asyncio.sleep" in result

    def test_dict_yield_raises_error(self):
        code = '''from tornado import gen

@gen.coroutine
def foo():
    result = yield {"a": bar()}
'''
        with pytest.raises(TransformError):
            transform(code)
