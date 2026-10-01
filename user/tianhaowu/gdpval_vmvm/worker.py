from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any

import httpx
from agent import ABANDON_FINISH_TOOL, GDPValAgent, build_finish_tool
from asset_fetch import asset_specs as mirror_asset_specs
from common import Endpoint, atomic_write_json, load_config, load_info_endpoint, load_jsonl, load_policy_endpoint
from judge import JudgeFatalError, JudgeRetryableError, score_comparison, score_rubric
from policy_client import GDPValPolicyClient, ModelFatalError, ModelRequestError
from stirrup.core.exceptions import ContextOverflowError
from stirrup.core.models import ToolResult
from stirrup.tools.web import MAX_LENGTH_WEB_FETCH_HTML, WebFetchMetadata, WebToolProvider
from stirrup.utils.text import truncate_msg
from vmvm_provider import VMVMCodeExecToolProvider, VMVMFatalError, VMVMInfrastructureLost

HERE = Path(__file__).resolve().parent


class CandidateSubmissionError(RuntimeError):
    pass


class WebFetchInputError(ValueError):
    pass


class GDPValWebToolProvider(WebToolProvider):
    def __init__(
        self,
        *,
        brave_api_key: str | None,
        trust_env: bool,
        timeout: float = 180,
    ) -> None:
        if not isinstance(trust_env, bool):
            raise TypeError("tools.web_fetch_trust_env must be a boolean")
        super().__init__(timeout=timeout, brave_api_key=brave_api_key)
        self._brave_api_key = brave_api_key
        self.trust_env = trust_env

    async def __aenter__(self) -> list[Any]:
        self._client = httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=True,
            trust_env=self.trust_env,
        )
        await self._client.__aenter__()
        return self.get_tools()

    def get_tools(self) -> list[Any]:
        tools = super().get_tools()
        guarded_tools: list[Any] = []
        for tool in tools:
            if tool.name != "fetch_web_page":
                guarded_tools.append(tool)
                continue
            executor = tool.executor

            async def guarded_fetch(params: Any, *, _executor: Any = executor) -> Any:
                try:
                    parsed = httpx.URL(params.url)
                    if parsed.port is not None and not 0 <= parsed.port <= 65_535:
                        raise WebFetchInputError("Destination port must be between 0 and 65535.")
                    return await _executor(params)
                except (httpx.InvalidURL, WebFetchInputError) as error:
                    return ToolResult(
                        content=(
                            f"<web_fetch><url>{params.url}</url><error>"
                            f"{truncate_msg(str(error), MAX_LENGTH_WEB_FETCH_HTML)}</error></web_fetch>"
                        ),
                        success=False,
                        metadata=WebFetchMetadata(pages_fetched=[params.url]),
                    )

            guarded_tools.append(tool.model_copy(update={"executor": guarded_fetch}))
        return guarded_tools


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, str):
        parsed = json.loads(value)
        return list(parsed) if isinstance(parsed, list) else []
    return list(value)


def _safe_relative(path: str) -> Path:
    pure = PurePosixPath(path.lstrip("/"))
    if not pure.parts or ".." in pure.parts:
        raise ValueError(f"Unsafe reference path: {path!r}")
    return Path(*pure.parts)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest(root: Path, *, exclude: set[str] | None = None) -> list[dict[str, Any]]:
    ignored = exclude or set()
    return [
        {
            "path": path.relative_to(root).as_posix(),
            "size": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in sorted(root.rglob("*"))
        if path.is_file() and not (len(path.relative_to(root).parts) == 1 and path.name in ignored)
    ]


def _verify_candidate(candidate_dir: Path) -> dict[str, Any] | None:
    marker = candidate_dir / "candidate.json"
    if not candidate_dir.exists() and not candidate_dir.is_symlink():
        return None
    for path in (candidate_dir.parent.parent, candidate_dir.parent, candidate_dir):
        if path.is_symlink():
            raise ValueError(f"Candidate path contains a symlink: {path}")
    if not candidate_dir.is_dir() or candidate_dir.is_symlink():
        raise ValueError(f"Candidate directory is invalid or unsafe: {candidate_dir}")
    if not marker.is_file() or marker.is_symlink():
        raise ValueError(f"Candidate manifest is missing or unsafe: {marker}")
    for path in candidate_dir.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Candidate contains a symlink: {path}")
    payload = json.loads(marker.read_text(encoding="utf-8"))
    expected = payload.get("files")
    actual = _manifest(candidate_dir, exclude={"candidate.json"})
    if expected != actual:
        raise ValueError(f"Candidate artifact manifest mismatch: {candidate_dir}")
    actual_digest = hashlib.sha256(json.dumps(actual, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if payload.get("candidate_sha256") != actual_digest:
        raise ValueError(f"Candidate aggregate digest mismatch: {candidate_dir}")
    return payload


def _asset_specs(
    task: dict[str, Any],
    config: dict[str, Any],
    *,
    label: str,
    names_key: str,
) -> list[dict[str, Any]]:
    names = [str(value) for value in _as_list(task.get(names_key))]
    specs = mirror_asset_specs(task, config, catalog_key=names_key)
    expected_paths = [_safe_relative(name).as_posix() for name in names]
    if [str(item["path"]) for item in specs] != expected_paths:
        raise ValueError(f"Task {task['task_id']} has inconsistent {label} mirror assets")
    return specs


def _reference_input_specs(task: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    return _asset_specs(
        task,
        config,
        label="reference input",
        names_key="reference_files",
    )


def _expert_deliverable_specs(task: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    specs = _asset_specs(
        task,
        config,
        label="expert deliverable",
        names_key="deliverable_files",
    )
    if not specs:
        raise ValueError(f"Task {task['task_id']} has no public expert deliverable")
    return specs


def _build_prompt(task: dict[str, Any]) -> str:
    paths = [f"- /workspace/{_safe_relative(path).as_posix()}" for path in _as_list(task.get("reference_files"))]
    task_text = f"Sector: {task.get('sector', '')}\nOccupation: {task.get('occupation', '')}\n\n{task['prompt']}"
    return (
        (HERE / "gdpval_user_prompt.txt")
        .read_text(encoding="utf-8")
        .format(
            task=task_text,
            reference_files="\n".join(paths) if paths else "None",
        )
    )


def _history_json(history: Any) -> list[Any]:
    output: list[Any] = []
    for group in history:
        output.append([item.model_dump() if hasattr(item, "model_dump") else item for item in group])
    return output


def _sft_compatibility_aliases(config: dict[str, Any]) -> bool:
    enabled = config.get("tools", {}).get("sft_compatibility_aliases", False)
    if not isinstance(enabled, bool):
        raise TypeError("tools.sft_compatibility_aliases must be a boolean")
    return enabled


def _tool_capabilities(config: dict[str, Any]) -> dict[str, Any]:
    sft_compatibility_aliases = _sft_compatibility_aliases(config)
    return {
        "run_shell": True,
        "code_exec": sft_compatibility_aliases,
        "web_fetch": True,
        "web_fetch_trust_env": config["tools"]["web_fetch_trust_env"],
        "web_search": bool(config["tools"]["require_brave_search"]),
        "finish": True,
        "finish_reason": True,
        "finish_summary_alias": sft_compatibility_aliases,
        "abandon_task_finish": True,
        "workspace_root": "/workspace",
        "home_user_workspace_alias": sft_compatibility_aliases,
    }


def _workspace_relative(path: str, *, allow_home_user: bool = False) -> str:
    pure = PurePosixPath(path)
    if pure.is_absolute():
        if len(pure.parts) >= 2 and pure.parts[1] in {"workspace", "working_dir"}:
            pure = PurePosixPath(*pure.parts[2:])
        elif allow_home_user and len(pure.parts) >= 3 and pure.parts[1:3] == ("home", "user"):
            pure = PurePosixPath(*pure.parts[3:])
        else:
            raise CandidateSubmissionError(f"Submitted path is outside /workspace: {path!r}")
    if not pure.parts or ".." in pure.parts:
        raise CandidateSubmissionError(f"Invalid submitted path: {path!r}")
    return pure.as_posix()


def _canonical_submission_paths(paths: list[str], *, allow_home_user: bool = False) -> list[str]:
    return list(dict.fromkeys(_workspace_relative(path, allow_home_user=allow_home_user) for path in paths))


async def _save_remote_tree(provider: VMVMCodeExecToolProvider, remote_root: str, local_root: Path) -> None:
    files = await provider.list_files(remote_root)
    local_root.mkdir(parents=True, exist_ok=True)
    for relative in files:
        if Path(relative).name.startswith(".gdpval-"):
            continue
        destination = local_root / _safe_relative(relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(await provider.read_file_bytes(f"{remote_root.rstrip('/')}/{relative}"))


async def _save_submitted_artifacts(
    provider: VMVMCodeExecToolProvider,
    submitted_paths: list[str],
    local_root: Path,
    *,
    allow_home_user: bool = False,
) -> list[dict[str, Any]]:
    saved: list[dict[str, Any]] = []
    destinations: set[str] = set()
    local_root.mkdir(parents=True, exist_ok=True)

    async def save_file(remote_path: str, relative: str) -> None:
        if relative in destinations:
            raise CandidateSubmissionError(f"Duplicate submitted output path: {relative}")
        destinations.add(relative)
        destination = local_root / _safe_relative(relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        content = await provider.read_file_bytes(remote_path)
        destination.write_bytes(content)
        saved.append({"path": relative, "size": len(content), "sha256": hashlib.sha256(content).hexdigest()})

    for submitted_path in submitted_paths:
        relative = _workspace_relative(submitted_path, allow_home_user=allow_home_user)
        remote_path = f"/workspace/{relative}"
        if await provider.is_directory(remote_path):
            members = await provider.list_files(remote_path)
            if not members:
                raise CandidateSubmissionError(f"Submitted directory is empty: {submitted_path}")
            for member in members:
                await save_file(f"{remote_path.rstrip('/')}/{member}", f"{relative.rstrip('/')}/{member}")
        elif await provider.file_exists(remote_path):
            await save_file(remote_path, relative)
        else:
            raise CandidateSubmissionError(f"Submitted artifact does not exist: {submitted_path}")
    return saved


def _render_bundle_valid(path: Path, identity: dict[str, Any]) -> bool:
    marker = path / ".render_manifest.json"
    if not marker.is_file():
        return False
    payload = json.loads(marker.read_text(encoding="utf-8"))
    return payload.get("identity") == identity and payload.get("files") == _manifest(
        path, exclude={".render_manifest.json"}
    )


def _finish_render_bundle(
    temporary: Path,
    destination: Path,
    identity: dict[str, Any],
    *,
    staged_assets: list[dict[str, Any]],
    render_environment: dict[str, Any],
) -> None:
    files = _manifest(temporary, exclude={".render_manifest.json"})
    if not files:
        raise ValueError(f"Rendered comparison reference is empty: {destination}")
    atomic_write_json(
        temporary / ".render_manifest.json",
        {
            "identity": identity,
            "staged_assets": staged_assets,
            "render_environment": render_environment,
            "files": files,
        },
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(temporary, destination)
    except FileExistsError:
        if not _render_bundle_valid(destination, identity):
            raise ValueError(f"Conflicting rendered reference bundle: {destination}")
        shutil.rmtree(temporary)


async def _stage_reference(
    provider: VMVMCodeExecToolProvider,
    instance: dict[str, Any],
    task: dict[str, Any],
    config: dict[str, Any],
    remote_root: str,
) -> list[dict[str, Any]]:
    if instance["source"] == "dataset_reference_inputs":
        staged = await provider.stage_assets(
            _reference_input_specs(task, config),
            destination=remote_root,
        )
        if staged != instance["expected_assets"]:
            raise VMVMFatalError(f"Pristine task-input manifest mismatch for {task['task_id']}")
        return staged
    if instance["source"] == "dataset_deliverables":
        return await provider.stage_assets(
            _expert_deliverable_specs(task, config),
            destination=remote_root,
        )
    upload = await provider.upload_files(instance["path"], dest_dir=remote_root.removeprefix("/workspace/"))
    if upload.failed:
        raise VMVMInfrastructureLost(f"Failed to upload comparison reference: {upload.failed}")
    return [
        {
            "path": saved.dest_path,
            "size": saved.size,
            "source_path": str(saved.source_path),
        }
        for saved in upload.uploaded
    ]


async def _render_references(
    provider: VMVMCodeExecToolProvider,
    instances: list[dict[str, Any]],
    task: dict[str, Any],
    config: dict[str, Any],
) -> None:
    pending = [
        instance for instance in instances if not _render_bundle_valid(instance["rendered_dir"], instance["identity"])
    ]
    if not pending:
        return

    temporary_dirs: list[tuple[dict[str, Any], Path, str, list[dict[str, Any]]]] = []
    try:
        for index, instance in enumerate(pending):
            remote_root = f"/workspace/judge_references/reference_{index}"
            staged = await _stage_reference(provider, instance, task, config, remote_root)
            instance["rendered_dir"].parent.mkdir(parents=True, exist_ok=True)
            temporary = Path(
                tempfile.mkdtemp(prefix=f".{instance['rendered_dir'].name}-", dir=instance["rendered_dir"].parent)
            )
            temporary_dirs.append((instance, temporary, remote_root, staged))
        await provider.render_office("/workspace/judge_references")
        render_environment = provider.render_history[-1]
        for instance, temporary, remote_root, staged in temporary_dirs:
            await _save_remote_tree(provider, remote_root, temporary)
            _finish_render_bundle(
                temporary,
                instance["rendered_dir"],
                instance["identity"],
                staged_assets=staged,
                render_environment=render_environment,
            )
    except Exception:
        for _, temporary, _, _ in temporary_dirs:
            shutil.rmtree(temporary, ignore_errors=True)
        raise


async def _render_references_only(
    *,
    task: dict[str, Any],
    config: dict[str, Any],
    instances: list[dict[str, Any]],
) -> None:
    if all(_render_bundle_valid(instance["rendered_dir"], instance["identity"]) for instance in instances):
        return
    runtime = config["runtime"]
    sft_compatibility_aliases = _sft_compatibility_aliases(config)
    provider = VMVMCodeExecToolProvider(
        image=runtime["image"],
        fallback_image=runtime.get("fallback_image") or None,
        tenant_id=runtime["tenant_id"],
        lease_ttl=runtime["lease_ttl"],
        cpu=float(runtime["cpu"]),
        memory_gb=float(runtime["memory_gb"]),
        command_timeout_seconds=int(runtime["command_timeout_seconds"]),
        max_connection_drops=int(runtime["max_connection_drops"]),
        asset_cache_dir=config["source"]["asset_cache_dir"],
        preload_image=bool(runtime.get("preload_image", True)),
        sft_compatibility_aliases=sft_compatibility_aliases,
    )
    async with provider:
        await _render_references(provider, instances, task, config)


async def _rollout(
    *,
    task: dict[str, Any],
    trial: int,
    config: dict[str, Any],
    fingerprint: str,
    endpoint_session_id: str,
    policy: Endpoint | None,
    candidate_dir: Path,
) -> dict[str, Any]:
    existing = _verify_candidate(candidate_dir)
    if existing is not None:
        if existing.get("task_id") != str(task["task_id"]) or int(existing.get("trial", -1)) != trial:
            raise ValueError(f"Existing candidate identity does not match task/trial: {candidate_dir}")
        if existing.get("config_fingerprint") != fingerprint:
            raise ValueError(f"Existing candidate has a different config fingerprint: {candidate_dir}")
        return existing

    if policy is None:
        raise ValueError("A policy endpoint is required when no persisted candidate exists")

    input_assets = _reference_input_specs(task, config)
    candidate_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{candidate_dir.name}-", dir=candidate_dir.parent))
    submission_dir = temporary / "submission"
    submission_dir.mkdir()
    runtime = config["runtime"]
    sft_compatibility_aliases = _sft_compatibility_aliases(config)
    provider = VMVMCodeExecToolProvider(
        image=runtime["image"],
        fallback_image=runtime.get("fallback_image") or None,
        tenant_id=runtime["tenant_id"],
        lease_ttl=runtime["lease_ttl"],
        cpu=float(runtime["cpu"]),
        memory_gb=float(runtime["memory_gb"]),
        command_timeout_seconds=int(runtime["command_timeout_seconds"]),
        max_connection_drops=int(runtime["max_connection_drops"]),
        bootstrap_assets=input_assets,
        asset_cache_dir=config["source"]["asset_cache_dir"],
        preload_image=bool(runtime.get("preload_image", True)),
        sft_compatibility_aliases=sft_compatibility_aliases,
    )
    policy_config = config["policy"]
    web_search_enabled = bool(config.get("tools", {}).get("require_brave_search"))
    brave_api_key = os.getenv("BRAVE_API_KEY") if web_search_enabled else None
    if web_search_enabled and not brave_api_key:
        raise ValueError("tools.require_brave_search=true but BRAVE_API_KEY is unset")
    web_provider = GDPValWebToolProvider(
        brave_api_key=brave_api_key,
        trust_env=config["tools"]["web_fetch_trust_env"],
    )
    session_id = f"gdpval-{task['task_id']}-{trial}"
    headers = {str(policy_config["sticky_session_header"]): session_id} if policy_config.get("sticky_session") else {}
    client = GDPValPolicyClient(
        model=policy.model,
        base_url=policy.base_url,
        api_key=policy.api_key,
        context_window=int(policy_config["context_window"]),
        max_completion_tokens=int(policy_config["max_completion_tokens"]),
        completion_token_buffer=int(policy_config["completion_token_buffer"]),
        temperature=float(policy_config["temperature"]),
        top_p=float(policy_config["top_p"]),
        thinking=bool(policy_config["thinking"]),
        request_retries=int(policy_config["request_retries"]),
        request_retry_delay_seconds=float(policy_config["request_retry_delay_seconds"]),
        request_timeout_seconds=float(policy_config["request_timeout_seconds"]),
        extra_headers=headers,
    )
    agent = GDPValAgent(
        client=client,
        name="gdpval_stirrup_agent",
        max_turns=int(config["benchmark"]["max_turns"]),
        tools=[provider, web_provider],
        finish_tool=[
            build_finish_tool(sft_compatibility_aliases=sft_compatibility_aliases),
            ABANDON_FINISH_TOOL,
        ],
    )
    started = time.time()
    try:
        async with agent.session(output_dir=submission_dir) as session:
            finish_params, history, metadata = await asyncio.wait_for(
                session.run(_build_prompt(task)),
                timeout=float(config["benchmark"]["task_timeout_seconds"]),
            )
            finish_payload = finish_params.model_dump() if hasattr(finish_params, "model_dump") else finish_params
            submitted_paths = list(getattr(finish_params, "paths", []) or [])
            submitted_relative_paths = _canonical_submission_paths(
                submitted_paths,
                allow_home_user=sft_compatibility_aliases,
            )
            try:
                rendered_paths = await provider.render_office(
                    "/workspace",
                    paths=submitted_relative_paths,
                )
            except VMVMFatalError as error:
                if "GDPval Office rendering failed:" not in str(error):
                    raise
                raise CandidateSubmissionError(str(error)) from error
            rendered_set = set(rendered_paths)
            helper_paths: list[str] = []
            helper_relative_paths: list[str] = []
            for relative in submitted_relative_paths:
                if Path(relative).suffix.lower() not in {".docx", ".pptx", ".xlsx"}:
                    continue
                rendered_relative = str(PurePosixPath(relative).with_suffix(".pdf"))
                if rendered_relative not in rendered_set:
                    raise CandidateSubmissionError(f"Submitted Office artifact was not rendered: {relative}")
                helper_relative_paths.append(rendered_relative)
                helper_paths.append(f"/workspace/{rendered_relative}")
            final_paths = list(dict.fromkeys([*submitted_relative_paths, *helper_relative_paths]))
            submitted_files = await _save_submitted_artifacts(
                provider,
                final_paths,
                submission_dir,
            )
            if hasattr(finish_params, "paths"):
                finish_params.paths = []

            provider_info = provider.debugging_info
            staged_inputs = list(provider.staged_assets)
        atomic_write_json(temporary / "finish_params.json", finish_payload)
        atomic_write_json(temporary / "history.json", _history_json(history))
        atomic_write_json(temporary / "metadata.json", metadata)
        manifest = {
            "schema_version": 1,
            "task_id": str(task["task_id"]),
            "trial": trial,
            "config_fingerprint": fingerprint,
            "policy_endpoint_session_id": endpoint_session_id,
            "finished_at": time.time(),
            "elapsed_seconds": time.time() - started,
            "abandoned": not hasattr(finish_params, "paths"),
            "finish": finish_payload,
            "vmvm": provider_info,
            "reference_input_assets": staged_inputs,
            "submitted_files": submitted_files,
            "office_render_helpers": helper_paths,
            "office_render_history": list(provider.render_history),
            "web_fetch_trust_env": web_provider.trust_env,
            "web_search_available": web_search_enabled,
            "tool_capabilities": _tool_capabilities(config),
            "files": _manifest(temporary, exclude={"candidate.json"}),
        }
        manifest["candidate_sha256"] = hashlib.sha256(
            json.dumps(manifest["files"], sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        atomic_write_json(temporary / "candidate.json", manifest)
        os.replace(temporary, candidate_dir)
        return manifest
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _select_reference(config: dict[str, Any], task_id: str) -> dict[str, Any]:
    references = config.get("references") or []
    if not references:
        raise ValueError("Comparison mode requires at least one [[references]] entry")
    ordered = sorted(references, key=lambda item: str(item["id"]))
    seed_material = f"{config['benchmark']['dispatch_seed']}|{task_id}".encode()
    index = int(hashlib.sha256(seed_material).hexdigest()[:16], 16) % len(ordered)
    return ordered[index]


def _safe_component(value: str) -> str:
    component = "".join(character if character.isalnum() or character in "-_." else "_" for character in value)
    if not component or component in {".", ".."}:
        raise ValueError(f"Unsafe path component: {value!r}")
    return component


def _task_input_instance(
    task: dict[str, Any],
    candidate: dict[str, Any],
    output_dir: Path,
    config: dict[str, Any],
) -> dict[str, Any] | None:
    specs = _reference_input_specs(task, config)
    if not specs:
        return None
    expected_assets = list(candidate.get("reference_input_assets") or [])
    if len(expected_assets) != len(specs):
        raise ValueError(f"Candidate input manifest is incomplete for task {task['task_id']}")
    identity = {
        "task_id": str(task["task_id"]),
        "source": "dataset_reference_inputs",
        "assets": specs,
        "expected_assets": expected_assets,
    }
    return {
        "reference_id": "task_inputs",
        "repeat": "pinned_dataset",
        "source": "dataset_reference_inputs",
        "expected_assets": expected_assets,
        "identity": identity,
        "rendered_dir": output_dir / "rendered_inputs" / f"task_{task['task_id']}",
    }


def _reference_instances(
    reference: dict[str, Any],
    task: dict[str, Any],
    trial: int,
    output_dir: Path,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    task_id = str(task["task_id"])
    reference_id = str(reference["id"])
    reference_component = _safe_component(reference_id)
    if reference.get("source") == "dataset_deliverables":
        specs = _expert_deliverable_specs(task, config)
        identity = {
            "task_id": task_id,
            "reference_id": reference_id,
            "repeat": "public_human_expert",
            "source": "dataset_deliverables",
            "assets": specs,
        }
        return [
            {
                "reference_id": reference_id,
                "reference_elo": float(reference["elo"]),
                "repeat": "public_human_expert",
                "source": "dataset_deliverables",
                "path": None,
                "identity": identity,
                "rendered_dir": output_dir
                / "rendered_references"
                / f"task_{task_id}"
                / reference_component
                / "public_human_expert",
            }
        ]

    root = Path(reference["deliverables_dir"]).expanduser().resolve()
    task_root = root / f"task_{task_id}"
    repeats = sorted(path for path in task_root.glob("repeat_*") if path.is_dir()) if task_root.is_dir() else []
    if not repeats:
        candidates = [task_root / f"repeat_{trial}", task_root / "repeat_0", task_root]
        repeats = [path for path in candidates if path.is_dir()][:1]
    instances: list[dict[str, Any]] = []
    for path in repeats:
        files = _manifest(path)
        if not files:
            raise ValueError(f"Empty reference deliverables for task {task_id}: {path}")
        repeat = path.name if path.name.startswith("repeat_") else "task_root"
        identity = {
            "task_id": task_id,
            "reference_id": reference_id,
            "repeat": repeat,
            "source": "external",
            "source_files": files,
        }
        instances.append(
            {
                "reference_id": reference_id,
                "reference_elo": float(reference["elo"]),
                "repeat": repeat,
                "source": "external",
                "path": path,
                "identity": identity,
                "rendered_dir": output_dir
                / "rendered_references"
                / f"task_{task_id}"
                / reference_component
                / _safe_component(repeat),
            }
        )
    if instances:
        return instances
    raise ValueError(f"Missing reference deliverables for task {task_id} under {root}")


def _write_result(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_json(path, payload)
    print(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str), flush=True)


def _candidate_result_fields(
    candidate_dir: Path,
    candidate: dict[str, Any] | None,
    *,
    required: bool = False,
) -> dict[str, str]:
    if candidate is None:
        if required:
            raise ValueError("Judge retry has no persisted candidate binding")
        return {}
    persisted = _verify_candidate(candidate_dir)
    if persisted is None:
        raise ValueError(f"Persisted candidate disappeared: {candidate_dir}")
    if persisted != candidate:
        raise ValueError(f"Persisted candidate manifest changed: {candidate_dir}")
    candidate_sha256 = persisted.get("candidate_sha256")
    if not isinstance(candidate_sha256, str) or not candidate_sha256:
        raise ValueError(f"Candidate manifest has no aggregate digest: {candidate_dir}")
    return {
        "candidate_dir": str(candidate_dir.resolve()),
        "candidate_sha256": candidate_sha256,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--trial", type=int, required=True)
    parser.add_argument("--attempt", type=int, required=True)
    parser.add_argument("--fingerprint", required=True)
    parser.add_argument("--endpoint-session-id", required=True)
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--expected-candidate-sha256")
    parser.add_argument("--judge-journal", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--policy-base-url")
    parser.add_argument("--policy-job-id")
    parser.add_argument("--judge-base-url")
    args = parser.parse_args()

    config = load_config(args.config.resolve())
    tasks = {str(row["task_id"]): row for row in load_jsonl(args.catalog.resolve())}
    if args.task_id not in tasks:
        raise ValueError(f"Unknown task_id: {args.task_id}")
    task = tasks[args.task_id]
    base = {
        "schema_version": 1,
        "task_id": args.task_id,
        "trial": args.trial,
        "attempt": args.attempt,
        "config_fingerprint": args.fingerprint,
        "endpoint_session_id": args.endpoint_session_id,
        "time": time.time(),
    }
    candidate: dict[str, Any] | None = None
    failure_role = "judge"
    try:
        mode = str(config["scoring"]["mode"])
        run_output_dir = args.candidate_dir.resolve().parents[2]
        reference_instances: list[dict[str, Any]] = []
        if mode == "comparison":
            reference = _select_reference(config, args.task_id)
            reference_instances = _reference_instances(
                reference,
                task,
                args.trial,
                run_output_dir,
                config,
            )
        candidate_persisted = (args.candidate_dir.resolve() / "candidate.json").is_file()
        failure_role = "judge" if args.expected_candidate_sha256 or candidate_persisted else "policy"
        if args.expected_candidate_sha256 and not candidate_persisted:
            raise ValueError("The required persisted candidate is missing before judge-only execution")
        policy = (
            None
            if candidate_persisted
            else load_policy_endpoint(config["policy"], args.policy_base_url, args.policy_job_id)
        )
        candidate = asyncio.run(
            _rollout(
                task=task,
                trial=args.trial,
                config=config,
                fingerprint=args.fingerprint,
                endpoint_session_id=args.endpoint_session_id,
                policy=policy,
                candidate_dir=args.candidate_dir.resolve(),
            )
        )
        if args.expected_candidate_sha256 and candidate.get("candidate_sha256") != args.expected_candidate_sha256:
            raise ValueError("The persisted candidate changed before judge-only execution")
        failure_role = "judge"
        input_instance = _task_input_instance(task, candidate, run_output_dir, config)
        render_instances = ([input_instance] if input_instance is not None else []) + reference_instances
        if render_instances:
            asyncio.run(_render_references_only(task=task, config=config, instances=render_instances))
        reference_inputs_dir = input_instance["rendered_dir"] if input_instance is not None else None
        judge = load_info_endpoint(config["judge"], args.judge_base_url)
        if mode == "rubric":
            score = score_rubric(
                task=task,
                candidate_dir=args.candidate_dir.resolve(),
                reference_inputs_dir=reference_inputs_dir,
                endpoint_session_id=args.endpoint_session_id,
                journal_path=args.judge_journal.resolve(),
                endpoint={"base_url": judge.base_url, "api_key": judge.api_key},
                judge_config=config["judge"],
                scoring_config=config["scoring"],
            )
        elif mode == "comparison":
            matchups: list[dict[str, Any]] = []
            for instance in reference_instances:
                base_journal = args.judge_journal.resolve()
                suffix = f".{_safe_component(instance['reference_id'])}.{_safe_component(instance['repeat'])}"
                journal_path = base_journal.with_name(base_journal.stem + suffix + base_journal.suffix)
                matchups.append(
                    score_comparison(
                        task=task,
                        candidate_dir=args.candidate_dir.resolve(),
                        reference_inputs_dir=reference_inputs_dir,
                        reference_dir=instance["rendered_dir"],
                        reference_id=str(instance["reference_id"]),
                        reference_repeat=str(instance["repeat"]),
                        reference_elo=float(instance["reference_elo"]),
                        endpoint_session_id=args.endpoint_session_id,
                        journal_path=journal_path,
                        endpoint={"base_url": judge.base_url, "api_key": judge.api_key},
                        judge_config=config["judge"],
                        scoring_config=config["scoring"],
                    )
                )
            wins = sum(int(matchup["wins"]) for matchup in matchups)
            losses = sum(int(matchup["losses"]) for matchup in matchups)
            ties = sum(int(matchup["ties"]) for matchup in matchups)
            invalid = sum(int(matchup["invalid_trials"]) for matchup in matchups)
            valid = wins + losses + ties
            if valid == 0:
                raise JudgeFatalError("All comparison judge responses were malformed")
            reward = 1.0 if wins > losses else 0.0 if losses > wins else 0.5
            score = {
                "mode": "comparison",
                "reward": reward,
                "reference_id": str(reference["id"]),
                "reference_elo": float(reference["elo"]),
                "reference_repeats": len(reference_instances),
                "wins": wins,
                "losses": losses,
                "ties": ties,
                "invalid_trials": invalid,
                "matchups": matchups,
            }
        else:
            raise ValueError(f"Unsupported scoring mode: {mode!r}")
        _write_result(
            args.result,
            base
            | {
                "status": "completed",
                "reward": score["reward"],
                "candidate_sha256": candidate["candidate_sha256"],
                "candidate_dir": str(args.candidate_dir.resolve()),
                "score": score,
            },
        )
        return 0
    except VMVMInfrastructureLost as error:
        status = "judge_retryable" if candidate is not None else "retryable_error"
        payload = base | {
            "status": status,
            "failure_role": "judge" if candidate is not None else "policy",
            "error": str(error),
        }
        payload.update(_candidate_result_fields(args.candidate_dir, candidate))
        _write_result(args.result, payload)
        return 76 if candidate is not None else 75
    except JudgeRetryableError as error:
        _write_result(
            args.result,
            base
            | {
                "status": "judge_retryable",
                "failure_role": "judge",
                "error": str(error),
            }
            | _candidate_result_fields(args.candidate_dir, candidate, required=True),
        )
        return 76
    except asyncio.TimeoutError as error:
        _write_result(args.result, base | {"status": "model_timeout", "reward": 0.0, "error": str(error)})
        return 0
    except (CandidateSubmissionError, ContextOverflowError, ModelRequestError) as error:
        _write_result(args.result, base | {"status": "model_error", "reward": 0.0, "error": str(error)})
        return 0
    except JudgeFatalError as error:
        _write_result(
            args.result,
            base
            | {
                "status": "fatal_error",
                "failure_role": "judge",
                "error": f"{type(error).__name__}: {error}",
            }
            | _candidate_result_fields(args.candidate_dir, candidate),
        )
        return 2
    except ModelFatalError as error:
        _write_result(
            args.result,
            base
            | {
                "status": "fatal_error",
                "failure_role": "policy",
                "error": f"{type(error).__name__}: {error}",
            },
        )
        return 2
    except (VMVMFatalError, ValueError) as error:
        _write_result(
            args.result,
            base
            | {
                "status": "fatal_error",
                "failure_role": failure_role,
                "error": f"{type(error).__name__}: {error}",
            }
            | _candidate_result_fields(args.candidate_dir, candidate),
        )
        return 2
    except Exception as error:
        _write_result(
            args.result,
            base
            | {
                "status": "fatal_error",
                "failure_role": failure_role,
                "error": f"{type(error).__name__}: {error}",
            }
            | _candidate_result_fields(args.candidate_dir, candidate),
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
