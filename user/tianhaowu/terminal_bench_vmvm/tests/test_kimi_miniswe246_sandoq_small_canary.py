from __future__ import annotations

import asyncio
import json
import stat
import tomllib
from pathlib import Path

import kimi_miniswe246_sandoq_small_canary as canary
import pytest
import qwen_miniswe246_sandoq_smoke as shared
from aiohttp import ClientSession, web


def _router_stats(*, model_calls: int = 3) -> dict[str, object]:
    session_counts = [0] * canary.EXPECTED_WORKERS
    session_counts[7] = 1
    return {
        "kind": "direct-kimi-transparent-router",
        "implementation": "direct-kimi-transparent-v2",
        "policy": "consistent_hash",
        "request_id_headers": ["x-session-id"],
        "capacity_profile": canary.EXPECTED_ROUTER_PROFILE,
        "endpoint_identifier": canary.EXPECTED_ENDPOINT_IDENTIFIER,
        "worker_count": canary.EXPECTED_WORKERS,
        "active_workers": canary.EXPECTED_WORKERS,
        "configured_capacity": 64,
        "configured_per_worker_capacity": 2,
        "chat_requests": model_calls,
        "total_requests": model_calls + 1,
        "active_requests": 0,
        "active_forwarded_requests": 0,
        "active_chat_requests": 0,
        "active_worker_waiters": 0,
        "missing_session_rejections": 0,
        "upstream_failures": 0,
        "upstream_http_429": 0,
        "upstream_http_5xx": 0,
        "worker_queue_timeouts": 0,
        "capacity_rejections": 0,
        "max_active_forwarded_requests": 1,
        "tracked_sessions": 1,
        "cross_route_anomalies": 0,
        "worker_session_counts": session_counts,
    }


def test_router_audit_requires_w2_sticky_healthy_route() -> None:
    assert canary.router_audit(_router_stats(), 3) == {
        "router_w2_profile_configured": True,
        "sticky_routing": True,
        "router_healthy": True,
    }
    changed = _router_stats()
    changed["configured_per_worker_capacity"] = 1
    assert canary.router_audit(changed, 3)["router_w2_profile_configured"] is False
    changed = _router_stats()
    changed["cross_route_anomalies"] = 1
    assert canary.router_audit(changed, 3)["sticky_routing"] is False
    changed = _router_stats()
    changed["upstream_failures"] = 1
    assert canary.router_audit(changed, 3)["router_healthy"] is False


def test_public_receipt_is_aggregate_only() -> None:
    state = {
        "sandbox_lifecycle": True,
        "model_calls": 3,
        "shell_execution": True,
        "exact_native_submission_marker": True,
        "reasoning_content_retained": True,
        "reward": 1.0,
        "program_exit_ok": True,
        "api_calls_match": True,
        "mini_version_match": True,
    }
    receipt = canary.public_receipt(
        state,
        cleanup=True,
        router=canary.router_audit(_router_stats(), 3),
    )

    assert receipt["status"] == "strict_passed"
    assert receipt["kind"] == canary.RECEIPT_KIND
    assert receipt["task_count"] == 1
    assert receipt["max_model_calls"] == 3
    assert receipt["harness_version"] == "2.4.6"
    assert receipt["sandbox_environment"] == "oci-runner-firecracker-small"
    assert set(receipt) == {
        "schema_version",
        "kind",
        "task_count",
        "max_model_calls",
        "harness_version",
        "sandbox_environment",
        "sandbox_lifecycle",
        "model_calls",
        "shell_execution",
        "exact_native_submission_marker",
        "reasoning_content_retained",
        "reward",
        "cleanup",
        "router_w2_profile_configured",
        "sticky_routing",
        "router_healthy",
        "status",
    }


def test_direct_router_urls_are_loopback_only() -> None:
    assert canary._loopback_url("http://127.0.0.1:8123/v1/", "/v1") == "http://127.0.0.1:8123/v1"
    with pytest.raises(canary.CanaryError, match="direct_router_url_invalid"):
        canary._loopback_url("http://example.invalid:8123/v1", "/v1")
    with pytest.raises(canary.CanaryError, match="direct_router_url_invalid"):
        canary._loopback_url("http://127.0.0.1:8123/not-v1", "/v1")


def test_kimi_model_relay_caps_tokens_and_preserves_reasoning() -> None:
    async def scenario() -> None:
        seen: list[dict[str, object]] = []

        async def completion(request: web.Request) -> web.Response:
            seen.append(await request.json())
            return web.json_response(
                {
                    "id": "completion-1",
                    "object": "chat.completion",
                    "created": 1,
                    "model": canary.MODEL,
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "done",
                                "reasoning": "retained",
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }
            )

        app = web.Application()
        app.router.add_post("/v1/chat/completions", completion)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        assert site._server is not None and site._server.sockets
        port = int(site._server.sockets[0].getsockname()[1])
        relay = shared.ModelRelay(
            f"http://127.0.0.1:{port}/v1",
            "EMPTY",
            "opaque-session",
            model=canary.MODEL,
            max_output_tokens=canary.MAX_OUTPUT_TOKENS,
            reasoning_effort="max",
        )
        await relay.start()
        try:
            async with ClientSession() as client:
                async with client.post(
                    f"http://127.0.0.1:{relay.port}/v1/chat/completions",
                    json={
                        "model": canary.MODEL,
                        "messages": [{"role": "user", "content": "test"}],
                        "max_tokens": 4096,
                        "stream": False,
                    },
                ) as response:
                    assert response.status == 200
                    forwarded = await response.json()
        finally:
            await relay.close()
            await runner.cleanup()

        assert len(seen) == 1
        assert seen[0]["model"] == canary.MODEL
        assert seen[0]["max_tokens"] == canary.MAX_OUTPUT_TOKENS
        assert seen[0]["reasoning_effort"] == "max"
        assert seen[0]["chat_template_kwargs"] == {
            "enable_thinking": True,
            "preserve_thinking": True,
        }
        message = forwarded["choices"][0]["message"]
        assert message["reasoning"] == "retained"
        assert message["reasoning_content"] == "retained"
        assert relay.reasoning == [True]

    asyncio.run(scenario())


def test_model_relay_hard_caps_concurrent_requests() -> None:
    async def scenario() -> None:
        entered = asyncio.Event()
        release = asyncio.Event()
        upstream_calls = 0

        async def completion(_request: web.Request) -> web.Response:
            nonlocal upstream_calls
            upstream_calls += 1
            if upstream_calls == 1:
                entered.set()
            await release.wait()
            return web.json_response(
                {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "done",
                                "reasoning_content": "retained",
                            }
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
        assert site._server is not None and site._server.sockets
        port = int(site._server.sockets[0].getsockname()[1])
        relay = shared.ModelRelay(
            f"http://127.0.0.1:{port}/v1",
            "EMPTY",
            "opaque-session",
            model=canary.MODEL,
            max_output_tokens=canary.MAX_OUTPUT_TOKENS,
            reasoning_effort="max",
        )
        await relay.start()
        try:
            async with ClientSession() as client:
                requests = [
                    asyncio.create_task(
                        client.post(
                            f"http://127.0.0.1:{relay.port}/v1/chat/completions",
                            json={"model": canary.MODEL, "messages": [], "stream": False},
                        )
                    )
                    for _ in range(canary.MAX_MODEL_CALLS + 1)
                ]
                await asyncio.wait_for(entered.wait(), timeout=5)
                for _ in range(100):
                    if len(relay.requests) == canary.MAX_MODEL_CALLS:
                        break
                    await asyncio.sleep(0.01)
                assert len(relay.requests) == canary.MAX_MODEL_CALLS
                release.set()
                responses = await asyncio.gather(*requests)
                statuses = [response.status for response in responses]
                for response in responses:
                    await response.read()
                    response.release()
        finally:
            release.set()
            await relay.close()
            await runner.cleanup()

        assert statuses.count(200) == canary.MAX_MODEL_CALLS
        assert statuses.count(429) == 1
        assert upstream_calls == canary.MAX_MODEL_CALLS
        assert len(relay.requests) == canary.MAX_MODEL_CALLS

    asyncio.run(scenario())


def test_frozen_config_and_launcher_contract() -> None:
    workflow = Path(__file__).resolve().parents[1]
    config_path = (
        workflow
        / "configs/eval/servers/cpu-132-021_8103/kimi_miniswe246_sandoq_firecracker_small_smoke.toml"
    )
    profile_path = (
        workflow
        / "configs/provider_context/use2/cpu-132-021_8103/kimi_sandoq_firecracker_small_host.json"
    )
    launcher_path = workflow / "run_kimi_miniswe246_sandoq_small_canary.sbatch"
    config = tomllib.loads(config_path.read_text())
    profile = json.loads(profile_path.read_text())
    launcher = launcher_path.read_text()
    runner = (workflow / "kimi_miniswe246_sandoq_small_canary.py").read_text()

    assert shared.sha256_file(config_path) == canary.EVAL_CONFIG_SHA256
    assert shared.sha256_file(profile_path) == canary.PROVIDER_PROFILE_SHA256
    assert shared.sha256_file(workflow / "qwen_miniswe246_sandoq_smoke.py") == canary.SHARED_SMOKE_SHA256
    assert config["model"] == canary.MODEL
    assert config["num_tasks"] == 1
    assert config["num_rollouts"] == 1
    assert config["max_turns"] == canary.MAX_MODEL_CALLS
    assert canary.MAX_MODEL_CALLS == 3
    assert canary.MODEL_TIMEOUT_SECONDS * canary.MAX_MODEL_CALLS < canary.EXECUTION_WALL_SECONDS
    assert canary.EXECUTE_PROCESS_TIMEOUT_SECONDS >= canary.EXECUTION_WALL_SECONDS
    assert (
        canary.EXECUTE_PROCESS_TIMEOUT_SECONDS
        + 10
        + canary.CLEANUP_PROCESS_TIMEOUT_SECONDS
        + 10
        + canary.SANITIZE_PROCESS_TIMEOUT_SECONDS
        + 10
        <= canary.SUPERVISOR_WALL_SECONDS
    )
    assert canary.SUPERVISOR_WALL_SECONDS + 10 <= canary.ORCHESTRATOR_WALL_SECONDS
    assert canary.ORCHESTRATOR_WALL_SECONDS <= 490
    assert config["sampling"]["reasoning_effort"] == "max"
    assert config["sampling"]["max_tokens"] == canary.MAX_OUTPUT_TOKENS
    assert config["harness"]["version"] == "2.4.6"
    assert config["harness"]["runtime"]["expected_environment"] == "oci-runner-firecracker-small"
    assert profile["environment"] == "oci-runner-firecracker-small"
    assert profile_path != workflow / "configs/provider_context/use2/qwen_sandoq_firecracker_host.json"
    assert "#SBATCH --time=00:10:00" in launcher
    assert "--capacity-profile sandoq-c64-w2-v1" in launcher
    assert "KIMI_SMALL_CANARY_EXPECTED_REVISION" in launcher
    assert '"--startup-timeout-seconds",\n            "3600",' in runner
    assert stat.S_IMODE(launcher_path.stat().st_mode) & 0o111
