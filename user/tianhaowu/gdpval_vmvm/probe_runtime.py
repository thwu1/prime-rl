from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import logging
import os
from pathlib import Path

import httpx
from agent import build_finish_tool
from asset_fetch import asset_cache_status, load_asset_manifest, prepare_asset_cache, select_manifest_entries
from common import (
    atomic_write_json,
    judge_deployment_identity,
    load_config,
    load_info_endpoint,
    load_jsonl,
    load_policy_endpoint,
    policy_deployment_identity,
)
from openai import OpenAI
from PIL import Image
from pydantic import ValidationError
from run_eval import (
    PREFLIGHT_SCHEMA_VERSION,
    WEB_FETCH_INVALID_URL,
    WEB_FETCH_PROBE_URL,
    _expected_code_execution_tool_names,
    _expected_finish_contract,
    _expected_tool_capabilities,
    _expected_workspace_contract,
    _fingerprint,
    _probe,
    _sft_compatibility_aliases,
    _validate_config,
)
from vmvm_provider import VMVMCodeExecToolProvider
from worker import GDPValWebToolProvider, _reference_input_specs

WEB_FETCH_PROBE_MARKER = "This domain is for use in documentation examples"
PROXY_ENVIRONMENT_VARIABLES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def _probe_chat(
    endpoint,
    *,
    thinking_key: str,
    thinking: bool,
    completion_parameter: str,
) -> dict:
    client = OpenAI(
        base_url=endpoint.base_url.rstrip("/") + "/v1/",
        api_key=endpoint.api_key,
        timeout=120,
        max_retries=0,
        http_client=httpx.Client(trust_env=False),
    )
    request = {
        "model": endpoint.model,
        "messages": [{"role": "user", "content": "Reply with exactly OK."}],
        "temperature": 0.0,
        completion_parameter: 256,
        "extra_body": {"chat_template_kwargs": {thinking_key: thinking}},
    }
    response = client.chat.completions.create(
        **request,
    )
    if not response.choices:
        raise RuntimeError(f"{endpoint.model} returned no choices")
    message = response.choices[0].message
    normalized = (message.content or "").strip().upper().strip(".!")
    if normalized != "OK":
        raise RuntimeError(f"{endpoint.model} failed the semantic text probe: {message.content!r}")
    return {
        "finish_reason": response.choices[0].finish_reason,
        "content_chars": len(message.content or ""),
        "matched_expected_answer": True,
        "reasoning_chars": len(
            str(getattr(message, "reasoning_content", None) or getattr(message, "reasoning", None) or "")
        ),
    }


def _probe_visual(endpoint, *, thinking: bool) -> dict:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), (0, 80, 255)).save(buffer, format="PNG")
    image_url = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
    client = OpenAI(
        base_url=endpoint.base_url.rstrip("/") + "/v1/",
        api_key=endpoint.api_key,
        timeout=120,
        max_retries=0,
        http_client=httpx.Client(trust_env=False),
    )
    response = client.chat.completions.create(
        model=endpoint.model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Name the dominant color in this image in one word."},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        ],
        temperature=0.0,
        max_tokens=256,
        extra_body={"chat_template_kwargs": {"thinking": thinking}},
    )
    if not response.choices:
        raise RuntimeError(f"{endpoint.model} returned no visual-probe choices")
    message = response.choices[0].message
    if "blue" not in (message.content or "").lower():
        raise RuntimeError(f"{endpoint.model} failed the semantic visual probe: {message.content!r}")
    return {
        "content_chars": len(message.content or ""),
        "finish_reason": response.choices[0].finish_reason,
        "matched_expected_answer": True,
    }


def _probe_tool_call(endpoint, *, thinking: bool) -> dict:
    client = OpenAI(
        base_url=endpoint.base_url.rstrip("/") + "/v1/",
        api_key=endpoint.api_key,
        timeout=120,
        max_retries=0,
        http_client=httpx.Client(trust_env=False),
    )
    response = client.chat.completions.create(
        model=endpoint.model,
        messages=[{"role": "user", "content": "Call the echo tool with value ping."}],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "echo",
                    "description": "Echo one value.",
                    "parameters": {
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                        "required": ["value"],
                        "additionalProperties": False,
                    },
                },
            }
        ],
        tool_choice={"type": "function", "function": {"name": "echo"}},
        temperature=0.0,
        max_completion_tokens=256,
        extra_body={"chat_template_kwargs": {"enable_thinking": thinking}},
    )
    if not response.choices:
        raise RuntimeError(f"{endpoint.model} returned no tool-probe choices")
    calls = response.choices[0].message.tool_calls or []
    if len(calls) != 1 or calls[0].function.name != "echo":
        raise RuntimeError(f"{endpoint.model} failed the tool-call probe: {calls!r}")
    arguments = json.loads(calls[0].function.arguments)
    if arguments.get("value") != "ping":
        raise RuntimeError(f"{endpoint.model} returned incorrect tool arguments: {arguments!r}")
    return {"tool": "echo", "arguments_valid": True}


def _probe_brave(api_key: str, *, trust_env: bool) -> dict:
    with httpx.Client(timeout=60, trust_env=trust_env) as client:
        response = client.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
            params={"q": "GDPval benchmark", "count": 1},
        )
    response.raise_for_status()
    results = response.json().get("web", {}).get("results", [])
    if not results or not results[0].get("url"):
        raise RuntimeError("Brave Search semantic probe returned no web result")
    return {"matched_expected_shape": True, "pages_returned": len(results)}


async def _probe_web_fetch(config: dict) -> dict:
    trust_env = config["tools"]["web_fetch_trust_env"]
    web_search_enabled = bool(config["tools"]["require_brave_search"])
    provider = GDPValWebToolProvider(
        brave_api_key=os.getenv("BRAVE_API_KEY") if web_search_enabled else None,
        trust_env=trust_env,
        timeout=30,
    )
    async with provider as tools:
        tool_names = sorted(tool.name for tool in tools)
        expected_tool_names = ["fetch_web_page", "web_search"] if web_search_enabled else ["fetch_web_page"]
        if tool_names != expected_tool_names:
            raise RuntimeError(f"Stirrup web tool set mismatch: {tool_names!r} != {expected_tool_names!r}")
        fetch_tool = next((tool for tool in tools if tool.name == "fetch_web_page"), None)
        if fetch_tool is None:
            raise RuntimeError("Stirrup WebToolProvider did not expose fetch_web_page")
        result = await fetch_tool.executor(fetch_tool.parameters(url=WEB_FETCH_PROBE_URL))
        invalid_result = await fetch_tool.executor(fetch_tool.parameters(url=WEB_FETCH_INVALID_URL))
    if result.success is not True or not isinstance(result.content, str):
        raise RuntimeError(f"Stirrup web fetch probe failed: {result.content!r}")
    if WEB_FETCH_PROBE_MARKER not in result.content:
        raise RuntimeError("Stirrup web fetch probe returned unexpected content")
    pages_fetched = list(getattr(result.metadata, "pages_fetched", []))
    if pages_fetched != [WEB_FETCH_PROBE_URL]:
        raise RuntimeError(f"Stirrup web fetch probe returned unexpected metadata: {pages_fetched!r}")
    invalid_pages_fetched = list(getattr(invalid_result.metadata, "pages_fetched", []))
    if invalid_result.success is not False or invalid_pages_fetched != [WEB_FETCH_INVALID_URL]:
        raise RuntimeError("Stirrup malformed-URL probe was not converted to a failed tool result")
    return {
        "tool": "fetch_web_page",
        "tool_names": tool_names,
        "url": WEB_FETCH_PROBE_URL,
        "trust_env": trust_env,
        "success": True,
        "matched_expected_content": True,
        "pages_fetched": pages_fetched,
        "invalid_url": WEB_FETCH_INVALID_URL,
        "invalid_url_handled": True,
        "invalid_url_pages_fetched": invalid_pages_fetched,
        "proxy_environment_variables_present": sorted(name for name in PROXY_ENVIRONMENT_VARIABLES if os.getenv(name)),
    }


async def _probe_vmvm(config: dict, task_id: str | None = None) -> dict:
    runtime = config["runtime"]
    sft_compatibility_aliases = _sft_compatibility_aliases(config)
    catalog = load_jsonl(Path(config["source"]["catalog_file"]).expanduser().resolve())
    if not catalog:
        raise ValueError("GDPval catalog is empty")
    task = next((row for row in catalog if str(row["task_id"]) == task_id), None) if task_id else catalog[0]
    if task is None:
        raise ValueError(f"Unknown GDPval preflight task ID: {task_id}")
    bootstrap_assets = _reference_input_specs(task, config)
    if not bootstrap_assets:
        raise ValueError(f"GDPval preflight task has no reference assets: {task['task_id']}")
    manifest = load_asset_manifest(config)
    selected_entries = select_manifest_entries(
        manifest,
        [(str(task["task_id"]), str(path)) for path in task.get("reference_files") or []],
    )
    cache = asset_cache_status(config, selected_entries, verify_hashes=True)
    if not cache["ready"]:
        cache = prepare_asset_cache(config, selected_entries, workers=2)
    provider = VMVMCodeExecToolProvider(
        image=runtime["image"],
        fallback_image=runtime.get("fallback_image") or None,
        tenant_id=runtime["tenant_id"],
        lease_ttl=runtime["lease_ttl"],
        cpu=float(runtime["cpu"]),
        memory_gb=float(runtime["memory_gb"]),
        command_timeout_seconds=int(runtime["command_timeout_seconds"]),
        max_connection_drops=int(runtime["max_connection_drops"]),
        bootstrap_assets=bootstrap_assets,
        asset_cache_dir=config["source"]["asset_cache_dir"],
        preload_image=bool(runtime.get("preload_image", True)),
        sft_compatibility_aliases=sft_compatibility_aliases,
    )
    async with provider as code_execution_tools:
        tools = code_execution_tools if isinstance(code_execution_tools, list) else [code_execution_tools]
        tool_names = [tool.name for tool in tools]
        expected_tool_names = _expected_code_execution_tool_names(config)
        if tool_names != expected_tool_names:
            raise RuntimeError(f"Stirrup code-execution tool set mismatch: {tool_names!r} != {expected_tool_names!r}")
        if sft_compatibility_aliases:
            tool_probe_command = (
                'test "$PWD" = /home/user && test "$HOME" = /home/user && '
                'test /home/user -ef /workspace && test "$(readlink -f /home/user)" = /workspace && '
                "rm -f /home/user/.gdpval-sft-alias-probe && "
                "trap 'rm -f /home/user/.gdpval-sft-alias-probe' EXIT && "
                "printf sft-compatibility > /home/user/.gdpval-sft-alias-probe && "
                'test "$(cat /workspace/.gdpval-sft-alias-probe)" = sft-compatibility && '
                "printf SFT_COMPATIBILITY_OK"
            )
        else:
            tool_probe_command = 'test "$PWD" = /workspace && printf RUN_SHELL_OK'
        expected_marker = "SFT_COMPATIBILITY_OK" if sft_compatibility_aliases else "RUN_SHELL_OK"
        for tool in tools:
            tool_result = await tool.executor(tool.parameters(cmd=tool_probe_command))
            if tool_result.success is not True or expected_marker not in str(tool_result.content):
                raise RuntimeError(f"Stirrup code-execution tool {tool.name!r} failed its workspace probe")

        finish_tool = build_finish_tool(sft_compatibility_aliases=sft_compatibility_aliases)
        finish_schema = finish_tool.parameters.model_json_schema()
        schema_fields = list(finish_schema.get("properties", {}))
        finish_tool.parameters.model_validate({"reason": "done", "paths": []})
        summary_alias_accepted = True
        try:
            finish_tool.parameters.model_validate({"summary": "done", "paths": []})
        except ValidationError:
            summary_alias_accepted = False
        if summary_alias_accepted is not sft_compatibility_aliases:
            raise RuntimeError("Stirrup finish.summary compatibility does not match the configured mode")
        conflicting_aliases_rejected = False
        if sft_compatibility_aliases:
            try:
                finish_tool.parameters.model_validate({"reason": "a", "summary": "b", "paths": []})
            except ValidationError:
                conflicting_aliases_rejected = True
            if not conflicting_aliases_rejected:
                raise RuntimeError("Stirrup finish tool accepted conflicting reason and summary values")
        finish_contract = {
            "tool_name": finish_tool.name,
            "canonical_field": "reason",
            "schema_fields": schema_fields,
            "summary_alias_enabled": sft_compatibility_aliases,
            "summary_alias_accepted": summary_alias_accepted,
            "conflicting_aliases_rejected": conflicting_aliases_rejected,
        }
        if finish_contract != _expected_finish_contract(config):
            raise RuntimeError("Stirrup finish-tool contract does not match the configured mode")

        result = await provider.run_command(
            "for command in bash python git gcc g++ cmake swig pkg-config make libreoffice tesseract pandoc "
            "pdftotext gs ffmpeg dot convert pdflatex xelatex lualatex latexmk biber java gdalinfo jq unzip "
            'unar curl wget; do command -v "$command" >/dev/null || { echo "missing command: $command"; exit 1; }; '
            "done && (command -v chromium >/dev/null || command -v chromium-browser >/dev/null) && "
            'for style in tikz.sty siunitx.sty pst-plot.sty; do kpsewhich "$style" >/dev/null || '
            '{ echo "missing TeX style: $style"; exit 1; }; done && '
            "python --version && libreoffice --version && "
            "python - <<'PY'\n"
            "import importlib.util\n"
            "modules = ['numpy', 'pandas', 'polars', 'scipy', 'matplotlib', 'plotly', 'sklearn', "
            "'docx', 'pptx', 'openpyxl', 'fitz', 'pdfplumber', 'reportlab', 'weasyprint', 'PIL', 'cv2', "
            "'playwright']\n"
            "missing = [name for name in modules if importlib.util.find_spec(name) is None]\n"
            "print({'missing_modules': missing})\n"
            "raise SystemExit(bool(missing))\n"
            "PY",
            timeout=300,
        )
        if result.exit_code != 0:
            raise RuntimeError(f"GDPval image probe failed: {result.stdout}\n{result.stderr}")
        await provider.render_office("/workspace/reference_files")
        rendered_files = await provider.list_files("/workspace/reference_files")
        if not any(path.endswith(".pdf") for path in rendered_files):
            raise RuntimeError("GDPval Office render probe produced no PDF")
        return {
            "asset_mirror": cache,
            "output": result.stdout,
            "staged_assets": provider.staged_assets,
            "render_history": provider.render_history,
            "rendered_files": rendered_files,
            "tool_capabilities": _expected_tool_capabilities(config),
            "code_execution_tool_names": tool_names,
            "workspace_contract": _expected_workspace_contract(config),
            "finish_contract": finish_contract,
            "vmvm": provider.debugging_info,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("--policy-base-url")
    parser.add_argument("--policy-job-id")
    parser.add_argument("--judge-base-url")
    parser.add_argument("--endpoints-only", action="store_true")
    parser.add_argument("--judge-only", action="store_true")
    parser.add_argument("--asset-task-id")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_config(args.config.resolve())
    _validate_config(config)
    policy_deployment = policy_deployment_identity(config["policy"])
    judge_deployment = judge_deployment_identity(config["judge"])
    judge = load_info_endpoint(config["judge"], args.judge_base_url)
    if judge.deployment != judge_deployment:
        raise ValueError("Resolved judge deployment differs from the configured deployment")
    payload = {
        "schema_version": PREFLIGHT_SCHEMA_VERSION,
        "ok": True,
        "config_fingerprint": _fingerprint(config),
        "policy_deployment_id": policy_deployment["deployment_id"],
        "policy_slurm_job_id": policy_deployment["slurm_job_id"],
        "judge_deployment_id": judge_deployment["deployment_id"],
        "judge_proxy_jobid": judge_deployment["proxy_jobid"],
        "sandbox_image": config["runtime"]["image"],
        "judge": _probe(judge)
        | {
            "chat": _probe_chat(
                judge,
                thinking_key="thinking",
                thinking=bool(config["judge"]["thinking"]),
                completion_parameter="max_tokens",
            ),
            "visual_chat": _probe_visual(judge, thinking=bool(config["judge"]["thinking"])),
        },
    }
    if args.judge_only:
        payload["probe_scope"] = "judge_only"
    else:
        policy = load_policy_endpoint(config["policy"], args.policy_base_url, args.policy_job_id)
        if policy.deployment != policy_deployment:
            raise ValueError("Resolved policy deployment differs from the configured deployment")
        payload["policy"] = _probe(policy, str(config["policy"]["server_version"])) | {
            "chat": _probe_chat(
                policy,
                thinking_key="enable_thinking",
                thinking=bool(config["policy"]["thinking"]),
                completion_parameter="max_completion_tokens",
            ),
            "tool_call": _probe_tool_call(policy, thinking=bool(config["policy"]["thinking"])),
        }
    if not args.endpoints_only and not args.judge_only:
        payload["web_fetch"] = asyncio.run(_probe_web_fetch(config))
        if config.get("tools", {}).get("require_brave_search"):
            brave_api_key = os.getenv("BRAVE_API_KEY")
            if not brave_api_key:
                raise ValueError("BRAVE_API_KEY is required for the full runtime preflight")
            payload["web_search"] = _probe_brave(
                brave_api_key,
                trust_env=config["tools"]["web_fetch_trust_env"],
            )
        payload["sandbox"] = asyncio.run(_probe_vmvm(config, args.asset_task_id))
    if args.output:
        atomic_write_json(args.output.resolve(), payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
