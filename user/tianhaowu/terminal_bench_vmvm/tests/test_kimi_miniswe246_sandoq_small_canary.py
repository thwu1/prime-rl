from __future__ import annotations

import asyncio
import json
import stat
import tomllib
from pathlib import Path
from types import SimpleNamespace

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


def _stock_binding() -> dict[str, object]:
    return {
        "kind": "direct-kimi-smoke-binding",
        "source_revision": "1" * 40,
        "slurm_job_id": "123",
        "worker_manifest_sha256": "2" * 64,
        "source_spec_sha256": canary.direct_kimi_workers.STOCK_SINGLE_SPEC_SHA256,
        "source_proxy_config_sha256": canary.direct_kimi_workers.STOCK_SINGLE_PROXY_CONFIG_SHA256,
        "endpoint_bundle_sha256": "3" * 64,
        "router": {
            "capacity_profile": "sandoq-stock-single-c64-v1",
            "endpoint_identifier": "tianhaowu-kimi-k3-stock-eval-20260927",
            "worker_count": 1,
            "per_worker_capacity": 64,
        },
    }


def _transport(model_calls: int = 3) -> dict[str, object]:
    summary = {
        "requests": model_calls,
        "upstream_attempts": model_calls,
        "logical_requests": model_calls,
        "logical_upstream_attempts": model_calls,
        "anonymous_upstream_attempts": 0,
        "coalesced_requests": 0,
        "replayed_requests": 0,
        "expired_logical_retries": 0,
        "downstream_disconnects": 0,
        "conflicting_requests": 0,
        "inflight": 0,
        "streamed_requests": model_calls,
        "response_bytes": 123,
        "error_count": 0,
        "unknown_path_requests": 0,
        "statuses": {"200": model_calls},
        "protocols": {"chat_completions": model_calls},
        "path_counts": {
            "/muse-code/models": 0,
            "/v1/chat/completions": model_calls,
            "/v1/responses": 0,
        },
    }
    body = shared.canonical_json(
        {
            "schema_version": 1,
            "kind": "sandoq-buffered-model-proxy-summary",
            "counters": summary,
        }
    )
    return {
        "schema_version": 1,
        "kind": "sandoq-buffered-chat-logical-exact-once",
        "summary_record": {
            "bytes": len(body),
            "sha256": "4" * 64,
        },
        "summary": canary.supersession._buffered_proxy_audit(
            b"00:00:00 INFO "
            + canary.supersession.PROXY_SUMMARY_MARKER
            + json.dumps(summary, sort_keys=True, separators=(",", ":")).encode()
            + b"\n",
            expected_schema="logical-exact-once-v1",
        ),
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


def test_router_audit_accepts_exact_stock_single_contract() -> None:
    stats = _router_stats()
    stats.update(
        {
            "capacity_profile": "sandoq-stock-single-c64-v1",
            "endpoint_identifier": "tianhaowu-kimi-k3-stock-eval-20260927",
            "worker_count": 1,
            "active_workers": 1,
            "configured_per_worker_capacity": 64,
            "worker_session_counts": [1],
        }
    )

    assert canary.router_audit(
        stats,
        3,
        expected_profile="sandoq-stock-single-c64-v1",
        expected_endpoint_identifier="tianhaowu-kimi-k3-stock-eval-20260927",
        expected_workers=1,
        expected_per_worker_capacity=64,
    ) == {
        "router_w2_profile_configured": True,
        "sticky_routing": True,
        "router_healthy": True,
    }


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


def test_tb4_receipt_requires_numeric_reward_and_cleanup() -> None:
    state = {
        "sandbox_lifecycle": True,
        "model_calls": 3,
        "shell_execution": True,
        "exact_native_submission_marker": False,
        "reasoning_content_retained": True,
        "reward": 0.0,
        "program_exit_ok": True,
        "api_calls_match": True,
        "mini_version_match": True,
    }
    router = canary.router_audit(_router_stats(), 3)
    receipt = canary.public_receipt(
        state,
        cleanup=True,
        router=router,
        kind=canary.TB4_RECEIPT_KIND,
        binding=_stock_binding(),
        transport=_transport(),
    )
    assert receipt["schema_version"] == 3
    assert receipt["deployment"] == _stock_binding()
    assert receipt["transport"] == _transport()
    assert receipt["kind"] == canary.TB4_RECEIPT_KIND
    assert receipt["status"] == "diagnostic_passed"
    assert receipt["reward"] == 0.0
    assert canary.receipt_exit_code(receipt["status"], "tb4") == 0
    assert canary.receipt_exit_code(receipt["status"], "mobius") == 2

    missing_reward = dict(state, reward=None)
    assert (
        canary.public_receipt(
            missing_reward,
            cleanup=True,
            router=router,
            kind=canary.TB4_RECEIPT_KIND,
            binding=_stock_binding(),
            transport=_transport(),
        )["status"]
        == "failed"
    )
    assert (
        canary.public_receipt(
            state,
            cleanup=False,
            router=router,
            kind=canary.TB4_RECEIPT_KIND,
            binding=_stock_binding(),
            transport=_transport(),
        )["status"]
        == "failed"
    )
    assert (
        canary.public_receipt(
            state,
            cleanup=True,
            router=router,
            kind=canary.TB4_RECEIPT_KIND,
            binding=_stock_binding(),
        )["status"]
        == "failed"
    )


def test_transport_attestation_parses_only_exact_once_summary(tmp_path: Path) -> None:
    value = _transport()
    summary = value["summary"]
    counters = summary["integer_totals"]
    record = {
        **{key: counters[key] for key in canary.supersession.PROXY_SUMMARY_INTEGER_FIELDS},
        **{
            key: summary["mapping_totals"][key]
            for key in canary.supersession.PROXY_SUMMARY_MAPPING_FIELDS
        },
        **{
            key: counters[key]
            for key in canary.supersession.PROXY_SUMMARY_EXACT_ONCE_FIELDS
        },
    }
    directory = tmp_path / "buffered-proxy-stats"
    directory.mkdir(mode=0o700)
    path = directory / ("summary-" + "1" * 32 + ".json")
    path.write_bytes(
        shared.canonical_json(
            {
                "schema_version": 1,
                "kind": "sandoq-buffered-model-proxy-summary",
                "counters": record,
            }
        )
    )
    path.chmod(0o600)
    attestation = canary.transport_attestation(directory)
    assert canary._transport_audit_valid(attestation, 3)
    record["anonymous_upstream_attempts"] = 1
    path.write_bytes(
        shared.canonical_json(
            {
                "schema_version": 1,
                "kind": "sandoq-buffered-model-proxy-summary",
                "counters": record,
            }
        )
    )
    with pytest.raises(canary.CanaryError, match="transport_audit_invalid"):
        canary.transport_attestation(directory)


def test_smoke_binding_seals_stock_generation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_path = tmp_path / "direct_kimi_workers.json"
    manifest_path.write_text("sealed\n")
    manifest = {
        "source_spec_sha256": canary.direct_kimi_workers.STOCK_SINGLE_SPEC_SHA256,
        "source_proxy_config_sha256": canary.direct_kimi_workers.STOCK_SINGLE_PROXY_CONFIG_SHA256,
        "endpoint_bundle_sha256": "3" * 64,
        "workers": [{"backend_sha256": "4" * 64}],
        "router": {
            "capacity_profile": "sandoq-stock-single-c64-v1",
            "endpoint_identifier": "tianhaowu-kimi-k3-stock-eval-20260927",
            "per_worker_capacity": 64,
        },
    }
    monkeypatch.setattr(canary.direct_kimi_workers, "validate_saved_manifest", lambda _path: manifest)

    binding = canary.smoke_binding(
        manifest_path,
        expected_revision="1" * 40,
        expected_profile="sandoq-stock-single-c64-v1",
        expected_endpoint_identifier="tianhaowu-kimi-k3-stock-eval-20260927",
        expected_workers=1,
        expected_per_worker_capacity=64,
        slurm_job_id="123",
    )

    assert binding == {
        **_stock_binding(),
        "worker_manifest_sha256": shared.sha256_file(manifest_path),
    }


def test_cleanup_contract_counts_both_tb4_assignments(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    audit = tmp_path / "sandoq_cleanup_audit.json"
    base = {
        "kind": "sandoq-pool-cleanup",
        "state": "passed",
        "failures": 0,
        "assignments_acquired": 2,
        "assignments_cleanup_verified": 2,
        "assignment_release_rows": 2,
        "assignment_cancellation_rows": 0,
        "recorded_outer_sessions": 2,
        "outer_sessions_created": 2,
        "outer_sessions_deleted": 2,
        "verified_http_404": 2,
        "deleted_and_verified": 0,
        "already_absent": 2,
        "outer_session_high_water": 1,
        "assignment_measured_high_water": 1,
    }
    audit.write_text(json.dumps(base))
    audit.chmod(0o600)
    assert canary.cleanup_passed(audit, "tb4") is True

    mobius = dict(base)
    for field in (
        "assignments_acquired",
        "assignments_cleanup_verified",
        "assignment_release_rows",
        "recorded_outer_sessions",
        "outer_sessions_created",
        "outer_sessions_deleted",
        "verified_http_404",
        "already_absent",
    ):
        mobius[field] = 1
    audit.write_text(json.dumps(mobius))
    audit.chmod(0o600)
    assert canary.cleanup_passed(audit, "mobius") is True

    for field in (
        "assignments_acquired",
        "assignments_cleanup_verified",
        "recorded_outer_sessions",
        "outer_sessions_created",
        "outer_sessions_deleted",
    ):
        changed = dict(base, **{field: 1})
        audit.write_text(json.dumps(changed))
        audit.chmod(0o600)
        assert canary.cleanup_passed(audit, "tb4") is False


def test_tb4_releases_agent_before_separate_verifier() -> None:
    events: list[str] = []

    class Runtime:
        async def stop(self) -> None:
            events.append("agent-stop")

    class Taskset:
        async def finalize(self, _task: object, _trace: object, _runtime: object) -> None:
            events.append("finalize")

        async def solved(self, _task: object, _trace: object, _runtime: object) -> float:
            assert events == ["finalize", "agent-stop"]
            events.append("separate-verifier")
            return 0.0

    reward = asyncio.run(
        canary.finalize_and_score("tb4", Taskset(), object(), object(), Runtime())
    )
    assert reward == 0.0
    assert events == ["finalize", "agent-stop", "separate-verifier"]


def test_tb4_preserves_diagnostic_state_when_scoring_fails() -> None:
    class Runtime:
        async def stop(self) -> None:
            return None

    class Taskset:
        async def finalize(self, _task: object, _trace: object, _runtime: object) -> None:
            return None

        async def solved(self, _task: object, _trace: object, _runtime: object) -> float:
            raise RuntimeError("opaque verifier failure")

    args = (Taskset(), object(), object(), Runtime())
    reward, scoring = asyncio.run(canary.score_with_tb4_diagnostics("tb4", *args))
    assert reward is None
    assert scoring == {
        "schema_version": 1,
        "stage": "separate_verifier",
        "state": "failed",
        "failure_class": "runtime",
        "numeric_reward": False,
    }
    with pytest.raises(RuntimeError, match="opaque verifier failure"):
        asyncio.run(canary.score_with_tb4_diagnostics("mobius", *args))


def test_tb4_task_rejects_gpu_and_compose_before_clamping(tmp_path: Path) -> None:
    class Resources:
        def __init__(self, cpu: float, memory: float, disk: float, gpu: str | None = None) -> None:
            self.cpu = cpu
            self.memory = memory
            self.disk = disk
            self.gpu = gpu

        def model_copy(self, *, update: dict[str, object]) -> Resources:
            return Resources(**update)

    class Task(SimpleNamespace):
        def model_copy(self, *, update: dict[str, object]) -> Task:
            return Task(**{**vars(self), **update})

    task_dir = tmp_path / "opaque-task"
    task_dir.mkdir()
    task = Task(
        verifier_mode="separate",
        image="agent@sha256:" + "a" * 64,
        verifier_image="verifier@sha256:" + "b" * 64,
        task_dir=str(task_dir),
        resources=Resources(2.0, 4.0, 10.0),
        verifier_resources=Resources(2.0, 4.0, 10.0),
    )
    bounded = canary.clamp_tb4_task(task)
    assert (bounded.resources.cpu, bounded.resources.memory, bounded.resources.disk) == (
        1.0,
        2.0,
        10.0,
    )
    assert (
        bounded.verifier_resources.cpu,
        bounded.verifier_resources.memory,
        bounded.verifier_resources.disk,
    ) == (1.0, 2.0, 10.0)

    with pytest.raises(canary.CanaryError, match="tb4_task_invalid"):
        canary.clamp_tb4_task(task.model_copy(update={"resources": Resources(2.0, 4.0, 10.0, "GPU")}))

    environment = task_dir / "environment"
    environment.mkdir()
    (environment / "compose.yaml").write_text("services: {}\n")
    with pytest.raises(canary.CanaryError, match="tb4_task_invalid"):
        canary.clamp_tb4_task(task)


def test_tb4_task_tree_identity_detects_mutation(tmp_path: Path) -> None:
    task_dir = tmp_path / "opaque-task"
    nested = task_dir / "nested"
    nested.mkdir(parents=True)
    first = task_dir / "task.toml"
    second = nested / "payload"
    first.write_bytes(b"first\n")
    second.write_bytes(b"second\n")
    original = canary._task_tree_identity(task_dir)
    original_mode = stat.S_IMODE(second.stat().st_mode)
    assert original[0] == 2
    assert canary._task_tree_identity(task_dir) == original
    second.chmod(0o700)
    assert canary._task_tree_identity(task_dir) != original
    second.chmod(original_mode)
    assert canary._task_tree_identity(task_dir) == original
    second.write_bytes(b"changed\n")
    assert canary._task_tree_identity(task_dir) != original


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
        raw_message = relay.responses[0]["choices"][0]["message"]
        assert raw_message["reasoning"] == "retained"
        assert "reasoning_content" not in raw_message
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
    assert canary.ORCHESTRATOR_WALL_SECONDS <= 1050
    assert config["sampling"]["reasoning_effort"] == "max"
    assert config["sampling"]["max_tokens"] == canary.MAX_OUTPUT_TOKENS
    assert config["harness"]["version"] == "2.4.6"
    assert config["harness"]["runtime"]["expected_environment"] == "oci-runner-firecracker-small"
    assert profile["environment"] == "oci-runner-firecracker-small"
    assert profile_path != workflow / "configs/provider_context/use2/qwen_sandoq_firecracker_host.json"
    assert "#SBATCH --time=00:20:00" in launcher
    assert "router_deadline=$((SECONDS + 90))" in launcher
    assert "[[ $router_ready == 1 ]] || blocked router_start_failed" in launcher
    assert '--capacity-profile "$router_profile"' in launcher
    assert "sandoq-stock-single-c64-v1" in launcher
    assert "KIMI_SMALL_CANARY_EXPECTED_REVISION" in launcher
    assert '"--startup-timeout-seconds",\n            "3600",' in runner
    assert stat.S_IMODE(launcher_path.stat().st_mode) & 0o111


def test_tb4_small_scored_diagnostic_contract() -> None:
    workflow = Path(__file__).resolve().parents[1]
    config_path = (
        workflow
        / "configs/eval/servers/cpu-132-021_8103/"
        "tb4_kimi_k3_miniswe246_sandoq_firecracker_small_smoke.toml"
    )
    selector = workflow / "configs/eval/tb4_kimi_k3_short_smoke.tasks.txt"
    image_manifest = (
        workflow / "configs/eval/servers/cpu-132-021_8103/tb4_images.sandoq.json"
    )
    wrapper = workflow / "run_kimi_tb4_miniswe246_sandoq_small_smoke.sbatch"
    generic_launcher = workflow / "run_kimi_miniswe246_sandoq_small_canary.sbatch"
    runner = (workflow / "kimi_miniswe246_sandoq_small_canary.py").read_text()
    config = tomllib.loads(config_path.read_text())

    assert shared.sha256_file(config_path) == canary.TB4_EVAL_CONFIG_SHA256
    assert shared.sha256_file(selector) == canary.TB4_SELECTOR_SHA256
    assert shared.sha256_file(image_manifest) == canary.TB4_IMAGE_MANIFEST_SHA256
    assert shared.sha256_file(workflow / "direct_kimi_workers.py") == canary.DIRECT_WORKERS_SHA256
    assert config["num_tasks"] == 1
    assert config["num_rollouts"] == 1
    assert config["max_turns"] == 3
    assert config["client"]["capture_model_io"] is True
    assert config["client"]["max_retries"] == 0
    assert config["sampling"]["reasoning_effort"] == "max"
    assert config["sampling"]["max_tokens"] == canary.TB4_MAX_OUTPUT_TOKENS == 512
    assert canary.TB4_MAX_OUTPUT_TOKENS > canary.MAX_OUTPUT_TOKENS
    assert config["sampling"]["chat_template_kwargs"] == {
        "enable_thinking": True,
        "preserve_thinking": True,
    }
    assert config["taskset"]["timeout_multiplier"] == 0.5
    assert config["taskset"]["verifier_runtime_retries"] == 0
    assert config["harness"]["version"] == "2.4.6"
    assert config["harness"]["env"] == {"MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT": "10"}
    assert config["harness"]["runtime"]["expected_environment"] == (
        "oci-runner-firecracker-small"
    )
    assert config["harness"]["runtime"]["buffered_chat_completions"] is True
    assert config["harness"]["runtime"]["cpu"] == 1.0
    assert config["harness"]["runtime"]["memory"] == 2.0
    assert config["harness"]["runtime"]["disk"] == 10.0
    assert config["client"]["timeout"] == canary.TB4_MODEL_TIMEOUT_SECONDS == 1800
    assert canary.TB4_MODEL_TIMEOUT_SECONDS > canary.MODEL_TIMEOUT_SECONDS
    assert config["harness"]["runtime"]["session_timeout"] == canary.TB4_SESSION_TIMEOUT_SECONDS
    assert config["timeout"]["rollout"] == canary.TB4_EXECUTION_WALL_SECONDS
    assert "agent.wall_time_limit_seconds=6000" in config["harness"]["config_overrides"]
    assert "model.model_kwargs.timeout=1800" in config["harness"]["config_overrides"]
    assert "model.model_kwargs.max_tokens=512" in config["harness"]["config_overrides"]
    assert canary.TB4_EXECUTION_WALL_SECONDS > canary.EXECUTION_WALL_SECONDS
    assert canary.TB4_MODEL_TIMEOUT_SECONDS * canary.MAX_MODEL_CALLS < canary.TB4_AGENT_WALL_SECONDS
    assert canary.TB4_AGENT_WALL_SECONDS < canary.TB4_EXECUTION_WALL_SECONDS
    assert canary.TB4_EXECUTION_WALL_SECONDS < canary.TB4_SESSION_TIMEOUT_SECONDS
    assert canary.TB4_EXECUTION_WALL_SECONDS <= canary.TB4_EXECUTE_PROCESS_TIMEOUT_SECONDS
    assert (
        canary.TB4_EXECUTE_PROCESS_TIMEOUT_SECONDS
        + 10
        + canary.CLEANUP_PROCESS_TIMEOUT_SECONDS
        + 10
        + canary.SANITIZE_PROCESS_TIMEOUT_SECONDS
        + 10
        <= canary.TB4_SUPERVISOR_WALL_SECONDS
    )
    assert canary.TB4_SUPERVISOR_WALL_SECONDS + 10 <= canary.TB4_ORCHESTRATOR_WALL_SECONDS
    assert "return float(await taskset.solved(task, trace, runtime))" in runner
    assert 'choices=("mobius", "tb4")' in runner
    assert "KIMI_SMALL_CANARY_TASK_PROFILE=tb4" in wrapper.read_text()
    assert "#SBATCH --time=02:00:00" in wrapper.read_text()
    assert '"kimi-tb4-long" if args.task_profile == "tb4" else "standard"' in runner
    assert 'runtime.interception_endpoint(relay.port, "sandoq-local-relay")' in runner
    assert '"MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT": "10" if tb4 else "1"' in runner
    assert '"SANDOQ_BUFFERED_STATS_DIR": str(buffered_stats_dir)' in runner
    assert 'task_profile=${KIMI_SMALL_CANARY_TASK_PROFILE:-mobius}' in generic_launcher.read_text()
    assert stat.S_IMODE(wrapper.stat().st_mode) & 0o111
