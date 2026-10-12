from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from aiohttp import web
from sandoq_provider.buffered_chat import BufferedChatCompletionsProxy

TOOLBOX_IMAGE = "localhost/prime-agent-toolbox:probe"
BASE_IMAGE = "localhost/dabstep:latest"


def _podman_command(temp: str, *, env: list[str], argv: list[str]) -> list[str]:
    command = [
        "podman",
        "run",
        "--rm",
        "--network",
        "host",
        "--volume",
        f"{temp}/workspace:/workspace",
        "--volume",
        f"{temp}/state:/state",
        "--mount",
        f"type=image,source={TOOLBOX_IMAGE},target=/toolbox",
    ]
    for value in env:
        command.extend(("--env", value))
    return [*command, BASE_IMAGE, *argv]


async def _exercise_toolbox(command_factory) -> tuple[subprocess.CompletedProcess[str], BufferedChatCompletionsProxy]:
    requests: list[dict] = []

    async def completion(request: web.Request) -> web.Response:
        body = await request.json()
        requests.append(body)
        return web.json_response(
            {
                "id": "completion-agent",
                "object": "chat.completion",
                "created": 1,
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "The requested smoke test is complete.",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 8,
                    "total_tokens": 18,
                },
            }
        )

    upstream = web.Application(client_max_size=1024**3)
    upstream.router.add_post("/v1/chat/completions", completion)
    runner = web.AppRunner(upstream)
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
        with tempfile.TemporaryDirectory(prefix="toolbox-protocol-") as temp:
            workspace = Path(temp) / "workspace"
            state = Path(temp) / "state"
            workspace.mkdir()
            state.mkdir()
            command = command_factory(temp, proxy.port)
            result = await asyncio.to_thread(
                subprocess.run,
                command,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        assert result.returncode == 0, result.stderr[-4000:] + "\n" + repr(proxy.stats.snapshot())
        assert requests
        return result, proxy
    finally:
        await proxy.close()
        await runner.cleanup()


@pytest.mark.skipif(
    os.environ.get("RUN_TOOLBOX_PROTOCOL_TEST") != "1" or shutil.which("podman") is None,
    reason="requires the locally built agent toolbox images",
)
def test_muse_openrouter_chat_protocol_round_trip() -> None:
    async def scenario() -> None:
        def command(temp: str, port: int) -> list[str]:
            (Path(temp) / "state" / "prompt.txt").write_text("finish without using tools")
            return _podman_command(
                temp,
                env=[
                    "HOME=/state",
                    "TMPDIR=/state",
                    "NO_COLOR=1",
                    "OPENROUTER_API_KEY=rollout-secret",
                ],
                argv=[
                    "/toolbox/opt/prime-agents/muse/muse",
                    "exec",
                    "--json",
                    "--provider",
                    "openrouter",
                    "--model",
                    "policy",
                    "--base-url",
                    f"http://127.0.0.1:{port}/v1",
                    "--workspace",
                    "/workspace",
                    "--reasoning-effort",
                    "high",
                    "--max-model-steps",
                    "1",
                    "--preset",
                    "native-basic",
                    "--yolo",
                    "--disable-web-tools",
                    "--no-foreign-personal-context",
                    "--no-session-log",
                    "--prompt-file",
                    "/state/prompt.txt",
                ],
            )

        _, proxy = await _exercise_toolbox(command)
        # Muse runs auxiliary reminder decisions through the model as well, so
        # assert the protocol rather than assuming exactly one model request.
        assert proxy.stats.protocols.get("chat_completions", 0) >= 1
        assert proxy.stats.paths.get("/v1/chat/completions", 0) >= 1

    asyncio.run(scenario())


@pytest.mark.skipif(
    os.environ.get("RUN_TOOLBOX_PROTOCOL_TEST") != "1" or shutil.which("podman") is None,
    reason="requires the locally built agent toolbox images",
)
@pytest.mark.parametrize("agent_name", ["opencode", "pi"])
def test_chat_harness_protocol_round_trip(agent_name: str) -> None:
    async def scenario() -> None:
        def command(temp: str, port: int) -> list[str]:
            if agent_name == "opencode":
                config = {
                    "tools": {"webfetch": False, "websearch": False},
                    "provider": {
                        "prime": {
                            "npm": "@ai-sdk/openai-compatible",
                            "name": "Prime-RL",
                            "options": {
                                "baseURL": f"http://127.0.0.1:{port}/v1",
                                "apiKey": "rollout-secret",
                            },
                            "models": {
                                "policy": {
                                    "name": "policy",
                                    "limit": {"context": 65536, "output": 32768},
                                }
                            },
                        }
                    },
                }
                return _podman_command(
                    temp,
                    env=[
                        "HOME=/state",
                        "XDG_CONFIG_HOME=/state/config",
                        "XDG_DATA_HOME=/state/data",
                        "XDG_CACHE_HOME=/state/cache",
                        "XDG_STATE_HOME=/state/state",
                        "OPENCODE_DISABLE_AUTOUPDATE=1",
                        f"OPENCODE_CONFIG_CONTENT={json.dumps(config, separators=(',', ':'))}",
                    ],
                    argv=[
                        "/toolbox/opt/prime-agents/opencode/opencode",
                        "run",
                        "--format",
                        "json",
                        "--model",
                        "prime/policy",
                        "--variant",
                        "high",
                        "--auto",
                        "--pure",
                        "--dir",
                        "/workspace",
                        "finish without using tools",
                    ],
                )

            models = {
                "providers": {
                    "prime": {
                        "baseUrl": f"http://127.0.0.1:{port}/v1",
                        "api": "openai-completions",
                        "apiKey": "$PI_INTERCEPT_KEY",
                        "models": [
                            {
                                "id": "policy",
                                "name": "policy",
                                "reasoning": True,
                                "input": ["text"],
                                "contextWindow": 65536,
                                "maxTokens": 32768,
                            }
                        ],
                    }
                }
            }
            models_path = Path(temp) / "state" / "pi" / "models.json"
            models_path.parent.mkdir()
            models_path.write_text(json.dumps(models))
            return _podman_command(
                temp,
                env=[
                    "HOME=/state",
                    "PI_CODING_AGENT_DIR=/state/pi",
                    "PI_TELEMETRY=0",
                    "PI_INTERCEPT_KEY=rollout-secret",
                ],
                argv=[
                    "/toolbox/opt/prime-agents/pi/pi",
                    "--provider",
                    "prime",
                    "--model",
                    "policy",
                    "--mode",
                    "json",
                    "--print",
                    "--no-session",
                    "--no-extensions",
                    "--no-skills",
                    "--no-prompt-templates",
                    "--no-context-files",
                    "--approve",
                    "--thinking",
                    "high",
                    "--tools",
                    "read,bash,edit,write,grep,find,ls",
                    "finish without using tools",
                ],
            )

        _, proxy = await _exercise_toolbox(command)
        assert proxy.stats.protocols.get("chat_completions", 0) >= 1

    asyncio.run(scenario())
