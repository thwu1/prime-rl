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


def test_streaming_request_gets_keepalives_while_upstream_is_quiet() -> None:
    async def scenario() -> None:
        entered = asyncio.Event()
        release = asyncio.Event()

        async def completion(request: web.Request) -> web.Response:
            body = await request.json()
            assert body["stream"] is False
            entered.set()
            await release.wait()
            return web.json_response(
                {
                    "id": "completion-delayed",
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
                    "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
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
            keepalive_interval_seconds=0.01,
        )
        await proxy.start()
        try:
            async with ClientSession() as client:
                async with client.post(
                    f"http://127.0.0.1:{proxy.port}/v1/chat/completions",
                    headers={"Authorization": "Bearer rollout-secret"},
                    json={"model": "test-model", "messages": [], "stream": True},
                ) as response:
                    await entered.wait()
                    assert await asyncio.wait_for(response.content.readline(), timeout=1) == b": keepalive\n"
                    assert await asyncio.wait_for(response.content.readline(), timeout=1) == b"\n"
                    release.set()
                    payload = await response.text()
                    assert response.status == 200
                    assert '"content": "done"' in payload
                    assert payload.endswith("data: [DONE]\n\n")
        finally:
            release.set()
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


def test_disconnected_stream_retry_reuses_one_exact_upstream_completion() -> None:
    async def scenario() -> None:
        entered = asyncio.Event()
        release = asyncio.Event()
        upstream_bodies: list[dict] = []
        upstream_logical_ids: list[str | None] = []

        async def completion(request: web.Request) -> web.Response:
            upstream_bodies.append(await request.json())
            upstream_logical_ids.append(request.headers.get("X-VF-Logical-Request-ID"))
            entered.set()
            await release.wait()
            return web.json_response(
                {
                    "id": "completion-reused",
                    "object": "chat.completion",
                    "created": 3,
                    "model": "test-model",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "reasoning_content": "reasoning retained",
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
                    "usage": {"prompt_tokens": 8, "completion_tokens": 5, "total_tokens": 13},
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
            keepalive_interval_seconds=0.01,
        )
        await proxy.start()
        body = {"model": "test-model", "messages": [], "stream": True}
        headers = {
            "Authorization": "Bearer rollout-secret",
            "X-VF-Logical-Request-ID": "a" * 32,
        }
        first_client = ClientSession()
        retry_client = ClientSession()
        try:
            first_response = await first_client.post(
                f"http://127.0.0.1:{proxy.port}/v1/chat/completions",
                headers=headers,
                json=body,
            )
            await entered.wait()
            first_response.close()
            await first_client.close()
            for _ in range(200):
                if proxy.stats.downstream_disconnects:
                    break
                await asyncio.sleep(0.01)

            retry = await retry_client.post(
                f"http://127.0.0.1:{proxy.port}/v1/chat/completions",
                headers=headers,
                json=body,
            )
            for _ in range(200):
                if proxy.stats.coalesced_requests:
                    break
                await asyncio.sleep(0.01)
            release.set()
            payload = await retry.text()

            assert retry.status == 200
            assert '"reasoning_content": "reasoning retained"' in payload
            assert '"name": "bash"' in payload
            assert '\\"command\\":\\"pwd\\"' in payload
            assert '"finish_reason": "tool_calls"' in payload
            assert '"completion_tokens": 5' in payload
            assert len(upstream_bodies) == 1
            assert upstream_logical_ids == [None]
            stats = proxy.stats.snapshot()
            assert stats["upstream_attempts"] == 1
            assert stats["coalesced_requests"] == 1
            assert stats["downstream_disconnects"] == 1
            assert stats["inflight"] == 0
        finally:
            release.set()
            await first_client.close()
            await retry_client.close()
            await proxy.close()
            await runner.cleanup()

    asyncio.run(scenario())


def test_same_logical_request_id_with_different_body_is_rejected() -> None:
    async def scenario() -> None:
        entered = asyncio.Event()
        release = asyncio.Event()
        upstream_calls = 0

        async def completion(request: web.Request) -> web.Response:
            nonlocal upstream_calls
            upstream_calls += 1
            await request.json()
            entered.set()
            await release.wait()
            return web.json_response(
                {
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "done"},
                            "finish_reason": "stop",
                        }
                    ]
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
            keepalive_interval_seconds=0.01,
        )
        await proxy.start()
        headers = {
            "Authorization": "Bearer rollout-secret",
            "X-VF-Logical-Request-ID": "b" * 32,
        }
        client = ClientSession()
        first = asyncio.create_task(
            client.post(
                f"http://127.0.0.1:{proxy.port}/v1/chat/completions",
                headers=headers,
                json={"model": "test-model", "messages": [], "stream": True},
            )
        )
        try:
            await entered.wait()
            async with client.post(
                f"http://127.0.0.1:{proxy.port}/v1/chat/completions",
                headers=headers,
                json={
                    "model": "test-model",
                    "messages": [{"role": "user", "content": "different"}],
                    "stream": True,
                },
            ) as conflict:
                assert conflict.status == 409
                assert (await conflict.json())["error"]["message"] == "concurrent model request conflict"
            assert upstream_calls == 1
            assert proxy.stats.snapshot()["conflicting_requests"] == 1
        finally:
            release.set()
            response = await first
            await response.read()
            await client.close()
            await proxy.close()
            await runner.cleanup()

    asyncio.run(scenario())


def test_invalid_logical_request_id_is_rejected_without_upstream_call() -> None:
    async def scenario() -> None:
        proxy = BufferedChatCompletionsProxy("http://127.0.0.1:1/v1", "rollout-secret")
        await proxy.start()
        try:
            async with ClientSession() as client:
                async with client.post(
                    f"http://127.0.0.1:{proxy.port}/v1/chat/completions",
                    headers={
                        "Authorization": "Bearer rollout-secret",
                        "X-VF-Logical-Request-ID": "not-valid",
                    },
                    json={"model": "test-model", "messages": [], "stream": True},
                ) as response:
                    assert response.status == 400
            assert proxy.stats.snapshot()["upstream_attempts"] == 0
        finally:
            await proxy.close()

    asyncio.run(scenario())


def test_completed_detached_request_is_replayed_without_second_upstream_call() -> None:
    async def scenario() -> None:
        entered = asyncio.Event()
        release = asyncio.Event()
        upstream_calls = 0

        async def completion(request: web.Request) -> web.Response:
            nonlocal upstream_calls
            upstream_calls += 1
            await request.json()
            entered.set()
            await release.wait()
            return web.json_response(
                {
                    "id": "completion-replayed",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "replayed"},
                            "finish_reason": "stop",
                        }
                    ],
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
            keepalive_interval_seconds=0.01,
        )
        await proxy.start()
        body = {"model": "test-model", "messages": [], "stream": True}
        headers = {
            "Authorization": "Bearer rollout-secret",
            "X-VF-Logical-Request-ID": "c" * 32,
        }
        first_client = ClientSession()
        retry_client = ClientSession()
        try:
            first_response = await first_client.post(
                f"http://127.0.0.1:{proxy.port}/v1/chat/completions",
                headers=headers,
                json=body,
            )
            await entered.wait()
            first_response.close()
            await first_client.close()
            for _ in range(200):
                if proxy.stats.downstream_disconnects:
                    break
                await asyncio.sleep(0.01)
            release.set()
            for _ in range(200):
                if proxy.stats.inflight == 0:
                    break
                await asyncio.sleep(0.01)

            async with retry_client.post(
                f"http://127.0.0.1:{proxy.port}/v1/chat/completions",
                headers=headers,
                json=body,
            ) as retry:
                payload = await retry.text()
                assert retry.status == 200
            assert '"content": "replayed"' in payload
            assert upstream_calls == 1
            assert proxy.stats.snapshot()["replayed_requests"] == 1
        finally:
            release.set()
            await first_client.close()
            await retry_client.close()
            await proxy.close()
            await runner.cleanup()

    asyncio.run(scenario())


def test_successfully_delivered_response_remains_available_for_exact_retry() -> None:
    async def scenario() -> None:
        upstream_calls = 0

        async def completion(request: web.Request) -> web.Response:
            nonlocal upstream_calls
            upstream_calls += 1
            await request.json()
            return web.json_response(
                {
                    "id": "completion-delivered",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "same bytes"},
                            "finish_reason": "stop",
                        }
                    ],
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
        body = {"model": "test-model", "messages": [], "stream": True}
        headers = {
            "Authorization": "Bearer rollout-secret",
            "X-VF-Logical-Request-ID": "f" * 32,
        }
        try:
            async with ClientSession() as client:
                async with client.post(
                    f"http://127.0.0.1:{proxy.port}/v1/chat/completions",
                    headers=headers,
                    json=body,
                ) as first:
                    first_payload = await first.read()
                async with client.post(
                    f"http://127.0.0.1:{proxy.port}/v1/chat/completions",
                    headers=headers,
                    json=body,
                ) as retry:
                    retry_payload = await retry.read()

            assert first_payload.replace(b": keepalive\n\n", b"") == retry_payload.replace(b": keepalive\n\n", b"")
            assert upstream_calls == 1
            assert proxy.stats.snapshot()["replayed_requests"] == 1
        finally:
            await proxy.close()
            await runner.cleanup()

    asyncio.run(scenario())


def test_sequential_identical_requests_without_logical_identity_resample() -> None:
    async def scenario() -> None:
        upstream_calls = 0

        async def completion(request: web.Request) -> web.Response:
            nonlocal upstream_calls
            upstream_calls += 1
            await request.json()
            return web.json_response(
                {
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": str(upstream_calls)},
                            "finish_reason": "stop",
                        }
                    ]
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
        body = {"model": "test-model", "messages": [], "stream": True}
        headers = {"Authorization": "Bearer rollout-secret"}
        try:
            async with ClientSession() as client:
                payloads = []
                for _ in range(2):
                    async with client.post(
                        f"http://127.0.0.1:{proxy.port}/v1/chat/completions",
                        headers=headers,
                        json=body,
                    ) as response:
                        payloads.append(await response.text())
            assert upstream_calls == 2
            assert '"content": "1"' in payloads[0]
            assert '"content": "2"' in payloads[1]
            assert proxy.stats.snapshot()["replayed_requests"] == 0
        finally:
            await proxy.close()
            await runner.cleanup()

    asyncio.run(scenario())


def test_failed_detached_request_is_not_replayed() -> None:
    async def scenario() -> None:
        entered = asyncio.Event()
        release = asyncio.Event()
        upstream_calls = 0

        async def completion(request: web.Request) -> web.Response:
            nonlocal upstream_calls
            upstream_calls += 1
            await request.json()
            if upstream_calls == 1:
                entered.set()
                await release.wait()
                return web.json_response({"error": {"message": "retry"}}, status=503)
            return web.json_response(
                {
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "second attempt"},
                            "finish_reason": "stop",
                        }
                    ]
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
            keepalive_interval_seconds=0.01,
        )
        await proxy.start()
        body = {"model": "test-model", "messages": [], "stream": True}
        headers = {
            "Authorization": "Bearer rollout-secret",
            "X-VF-Logical-Request-ID": "d" * 32,
        }
        first_client = ClientSession()
        retry_client = ClientSession()
        try:
            first_response = await first_client.post(
                f"http://127.0.0.1:{proxy.port}/v1/chat/completions",
                headers=headers,
                json=body,
            )
            await entered.wait()
            first_response.close()
            await first_client.close()
            for _ in range(200):
                if proxy.stats.downstream_disconnects:
                    break
                await asyncio.sleep(0.01)
            release.set()
            for _ in range(200):
                if proxy.stats.inflight == 0:
                    break
                await asyncio.sleep(0.01)

            async with retry_client.post(
                f"http://127.0.0.1:{proxy.port}/v1/chat/completions",
                headers=headers,
                json=body,
            ) as retry:
                payload = await retry.text()
                assert retry.status == 200
            assert '"content": "second attempt"' in payload
            assert upstream_calls == 2
            stats = proxy.stats.snapshot()
            assert stats["upstream_attempts"] == 2
            assert stats["replayed_requests"] == 0
        finally:
            release.set()
            await first_client.close()
            await retry_client.close()
            await proxy.close()
            await runner.cleanup()

    asyncio.run(scenario())


def test_proxy_close_cancels_retained_upstream_and_stats_are_aggregate_only() -> None:
    async def scenario() -> None:
        entered = asyncio.Event()
        release = asyncio.Event()

        async def completion(request: web.Request) -> web.Response:
            await request.json()
            entered.set()
            await release.wait()
            return web.json_response({"unreachable": True})

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
        retained = await proxy._join_completion(
            "chat_completions",
            {"model": "test-model", "messages": [], "stream": False},
            {"Authorization": "Bearer rollout-secret"},
            "e" * 32,
        )
        assert retained is not None
        await entered.wait()
        await asyncio.wait_for(proxy.close(), timeout=2)

        assert retained.task.cancelled()
        snapshot = proxy.stats.snapshot()
        assert snapshot["inflight"] == 0
        assert not any("identity" in key or "digest" in key or "session" in key for key in snapshot)
        release.set()
        await runner.cleanup()

    asyncio.run(scenario())
