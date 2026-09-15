#!/usr/bin/env python3
"""Sets up the tornado-async-transformer project skeleton at /app/."""
import os


def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)


# =============================================================================
# Package: tornado_async_transformer
# =============================================================================

write_file('/app/tornado_async_transformer/__init__.py', '''\
from tornado_async_transformer.transformer import TornadoAsyncTransformer, TransformError

__all__ = ["TornadoAsyncTransformer", "TransformError"]
''')

write_file('/app/tornado_async_transformer/transformer.py', '''\
"""
Implement the TornadoAsyncTransformer here.

This transformer should convert Tornado's legacy @gen.coroutine/yield
async syntax to Python 3.5+ native async/await syntax.

The transformer should:
- Be a subclass of libcst.CSTTransformer
- Transform @gen.coroutine decorated functions to async functions
- Convert yield expressions to await expressions within coroutines
- Convert raise gen.Return(x) to return x
- Handle various import styles (import tornado, from tornado import gen,
  from tornado.gen import coroutine, etc.)
- Handle @tornado.testing.gen_test decorators (keep the decorator, but
  still make the function async and convert yields)
- Convert yield [list] and yield [listcomp] to await asyncio.gather(*)
- Convert gen.sleep() to asyncio.sleep()
- Automatically add 'import asyncio' when asyncio usage is introduced
- Raise TransformError for unsupported patterns (gen.Task, dict yields)
- Correctly handle nested coroutines vs nested plain generator functions
- Preserve all other code, whitespace, and formatting exactly

See the test cases in tests/test_cases/ for specific transformation examples.
See the exception cases in tests/exception_cases/ for error handling examples.
"""
import libcst as cst


class TransformError(Exception):
    """Error raised upon encountering a known unsupported pattern."""
    pass


class TornadoAsyncTransformer(cst.CSTTransformer):
    """
    A libcst transformer that replaces the legacy @gen.coroutine/yield
    async syntax with Python 3.5+ native async/await syntax.

    This transformer does not remove any tornado imports from modified files.
    """
    pass
''')

write_file('/app/tornado_async_transformer/helpers.py', '''\
"""
Implement any helper functions needed by the transformer here.

You may want helpers for:
- Generating matchers that handle multiple import styles for the same symbol
  (e.g. matching tornado.gen.coroutine, gen.coroutine, and coroutine)
- Adding import statements to a module's CST
"""
''')

# =============================================================================
# Test infrastructure
# =============================================================================

write_file('/app/tests/__init__.py', '')

write_file('/app/tests/collector.py', '''\
import ast
import os
from typing import Any, List, NamedTuple, Tuple

import pytest


class TestCase(NamedTuple):
    before: str
    after: str


def collect_test_cases() -> Tuple[Any, ...]:
    root_test_cases_directory = os.path.join(os.path.dirname(__file__), "test_cases")

    test_cases: List = []
    for root, _, files in os.walk(root_test_cases_directory):
        if not {"before.py", "after.py"} <= set(files):
            continue

        test_case_name = os.path.basename(root).replace("_", " ")

        with open(os.path.join(root, "before.py")) as before_file:
            before = before_file.read()

        with open(os.path.join(root, "after.py")) as after_file:
            after = after_file.read()

        test_cases.append(
            pytest.param(TestCase(before=before, after=after), id=test_case_name)
        )

    return tuple(test_cases)


class ExceptionCase(NamedTuple):
    source: str
    expected_error_message: str


def collect_exception_cases() -> Tuple[Any, ...]:
    root_exception_cases_directory = os.path.join(
        os.path.dirname(__file__), "exception_cases"
    )

    # all .py files in the top-level of exception cases directory
    python_files = [
        os.path.join(root_exception_cases_directory, file)
        for file in os.listdir(root_exception_cases_directory)
        if file[-3:] == ".py"
    ]

    exception_cases: List = []
    for python_filename in python_files:
        with open(python_filename) as python_file:
            source = python_file.read()

        # the module\'s docstring is the expected error message
        ast_tree = ast.parse(source)
        docstring = ast.get_docstring(ast_tree)
        expected_error_message = docstring.replace("\\n", " ")

        test_case_name = os.path.basename(python_filename).replace("_", " ")

        exception_cases.append(
            pytest.param(
                ExceptionCase(
                    source=source, expected_error_message=expected_error_message
                ),
                id=test_case_name,
            )
        )

    return tuple(exception_cases)
''')

write_file('/app/tests/test_transformer.py', '''\
import libcst
import pytest

from tornado_async_transformer import TornadoAsyncTransformer, TransformError

from tests.collector import (
    ExceptionCase,
    collect_exception_cases,
    TestCase,
    collect_test_cases,
)


@pytest.mark.parametrize("test_case", collect_test_cases())
def test_python_module(test_case: TestCase) -> None:
    source_tree = libcst.parse_module(test_case.before)
    visited_tree = source_tree.visit(TornadoAsyncTransformer())
    assert visited_tree.code == test_case.after


@pytest.mark.parametrize("exception_case", collect_exception_cases())
def test_unsupported_python_module(exception_case: ExceptionCase) -> None:
    source_tree = libcst.parse_module(exception_case.source)

    with pytest.raises(TransformError) as exception:
        source_tree.visit(TornadoAsyncTransformer())

    assert exception_case.expected_error_message in str(exception.value)
''')

# =============================================================================
# Test cases: before/after transformation pairs
# =============================================================================

test_cases = {}

# 1. simple_coroutine
test_cases['simple_coroutine'] = {
    'before': '''\
"""
A simple coroutine.
"""
from tornado import gen


@gen.coroutine
def call_api():
    response = yield fetch()
    if response.status != 200:
        raise BadStatusError()
    raise gen.Return(response.data)
''',
    'after': '''\
"""
A simple coroutine.
"""
from tornado import gen


async def call_api():
    response = await fetch()
    if response.status != 200:
        raise BadStatusError()
    return response.data
''',
}

# 2. simple_coroutine_import_tornado
test_cases['simple_coroutine_import_tornado'] = {
    'before': '''\
"""
A simple coroutine in a module that imports the tornado package.
"""
import tornado


@tornado.gen.coroutine
def call_api():
    response = yield fetch()
    if response.status != 200:
        raise BadStatusError()
    if response.status == 204:
        raise tornado.gen.Return
    raise tornado.gen.Return(response.data)
''',
    'after': '''\
"""
A simple coroutine in a module that imports the tornado package.
"""
import tornado


async def call_api():
    response = await fetch()
    if response.status != 200:
        raise BadStatusError()
    if response.status == 204:
        return
    return response.data
''',
}

# 3. gen_return_statement
test_cases['gen_return_statement'] = {
    'before': '''\
"""
A coroutine that raises gen.Return directly instead of gen.Return(...).
"""
from tornado import gen


@gen.coroutine
def check_id_valid(id: str):
    response = yield fetch(id)
    if response.status != 200:
        raise InvalidID()

    raise gen.Return
''',
    'after': '''\
"""
A coroutine that raises gen.Return directly instead of gen.Return(...).
"""
from tornado import gen


async def check_id_valid(id: str):
    response = await fetch(id)
    if response.status != 200:
        raise InvalidID()

    return
''',
}

# 4. gen_return_call_no_args
test_cases['gen_return_call_no_args'] = {
    'before': '''\
"""
A coroutine that raises gen.Return() with no args.
"""
from tornado import gen


@gen.coroutine
def check_id_valid(id: str):
    response = yield fetch(id)
    if response.status != 200:
        raise InvalidID()

    raise gen.Return()
''',
    'after': '''\
"""
A coroutine that raises gen.Return() with no args.
"""
from tornado import gen


async def check_id_valid(id: str):
    response = await fetch(id)
    if response.status != 200:
        raise InvalidID()

    return
''',
}

# 5. gen_return_dict_multi_line
test_cases['gen_return_dict_multi_line'] = {
    'before': '''\
"""
A coroutine that returns a dict that spanning multiple lines.
"""
from tornado import gen

@gen.coroutine
def fetch_user(id):
    response = yield fetch(id)
    raise gen.Return({
        'user': response.user,
        'source': 'user-api'
    })
''',
    'after': '''\
"""
A coroutine that returns a dict that spanning multiple lines.
"""
from tornado import gen

async def fetch_user(id):
    response = await fetch(id)
    return {
        'user': response.user,
        'source': 'user-api'
    }
''',
}

# 6. gen_sleep
test_cases['gen_sleep'] = {
    'before': '''\
"""
A coroutine that calls gen.sleep.
"""
from tornado import gen


@gen.coroutine
def ping():
    yield gen.sleep(10)
    raise gen.Return("pong")
''',
    'after': '''\
"""
A coroutine that calls gen.sleep.
"""
from tornado import gen
import asyncio


async def ping():
    await asyncio.sleep(10)
    return "pong"
''',
}

# 7. yield_list
test_cases['yield_list'] = {
    'before': '''\
"""
A coroutine that yields a list of yieldable objects.
See: https://www.tornadoweb.org/en/stable/gen.html.
"""
from tornado import gen


@gen.coroutine
def get_two_users(user_id_1, user_id_2):
    response_1, reponse_2 = yield [fetch(user_id_1), fetch(user_id_2)]
    raise gen.Return((response_1.user, response_2.user))
''',
    'after': '''\
"""
A coroutine that yields a list of yieldable objects.
See: https://www.tornadoweb.org/en/stable/gen.html.
"""
from tornado import gen
import asyncio


async def get_two_users(user_id_1, user_id_2):
    response_1, reponse_2 = await asyncio.gather(*[fetch(user_id_1), fetch(user_id_2)])
    return (response_1.user, response_2.user)
''',
}

# 8. yield_list_comprehension
test_cases['yield_list_comprehension'] = {
    'before': '''\
"""
A coroutine that yields a list comprehension that creates a list of yieldable objects.
See: https://www.tornadoweb.org/en/stable/gen.html.
"""
from tornado import gen


@gen.coroutine
def get_users(user_ids):
    users = yield [fetch(user_id) for user_id in user_ids]
    raise gen.Return(users)
''',
    'after': '''\
"""
A coroutine that yields a list comprehension that creates a list of yieldable objects.
See: https://www.tornadoweb.org/en/stable/gen.html.
"""
from tornado import gen
import asyncio


async def get_users(user_ids):
    users = await asyncio.gather(*[fetch(user_id) for user_id in user_ids])
    return users
''',
}

# 9. nested_coroutine
test_cases['nested_coroutine'] = {
    'before': '''\
"""
A simple coroutine that contains a nested coroutine.
"""
from tornado import gen


@gen.coroutine
def call_api():
    @gen.coroutine
    def nested_callback(response):
        if response.status != 200:
            raise gen.Return(response)

        body = yield response.json()
        if body["api-update-available"]:
            print("note: update api")
        raise gen.Return(response)

    response = yield fetch(middleware=nested_callback)
    if response.status != 200:
        raise BadStatusError()
    raise gen.Return(response.data)
''',
    'after': '''\
"""
A simple coroutine that contains a nested coroutine.
"""
from tornado import gen


async def call_api():
    async def nested_callback(response):
        if response.status != 200:
            return response

        body = await response.json()
        if body["api-update-available"]:
            print("note: update api")
        return response

    response = await fetch(middleware=nested_callback)
    if response.status != 200:
        raise BadStatusError()
    return response.data
''',
}

# 10. coroutine_with_nested_generator_function
test_cases['coroutine_with_nested_generator_function'] = {
    'before': '''\
"""
A coroutine with a nested, non-coroutine generator function.
"""
from typing import List

from tornado import gen


@gen.coroutine
def save_users(users):
    def build_user_ids(users):
        for user in users:
            yield "{}-{}".format(user.first_name, user.last_name)

    for user_id in build_user_ids(users):
        yield fetch("POST", user_id)
''',
    'after': '''\
"""
A coroutine with a nested, non-coroutine generator function.
"""
from typing import List

from tornado import gen


async def save_users(users):
    def build_user_ids(users):
        for user in users:
            yield "{}-{}".format(user.first_name, user.last_name)

    for user_id in build_user_ids(users):
        await fetch("POST", user_id)
''',
}

# 11. non_coroutine_returns_coroutine
test_cases['non_coroutine_returns_coroutine'] = {
    'before': '''\
"""
A non-coroutine function that returns a coroutine.
"""
from tornado import gen


def make_simple_fetch(url: str):
    @gen.coroutine
    def my_simple_fetch(body):
        response = yield fetch(url, body)
        raise gen.Return(response.body)

    return my_simple_fetch
''',
    'after': '''\
"""
A non-coroutine function that returns a coroutine.
"""
from tornado import gen


def make_simple_fetch(url: str):
    async def my_simple_fetch(body):
        response = await fetch(url, body)
        return response.body

    return my_simple_fetch
''',
}

# 12. multiple_decorators
test_cases['multiple_decorators'] = {
    'before': '''\
"""
A few coroutines that have multiple decorators in addition to @gen.coroutine.
"""
from tornado import gen
from util.decorators import route, deprecated, log_args

@gen.coroutine
@route("/user/:id")
def user_page(id):
    user = yield get_user(id)
    user_page = "<div>{}</div>".format(user.name)
    raise gen.Return(user_page)


@deprecated
@gen.coroutine
@log_args
def get_user(id):
    response = yield fetch(id)
    raise gen.Return(response.user)
''',
    'after': '''\
"""
A few coroutines that have multiple decorators in addition to @gen.coroutine.
"""
from tornado import gen
from util.decorators import route, deprecated, log_args

@route("/user/:id")
async def user_page(id):
    user = await get_user(id)
    user_page = "<div>{}</div>".format(user.name)
    return user_page


@deprecated
@log_args
async def get_user(id):
    response = await fetch(id)
    return response.user
''',
}

# 13. gen_test
test_cases['gen_test'] = {
    'before': '''\
"""
A tornado gen_test using @gen_test decorator.
"""

from tornado.testing import gen_test, AsyncHTTPTestCase

from my_app import make_application


class TestMyTornadoApp(AsyncHTTPTestCase):
    def get_app(self):
        return make_application()

    @gen_test
    def test_ping_route(self):
        response = yield self.fetch("/ping")
        assert response.body == b"pong"
''',
    'after': '''\
"""
A tornado gen_test using @gen_test decorator.
"""

from tornado.testing import gen_test, AsyncHTTPTestCase

from my_app import make_application


class TestMyTornadoApp(AsyncHTTPTestCase):
    def get_app(self):
        return make_application()

    @gen_test
    async def test_ping_route(self):
        response = await self.fetch("/ping")
        assert response.body == b"pong"
''',
}

# 14. testing_gen_test
test_cases['testing_gen_test'] = {
    'before': '''\
"""
A tornado gen_test using @testing.gen_test decorator.
"""

from tornado import testing

from my_app import make_application


class TestMyTornadoApp(testing.AsyncHTTPTestCase):
    def get_app(self):
        return make_application()

    @testing.gen_test
    def test_ping_route(self):
        response = yield self.fetch("/ping")
        assert response.body == b"pong"
''',
    'after': '''\
"""
A tornado gen_test using @testing.gen_test decorator.
"""

from tornado import testing

from my_app import make_application


class TestMyTornadoApp(testing.AsyncHTTPTestCase):
    def get_app(self):
        return make_application()

    @testing.gen_test
    async def test_ping_route(self):
        response = await self.fetch("/ping")
        assert response.body == b"pong"
''',
}

# 15. module_level_raise
test_cases['module_level_raise'] = {
    'before': '''\
"""
A module that raises an exception outside of a function.
"""
raise NotImplementedError("This module isn't ready!")
''',
    'after': '''\
"""
A module that raises an exception outside of a function.
"""
raise NotImplementedError("This module isn't ready!")
''',
}


for name, data in test_cases.items():
    write_file(f'/app/tests/test_cases/{name}/before.py', data['before'])
    write_file(f'/app/tests/test_cases/{name}/after.py', data['after'])


# =============================================================================
# Exception cases
# =============================================================================

exception_cases = {}

exception_cases['coroutine_gen_task.py'] = '''\
"""
gen.Task (https://www.tornadoweb.org/en/branch2.4/gen.html#tornado.gen.Task)
from tornado 2.4.1 is unsupported by this codemod. This file has not been modified.
Manually update to supported syntax before running again.
"""
import time
from tornado import gen
from tornado.ioloop import IOLoop


@gen.coroutine
def ping():
    yield gen.Task(IOLoop.instance().add_timeout, time.time() + 1.5)
    raise gen.Return("pong")
'''

exception_cases['yield_dict_literal.py'] = '''\
"""
Yielding a dict of futures
(https://www.tornadoweb.org/en/branch3.2/releases/v3.2.0.html#tornado-gen)
added in tornado 3.2 is unsupported by the codemod. This file has not been
modified. Manually update to supported syntax before running again.
"""
from tornado import gen


@gen.coroutine
def get_two_users_by_id(user_id_1, user_id_2):
    users = yield {user_id_1: fetch(user_id_1), user_id_2: fetch(user_id_2)}
    raise gen.Return(users)
'''

exception_cases['yield_dict_comprehension.py'] = '''\
"""
Yielding a dict of futures
(https://www.tornadoweb.org/en/branch3.2/releases/v3.2.0.html#tornado-gen)
added in tornado 3.2 is unsupported by the codemod. This file has not been
modified. Manually update to supported syntax before running again.
"""
from tornado import gen


@gen.coroutine
def get_users_by_id(user_ids):
    users = yield {user_id: fetch(user_ids) for user_id in user_ids}
    raise gen.Return(users)
'''

exception_cases['yield_dict_call.py'] = '''\
"""
Yielding a dict of futures
(https://www.tornadoweb.org/en/branch3.2/releases/v3.2.0.html#tornado-gen)
added in tornado 3.2 is unsupported by the codemod. This file has not been
modified. Manually update to supported syntax before running again.
"""
from tornado import gen


@gen.coroutine
def get_user_friends_and_relatives(user_id):
    users = yield dict(
        friends=fetch("/friends", user_id), relatives=fetch("/relatives", user_id)
    )
    raise gen.Return(users)
'''

for name, content in exception_cases.items():
    write_file(f'/app/tests/exception_cases/{name}', content)


print("Project setup complete at /app/")
