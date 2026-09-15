"""
A coroutine that yields gen.moment to allow the IOLoop to run one iteration.
"""
from tornado import gen
import asyncio


async def process_with_yield_point():
    await asyncio.sleep(0)
    result = await compute()
    return result
