"""
Yielding a set of futures is unsupported by this codemod. This file has not
been modified. Manually update to supported syntax before running again.
"""
from tornado import gen


@gen.coroutine
def get_all_data():
    results = yield {fetch_a(), fetch_b(), fetch_c()}
    raise gen.Return(results)
