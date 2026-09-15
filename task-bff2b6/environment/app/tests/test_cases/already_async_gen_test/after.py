"""
A tornado gen_test that is already async. Function should not be modified.
"""

# Contrived example confirming that already-async functions are left unchanged.
import some_experimental_pytest_decorator_that_allows_yielding_in_test_flow
import tornado

from my_app import make_application


class TestMyTornadoApp(tornado.testing.AsyncHTTPTestCase):
    def get_app(self):
        return make_application()

    @tornado.testing.gen_test
    @some_experimental_pytest_decorator_that_allows_yielding_in_test_flow(b"pong")
    async def test_ping_route(self, yielder):
        response = await self.fetch("/ping")
        expected_response = yield yielder()
        assert response.body == expected_response
