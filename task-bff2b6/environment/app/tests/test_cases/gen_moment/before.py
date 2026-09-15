"""
A coroutine that yields gen.moment to allow the IOLoop to run one iteration.
"""
from tornado import gen


@gen.coroutine
def process_with_yield_point():
    yield gen.moment
    result = yield compute()
    raise gen.Return(result)
