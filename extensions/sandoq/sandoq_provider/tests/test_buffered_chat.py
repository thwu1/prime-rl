from __future__ import annotations

import asyncio

from aiohttp import ClientSession, web
from sandoq_provider.buffered_chat import BufferedChatCompletionsProxy
from verifiers.v1.dialects import ResponsesDialect


def test_streaming_request_is_buffered_upstream_and_returned_as_sse() -> None:
    async def scenario() -> None:
        seen: list[dict] = []

        async def completion(request: web.Request) -> web.Response:
            seen.append(await request.json())
            return web.json_response(
                {
                    "id": "completion-1",
                    "object": "chat.completion",
                    "created": 1,
                    "model": "test-model",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "done"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 3,
                        "completion_tokens": 1,
                        "total_tokens": 4,
                    },
                }
            )

        app = web.Application()
        app.router.add_post("/v1/chat/completions", completion)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        server = site._server
        assert server is not None and server.sockets
        upstream_port = int(server.sockets[0].getsockname()[1])

        proxy = BufferedChatCompletionsProxy(
            f"http://127.0.0.1:{upstream_port}/v1",
            "rollout-secret",
        )
        await proxy.start()
        try:
            async with ClientSession() as client:
                async with client.post(
                    f"http://127.0.0.1:{proxy.port}/v1/chat/completions",
                    headers={"Authorization": "Bearer rollout-secret"},
                    json={"model": "test-model", "messages": [], "stream": True},
                ) as response:
                    payload = await response.text()
                    assert response.status == 200
                    assert response.content_type == "text/event-stream"
            assert seen == [{"model": "test-model", "messages": [], "stream": False}]
            assert '"object": "chat.completion.chunk"' in payload
            assert '"content": "done"' in payload
            assert payload.endswith("data: [DONE]\n\n")
            assert proxy.stats.snapshot()["streamed_requests"] == 1
        finally:
            await proxy.close()
            await runner.cleanup()

    asyncio.run(scenario())


def test_proxy_rejects_wrong_rollout_secret() -> None:
    async def scenario() -> None:
        proxy = BufferedChatCompletionsProxy("http://127.0.0.1:1/v1", "right")
        await proxy.start()
        try:
            async with ClientSession() as client:
                async with client.post(
                    f"http://127.0.0.1:{proxy.port}/v1/chat/completions",
                    headers={"Authorization": "Bearer wrong"},
                    json={},
                ) as response:
                    assert response.status == 401
        finally:
            await proxy.close()

    asyncio.run(scenario())


def test_responses_request_is_translated_through_chat_completions() -> None:
    async def scenario() -> None:
        seen: list[dict] = []

        async def completion(request: web.Request) -> web.Response:
            seen.append(await request.json())
            return web.json_response(
                {
                    "id": "completion-2",
                    "object": "chat.completion",
                    "created": 2,
                    "model": "policy-model",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "reasoning_content": "inspect first",
                                "tool_calls": [
                                    {
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {
                                            "name": "bash",
                                            "arguments": '{"command":"pwd"}',
                                        },
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 5,
                        "completion_tokens": 7,
                        "total_tokens": 12,
                    },
                }
            )

        app = web.Application()
        app.router.add_post("/v1/chat/completions", completion)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        server = site._server
        assert server is not None and server.sockets
        upstream_port = int(server.sockets[0].getsockname()[1])

        proxy = BufferedChatCompletionsProxy(
            f"http://127.0.0.1:{upstream_port}/v1",
            "rollout-secret",
        )
        await proxy.start()
        try:
            async with ClientSession() as client:
                async with client.post(
                    f"http://127.0.0.1:{proxy.port}/v1/responses",
                    headers={"Authorization": "Bearer rollout-secret"},
                    json={
                        "model": "policy",
                        "instructions": "work carefully",
                        "input": "fix the bug",
                        "tools": [
                            {
                                "type": "function",
                                "name": "bash",
                                "description": "run a command",
                                "parameters": {
                                    "type": "object",
                                    "properties": {"command": {"type": "string"}},
                                    "required": ["command"],
                                },
                            }
                        ],
                        "stream": True,
                        "max_output_tokens": 128,
                        "reasoning": {"effort": "high"},
                    },
                ) as response:
                    chunks = [chunk async for chunk in response.content.iter_any() if chunk]
                    assert response.status == 200
                    assert response.content_type == "text/event-stream"

            assert seen[0]["stream"] is False
            assert seen[0]["messages"][0] == {
                "role": "system",
                "content": "work carefully",
            }
            assert seen[0]["messages"][1] == {
                "role": "user",
                "content": "fix the bug",
            }
            assert seen[0]["tools"][0]["function"]["name"] == "bash"
            assert seen[0]["max_completion_tokens"] == 128
            assert seen[0]["reasoning_effort"] == "high"

            # The production interception parser accepts the synthesized stream
            # and recovers the model's tool call from its terminal response.
            parser = ResponsesDialect().stream_parser()
            events = [event + b"\n\n" for event in b"".join(chunks).split(b"\n\n") if event]
            for event in events:
                parser.feed(event)
                if event.startswith(b"data: [DONE]"):
                    parser.on_done()
            parsed = parser.finish()
            assert parsed.message.reasoning_content == "inspect first"
            assert parsed.message.tool_calls is not None
            assert parsed.message.tool_calls[0].name == "bash"
            assert parsed.message.tool_calls[0].arguments == '{"command":"pwd"}'
            assert proxy.stats.snapshot()["protocols"] == {"responses": 1}
        finally:
            await proxy.close()
            await runner.cleanup()

    asyncio.run(scenario())
