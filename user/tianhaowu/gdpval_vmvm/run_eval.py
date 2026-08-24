from __future__ import annotations

import argparse
import concurrent.futures
import fcntl
import gzip
import hashlib
import importlib.metadata
import json
import logging
import os
import queue
import random
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from asset_fetch import (
    asset_cache_status,
    bind_manifest_to_catalog,
    load_asset_manifest,
    mirror_provenance,
    prepare_asset_cache,
    select_manifest_entries,
)
from common import (
    Endpoint,
    append_jsonl,
    atomic_write_json,
    judge_deployment_identity,
    load_config,
    load_info_endpoint,
    load_jsonl,
    load_policy_endpoint,
    policy_deployment_identity,
    repair_truncated_jsonl_tail,
    sha256_file,
)
from judge import calculate_mle_elo_report
from prepare import prepare

logger = logging.getLogger("gdpval_vmvm")
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]

EXPECTED_SOURCE_PINS = {
    "dataset": "openai/gdpval",
    "dataset_revision": "11e7900cdcac61bc4daf59e65feb238acda98fbf",
    "dataset_parquet_sha256": "f8422fab9b21d90c0ee5f0659842ab666d418cb8940842918f9f4b0df7ae0202",
    "dataset_mirror_commit": "501e302a9da6d889895b6df693b955c41ca60719",
    "dataset_mirror_url": (
        "https://raw.githubusercontent.com/Wrigggy/evolving-quant-agent/"
        "501e302a9da6d889895b6df693b955c41ca60719/data/gdpval/gdpval_gold.parquet"
    ),
    "asset_mirror_repository": "ycm824632241/benchmark-8.13",
    "asset_mirror_commit": "ab55c6be877d2da8d7016e809cbfc9cab2ed1e90",
    "asset_mirror_tasks_tree": "2a76ef74c516bbebca41150458ab5bb06983a2d1",
    "asset_manifest_file": "gdpval_asset_manifest.tsv",
    "asset_manifest_sha256": "3df5445b1d3a321b9c3c2b7abc418a273d189149e0e966cfc6e0a8604ba38b91",
    "gym_recipe_commit": "57c15a22f8b82d3d859b71468fe3329f4e2093b4",
    "gym_kimi_judge_commit": "13e181aa1779809457d1abbf47ab209d8d0f5ab3",
    "stirrup_commit": "3e988e5a1729cea37e6484e5cab2ab0f9eae4ffb",
}
EXPECTED_POLICY_REVISION = "d51eab0d1f979ebc26b546e634a04f450d99158e"
EXPECTED_JUDGE_REVISION = "2755962d07cb42aa2d988a35bcb65cd4a9c2de82"
EXPECTED_SANDBOX_PROVENANCE = {
    "source_image": (
        "docker.io/tianhao0122/optimbench-tb@sha256:31aa69a13dee68d525e49748d937f9a26b05e24aff769f5348b83902f34014df"
    ),
    "sandbox_definition_commit": "57c15a22f8b82d3d859b71468fe3329f4e2093b4",
    "sandbox_definition_sha256": "66273c6372fc5bf51b61bde99ada6e1f0f87e4df637e149039170a13aefa7283",
    "sandbox_dockerfile_sha256": "8a078c82c12c7a4eebfd72b47a516c2a5db40f3f8244174cbad3184515dd7001",
    "sandbox_base_image_index": "sha256:62eafe52c91cad83c2c74e630bfde917da8c253673e695665d454def84fc9a13",
    "sandbox_base_image_amd64": "sha256:0a8602b4fbafe6dd46993ae2f94dbb673d8c9c534100e77641973c43f8469cf0",
    "sandbox_pip_freeze_sha256": "a7600f936030214eec6d9cd9546599f9d75ff4c891a2e9d583af97e2518bd29e",
}
EXPECTED_OFFICIAL_REFERENCE = {
    "snapshot_date": "2026-08-22",
    "elo": 698.06,
    "normalized_score": 9.903,
    "model_url": "https://artificialanalysis.ai/models/nvidia-nemotron-3-super-120b-a12b",
    "snapshot_url": (
        "https://github.com/TabNahida/AInsights/blob/"
        "e45e3eac0cf0fa69f4cf9e14e2e45fbd347f00be/ArtificialAnalysis/artificialanalysis_raw_scores_wide.csv"
    ),
}
SCORED_STATUSES = {"completed", "model_error", "model_timeout"}
RETRYABLE_STATUSES = {"retryable_error", "judge_retryable"}
FAILURE_ROLES = {"policy", "judge"}
UNSUPPORTED_KIMI_ARTIFACTS = {
    ".wav",
    ".mp3",
    ".ogg",
    ".aiff",
    ".aac",
    ".flac",
    ".mp4",
    ".mov",
    ".avi",
    ".webm",
    ".wmv",
    ".3gpp",
    ".step",
    ".stp",
    ".psd",
}
PINNED_NESTED_UNSUPPORTED = {
    "5e2b6aab-f9fb-4dd6-a1a5-874ef1743909": ".step files inside TOASTY_REVA_STEP_FILES.zip",
}
PINNED_INVALID_REFERENCE_ARTIFACTS = {
    "0e386e32-df20-4d1f-b536-7159bc409ad5": (
        "PrivateCrypMixV2.zip in the pinned mirror is truncated at exactly 32 MiB and has no ZIP central directory"
    ),
}
IMPLEMENTATION_FILES = [
    "__init__.py",
    "agent.py",
    "asset_fetch.py",
    "audit.py",
    "common.py",
    "Dockerfile.sandbox",
    "gdpval_user_prompt.txt",
    "gdpval_asset_manifest.tsv",
    "judge.py",
    "nemotron_super_kimi.toml",
    "nemotron_super_kimi_comparison.example.toml",
    "office_render.py",
    "policy_client.py",
    "prepare.py",
    "probe_runtime.py",
    "pyproject.toml",
    "README.md",
    "run_eval.py",
    "run_eval.sbatch",
    "uv.lock",
    "vmvm_provider.py",
    "worker.py",
]
GENERATION_IMPLEMENTATION_FILES = {
    f"user/tianhaowu/gdpval_vmvm/{name}"
    for name in (
        "agent.py",
        "asset_fetch.py",
        "common.py",
        "Dockerfile.sandbox",
        "gdpval_user_prompt.txt",
        "office_render.py",
        "policy_client.py",
        "pyproject.toml",
        "uv.lock",
        "vmvm_provider.py",
        "worker.py",
    )
}
GENERATION_VMVM_PREFIX = "environments/vmvm_tb_v2/vmvm_tb_v2/"
CANDIDATE_IMPORT_SCHEMA_VERSION = 1
PREFLIGHT_SCHEMA_VERSION = 2
ENDPOINT_SESSION_SCHEMA_VERSION = 2
RUN_METADATA_SCHEMA_VERSION = 2
WEB_FETCH_PROBE_URL = "https://example.com/"
WEB_FETCH_INVALID_URL = "https://example.com/invalid\npath"
DATASET_PARQUET_FILE = "data/train-00000-of-00001.parquet"
EXPECTED_CATALOG_SHAPE = {
    "tasks": 220,
    "sectors": 9,
    "occupations": 44,
    "reference_files": 261,
    "deliverable_files": 248,
    "rubric_items": 10_453,
}


def _sft_compatibility_aliases(config: dict[str, Any]) -> bool:
    enabled = config.get("tools", {}).get("sft_compatibility_aliases", False)
    if not isinstance(enabled, bool):
        raise ValueError("tools.sft_compatibility_aliases must be a boolean")
    return enabled


def _expected_tool_capabilities(config: dict[str, Any]) -> dict[str, Any]:
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


def _expected_code_execution_tool_names(config: dict[str, Any]) -> list[str]:
    names = ["run_shell"]
    if _sft_compatibility_aliases(config):
        names.append("code_exec")
    return names


def _expected_workspace_contract(config: dict[str, Any]) -> dict[str, Any]:
    sft_compatibility_aliases = _sft_compatibility_aliases(config)
    return {
        "canonical_root": "/workspace",
        "command_working_directory": "/workspace",
        "home_directory": "/home/user" if sft_compatibility_aliases else None,
        "home_user_resolves_to_workspace": sft_compatibility_aliases,
        "write_through_verified": sft_compatibility_aliases,
    }


def _expected_finish_contract(config: dict[str, Any]) -> dict[str, Any]:
    sft_compatibility_aliases = _sft_compatibility_aliases(config)
    return {
        "tool_name": "finish",
        "canonical_field": "reason",
        "schema_fields": ["reason", "paths", "summary"] if sft_compatibility_aliases else ["reason", "paths"],
        "summary_alias_enabled": sft_compatibility_aliases,
        "summary_alias_accepted": sft_compatibility_aliases,
        "conflicting_aliases_rejected": sft_compatibility_aliases,
    }


def _validate_sandbox_tool_contract(sandbox: dict[str, Any], config: dict[str, Any], *, context: str) -> None:
    if sandbox.get("tool_capabilities") != _expected_tool_capabilities(config):
        raise ValueError(f"{context} has mismatched tool capabilities")
    if sandbox.get("code_execution_tool_names") != _expected_code_execution_tool_names(config):
        raise ValueError(f"{context} has mismatched code-execution tool names")
    if sandbox.get("workspace_contract") != _expected_workspace_contract(config):
        raise ValueError(f"{context} has mismatched workspace alias evidence")
    if sandbox.get("finish_contract") != _expected_finish_contract(config):
        raise ValueError(f"{context} has mismatched finish-tool evidence")
    expected_provider_capabilities = {
        "run_shell": True,
        "code_exec": _sft_compatibility_aliases(config),
        "home_user_workspace_alias": _sft_compatibility_aliases(config),
    }
    if sandbox.get("vmvm", {}).get("tool_capabilities") != expected_provider_capabilities:
        raise ValueError(f"{context} has mismatched VMVM provider capabilities")


class MissingWorkerResult(RuntimeError):
    pass


@dataclass(frozen=True)
class Trial:
    task: dict[str, Any]
    trial: int

    @property
    def task_id(self) -> str:
        return str(self.task["task_id"])

    @property
    def key(self) -> tuple[str, int]:
        return self.task_id, self.trial


@dataclass(frozen=True)
class CandidateSource:
    run_dir: Path
    config: dict[str, Any]
    config_fingerprint: str
    generation_fingerprint: str
    catalog: dict[str, dict[str, Any]]
    catalog_provenance_path: Path
    catalog_provenance: dict[str, Any]
    planned_keys: set[tuple[str, int]]
    implementation: dict[str, str]
    metadata: dict[str, Any]
    endpoint_sessions: dict[str, dict[str, Any]]
    preflight_path: Path
    preflight: dict[str, Any]


class JsonlStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()

    def append(self, row: dict[str, Any]) -> None:
        with self.lock:
            append_jsonl(self.path, row)


def _validate_config(config: dict[str, Any]) -> None:
    source = config["source"]
    for key, expected in EXPECTED_SOURCE_PINS.items():
        if source.get(key) != expected:
            raise ValueError(f"source.{key} must be pinned to {expected}")
    if not source.get("asset_cache_dir"):
        raise ValueError("source.asset_cache_dir is required for the pinned GitHub asset mirror")
    benchmark = config["benchmark"]
    if int(benchmark["expected_tasks"]) != 220:
        raise ValueError("GDPval v2 must contain 220 tasks")
    if int(benchmark["max_turns"]) != 250:
        raise ValueError("GDPval-AA v2 parity requires 250 Stirrup turns")
    policy = config["policy"]
    if policy.get("api_key"):
        raise ValueError("Inline policy.api_key is forbidden; use policy.api_key_env")
    policy_deployment_identity(policy)
    if not policy.get("slurm_job_name"):
        raise ValueError("policy.slurm_job_name is required for deployment provenance")
    if policy.get("checkpoint_revision") != EXPECTED_POLICY_REVISION:
        raise ValueError(f"policy.checkpoint_revision must be pinned to {EXPECTED_POLICY_REVISION}")
    if not policy.get("server_version"):
        raise ValueError("policy.server_version is required for provenance")
    if policy["model"] != "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16":
        raise ValueError("This config is specifically for NVIDIA Nemotron 3 Super 120B A12B BF16")
    if float(policy["temperature"]) != 1.0 or float(policy["top_p"]) != 0.95:
        raise ValueError("Nemotron vendor generation parity requires temperature=1.0 and top_p=0.95")
    if policy.get("thinking") is not True:
        raise ValueError("Nemotron reasoning must be enabled")
    judge = config["judge"]
    if judge.get("api_key"):
        raise ValueError("Inline judge.api_key is forbidden; use judge.api_key_env or judge.info_path")
    judge_deployment_identity(judge)
    if not judge.get("info_path"):
        raise ValueError("judge.info_path is required to resolve judge.proxy_jobid")
    if judge["model"] != "Kimi-K2.6":
        raise ValueError("This runner's local judge configuration must use Kimi-K2.6")
    if int(judge["context_window"]) != 262144:
        raise ValueError("The pinned Kimi K2.6 judge context window must be 262144")
    if int(judge["max_tokens"]) >= int(judge["context_window"]):
        raise ValueError("judge.max_tokens must leave room for judge input")
    if judge.get("protocol_checkpoint_revision") != EXPECTED_JUDGE_REVISION:
        raise ValueError(f"judge.protocol_checkpoint_revision must be pinned to {EXPECTED_JUDGE_REVISION}")
    if int(judge["pdf_render_dpi"]) != 150 or int(judge["pdf_max_pages"]) != 30:
        raise ValueError("The pinned Kimi overlay requires 150 DPI and a 30-page per-file cap")
    if judge.get("deduplicate_office_pdf_sidecars") is not True:
        raise ValueError("The 262k Kimi adapter requires Office/PDF sidecar deduplication")
    if not 1 <= int(judge["max_visual_blocks_per_section"]) <= 18:
        raise ValueError("judge.max_visual_blocks_per_section must be between 1 and the safe maximum of 18")
    if not 512 <= int(judge["max_text_characters_per_section"]) <= 20_000:
        raise ValueError("judge.max_text_characters_per_section must be between 512 and the safe maximum of 20000")
    if int(judge["max_tokens"]) != 65535:
        raise ValueError("The pinned Kimi judge output budget must be 65535 tokens")
    if int(judge["format_retries"]) != 1:
        raise ValueError("The pinned Kimi overlay makes exactly one call per judge trial")
    if int(config["scoring"]["num_trials"]) != 4:
        raise ValueError("GDPval comparison/rubric judging requires four trials")
    if config["scoring"].get("terminal_failure_policy") != "withhold_headline_elo":
        raise ValueError("scoring.terminal_failure_policy must be 'withhold_headline_elo'")
    if config["scoring"]["mode"] not in {"rubric", "comparison"}:
        raise ValueError("scoring.mode must be 'rubric' or 'comparison'")
    if config["scoring"]["mode"] == "comparison":
        references = config.get("references") or []
        if not references:
            raise ValueError("Comparison mode requires at least one [[references]] entry")
        for reference in references:
            if not reference.get("id") or not isinstance(reference.get("elo"), (int, float)):
                raise ValueError("Every comparison reference requires an id and numeric elo")
            if reference.get("source") != "dataset_deliverables" and not reference.get("deliverables_dir"):
                raise ValueError("External comparison references require deliverables_dir")
    tools = config.get("tools")
    if not isinstance(tools, dict):
        raise ValueError("The [tools] configuration is required")
    if not isinstance(tools.get("require_brave_search"), bool):
        raise ValueError("tools.require_brave_search must be a boolean")
    _sft_compatibility_aliases(config)
    if tools.get("web_fetch_trust_env") is not False:
        raise ValueError("tools.web_fetch_trust_env must be false on the Slurm CPU runtime")
    runtime = config["runtime"]
    for key, expected in EXPECTED_SANDBOX_PROVENANCE.items():
        if runtime.get(key) != expected:
            raise ValueError(f"runtime.{key} must be pinned to {expected}")
    image = str(runtime["image"])
    if "@sha256:" not in image:
        raise ValueError("runtime.image must be content-addressed with an OCI digest")
    source_image = str(runtime.get("source_image", image))
    if source_image.rsplit("@", 1)[-1] != image.rsplit("@", 1)[-1]:
        raise ValueError("runtime.source_image and runtime.image must use the same OCI digest")
    if runtime.get("preload_image") and not image.startswith(
        (
            "registry-oci1.fbinfra.net/",
            "registry-oci1-test.fbinfra.net/",
            "vmvm-registry.fbinfra.net/",
            "registry-oci-public.atmeta.com/",
        )
    ):
        raise ValueError("VMVM image preloading requires an approved internal registry mirror")
    if int(runtime["command_timeout_seconds"]) != 600:
        raise ValueError("GDPval-AA parity requires the 10-minute shell-command limit")
    if runtime.get("require_preflight") is not True:
        raise ValueError("runtime.require_preflight must be true for a referenceable run")
    if int(config["retry"]["max_infrastructure_retries"]) < 0:
        raise ValueError("max_infrastructure_retries must be nonnegative")
    if int(config["retry"]["max_judge_retries"]) < 0:
        raise ValueError("max_judge_retries must be nonnegative")
    if config["official_reference"] != EXPECTED_OFFICIAL_REFERENCE:
        raise ValueError("official_reference does not match the pinned 2026-08-22 Artificial Analysis snapshot")


def _implementation_sources() -> list[Path]:
    sources = [HERE / name for name in IMPLEMENTATION_FILES if (HERE / name).exists()]
    sources.extend(sorted((REPO_ROOT / "environments" / "vmvm_tb_v2" / "vmvm_tb_v2").rglob("*.py")))
    return sorted(sources)


def _source_hashes() -> dict[str, str]:
    return {str(path.relative_to(REPO_ROOT)): sha256_file(path) for path in _implementation_sources()}


def _semantic_config(
    config: dict[str, Any],
    implementation: dict[str, str] | None = None,
) -> dict[str, Any]:
    endpoint_keys = {
        "api_key",
        "api_key_env",
        "base_url",
        "base_url_env",
        "info_path",
        "proxy_jobid",
        "slurm_job_id",
        "slurm_job_id_env",
        "slurm_job_name",
        "port",
    }
    source_path_keys = {"catalog_file", "asset_cache_dir", "reference_cache_dir", "expert_cache_dir"}
    return {
        "source": {key: value for key, value in config["source"].items() if key not in source_path_keys},
        "benchmark": config["benchmark"],
        "policy": {key: value for key, value in config["policy"].items() if key not in endpoint_keys},
        "judge": {key: value for key, value in config["judge"].items() if key not in endpoint_keys},
        "scoring": config["scoring"],
        "tools": config.get("tools", {}),
        "references": config.get("references", []),
        "runtime": config["runtime"],
        "retry": config["retry"],
        "official_reference": config["official_reference"],
        "implementation": _source_hashes() if implementation is None else implementation,
    }


def _fingerprint(config: dict[str, Any], implementation: dict[str, str] | None = None) -> str:
    payload = json.dumps(_semantic_config(config, implementation), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _sha256_json(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def _generation_implementation_hashes(implementation: dict[str, str]) -> dict[str, str]:
    selected = {
        path: digest
        for path, digest in implementation.items()
        if path in GENERATION_IMPLEMENTATION_FILES or (path.startswith(GENERATION_VMVM_PREFIX) and path.endswith(".py"))
    }
    missing = sorted(GENERATION_IMPLEMENTATION_FILES - set(selected))
    if missing:
        raise ValueError(f"Generation implementation manifest is missing required files: {missing}")
    if not any(path.startswith(GENERATION_VMVM_PREFIX) for path in selected):
        raise ValueError("Generation implementation manifest has no VMVM backend files")
    return dict(sorted(selected.items()))


def _generation_fingerprint(config: dict[str, Any], implementation: dict[str, str]) -> str:
    payload = {
        "schema_version": 1,
        "config": {
            section: config.get(section, {}) for section in ("source", "benchmark", "policy", "tools", "runtime")
        },
        "implementation": _generation_implementation_hashes(implementation),
    }
    return _sha256_json(payload)


def _package_versions() -> dict[str, str]:
    packages = ["openai", "stirrup", "PyMuPDF", "pdfminer.six", "Pillow", "httpx"]
    return {name: importlib.metadata.version(name) for name in packages}


def _probe(endpoint: Endpoint, expected_server_version: str | None = None) -> dict[str, Any]:
    request = urllib.request.Request(
        endpoint.base_url.rstrip("/") + "/v1/models",
        headers={"Authorization": f"Bearer {endpoint.api_key}"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=30) as response:
        payload = json.load(response)
    model_ids = {str(item.get("id")) for item in payload.get("data", []) if isinstance(item, dict)}
    if endpoint.model not in model_ids:
        raise ValueError(f"Endpoint {endpoint.base_url} does not advertise {endpoint.model!r}: {sorted(model_ids)}")
    selected = [item for item in payload.get("data", []) if isinstance(item, dict) and item.get("id") == endpoint.model]
    result = endpoint.public() | {
        "advertised_models": sorted(model_ids),
        "advertised_model_metadata": selected,
    }
    if expected_server_version is not None:
        version_request = urllib.request.Request(
            endpoint.base_url.rstrip("/") + "/version",
            headers={"Authorization": f"Bearer {endpoint.api_key}"},
        )
        with opener.open(version_request, timeout=30) as response:
            version_payload = json.load(response)
        version = str(version_payload.get("version", ""))
        if version != expected_server_version:
            raise ValueError(
                f"Endpoint {endpoint.base_url} server version mismatch: "
                f"expected {expected_server_version}, got {version!r}"
            )
        result["server"] = {"version": version, "matched_expected_version": True}
    return result


def _stable_probe_identity(probe: dict[str, Any]) -> dict[str, Any]:
    stable_metadata = [
        {key: item.get(key) for key in ("id", "root", "max_model_len", "owned_by", "parent") if key in item}
        for item in probe.get("advertised_model_metadata", [])
        if isinstance(item, dict)
    ]
    return {
        "base_url": probe.get("base_url"),
        "model": probe.get("model"),
        "deployment_id": probe.get("deployment_id"),
        "slurm_job_id": probe.get("slurm_job_id"),
        "proxy_jobid": probe.get("proxy_jobid"),
        "advertised_models": probe.get("advertised_models"),
        "advertised_model_metadata": stable_metadata,
        "server": probe.get("server"),
    }


def _validate_probe_deployment(probe: dict[str, Any], expected: dict[str, str], role: str) -> None:
    if any(probe.get(key) != value for key, value in expected.items()):
        raise ValueError(f"{role.capitalize()} probe has mismatched resolved deployment provenance")


def _validate_endpoint_session_deployments(row: dict[str, Any], config: dict[str, Any]) -> None:
    if row.get("schema_version") != ENDPOINT_SESSION_SCHEMA_VERSION:
        raise ValueError("Endpoint session has an unsupported schema version")
    deployments = {
        "policy": policy_deployment_identity(config["policy"]),
        "judge": judge_deployment_identity(config["judge"]),
    }
    for role, expected in deployments.items():
        required = row.get(f"{role}_required")
        if not isinstance(required, bool):
            raise ValueError(f"Endpoint session has invalid {role}_required")
        for key, value in expected.items():
            session_key = f"{role}_{key}" if key != "deployment_id" else f"{role}_deployment_id"
            if row.get(session_key) != value:
                raise ValueError(f"Endpoint session has a mismatched {session_key}")
        probe = row.get(role)
        if required and not isinstance(probe, dict):
            raise ValueError(f"Endpoint session has no required {role} probe")
        if isinstance(probe, dict):
            _validate_probe_deployment(probe, expected, role)
            expected_model = str(config[role]["model"])
            if probe.get("model") != expected_model:
                raise ValueError(f"Endpoint session has a mismatched {role} model")
            advertised = probe.get("advertised_models")
            if not isinstance(advertised, list) or expected_model not in advertised:
                raise ValueError(f"Endpoint session did not advertise the configured {role} model")
            if role == "policy" and probe.get("server", {}).get("version") != config[role]["server_version"]:
                raise ValueError("Endpoint session has a mismatched policy server version")


def _validated_endpoint_sessions(path: Path, config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sessions: dict[str, dict[str, Any]] = {}
    for row in load_jsonl(path):
        session_id = row.get("endpoint_session_id")
        if not isinstance(session_id, str) or not session_id or session_id in sessions:
            raise ValueError(f"Invalid or duplicate endpoint session in {path}")
        _validate_endpoint_session_deployments(row, config)
        sessions[session_id] = row
    return sessions


def _validate_generation_preflight_payload(
    payload: dict[str, Any],
    config: dict[str, Any],
    fingerprint: str,
) -> None:
    if not isinstance(payload, dict):
        raise ValueError("Generation preflight artifact must be an object")
    schema_version = payload.get("schema_version")
    if isinstance(schema_version, bool) or not isinstance(schema_version, int) or schema_version < 1:
        raise ValueError("Generation preflight artifact has an invalid schema version")
    if payload.get("ok") is not True or "sandbox" not in payload:
        raise ValueError("Generation preflight artifact does not contain a successful sandbox probe")
    sandbox = payload["sandbox"]
    if (
        not isinstance(sandbox, dict)
        or not sandbox.get("staged_assets")
        or not sandbox.get("render_history")
        or not any(str(path).lower().endswith(".pdf") for path in sandbox.get("rendered_files", []))
        or not isinstance(sandbox.get("vmvm"), dict)
    ):
        raise ValueError("Generation preflight artifact has incomplete sandbox and Office-render evidence")
    _validate_sandbox_tool_contract(sandbox, config, context="Generation preflight artifact")
    asset_mirror = sandbox.get("asset_mirror")
    expected_mirror = {
        "repository": config["source"]["asset_mirror_repository"],
        "commit": config["source"]["asset_mirror_commit"],
        "tasks_tree": config["source"]["asset_mirror_tasks_tree"],
        "manifest_file": config["source"]["asset_manifest_file"],
        "manifest_sha256": config["source"]["asset_manifest_sha256"],
    }
    if not isinstance(asset_mirror, dict) or any(
        asset_mirror.get(key) != value for key, value in expected_mirror.items()
    ):
        raise ValueError("Generation preflight artifact has mismatched GDPval asset-mirror provenance")
    if (
        Path(str(asset_mirror.get("cache_dir", ""))).expanduser().resolve()
        != Path(config["source"]["asset_cache_dir"]).expanduser().resolve()
    ):
        raise ValueError("Generation preflight artifact has a mismatched GDPval asset-cache path")
    if (
        asset_mirror.get("ready") is not True
        or asset_mirror.get("hashes_verified") is not True
        or int(asset_mirror.get("cached_assets", -1)) != int(asset_mirror.get("selected_assets", -2))
        or int(asset_mirror.get("selected_assets", -1)) != len(sandbox["staged_assets"])
        or int(asset_mirror.get("missing_assets", -1)) != 0
        or int(asset_mirror.get("corrupt_assets", -1)) != 0
    ):
        raise ValueError("Generation preflight artifact does not prove a complete verified host asset cache")
    if payload.get("config_fingerprint") != fingerprint:
        raise ValueError("Generation preflight artifact has a mismatched source fingerprint")
    policy_deployment = policy_deployment_identity(config["policy"])
    if payload.get("policy_deployment_id") != policy_deployment["deployment_id"]:
        raise ValueError("Generation preflight policy deployment identity mismatch")
    if payload.get("policy_slurm_job_id") != policy_deployment["slurm_job_id"]:
        raise ValueError("Generation preflight policy Slurm job mismatch")
    if payload.get("sandbox_image") != config["runtime"]["image"]:
        raise ValueError("Generation preflight sandbox image mismatch")
    policy_probe = payload.get("policy")
    if not isinstance(policy_probe, dict) or policy_probe.get("model") != config["policy"]["model"]:
        raise ValueError("Generation preflight policy probe mismatch")
    _validate_probe_deployment(policy_probe, policy_deployment, "policy")
    if policy_probe.get("chat", {}).get("matched_expected_answer") is not True:
        raise ValueError("Generation preflight has no successful policy text probe")
    if policy_probe.get("tool_call", {}).get("arguments_valid") is not True:
        raise ValueError("Generation preflight has no successful policy tool-call probe")
    if policy_probe.get("server", {}).get("version") != config["policy"]["server_version"]:
        raise ValueError("Generation preflight policy server version mismatch")
    if not any(
        item.get("id") == config["policy"]["model"]
        and int(item.get("max_model_len", -1)) == int(config["policy"]["context_window"])
        for item in policy_probe.get("advertised_model_metadata", [])
        if isinstance(item, dict)
    ):
        raise ValueError("Generation preflight does not confirm the policy context window")
    web_fetch = payload.get("web_fetch")
    if (
        not isinstance(web_fetch, dict)
        or web_fetch.get("tool") != "fetch_web_page"
        or web_fetch.get("url") != WEB_FETCH_PROBE_URL
        or web_fetch.get("trust_env") is not config["tools"]["web_fetch_trust_env"]
        or web_fetch.get("success") is not True
        or web_fetch.get("matched_expected_content") is not True
        or web_fetch.get("pages_fetched") != [WEB_FETCH_PROBE_URL]
        or web_fetch.get("invalid_url") != WEB_FETCH_INVALID_URL
        or web_fetch.get("invalid_url_handled") is not True
        or web_fetch.get("invalid_url_pages_fetched") != [WEB_FETCH_INVALID_URL]
        or web_fetch.get("tool_names")
        != (["fetch_web_page", "web_search"] if config["tools"]["require_brave_search"] else ["fetch_web_page"])
        or not isinstance(web_fetch.get("proxy_environment_variables_present"), list)
    ):
        raise ValueError("Generation preflight has no successful scoped Stirrup web-fetch probe")
    if (
        config.get("tools", {}).get("require_brave_search")
        and payload.get("web_search", {}).get("matched_expected_shape") is not True
    ):
        raise ValueError("Generation preflight has no successful Brave Search probe")


def _snapshot(
    config_path: Path,
    catalog_path: Path,
    catalog_provenance_path: Path,
    output_dir: Path,
) -> None:
    config_snapshot = output_dir / "config.toml"
    catalog_snapshot = output_dir / "gdpval_benchmark.jsonl"
    provenance_snapshot = output_dir / catalog_provenance_path.name
    for source, destination in (
        (config_path, config_snapshot),
        (catalog_path, catalog_snapshot),
        (catalog_provenance_path, provenance_snapshot),
    ):
        if destination.exists() and destination.read_bytes() != source.read_bytes():
            raise ValueError(f"Snapshot mismatch in existing output directory: {destination}")
        if not destination.exists():
            shutil.copy2(source, destination)

    hashes = _source_hashes()
    hashes_path = output_dir / "implementation.sha256.json"
    if hashes_path.exists():
        if json.loads(hashes_path.read_text(encoding="utf-8")) != hashes:
            raise ValueError("Implementation changed since this output directory was created")
    else:
        atomic_write_json(hashes_path, hashes)

    snapshot_root = output_dir / "implementation"
    if snapshot_root.exists():
        actual_files = {
            path.relative_to(snapshot_root).as_posix() for path in snapshot_root.rglob("*") if path.is_file()
        }
        if actual_files != set(hashes):
            raise ValueError("Implementation snapshot file set does not match its recorded hashes")
        for relative, expected in hashes.items():
            path = snapshot_root / relative
            if not path.is_file() or sha256_file(path) != expected:
                raise ValueError(f"Implementation snapshot mismatch: {path}")
    else:
        temporary_root = Path(tempfile.mkdtemp(prefix=".implementation-", dir=output_dir))
        try:
            for path in _implementation_sources():
                destination = temporary_root / path.relative_to(REPO_ROOT)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
            os.replace(temporary_root, snapshot_root)
        except Exception:
            shutil.rmtree(temporary_root, ignore_errors=True)
            raise

    archive_path = output_dir / "implementation.tar.gz"
    if not archive_path.exists():
        temporary = archive_path.with_suffix(archive_path.suffix + ".tmp")
        with temporary.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for path in _implementation_sources():
                    relative = path.relative_to(REPO_ROOT)
                    info = archive.gettarinfo(str(path), arcname=relative.as_posix())
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mtime = 0
                    with path.open("rb") as handle:
                        archive.addfile(info, handle)
        os.replace(temporary, archive_path)


def _load_catalog(path: Path, expected_tasks: int) -> list[dict[str, Any]]:
    rows = load_jsonl(path)
    task_ids = [str(row["task_id"]) for row in rows]
    if len(task_ids) != len(set(task_ids)):
        raise ValueError(f"Duplicate task IDs in {path}")
    if len(rows) != expected_tasks:
        raise ValueError(f"Expected {expected_tasks} GDPval tasks, found {len(rows)}")
    return rows


def _catalog_shape(catalog: list[dict[str, Any]]) -> dict[str, int]:
    rubric_items = 0
    for task in catalog:
        rubric = task.get("rubric_json", {})
        parsed = json.loads(rubric) if isinstance(rubric, str) else rubric
        rubric_items += len(parsed) if isinstance(parsed, list) else len(parsed.get("criteria", []))
    return {
        "tasks": len(catalog),
        "sectors": len({str(task.get("sector", "")) for task in catalog}),
        "occupations": len({str(task.get("occupation", "")) for task in catalog}),
        "reference_files": sum(len(task.get("reference_files") or []) for task in catalog),
        "deliverable_files": sum(len(task.get("deliverable_files") or []) for task in catalog),
        "rubric_items": rubric_items,
    }


def _validate_catalog_provenance(
    catalog_path: Path,
    config: dict[str, Any],
    catalog: list[dict[str, Any]],
    asset_manifest_shape: dict[str, Any],
) -> dict[str, Any]:
    provenance_path = catalog_path.with_suffix(catalog_path.suffix + ".provenance.json")
    if not provenance_path.is_file() or provenance_path.is_symlink():
        raise ValueError(f"GDPval catalog provenance sidecar is missing or unsafe: {provenance_path}")
    payload = json.loads(provenance_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("GDPval catalog provenance sidecar must be an object")
    source = config["source"]
    for key, expected in EXPECTED_SOURCE_PINS.items():
        if source.get(key) != expected:
            raise ValueError(f"GDPval catalog source.{key} is not pinned to {expected}")
    catalog_sha256 = sha256_file(catalog_path)
    shape = _catalog_shape(catalog)
    if shape != EXPECTED_CATALOG_SHAPE:
        raise ValueError(f"GDPval catalog shape mismatch: expected {EXPECTED_CATALOG_SHAPE}, got {shape}")
    expected_asset_mirror = mirror_provenance(source) | {"shape": asset_manifest_shape}
    expected_transport = {
        "type": "sha256-verified-github-mirror",
        "url": source["dataset_mirror_url"],
    }
    if (
        payload.get("dataset") != source["dataset"]
        or payload.get("revision") != source["dataset_revision"]
        or payload.get("parquet_file") != DATASET_PARQUET_FILE
        or payload.get("parquet_sha256") != source["dataset_parquet_sha256"]
        or payload.get("catalog_sha256") != catalog_sha256
        or int(payload.get("tasks", -1)) != int(config["benchmark"]["expected_tasks"])
        or payload.get("shape") != shape
        or payload.get("asset_mirror") != expected_asset_mirror
        or payload.get("transport") != expected_transport
    ):
        raise ValueError("GDPval catalog provenance sidecar does not match the pinned catalog and asset mirror")
    return {
        "path": str(provenance_path),
        "sha256": sha256_file(provenance_path),
        "catalog_sha256": catalog_sha256,
        "shape": shape,
        "asset_mirror": expected_asset_mirror,
    }


def _candidate_manifest(candidate_dir: Path) -> tuple[dict[str, Any], str]:
    for path in (candidate_dir.parent.parent, candidate_dir.parent, candidate_dir):
        if path.is_symlink():
            raise ValueError(f"Candidate path contains a symlink: {path}")
    if not candidate_dir.is_dir() or candidate_dir.is_symlink():
        raise ValueError(f"Candidate directory is missing or unsafe: {candidate_dir}")
    marker = candidate_dir / "candidate.json"
    if not marker.is_file() or marker.is_symlink():
        raise ValueError(f"Candidate manifest is missing or unsafe: {marker}")
    for path in candidate_dir.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Candidate contains a symlink: {path}")
    payload = json.loads(marker.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Candidate manifest is not an object: {marker}")
    actual = [
        {
            "path": path.relative_to(candidate_dir).as_posix(),
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in sorted(candidate_dir.rglob("*"))
        if path.is_file() and path != marker
    ]
    if payload.get("files") != actual:
        raise ValueError(f"Candidate artifact manifest mismatch: {candidate_dir}")
    candidate_sha256 = hashlib.sha256(json.dumps(actual, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if payload.get("candidate_sha256") != candidate_sha256:
        raise ValueError(f"Candidate aggregate digest mismatch: {candidate_dir}")
    return payload, sha256_file(marker)


def _candidate_binding(
    candidate_dir: Path,
    *,
    task_id: str,
    trial: int,
    fingerprint: str,
) -> dict[str, str]:
    manifest, _ = _candidate_manifest(candidate_dir)
    if (
        manifest.get("task_id") != task_id
        or int(manifest.get("trial", -1)) != trial
        or manifest.get("config_fingerprint") != fingerprint
    ):
        raise ValueError(f"Candidate identity mismatch: {candidate_dir}")
    candidate_sha256 = manifest.get("candidate_sha256")
    if not isinstance(candidate_sha256, str) or not candidate_sha256:
        raise ValueError(f"Candidate manifest has no aggregate digest: {candidate_dir}")
    return {
        "candidate_dir": str(candidate_dir.resolve()),
        "candidate_sha256": candidate_sha256,
    }


def _existing_candidate_binding(
    candidate_dir: Path,
    *,
    task_id: str,
    trial: int,
    fingerprint: str,
) -> dict[str, str] | None:
    if not candidate_dir.exists() and not candidate_dir.is_symlink():
        return None
    return _candidate_binding(
        candidate_dir,
        task_id=task_id,
        trial=trial,
        fingerprint=fingerprint,
    )


def _failure_role(row: dict[str, Any], *, context: str) -> str | None:
    status = str(row.get("status"))
    if status not in RETRYABLE_STATUSES | {"fatal_error"}:
        return None
    role = row.get("failure_role")
    if role not in FAILURE_ROLES:
        raise ValueError(f"{context} has invalid failure_role: {role!r}")
    if status == "retryable_error" and role != "policy":
        raise ValueError(f"{context} has policy retry status with {role!r} failure_role")
    if status == "judge_retryable" and role != "judge":
        raise ValueError(f"{context} has judge retry status with {role!r} failure_role")
    return str(role)


def _validate_failure_record(
    row: dict[str, Any],
    *,
    output_dir: Path,
    task_id: str,
    trial: int,
    fingerprint: str,
    context: str,
) -> dict[str, str] | None:
    role = _failure_role(row, context=context)
    status = str(row.get("status"))
    has_candidate_dir = row.get("candidate_dir") is not None
    has_candidate_sha256 = row.get("candidate_sha256") is not None
    if has_candidate_dir != has_candidate_sha256:
        raise ValueError(f"{context} has an incomplete candidate binding")
    if role == "policy" and has_candidate_dir:
        raise ValueError(f"{context} binds a candidate to a policy-side failure")
    if status == "judge_retryable":
        candidate_dir = output_dir / "artifacts" / f"task_{task_id}" / f"repeat_{trial}"
        expected = _candidate_binding(
            candidate_dir,
            task_id=task_id,
            trial=trial,
            fingerprint=fingerprint,
        )
        if row.get("candidate_dir") != expected["candidate_dir"]:
            raise ValueError(f"{context} has a missing or relocated candidate directory")
        if row.get("candidate_sha256") != expected["candidate_sha256"]:
            raise ValueError(f"{context} has a missing or changed candidate digest")
        return expected
    return None


def _tree_manifest(root: Path, *, exclude: set[str] | None = None) -> list[dict[str, Any]]:
    ignored = exclude or set()
    files: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Provenance bundle contains a symlink: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative in ignored:
            continue
        files.append({"path": relative, "size": path.stat().st_size, "sha256": sha256_file(path)})
    return files


def _required_source_file(source_run: Path, relative: str) -> Path:
    path = source_run / relative
    if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(source_run):
        raise ValueError(f"Candidate source is missing a safe {relative}: {path}")
    return path


def _candidate_source_lock(source_run: Path) -> Any:
    lock_path = source_run / ".writer.lock"
    if not lock_path.is_file() or lock_path.is_symlink():
        raise ValueError(f"Candidate source has no safe writer lock: {lock_path}")
    lock_file = lock_path.open("r")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except BlockingIOError as error:
        lock_file.close()
        raise RuntimeError(f"Candidate source run is still owned by a writer: {source_run}") from error
    return lock_file


def _load_candidate_source(source_run: Path) -> CandidateSource:
    config_path = _required_source_file(source_run, "config.toml")
    catalog_path = _required_source_file(source_run, "gdpval_benchmark.jsonl")
    catalog_provenance_path = _required_source_file(source_run, "gdpval_benchmark.jsonl.provenance.json")
    implementation_path = _required_source_file(source_run, "implementation.sha256.json")
    metadata_path = _required_source_file(source_run, "run_metadata.json")
    run_plan_path = _required_source_file(source_run, "run_plan.json")
    endpoint_sessions_path = _required_source_file(source_run, "endpoint_sessions.jsonl")

    config = load_config(config_path)
    implementation = json.loads(implementation_path.read_text(encoding="utf-8"))
    if not isinstance(implementation, dict):
        raise ValueError("Candidate source implementation manifest is not an object")
    config_fingerprint = _fingerprint(config, implementation)
    generation_fingerprint = _generation_fingerprint(config, implementation)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    source_deployments = {
        "policy": policy_deployment_identity(config["policy"]),
        "judge": judge_deployment_identity(config["judge"]),
    }
    if metadata.get("schema_version") != RUN_METADATA_SCHEMA_VERSION:
        raise ValueError("Candidate source metadata has an unsupported schema version")
    if metadata.get("config_fingerprint") != config_fingerprint:
        raise ValueError("Candidate source metadata fingerprint does not match its config and implementation")
    if metadata.get("deployments") != source_deployments:
        raise ValueError("Candidate source metadata has mismatched resolved deployment provenance")
    if metadata.get("implementation") != implementation:
        raise ValueError("Candidate source metadata implementation hashes do not match its manifest")
    catalog_rows = _load_catalog(catalog_path, int(config["benchmark"]["expected_tasks"]))
    asset_manifest_shape = bind_manifest_to_catalog(load_asset_manifest(config), catalog_rows)
    catalog_provenance = _validate_catalog_provenance(
        catalog_path,
        config,
        catalog_rows,
        asset_manifest_shape,
    )
    expected_catalog_provenance = catalog_provenance | {"path": str(catalog_provenance_path)}
    if metadata.get("catalog_provenance") != expected_catalog_provenance:
        raise ValueError("Candidate source catalog provenance does not match its metadata")
    if metadata.get("catalog_sha256") != catalog_provenance["catalog_sha256"]:
        raise ValueError("Candidate source catalog digest does not match its metadata")
    if metadata.get("run_plan_sha256") != sha256_file(run_plan_path):
        raise ValueError("Candidate source run-plan digest does not match its metadata")

    catalog = {str(row["task_id"]): row for row in catalog_rows}
    run_plan = json.loads(run_plan_path.read_text(encoding="utf-8"))
    if run_plan.get("config_fingerprint") != config_fingerprint:
        raise ValueError("Candidate source run plan has a mismatched fingerprint")
    if run_plan.get("catalog_sha256") != catalog_provenance["catalog_sha256"]:
        raise ValueError("Candidate source run plan has a mismatched catalog digest")
    if run_plan.get("catalog_provenance_sha256") != catalog_provenance["sha256"]:
        raise ValueError("Candidate source run plan has a mismatched catalog provenance digest")
    planned_keys = {(str(row["task_id"]), int(row["trial"])) for row in run_plan.get("trials", [])}
    if len(planned_keys) != len(run_plan.get("trials", [])):
        raise ValueError("Candidate source run plan contains duplicate task/trial keys")

    endpoint_sessions = _validated_endpoint_sessions(endpoint_sessions_path, config)

    preflight_record = metadata.get("preflight")
    if not isinstance(preflight_record, dict):
        raise ValueError("Candidate source metadata has no preflight record")
    preflight_sha256 = str(preflight_record.get("sha256", ""))
    preflight_path = Path(str(preflight_record.get("path", ""))).expanduser().resolve()
    expected_preflight_path = source_run / "preflights" / f"{preflight_sha256}.json"
    if not preflight_path.is_file() or preflight_path != expected_preflight_path:
        raise ValueError("Candidate source preflight is missing or outside the source run")
    if sha256_file(preflight_path) != preflight_sha256:
        raise ValueError("Candidate source preflight digest does not match its metadata")
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    _validate_generation_preflight_payload(preflight, config, config_fingerprint)

    for relative, expected_sha256 in _generation_implementation_hashes(implementation).items():
        path = _required_source_file(source_run, f"implementation/{relative}")
        if sha256_file(path) != expected_sha256:
            raise ValueError(f"Candidate source generation implementation mismatch: {relative}")

    return CandidateSource(
        run_dir=source_run,
        config=config,
        config_fingerprint=config_fingerprint,
        generation_fingerprint=generation_fingerprint,
        catalog=catalog,
        catalog_provenance_path=catalog_provenance_path,
        catalog_provenance=catalog_provenance,
        planned_keys=planned_keys,
        implementation=implementation,
        metadata=metadata,
        endpoint_sessions=endpoint_sessions,
        preflight_path=preflight_path,
        preflight=preflight,
    )


def _candidate_source_record(source: CandidateSource, missing_candidate_policy: str) -> dict[str, Any]:
    return {
        "source_run": str(source.run_dir),
        "source_config_fingerprint": source.config_fingerprint,
        "source_generation_fingerprint": source.generation_fingerprint,
        "source_catalog_provenance_sha256": source.catalog_provenance["sha256"],
        "missing_candidate_policy": missing_candidate_policy,
    }


def _inspect_candidate_source(
    source_run: Path,
    trials: list[Trial],
    config: dict[str, Any],
    missing_candidate_policy: str,
) -> tuple[dict[str, Any], list[tuple[str, int]]]:
    lock_file = _candidate_source_lock(source_run)
    try:
        source = _load_candidate_source(source_run)
        current_generation_fingerprint = _generation_fingerprint(config, _source_hashes())
        if source.generation_fingerprint != current_generation_fingerprint:
            raise ValueError(
                "Candidate source generation fingerprint differs from the current generation configuration or code"
            )
        missing: list[tuple[str, int]] = []
        for trial in trials:
            if source.catalog.get(trial.task_id) != trial.task:
                raise ValueError(f"Candidate source catalog row differs for task {trial.task_id}")
            candidate_dir = source_run / "artifacts" / f"task_{trial.task_id}" / f"repeat_{trial.trial}"
            if not (candidate_dir / "candidate.json").is_file():
                missing.append(trial.key)
                continue
            _validate_source_candidate(source, trial)
        if missing and missing_candidate_policy == "error":
            sample = ", ".join(f"{task_id}:{trial}" for task_id, trial in missing[:10])
            raise ValueError(
                f"Candidate source is missing {len(missing)} planned candidate(s): {sample}. "
                "Use --missing-candidate-policy generate only to generate genuinely absent candidates."
            )
        return _candidate_source_record(source, missing_candidate_policy), missing
    finally:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()


def _validate_source_candidate(source: CandidateSource, trial: Trial) -> tuple[dict[str, Any], str, Path]:
    if trial.key not in source.planned_keys:
        raise ValueError(f"Candidate source run did not plan task/trial {trial.key}")
    source_task = source.catalog.get(trial.task_id)
    if source_task != trial.task:
        raise ValueError(f"Candidate source catalog row differs for task {trial.task_id}")
    candidate_dir = source.run_dir / "artifacts" / f"task_{trial.task_id}" / f"repeat_{trial.trial}"
    manifest, manifest_sha256 = _candidate_manifest(candidate_dir)
    if manifest.get("candidate_import") is not None:
        raise ValueError(f"Nested candidate imports are not supported: {candidate_dir}")
    if (
        manifest.get("task_id") != trial.task_id
        or int(manifest.get("trial", -1)) != trial.trial
        or manifest.get("config_fingerprint") != source.config_fingerprint
    ):
        raise ValueError(f"Candidate source identity mismatch: {candidate_dir}")
    session_id = manifest.get("policy_endpoint_session_id")
    session = source.endpoint_sessions.get(str(session_id))
    source_policy_deployment = policy_deployment_identity(source.config["policy"])
    if (
        not isinstance(session, dict)
        or session.get("policy_required") is not True
        or session.get("policy_deployment_id") != source_policy_deployment["deployment_id"]
        or session.get("policy_slurm_job_id") != source_policy_deployment["slurm_job_id"]
        or session.get("policy", {}).get("model") != source.config["policy"]["model"]
        or any(session.get("policy", {}).get(key) != value for key, value in source_policy_deployment.items())
        or session.get("policy", {}).get("server", {}).get("version") != source.config["policy"]["server_version"]
    ):
        raise ValueError(f"Candidate source policy endpoint session is invalid: {candidate_dir}")
    return manifest, manifest_sha256, candidate_dir


def _copy_candidate_source_bundle(
    source: CandidateSource,
    trials: list[Trial],
    output_dir: Path,
) -> tuple[Path, str]:
    sources_root = output_dir / "candidate_imports" / "sources"
    sources_root.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = Path(tempfile.mkdtemp(prefix=".source-", dir=sources_root))
    try:
        files_to_copy = {
            "config.toml": source.run_dir / "config.toml",
            "endpoint_sessions.jsonl": source.run_dir / "endpoint_sessions.jsonl",
            "gdpval_benchmark.jsonl": source.run_dir / "gdpval_benchmark.jsonl",
            "gdpval_benchmark.jsonl.provenance.json": source.catalog_provenance_path,
            "implementation.sha256.json": source.run_dir / "implementation.sha256.json",
            "run_metadata.json": source.run_dir / "run_metadata.json",
            "run_plan.json": source.run_dir / "run_plan.json",
            "preflight.json": source.preflight_path,
        }
        for relative in _generation_implementation_hashes(source.implementation):
            files_to_copy[f"implementation/{relative}"] = source.run_dir / "implementation" / relative
        for relative, source_path in sorted(files_to_copy.items()):
            if not source_path.is_file() or source_path.is_symlink():
                raise ValueError(f"Candidate source provenance file is missing or unsafe: {source_path}")
            destination = temporary / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination)
        candidate_index: list[dict[str, Any]] = []
        missing_candidates: list[dict[str, Any]] = []
        for trial in trials:
            candidate_path = source.run_dir / "artifacts" / f"task_{trial.task_id}" / f"repeat_{trial.trial}"
            if not (candidate_path / "candidate.json").is_file():
                missing_candidates.append({"task_id": trial.task_id, "trial": trial.trial})
                continue
            candidate, candidate_manifest_sha256, _ = _validate_source_candidate(source, trial)
            candidate_index.append(
                {
                    "task_id": trial.task_id,
                    "trial": trial.trial,
                    "candidate_sha256": candidate["candidate_sha256"],
                    "candidate_manifest_sha256": candidate_manifest_sha256,
                    "task_record_sha256": _sha256_json(trial.task),
                }
            )
        manifest = {
            "schema_version": CANDIDATE_IMPORT_SCHEMA_VERSION,
            "source_run": str(source.run_dir),
            "source_config_fingerprint": source.config_fingerprint,
            "source_generation_fingerprint": source.generation_fingerprint,
            "source_preflight_sha256": sha256_file(source.preflight_path),
            "source_catalog_provenance_sha256": source.catalog_provenance["sha256"],
            "candidate_index": candidate_index,
            "missing_candidates": missing_candidates,
            "files": _tree_manifest(temporary),
        }
        atomic_write_json(temporary / "manifest.json", manifest)
        manifest_sha256 = sha256_file(temporary / "manifest.json")
        destination = sources_root / manifest_sha256
        if destination.exists():
            existing_manifest = destination / "manifest.json"
            if (
                not existing_manifest.is_file()
                or sha256_file(existing_manifest) != manifest_sha256
                or json.loads(existing_manifest.read_text(encoding="utf-8")) != manifest
                or _tree_manifest(destination, exclude={"manifest.json"}) != manifest["files"]
            ):
                raise ValueError(f"Conflicting candidate source bundle: {destination}")
        else:
            os.replace(temporary, destination)
            temporary = None
        return destination / "manifest.json", manifest_sha256
    finally:
        if temporary is not None and temporary.exists():
            shutil.rmtree(temporary)


def _import_candidate(
    *,
    source: CandidateSource,
    trial: Trial,
    output_dir: Path,
    fingerprint: str,
    source_bundle_manifest: Path,
    source_bundle_manifest_sha256: str,
) -> dict[str, Any]:
    source_manifest, source_manifest_sha256, source_candidate_dir = _validate_source_candidate(source, trial)
    receipt_dir = output_dir / "candidate_imports" / "candidates" / f"task_{trial.task_id}" / f"repeat_{trial.trial}"
    receipt_path = receipt_dir / "receipt.json"
    original_manifest_path = receipt_dir / "source_candidate.json"
    receipt = {
        "schema_version": CANDIDATE_IMPORT_SCHEMA_VERSION,
        "task_id": trial.task_id,
        "trial": trial.trial,
        "source_run": str(source.run_dir),
        "source_candidate_relative_path": source_candidate_dir.relative_to(source.run_dir).as_posix(),
        "source_candidate_manifest": original_manifest_path.relative_to(output_dir).as_posix(),
        "source_candidate_manifest_sha256": source_manifest_sha256,
        "source_candidate_sha256": source_manifest["candidate_sha256"],
        "source_config_fingerprint": source.config_fingerprint,
        "source_generation_fingerprint": source.generation_fingerprint,
        "source_policy_endpoint_session_id": source_manifest["policy_endpoint_session_id"],
        "source_bundle_manifest": source_bundle_manifest.relative_to(output_dir).as_posix(),
        "source_bundle_manifest_sha256": source_bundle_manifest_sha256,
        "task_record_sha256": _sha256_json(trial.task),
        "scorer_fingerprint": fingerprint,
        "files": source_manifest["files"],
    }
    if receipt_dir.exists():
        if receipt_dir.is_symlink() or _tree_manifest(receipt_dir) != [
            {
                "path": "receipt.json",
                "size": receipt_path.stat().st_size,
                "sha256": sha256_file(receipt_path),
            },
            {
                "path": "source_candidate.json",
                "size": original_manifest_path.stat().st_size,
                "sha256": sha256_file(original_manifest_path),
            },
        ]:
            raise ValueError(f"Candidate import receipt directory is unsafe: {receipt_dir}")
        if json.loads(receipt_path.read_text(encoding="utf-8")) != receipt:
            raise ValueError(f"Candidate import receipt differs from the requested source: {receipt_path}")
        if sha256_file(original_manifest_path) != source_manifest_sha256:
            raise ValueError(f"Candidate import source manifest differs from its receipt: {original_manifest_path}")
    else:
        receipt_dir.parent.mkdir(parents=True, exist_ok=True)
        temporary_receipt: Path | None = Path(tempfile.mkdtemp(prefix=f".{receipt_dir.name}-", dir=receipt_dir.parent))
        try:
            shutil.copy2(source_candidate_dir / "candidate.json", temporary_receipt / "source_candidate.json")
            atomic_write_json(temporary_receipt / "receipt.json", receipt)
            os.replace(temporary_receipt, receipt_dir)
            temporary_receipt = None
        finally:
            if temporary_receipt is not None and temporary_receipt.exists():
                shutil.rmtree(temporary_receipt)
    receipt_sha256 = sha256_file(receipt_path)
    import_metadata = {
        "schema_version": CANDIDATE_IMPORT_SCHEMA_VERSION,
        "receipt": receipt_path.relative_to(output_dir).as_posix(),
        "receipt_sha256": receipt_sha256,
        "source_candidate_manifest_sha256": source_manifest_sha256,
        "source_config_fingerprint": source.config_fingerprint,
        "source_generation_fingerprint": source.generation_fingerprint,
        "scorer_fingerprint": fingerprint,
    }
    target_manifest = source_manifest | {
        "config_fingerprint": fingerprint,
        "candidate_import": import_metadata,
    }
    target_candidate_dir = output_dir / "artifacts" / f"task_{trial.task_id}" / f"repeat_{trial.trial}"
    if target_candidate_dir.exists():
        existing_manifest, _ = _candidate_manifest(target_candidate_dir)
        if existing_manifest != target_manifest:
            raise ValueError(f"Existing target candidate conflicts with imported candidate: {target_candidate_dir}")
    else:
        target_candidate_dir.parent.mkdir(parents=True, exist_ok=True)
        temporary_root = Path(
            tempfile.mkdtemp(prefix=f".{target_candidate_dir.name}-", dir=target_candidate_dir.parent)
        )
        temporary_candidate = temporary_root / "candidate"
        try:
            shutil.copytree(source_candidate_dir, temporary_candidate)
            atomic_write_json(temporary_candidate / "candidate.json", target_manifest)
            copied_manifest, _ = _candidate_manifest(temporary_candidate)
            if copied_manifest != target_manifest:
                raise ValueError(f"Imported candidate verification failed: {temporary_candidate}")
            os.replace(temporary_candidate, target_candidate_dir)
        finally:
            if temporary_root.exists():
                shutil.rmtree(temporary_root)
    return {
        "task_id": trial.task_id,
        "trial": trial.trial,
        "candidate_sha256": source_manifest["candidate_sha256"],
        "receipt": str(receipt_path),
        "receipt_sha256": receipt_sha256,
    }


def _materialize_candidate_imports(
    *,
    source_run: Path,
    expected_source_record: dict[str, Any],
    trials: list[Trial],
    config: dict[str, Any],
    fingerprint: str,
    output_dir: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[tuple[str, int]]]:
    lock_file = _candidate_source_lock(source_run)
    try:
        source = _load_candidate_source(source_run)
        source_record = _candidate_source_record(
            source,
            str(expected_source_record["missing_candidate_policy"]),
        )
        if source_record != expected_source_record:
            raise ValueError("Candidate source changed between run planning and import")
        current_generation_fingerprint = _generation_fingerprint(config, _source_hashes())
        if source.generation_fingerprint != current_generation_fingerprint:
            raise ValueError(
                "Candidate source generation fingerprint differs from the current generation configuration or code"
            )
        source_bundle_manifest, source_bundle_manifest_sha256 = _copy_candidate_source_bundle(
            source,
            trials,
            output_dir,
        )
        imported: list[dict[str, Any]] = []
        missing: list[tuple[str, int]] = []
        for trial in trials:
            target_candidate = output_dir / "artifacts" / f"task_{trial.task_id}" / f"repeat_{trial.trial}"
            source_candidate = source_run / "artifacts" / f"task_{trial.task_id}" / f"repeat_{trial.trial}"
            if not (source_candidate / "candidate.json").is_file():
                missing.append(trial.key)
                if target_candidate.exists() and not (target_candidate / "candidate.json").is_file():
                    raise ValueError(f"Target candidate directory is incomplete: {target_candidate}")
                if (target_candidate / "candidate.json").is_file():
                    target_manifest, _ = _candidate_manifest(target_candidate)
                    if (
                        target_manifest.get("task_id") != trial.task_id
                        or int(target_manifest.get("trial", -1)) != trial.trial
                        or target_manifest.get("config_fingerprint") != fingerprint
                        or target_manifest.get("candidate_import") is not None
                    ):
                        raise ValueError(f"Generated target candidate identity mismatch: {target_candidate}")
                continue
            imported.append(
                _import_candidate(
                    source=source,
                    trial=trial,
                    output_dir=output_dir,
                    fingerprint=fingerprint,
                    source_bundle_manifest=source_bundle_manifest,
                    source_bundle_manifest_sha256=source_bundle_manifest_sha256,
                )
            )
        if missing and expected_source_record["missing_candidate_policy"] == "error":
            raise AssertionError("Candidate-source completeness changed while holding its writer lock")
        source_record = source_record | {
            "source_bundle_manifest": source_bundle_manifest.relative_to(output_dir).as_posix(),
            "source_bundle_manifest_sha256": source_bundle_manifest_sha256,
            "target_generation_fingerprint": current_generation_fingerprint,
        }
        return source_record, imported, missing
    finally:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()


def _assigned_reference(config: dict[str, Any], task_id: str) -> dict[str, Any] | None:
    references = config.get("references") or []
    if not references:
        return None
    ordered = sorted(references, key=lambda item: str(item["id"]))
    seed_material = f"{config['benchmark']['dispatch_seed']}|{task_id}".encode()
    index = int(hashlib.sha256(seed_material).hexdigest()[:16], 16) % len(ordered)
    return ordered[index]


def _filter_reference_eligible(
    catalog: list[dict[str, Any]], config: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    if config["scoring"]["mode"] != "comparison":
        return catalog, []
    eligible: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    for task in catalog:
        task_id = str(task["task_id"])
        reference = _assigned_reference(config, task_id)
        reasons: list[str] = []
        if reference and reference.get("source") == "dataset_deliverables" and not task.get("deliverable_files"):
            reasons.append("pinned public dataset has no human-expert deliverable")
        files = list(task.get("reference_files") or [])
        if reference and reference.get("source") == "dataset_deliverables":
            files.extend(task.get("deliverable_files") or [])
        unsupported = sorted(
            {
                Path(str(path)).suffix.lower()
                for path in files
                if Path(str(path)).suffix.lower() in UNSUPPORTED_KIMI_ARTIFACTS
            }
        )
        if config["scoring"].get("exclude_unsupported_artifacts", False) and unsupported:
            reasons.append("Kimi K2.6 overlay cannot inspect artifact type(s): " + ", ".join(unsupported))
        if (
            reference
            and reference.get("source") == "dataset_deliverables"
            and (nested := PINNED_NESTED_UNSUPPORTED.get(task_id))
        ):
            reasons.append("Kimi K2.6 overlay cannot inspect nested artifact type(s): " + nested)
        if (
            reference
            and reference.get("source") == "dataset_deliverables"
            and (invalid := PINNED_INVALID_REFERENCE_ARTIFACTS.get(task_id))
        ):
            reasons.append("pinned public expert deliverable is invalid: " + invalid)
        if reasons:
            excluded.append(
                {
                    "task_id": task_id,
                    "reason": "; ".join(reasons),
                }
            )
            continue
        eligible.append(task)
    return eligible, excluded


def _required_asset_entries(
    manifest: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    required: list[tuple[str, str]] = []
    for task in tasks:
        task_id = str(task["task_id"])
        required.extend((task_id, str(path)) for path in task.get("reference_files") or [])
        reference = _assigned_reference(config, task_id)
        if reference and reference.get("source") == "dataset_deliverables":
            required.extend((task_id, str(path)) for path in task.get("deliverable_files") or [])
    return select_manifest_entries(manifest, required)


def _completed_keys(results_path: Path, fingerprint: str) -> set[tuple[str, int]]:
    completed: set[tuple[str, int]] = set()
    for row in load_jsonl(results_path):
        if row.get("config_fingerprint") != fingerprint:
            raise ValueError("Existing result has a different config fingerprint")
        if row.get("status") not in SCORED_STATUSES:
            raise ValueError(f"Unexpected status in results: {row.get('status')!r}")
        key = str(row["task_id"]), int(row["trial"])
        if key in completed:
            raise ValueError(f"Duplicate scored result: {key}")
        completed.add(key)
    return completed


def _validate_preexisting_judge_retry_bindings(
    output_dir: Path,
    fingerprint: str,
    planned_keys: set[tuple[str, int]],
) -> None:
    records = [("attempt", row) for row in load_jsonl(output_dir / "attempts.jsonl")]
    worker_results_dir = output_dir / "worker_results"
    if worker_results_dir.is_dir():
        records.extend(
            (f"worker result {path.name}", json.loads(path.read_text(encoding="utf-8")))
            for path in sorted(worker_results_dir.glob("*.json"))
        )
    for source, row in records:
        if row.get("schema_version") != 1:
            raise ValueError(f"{source} has an unsupported schema version")
        if row.get("status") != "judge_retryable":
            continue
        if row.get("config_fingerprint") != fingerprint:
            raise ValueError(f"{source} has a mismatched config fingerprint")
        key = str(row.get("task_id")), int(row.get("trial", -1))
        if key not in planned_keys:
            raise ValueError(f"{source} is outside the run plan: {key}")
        _validate_failure_record(
            row,
            output_dir=output_dir,
            task_id=key[0],
            trial=key[1],
            fingerprint=fingerprint,
            context=f"Preexisting {source} {key}:{row.get('attempt')}",
        )


def _recover_terminal_attempts(output_dir: Path, fingerprint: str) -> int:
    results_path = output_dir / "results.jsonl"
    attempts_path = output_dir / "attempts.jsonl"
    completed = {(str(row["task_id"]), int(row["trial"])) for row in load_jsonl(results_path)}
    last_attempt: dict[tuple[str, int], dict[str, Any]] = {}
    for row in load_jsonl(attempts_path):
        if row.get("schema_version") != 1:
            raise ValueError("Attempt has an unsupported schema version during terminal recovery")
        last_attempt[(str(row["task_id"]), int(row["trial"]))] = row
    recovered = 0
    for key, row in last_attempt.items():
        if key in completed or row.get("status") not in SCORED_STATUSES:
            continue
        result_path = Path(str(row.get("worker_result", "")))
        if not result_path.is_file():
            raise ValueError(f"Terminal attempt for {key} has no recoverable worker result: {result_path}")
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        if (
            payload.get("schema_version") != 1
            or payload.get("config_fingerprint") != fingerprint
            or (str(payload.get("task_id")), int(payload.get("trial", -1))) != key
            or payload.get("status") not in SCORED_STATUSES
        ):
            raise ValueError(f"Invalid recoverable worker result for {key}: {result_path}")
        append_jsonl(results_path, payload | {"result_recovery": {"source": "worker_result"}})
        completed.add(key)
        recovered += 1
    return recovered


def _reconcile_orphan_worker_results(
    output_dir: Path,
    fingerprint: str,
    planned_keys: set[tuple[str, int]],
) -> int:
    results_path = output_dir / "results.jsonl"
    attempts_path = output_dir / "attempts.jsonl"
    attempts_by_key: dict[tuple[str, int], dict[int, dict[str, Any]]] = {}
    for row in load_jsonl(attempts_path):
        if row.get("schema_version") != 1:
            raise ValueError("Attempt has an unsupported schema version during orphan reconciliation")
        if row.get("config_fingerprint") != fingerprint:
            raise ValueError("Attempt/config fingerprint mismatch during orphan reconciliation")
        key = str(row["task_id"]), int(row["trial"])
        if key not in planned_keys:
            raise ValueError(f"Attempt is outside the run plan during orphan reconciliation: {key}")
        _validate_failure_record(
            row,
            output_dir=output_dir,
            task_id=key[0],
            trial=key[1],
            fingerprint=fingerprint,
            context=f"Attempt {key}:{row['attempt']}",
        )
        attempt = int(row["attempt"])
        if attempt in attempts_by_key.setdefault(key, {}):
            raise ValueError(f"Duplicate recorded attempt {attempt} for {key}")
        attempts_by_key[key][attempt] = row
    completed = {(str(row["task_id"]), int(row["trial"])) for row in load_jsonl(results_path)}

    recovered = 0
    worker_results = output_dir / "worker_results"
    if not worker_results.is_dir():
        return recovered
    for result_path in sorted(worker_results.glob("*.json")):
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != 1:
            raise ValueError(f"Worker result has an unsupported schema version: {result_path}")
        if payload.get("config_fingerprint") != fingerprint:
            raise ValueError(f"Worker-result fingerprint mismatch: {result_path}")
        key = str(payload.get("task_id")), int(payload.get("trial", -1))
        if key not in planned_keys:
            raise ValueError(f"Worker result is outside the run plan: {result_path}")
        attempt = int(payload.get("attempt", -1))
        if attempt < 1:
            raise ValueError(f"Worker result has an invalid attempt number: {result_path}")
        status = str(payload.get("status"))
        if status not in SCORED_STATUSES | RETRYABLE_STATUSES | {"fatal_error"}:
            raise ValueError(f"Unknown orphan worker-result status {status!r}: {result_path}")
        _validate_failure_record(
            payload,
            output_dir=output_dir,
            task_id=key[0],
            trial=key[1],
            fingerprint=fingerprint,
            context=f"Orphan worker result {key}:{attempt}",
        )
        recorded = attempts_by_key.setdefault(key, {})
        if attempt in recorded:
            recorded_path = Path(str(recorded[attempt].get("worker_result", "")))
            if recorded_path.resolve() != result_path.resolve():
                raise ValueError(f"Recorded worker-result path mismatch for {key} attempt {attempt}")
            for field in (
                "status",
                "failure_role",
                "endpoint_session_id",
                "candidate_dir",
                "candidate_sha256",
            ):
                if recorded[attempt].get(field) != payload.get(field):
                    raise ValueError(f"Recorded worker-result {field} mismatch for {key} attempt {attempt}")
            continue
        expected_attempt = max(recorded, default=0) + 1
        if attempt != expected_attempt:
            raise ValueError(
                f"Cannot reconcile non-contiguous worker result for {key}: expected attempt "
                f"{expected_attempt}, found {attempt}"
            )

        if any(row.get("status") == "judge_retryable" for row in recorded.values()) and (
            status in {"retryable_error", "model_error", "model_timeout"}
            or (status == "fatal_error" and payload.get("failure_role") != "judge")
        ):
            raise ValueError(f"Orphan worker result regressed from judge-only recovery for {key}: {status}")
        log_path = output_dir / "worker_logs" / f"{result_path.stem}.log"
        if not log_path.is_file():
            raise ValueError(f"Orphan worker result has no immutable worker log: {result_path}")
        attempt_row = {
            "schema_version": 1,
            "worker": None,
            "attempt": attempt,
            "task_id": key[0],
            "trial": key[1],
            "config_fingerprint": fingerprint,
            "endpoint_session_id": payload.get("endpoint_session_id"),
            "status": status,
            "failure_role": payload.get("failure_role"),
            "error": payload.get("error"),
            "candidate_dir": payload.get("candidate_dir"),
            "candidate_sha256": payload.get("candidate_sha256"),
            "worker_return_code": None,
            "worker_log": str(log_path),
            "worker_result": str(result_path),
            "worker_log_sha256": sha256_file(log_path),
            "attempt_recovery": {"source": "orphan_worker_result"},
            "time": time.time(),
        }
        append_jsonl(attempts_path, attempt_row)
        recorded[attempt] = attempt_row
        recovered += 1
        if status in SCORED_STATUSES and key not in completed:
            append_jsonl(results_path, payload | {"result_recovery": {"source": "orphan_worker_result"}})
            completed.add(key)
        if status == "fatal_error":
            raise ValueError(f"Recovered fatal worker result for {key}: {payload.get('error')}")
    return recovered


def _attempt_histories(
    attempts_path: Path,
    completed: set[tuple[str, int]],
    *,
    output_dir: Path,
    fingerprint: str,
) -> dict[tuple[str, int], list[dict[str, Any]]]:
    histories: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in load_jsonl(attempts_path):
        if row.get("schema_version") != 1:
            raise ValueError("Attempt has an unsupported schema version")
        if row.get("config_fingerprint") != fingerprint:
            raise ValueError("Attempt/config fingerprint mismatch")
        task_id, trial = str(row["task_id"]), int(row["trial"])
        key = task_id, trial
        _validate_failure_record(
            row,
            output_dir=output_dir,
            task_id=task_id,
            trial=trial,
            fingerprint=fingerprint,
            context=f"Attempt {key}:{row['attempt']}",
        )
        if key in completed:
            continue
        histories.setdefault(key, []).append(row)
    for key, rows in histories.items():
        numbers = [int(row["attempt"]) for row in rows]
        if numbers != list(range(1, len(rows) + 1)):
            raise ValueError(f"Cannot resume non-contiguous attempts for {key}: {numbers}")
        statuses = [str(row.get("status")) for row in rows]
        if any(status not in RETRYABLE_STATUSES for status in statuses):
            raise ValueError(f"Cannot resume unsafe unfinished attempts for {key}: {statuses}")
        if "judge_retryable" in statuses:
            first_judge_retry = statuses.index("judge_retryable")
            if any(status == "retryable_error" for status in statuses[first_judge_retry + 1 :]):
                raise ValueError(f"Cannot resume a retry chain that regressed to policy execution for {key}")
    return histories


def _read_worker_result(
    result_path: Path,
    log_path: Path,
    trial: Trial,
    *,
    attempt: int,
    endpoint_session_id: str,
) -> dict[str, Any]:
    if result_path.is_file():
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    else:
        payload = None
        if log_path.is_file():
            for line in reversed(log_path.read_text(encoding="utf-8", errors="replace").splitlines()):
                try:
                    candidate = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (
                    isinstance(candidate, dict)
                    and candidate.get("task_id") == trial.task_id
                    and int(candidate.get("trial", -1)) == trial.trial
                    and "status" in candidate
                ):
                    payload = candidate | {"result_recovery": {"source": "worker_stdout"}}
                    break
        if payload is None:
            raise MissingWorkerResult(f"Worker produced no durable terminal result; inspect {log_path}")
    if (
        payload.get("schema_version") != 1
        or payload.get("task_id") != trial.task_id
        or int(payload.get("trial", -1)) != trial.trial
        or int(payload.get("attempt", -1)) != attempt
        or payload.get("endpoint_session_id") != endpoint_session_id
    ):
        raise ValueError(f"Worker result identity mismatch for {trial.key}")
    return payload


def _worker_command(
    *,
    config_path: Path,
    catalog_path: Path,
    trial: Trial,
    attempt: int,
    fingerprint: str,
    endpoint_session_id: str,
    output_dir: Path,
    expected_candidate_sha256: str | None,
    policy_base_url: str | None,
    judge_base_url: str | None,
) -> tuple[list[str], Path, Path]:
    stem = f"{trial.task_id}.trial_{trial.trial}.attempt_{attempt}"
    result_path = output_dir / "worker_results" / f"{stem}.json"
    log_path = output_dir / "worker_logs" / f"{stem}.log"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(output_dir / "implementation" / "user" / "tianhaowu" / "gdpval_vmvm" / "worker.py"),
        str(config_path),
        "--catalog",
        str(catalog_path),
        "--task-id",
        trial.task_id,
        "--trial",
        str(trial.trial),
        "--attempt",
        str(attempt),
        "--fingerprint",
        fingerprint,
        "--endpoint-session-id",
        endpoint_session_id,
        "--candidate-dir",
        str(output_dir / "artifacts" / f"task_{trial.task_id}" / f"repeat_{trial.trial}"),
        "--judge-journal",
        str(output_dir / "judgements" / f"task_{trial.task_id}" / f"repeat_{trial.trial}.jsonl"),
        "--result",
        str(result_path),
    ]
    if expected_candidate_sha256:
        command.extend(["--expected-candidate-sha256", expected_candidate_sha256])
    if policy_base_url:
        command.extend(["--policy-base-url", policy_base_url])
    if judge_base_url:
        command.extend(["--judge-base-url", judge_base_url])
    return command, result_path, log_path


def _run_worker(command: list[str], log_path: Path) -> int:
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n=== worker invocation {time.time()} ===\n")
        log.flush()
        process = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, text=True)
    return process.returncode


def _summary(results_path: Path, expected: int, config: dict[str, Any]) -> dict[str, Any]:
    rows = load_jsonl(results_path)
    completed = [row for row in rows if row.get("status") == "completed"]
    rewards = [float(row["reward"]) for row in rows]
    summary: dict[str, Any] = {
        "expected": expected,
        "scored": len(rows),
        "completed": len(completed),
        "model_errors": sum(row.get("status") == "model_error" for row in rows),
        "model_timeouts": sum(row.get("status") == "model_timeout" for row in rows),
        "mean_reward": sum(rewards) / len(rewards) if rewards else None,
        "official_reference": config["official_reference"],
        "official_parity_claim": False,
    }
    if config["scoring"]["mode"] == "comparison":
        pooled: dict[str, dict[str, float]] = {}
        task_battles: list[tuple[str, float, float, float, float]] = []
        for row in completed:
            score = row["score"]
            ref_id = str(score["reference_id"])
            counts = pooled.setdefault(
                ref_id,
                {"reference_elo": float(score["reference_elo"]), "wins": 0, "losses": 0, "ties": 0},
            )
            counts["wins"] += int(score["wins"])
            counts["losses"] += int(score["losses"])
            counts["ties"] += int(score["ties"])
            task_battles.append(
                (
                    str(row["task_id"]),
                    float(score["reference_elo"]),
                    float(score["wins"]),
                    float(score["losses"]),
                    float(score["ties"]),
                )
            )
        fit = calculate_mle_elo_report(task_battles)
        elo_ready = len(rows) == expected and len(completed) == expected
        elo_finite = bool(fit and fit.get("elo") is not None)
        summary["elo_ready"] = elo_ready
        summary["elo_finite"] = elo_finite
        if not elo_ready:
            summary["elo_withheld_reason"] = (
                "Headline Elo requires a completed comparison for every planned task; model failures and "
                "partial rows are not silently dropped."
            )
        elif not elo_finite:
            summary["elo_withheld_reason"] = "The Bradley-Terry fit is completely separated; no finite Elo exists."
        else:
            summary["elo_withheld_reason"] = None
        summary["battle_totals"] = pooled
        summary["completed_comparisons_only_provisional_elo"] = fit
        summary["eval_elo"] = fit["elo"] if fit and elo_ready and elo_finite else None
        summary["normalized_elo"] = fit["normalized_elo"] if fit and elo_ready else None
        summary["normalized_score"] = fit["normalized_score"] if fit and elo_ready else None
        summary["confidence_interval_95"] = fit["confidence_interval_95"] if fit and elo_ready and elo_finite else None
    return summary


def _validate_preflight_payload(payload: dict[str, Any], config: dict[str, Any], fingerprint: str) -> None:
    if not isinstance(payload, dict):
        raise ValueError("Preflight artifact must be an object")
    policy_deployment = policy_deployment_identity(config["policy"])
    judge_deployment = judge_deployment_identity(config["judge"])
    if payload.get("schema_version") != PREFLIGHT_SCHEMA_VERSION:
        raise ValueError("Preflight artifact has an unsupported schema version")
    if payload.get("ok") is not True or "sandbox" not in payload:
        raise ValueError("Preflight artifact does not contain a successful sandbox probe")
    sandbox = payload["sandbox"]
    if (
        not isinstance(sandbox, dict)
        or not sandbox.get("staged_assets")
        or not sandbox.get("render_history")
        or not any(str(path).lower().endswith(".pdf") for path in sandbox.get("rendered_files", []))
        or not isinstance(sandbox.get("vmvm"), dict)
    ):
        raise ValueError("Preflight artifact does not contain complete sandbox and Office-render evidence")
    _validate_sandbox_tool_contract(sandbox, config, context="Preflight artifact")
    asset_mirror = sandbox.get("asset_mirror")
    expected_mirror = {
        "repository": config["source"]["asset_mirror_repository"],
        "commit": config["source"]["asset_mirror_commit"],
        "tasks_tree": config["source"]["asset_mirror_tasks_tree"],
        "manifest_file": config["source"]["asset_manifest_file"],
        "manifest_sha256": config["source"]["asset_manifest_sha256"],
    }
    if not isinstance(asset_mirror, dict) or any(
        asset_mirror.get(key) != value for key, value in expected_mirror.items()
    ):
        raise ValueError("Preflight artifact has mismatched GDPval asset-mirror provenance")
    if (
        Path(str(asset_mirror.get("cache_dir", ""))).expanduser().resolve()
        != Path(config["source"]["asset_cache_dir"]).expanduser().resolve()
    ):
        raise ValueError("Preflight artifact has a mismatched GDPval asset-cache path")
    if (
        asset_mirror.get("ready") is not True
        or asset_mirror.get("hashes_verified") is not True
        or int(asset_mirror.get("cached_assets", -1)) != int(asset_mirror.get("selected_assets", -2))
        or int(asset_mirror.get("selected_assets", -1)) != len(sandbox["staged_assets"])
        or int(asset_mirror.get("missing_assets", -1)) != 0
        or int(asset_mirror.get("corrupt_assets", -1)) != 0
    ):
        raise ValueError("Preflight artifact does not prove a complete verified host asset cache")
    if payload.get("config_fingerprint") != fingerprint:
        raise ValueError("Preflight artifact was produced for a different configuration or implementation")
    if payload.get("policy_deployment_id") != policy_deployment["deployment_id"]:
        raise ValueError("Preflight policy deployment identity does not match the configured deployment")
    if payload.get("policy_slurm_job_id") != policy_deployment["slurm_job_id"]:
        raise ValueError("Preflight policy Slurm job does not match the configured deployment")
    if payload.get("judge_deployment_id") != judge_deployment["deployment_id"]:
        raise ValueError("Preflight judge deployment identity does not match the configured deployment")
    if payload.get("judge_proxy_jobid") != judge_deployment["proxy_jobid"]:
        raise ValueError("Preflight judge proxy job does not match the configured deployment")
    if payload.get("sandbox_image") != config["runtime"]["image"]:
        raise ValueError("Preflight sandbox image does not match the configured image")
    for role in ("policy", "judge"):
        probe = payload.get(role)
        if not isinstance(probe, dict) or probe.get("model") != config[role]["model"]:
            raise ValueError(f"Preflight {role} probe does not match the configured model")
        expected_deployment = policy_deployment if role == "policy" else judge_deployment
        _validate_probe_deployment(probe, expected_deployment, role)
        if probe.get("chat", {}).get("matched_expected_answer") is not True:
            raise ValueError(f"Preflight artifact does not contain a successful {role} text probe")
    if payload["policy"].get("tool_call", {}).get("arguments_valid") is not True:
        raise ValueError("Preflight artifact does not contain a successful policy tool-call probe")
    if payload["judge"].get("visual_chat", {}).get("matched_expected_answer") is not True:
        raise ValueError("Preflight artifact does not contain a successful judge visual probe")
    policy_metadata = payload.get("policy", {}).get("advertised_model_metadata", [])
    if not any(
        item.get("id") == config["policy"]["model"]
        and int(item.get("max_model_len", -1)) == int(config["policy"]["context_window"])
        for item in policy_metadata
        if isinstance(item, dict)
    ):
        raise ValueError("Preflight policy model metadata does not confirm the configured context window")
    if payload.get("policy", {}).get("server", {}).get("version") != config["policy"]["server_version"]:
        raise ValueError("Preflight policy server version does not match the configured version")
    web_fetch = payload.get("web_fetch")
    if (
        not isinstance(web_fetch, dict)
        or web_fetch.get("tool") != "fetch_web_page"
        or web_fetch.get("url") != WEB_FETCH_PROBE_URL
        or web_fetch.get("trust_env") is not config["tools"]["web_fetch_trust_env"]
        or web_fetch.get("success") is not True
        or web_fetch.get("matched_expected_content") is not True
        or web_fetch.get("pages_fetched") != [WEB_FETCH_PROBE_URL]
        or web_fetch.get("invalid_url") != WEB_FETCH_INVALID_URL
        or web_fetch.get("invalid_url_handled") is not True
        or web_fetch.get("invalid_url_pages_fetched") != [WEB_FETCH_INVALID_URL]
        or web_fetch.get("tool_names")
        != (["fetch_web_page", "web_search"] if config["tools"]["require_brave_search"] else ["fetch_web_page"])
        or not isinstance(web_fetch.get("proxy_environment_variables_present"), list)
    ):
        raise ValueError("Preflight artifact does not contain a successful scoped Stirrup web-fetch probe")
    if (
        config.get("tools", {}).get("require_brave_search")
        and payload.get("web_search", {}).get("matched_expected_shape") is not True
    ):
        raise ValueError("Preflight artifact does not contain a successful Brave Search probe")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--policy-base-url")
    parser.add_argument("--policy-job-id")
    parser.add_argument("--judge-base-url")
    parser.add_argument("--task-id", action="append")
    parser.add_argument("--trial", type=int, action="append")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--workers", type=int)
    parser.add_argument("--preflight-file", type=Path)
    parser.add_argument(
        "--candidate-source-run",
        type=Path,
        help="Import matching immutable candidates from a prior run into this new output directory",
    )
    parser.add_argument(
        "--missing-candidate-policy",
        choices=("error", "generate"),
        help="How to handle planned candidates absent from --candidate-source-run (default: error)",
    )
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(threadName)s %(message)s")
    config_path = args.config.resolve()
    config = load_config(config_path)
    _validate_config(config)
    policy_deployment = policy_deployment_identity(config["policy"])
    judge_deployment = judge_deployment_identity(config["judge"])
    policy_url_env = os.getenv(str(config["policy"].get("base_url_env", "")))
    policy_job_env = os.getenv(str(config["policy"].get("slurm_job_id_env", "")))
    judge_url_env = os.getenv(str(config["judge"].get("base_url_env", "")))
    if (
        args.policy_base_url
        or args.policy_job_id
        or policy_url_env
        or policy_job_env
        or config["policy"].get("base_url")
    ):
        load_policy_endpoint(config["policy"], args.policy_base_url, args.policy_job_id)
    if args.judge_base_url or judge_url_env or config["judge"].get("base_url"):
        load_info_endpoint(config["judge"], args.judge_base_url)
    fingerprint = _fingerprint(config)
    catalog_path = Path(config["source"]["catalog_file"]).expanduser().resolve()
    asset_manifest = load_asset_manifest(config)
    if not catalog_path.exists():
        if args.dry_run:
            print(
                json.dumps(
                    {
                        "config_fingerprint": fingerprint,
                        "catalog": str(catalog_path),
                        "prepared": False,
                        "asset_mirror": mirror_provenance(config["source"])
                        | {
                            "manifest_entries": len(asset_manifest),
                            "ready": False,
                            "reason": "catalog is not prepared, so selected assets cannot be resolved",
                        },
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        prepare(config)

    catalog = _load_catalog(catalog_path, int(config["benchmark"]["expected_tasks"]))
    manifest_shape = bind_manifest_to_catalog(asset_manifest, catalog)
    catalog_provenance_path = catalog_path.with_suffix(catalog_path.suffix + ".provenance.json")
    catalog_provenance = _validate_catalog_provenance(
        catalog_path,
        config,
        catalog,
        manifest_shape,
    )
    eligible, reference_exclusions = _filter_reference_eligible(catalog, config)
    selected = eligible
    if args.task_id:
        requested = set(args.task_id)
        known = {str(task["task_id"]) for task in catalog}
        if unknown := requested - known:
            raise ValueError(f"Unknown GDPval task IDs: {sorted(unknown)}")
        excluded_requested = requested - {str(task["task_id"]) for task in eligible}
        if excluded_requested:
            raise ValueError(
                "Requested tasks have no eligible comparison reference: " + ", ".join(sorted(excluded_requested))
            )
        selected = [task for task in selected if str(task["task_id"]) in requested]
    if args.limit is not None:
        if args.limit < 1:
            raise ValueError("--limit must be positive")
        selected = selected[: args.limit]
    trial_indices = list(range(int(config["benchmark"]["num_trials"])))
    if args.trial:
        invalid = set(args.trial) - set(trial_indices)
        if invalid:
            raise ValueError(f"Invalid trial indices: {sorted(invalid)}")
        trial_indices = [trial for trial in trial_indices if trial in set(args.trial)]
    trials = [Trial(task, trial) for trial in trial_indices for task in selected]
    worker_count = int(args.workers or config["runtime"]["workers"])
    if args.missing_candidate_policy is not None and args.candidate_source_run is None:
        raise ValueError("--missing-candidate-policy requires --candidate-source-run")
    candidate_source_run = args.candidate_source_run.expanduser().resolve() if args.candidate_source_run else None
    missing_candidate_policy = args.missing_candidate_policy or ("error" if candidate_source_run else None)
    candidate_source_plan: dict[str, Any] | None = None
    candidate_source_missing: list[tuple[str, int]] = []
    if candidate_source_run is not None:
        candidate_source_plan, candidate_source_missing = _inspect_candidate_source(
            candidate_source_run,
            trials,
            config,
            str(missing_candidate_policy),
        )
    selected_assets = _required_asset_entries(asset_manifest, selected, config)
    cache_status = asset_cache_status(config, selected_assets, verify_hashes=True)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "config": str(config_path),
                    "config_fingerprint": fingerprint,
                    "scorer_fingerprint": fingerprint,
                    "scoring_mode": config["scoring"]["mode"],
                    "catalog_tasks": len(catalog),
                    "catalog_provenance": catalog_provenance,
                    "tasks": len(selected),
                    "trials": len(trials),
                    "workers": worker_count,
                    "task_ids": [trial.task_id for trial in trials[:10]],
                    "candidate_source": candidate_source_plan,
                    "candidate_source_missing": [
                        {"task_id": task_id, "trial": trial} for task_id, trial in candidate_source_missing
                    ],
                    "reference_exclusions": reference_exclusions,
                    "asset_manifest": manifest_shape,
                    "asset_mirror": cache_status,
                    "prerequisites": {
                        "brave_search_required": bool(config.get("tools", {}).get("require_brave_search")),
                        "brave_api_key_present": bool(os.getenv("BRAVE_API_KEY")),
                        "web_fetch_trust_env": config["tools"]["web_fetch_trust_env"],
                        "hf_token_required": False,
                        "runtime_image": config["runtime"]["image"],
                    },
                    "official_target": config["official_reference"],
                    "official_parity_possible": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    cache_status = prepare_asset_cache(
        config,
        selected_assets,
        workers=min(max(1, worker_count), 16),
    )
    if args.prepare_only:
        print(
            json.dumps(
                {
                    "catalog": str(catalog_path),
                    "catalog_tasks": len(catalog),
                    "catalog_provenance": catalog_provenance,
                    "eligible_tasks": len(eligible),
                    "selected_tasks": len(selected),
                    "candidate_source": candidate_source_plan,
                    "candidate_source_missing": [
                        {"task_id": task_id, "trial": trial} for task_id, trial in candidate_source_missing
                    ],
                    "asset_manifest": manifest_shape,
                    "asset_mirror": cache_status,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    output_dir = (args.output_dir or Path(config["output_dir"])).expanduser().resolve()
    if candidate_source_run == output_dir:
        raise ValueError("--candidate-source-run must be different from --output-dir")
    output_dir.mkdir(parents=True, exist_ok=True)
    lock_file = (output_dir / ".writer.lock").open("w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        raise RuntimeError(f"Another evaluator owns output directory {output_dir}") from error

    _snapshot(config_path, catalog_path, catalog_provenance_path, output_dir)
    snapshot_catalog_provenance = catalog_provenance | {"path": str(output_dir / catalog_provenance_path.name)}
    asset_cache_snapshot = {key: value for key, value in cache_status.items() if key != "downloaded_assets"}
    asset_cache_snapshot_path = output_dir / "asset_cache_provenance.json"
    if asset_cache_snapshot_path.exists():
        if json.loads(asset_cache_snapshot_path.read_text(encoding="utf-8")) != asset_cache_snapshot:
            raise ValueError("Asset-cache provenance differs from the existing output directory")
    else:
        atomic_write_json(asset_cache_snapshot_path, asset_cache_snapshot)
    run_plan = {
        "schema_version": 1,
        "config_fingerprint": fingerprint,
        "scorer_fingerprint": fingerprint,
        "trials": [{"task_id": trial.task_id, "trial": trial.trial} for trial in trials],
        "reference_exclusions": reference_exclusions,
        "catalog_sha256": catalog_provenance["catalog_sha256"],
        "catalog_provenance_sha256": catalog_provenance["sha256"],
        "asset_manifest_sha256": config["source"]["asset_manifest_sha256"],
        "selected_asset_manifest_sha256": cache_status["selected_manifest_sha256"],
        "selected_assets": cache_status["selected_assets"],
    }
    if candidate_source_plan is not None:
        run_plan["candidate_source"] = candidate_source_plan
    run_plan_path = output_dir / "run_plan.json"
    if run_plan_path.exists():
        if json.loads(run_plan_path.read_text(encoding="utf-8")) != run_plan:
            raise ValueError("Requested task/trial plan differs from the existing output directory")
    else:
        atomic_write_json(run_plan_path, run_plan)
    results_path = output_dir / "results.jsonl"
    attempts_path = output_dir / "attempts.jsonl"
    recovery_dir = output_dir / "jsonl_recovery"
    for jsonl_path in (results_path, attempts_path, output_dir / "endpoint_sessions.jsonl"):
        repair_truncated_jsonl_tail(
            jsonl_path,
            recovery_dir=recovery_dir,
            owner="output_directory_lock",
        )
    planned_keys = {(trial.task_id, trial.trial) for trial in trials}
    _validate_preexisting_judge_retry_bindings(output_dir, fingerprint, planned_keys)
    candidate_source: dict[str, Any] | None = None
    candidate_imports: list[dict[str, Any]] = []
    if candidate_source_run is not None:
        candidate_source, candidate_imports, candidate_source_missing = _materialize_candidate_imports(
            source_run=candidate_source_run,
            expected_source_record=candidate_source_plan,
            trials=trials,
            config=config,
            fingerprint=fingerprint,
            output_dir=output_dir,
        )
    _validated_endpoint_sessions(output_dir / "endpoint_sessions.jsonl", config)
    reconciled_orphan_worker_results = _reconcile_orphan_worker_results(
        output_dir,
        fingerprint,
        planned_keys,
    )
    recovered_terminal_results = _recover_terminal_attempts(output_dir, fingerprint)
    results = JsonlStore(results_path)
    attempts = JsonlStore(attempts_path)
    completed = _completed_keys(results_path, fingerprint)
    histories = _attempt_histories(
        attempts_path,
        completed,
        output_dir=output_dir,
        fingerprint=fingerprint,
    )
    pending = [trial for trial in trials if trial.key not in completed]
    pending_candidate_bindings = {
        trial.key: _existing_candidate_binding(
            output_dir / "artifacts" / f"task_{trial.task_id}" / f"repeat_{trial.trial}",
            task_id=trial.task_id,
            trial=trial.trial,
            fingerprint=fingerprint,
        )
        for trial in pending
    }
    needs_policy = any(binding is None for binding in pending_candidate_bindings.values())
    needs_judge = bool(pending)
    if needs_policy and config.get("tools", {}).get("require_brave_search") and not os.getenv("BRAVE_API_KEY"):
        raise ValueError("The configured Brave search provider requires BRAVE_API_KEY")

    metadata_path = output_dir / "run_metadata.json"
    previous_metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    if previous_metadata and previous_metadata.get("config_fingerprint") != fingerprint:
        raise ValueError("Existing run metadata has a different config fingerprint")
    if previous_metadata and previous_metadata.get("schema_version") != RUN_METADATA_SCHEMA_VERSION:
        raise ValueError("Existing run metadata has an unsupported schema version")
    if previous_metadata and previous_metadata.get("deployments") != {
        "policy": policy_deployment,
        "judge": judge_deployment,
    }:
        raise ValueError("Existing run metadata has mismatched resolved deployment provenance")

    preflight: dict[str, Any] | None = None
    preflight_path: Path | None = None
    if args.preflight_file:
        source_preflight = args.preflight_file.resolve()
        preflight = json.loads(source_preflight.read_text(encoding="utf-8"))
        _validate_preflight_payload(preflight, config, fingerprint)
        preflight_sha256 = sha256_file(source_preflight)
        preflight_path = output_dir / "preflights" / f"{preflight_sha256}.json"
        preflight_path.parent.mkdir(parents=True, exist_ok=True)
        if preflight_path.exists() and preflight_path.read_bytes() != source_preflight.read_bytes():
            raise ValueError(f"Conflicting preflight artifact: {preflight_path}")
        if not preflight_path.exists():
            shutil.copy2(source_preflight, preflight_path)
    elif previous_metadata.get("preflight"):
        preflight_record = previous_metadata["preflight"]
        preflight_path = Path(str(preflight_record["path"]))
        if not preflight_path.is_file() or sha256_file(preflight_path) != preflight_record.get("sha256"):
            raise ValueError("Previously recorded preflight artifact is missing or corrupt")
        preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
        _validate_preflight_payload(preflight, config, fingerprint)
    elif config["runtime"].get("require_preflight"):
        raise ValueError("A successful --preflight-file is required before dispatch")

    policy = load_policy_endpoint(config["policy"], args.policy_base_url, args.policy_job_id) if needs_policy else None
    judge = load_info_endpoint(config["judge"], args.judge_base_url) if needs_judge else None
    if policy is not None and policy.deployment != policy_deployment:
        raise ValueError("Resolved policy deployment differs from the configured deployment")
    if judge is not None and judge.deployment != judge_deployment:
        raise ValueError("Resolved judge deployment differs from the configured deployment")
    policy_probe = (
        _probe(policy, str(config["policy"]["server_version"]))
        if policy is not None
        else previous_metadata.get("policy")
    )
    judge_probe = _probe(judge) if judge is not None else previous_metadata.get("judge")
    if args.preflight_file:
        for role, current_probe in (("policy", policy_probe), ("judge", judge_probe)):
            if current_probe is None:
                continue
            preflight_probe = preflight.get(role) if preflight is not None else None
            if not isinstance(preflight_probe, dict):
                raise ValueError(f"Fresh preflight is missing the {role} endpoint probe")
            if _stable_probe_identity(current_probe) != _stable_probe_identity(preflight_probe):
                raise ValueError(f"The {role} endpoint changed between preflight and dispatch")
    endpoint_session_id = str(previous_metadata.get("endpoint_session_id") or "")
    if pending:
        endpoint_session_id = uuid.uuid4().hex
        append_jsonl(
            output_dir / "endpoint_sessions.jsonl",
            {
                "schema_version": ENDPOINT_SESSION_SCHEMA_VERSION,
                "endpoint_session_id": endpoint_session_id,
                "time": time.time(),
                "policy_required": needs_policy,
                "judge_required": needs_judge,
                "policy_deployment_id": policy_deployment["deployment_id"],
                "policy_slurm_job_id": policy_deployment["slurm_job_id"],
                "judge_deployment_id": judge_deployment["deployment_id"],
                "judge_proxy_jobid": judge_deployment["proxy_jobid"],
                "policy": policy_probe,
                "judge": judge_probe,
            },
        )
    random.Random(int(config["benchmark"]["dispatch_seed"])).shuffle(pending)
    work: queue.Queue[Trial] = queue.Queue()
    for trial in pending:
        work.put(trial)

    metadata = {
        "schema_version": RUN_METADATA_SCHEMA_VERSION,
        "config_fingerprint": fingerprint,
        "scorer_fingerprint": fingerprint,
        "source": config["source"],
        "catalog_sha256": catalog_provenance["catalog_sha256"],
        "catalog_provenance": snapshot_catalog_provenance,
        "run_plan_sha256": sha256_file(run_plan_path),
        "asset_manifest": manifest_shape,
        "asset_mirror": asset_cache_snapshot,
        "asset_cache_provenance": {
            "path": str(asset_cache_snapshot_path),
            "sha256": sha256_file(asset_cache_snapshot_path),
        },
        "candidate_source": candidate_source,
        "candidate_imports": candidate_imports,
        "candidate_source_missing": [
            {"task_id": task_id, "trial": trial} for task_id, trial in candidate_source_missing
        ],
        "implementation": _source_hashes(),
        "host_packages": _package_versions(),
        "policy": policy_probe,
        "judge": judge_probe,
        "deployments": {"policy": policy_deployment, "judge": judge_deployment},
        "endpoint_session_id": endpoint_session_id,
        "preflight": (
            {"path": str(preflight_path), "sha256": sha256_file(preflight_path)} if preflight_path is not None else None
        ),
        "scoring_mode": config["scoring"]["mode"],
        "tools": _expected_tool_capabilities(config),
        "workers": worker_count,
        "catalog_tasks": len(catalog),
        "selected_tasks": len(selected),
        "reference_exclusions": reference_exclusions,
        "expected_results": len(trials),
        "resumed_results": len(completed),
        "recovered_terminal_results": recovered_terminal_results,
        "reconciled_orphan_worker_results": reconciled_orphan_worker_results,
        "started_at": previous_metadata.get("started_at", time.time()),
        "resumed_at": time.time() if previous_metadata else None,
        "official_parity_possible": False,
        "official_parity_limit": (
            "The public dataset has human deliverables for only 185/220 tasks. Artificial Analysis does not "
            "publish its complete multi-model reference set, comparison graph, judge outcomes, exact sandbox, "
            "or Nemotron parser plugin; this run is a Kimi-judged surrogate."
        ),
    }
    atomic_write_json(output_dir / "run_metadata.json", metadata)

    fatal_errors: list[str] = []
    missing: list[dict[str, Any]] = []
    state_lock = threading.Lock()
    stop = threading.Event()
    completed_count = len(completed)
    max_infra = int(config["retry"]["max_infrastructure_retries"]) + 1
    max_judge = int(config["retry"]["max_judge_retries"]) + 1

    def worker_loop(worker_index: int) -> None:
        nonlocal completed_count
        while not stop.is_set():
            try:
                trial = work.get_nowait()
            except queue.Empty:
                return
            try:
                prior = histories.get(trial.key, [])
                infra_used = sum(row.get("status") == "retryable_error" for row in prior)
                judge_used = sum(row.get("status") == "judge_retryable" for row in prior)
                judge_candidate_binding = next(
                    (
                        {
                            "candidate_dir": str(row["candidate_dir"]),
                            "candidate_sha256": str(row["candidate_sha256"]),
                        }
                        for row in reversed(prior)
                        if row.get("status") == "judge_retryable"
                    ),
                    None,
                )
                attempt = len(prior) + 1
                while not stop.is_set():
                    candidate_dir = output_dir / "artifacts" / f"task_{trial.task_id}" / f"repeat_{trial.trial}"
                    candidate_binding_before = _existing_candidate_binding(
                        candidate_dir,
                        task_id=trial.task_id,
                        trial=trial.trial,
                        fingerprint=fingerprint,
                    )
                    if judge_candidate_binding is not None and candidate_binding_before != judge_candidate_binding:
                        raise ValueError(
                            f"Immutable judge-retry candidate is missing or changed for {trial.key}: "
                            f"expected {judge_candidate_binding}"
                        )
                    has_candidate = candidate_binding_before is not None
                    if has_candidate and judge_used >= max_judge:
                        with state_lock:
                            missing.append(
                                {"task_id": trial.task_id, "trial": trial.trial, "reason": "judge retries exhausted"}
                            )
                        break
                    if not has_candidate and infra_used >= max_infra:
                        with state_lock:
                            missing.append(
                                {
                                    "task_id": trial.task_id,
                                    "trial": trial.trial,
                                    "reason": "infrastructure retries exhausted",
                                }
                            )
                        break
                    command, result_path, log_path = _worker_command(
                        config_path=output_dir / "config.toml",
                        catalog_path=output_dir / "gdpval_benchmark.jsonl",
                        trial=trial,
                        attempt=attempt,
                        fingerprint=fingerprint,
                        endpoint_session_id=endpoint_session_id,
                        output_dir=output_dir,
                        expected_candidate_sha256=(
                            candidate_binding_before["candidate_sha256"]
                            if candidate_binding_before is not None
                            else None
                        ),
                        policy_base_url=policy.base_url if policy is not None else None,
                        judge_base_url=judge.base_url if judge is not None else None,
                    )
                    return_code = _run_worker(command, log_path)
                    try:
                        payload = _read_worker_result(
                            result_path,
                            log_path,
                            trial,
                            attempt=attempt,
                            endpoint_session_id=endpoint_session_id,
                        )
                        if payload.get("result_recovery") is not None:
                            atomic_write_json(result_path, payload)
                    except MissingWorkerResult as error:
                        if return_code not in {-9, 137}:
                            raise RuntimeError(
                                f"Unexpected worker exit for {trial.key}, rc={return_code}: {error}"
                            ) from error
                        base_payload = {
                            "schema_version": 1,
                            "task_id": trial.task_id,
                            "trial": trial.trial,
                            "attempt": attempt,
                            "config_fingerprint": fingerprint,
                            "endpoint_session_id": endpoint_session_id,
                            "error": f"worker was killed before writing a terminal result (rc={return_code})",
                            "result_recovery": {"source": "kill_shaped_worker_exit"},
                        }
                        try:
                            candidate_binding_after = _existing_candidate_binding(
                                candidate_dir,
                                task_id=trial.task_id,
                                trial=trial.trial,
                                fingerprint=fingerprint,
                            )
                        except ValueError as candidate_error:
                            payload = base_payload | {
                                "status": "fatal_error",
                                "failure_role": "judge" if candidate_binding_before is not None else "policy",
                                "error": f"{base_payload['error']}; candidate validation failed: {candidate_error}",
                            }
                        else:
                            if (
                                candidate_binding_before is not None
                                and candidate_binding_after != candidate_binding_before
                            ):
                                payload = (
                                    base_payload
                                    | {
                                        "status": "fatal_error",
                                        "failure_role": "judge",
                                        "error": f"{base_payload['error']}; immutable candidate disappeared or changed",
                                    }
                                    | candidate_binding_before
                                )
                            elif candidate_binding_after is not None:
                                payload = (
                                    base_payload
                                    | {"status": "judge_retryable", "failure_role": "judge"}
                                    | candidate_binding_after
                                )
                            else:
                                payload = base_payload | {
                                    "status": "retryable_error",
                                    "failure_role": "policy",
                                }
                        atomic_write_json(result_path, payload)
                    if payload.get("config_fingerprint") != fingerprint:
                        raise ValueError(f"Worker fingerprint mismatch for {trial.key}")
                    status = str(payload.get("status"))
                    _validate_failure_record(
                        payload,
                        output_dir=output_dir,
                        task_id=trial.task_id,
                        trial=trial.trial,
                        fingerprint=fingerprint,
                        context=f"Worker result {trial.key}:{attempt}",
                    )
                    if candidate_binding_before is not None:
                        if status in {"retryable_error", "model_error", "model_timeout"}:
                            raise ValueError(f"Worker regressed from judge-only execution for {trial.key}: {status}")
                        if status in {"completed", "judge_retryable"} and any(
                            payload.get(field) != candidate_binding_before[field]
                            for field in ("candidate_dir", "candidate_sha256")
                        ):
                            raise ValueError(f"Worker changed the immutable candidate for {trial.key}")
                        if status == "fatal_error" and payload.get("failure_role") != "judge":
                            raise ValueError(f"Worker misattributed a judge-only fatal error for {trial.key}")
                        if (
                            status == "fatal_error"
                            and payload.get("candidate_dir") is not None
                            and any(
                                payload.get(field) != candidate_binding_before[field]
                                for field in ("candidate_dir", "candidate_sha256")
                            )
                        ):
                            raise ValueError(f"Fatal worker result changed the immutable candidate for {trial.key}")
                    if status == "completed":
                        completed_candidate_binding = _candidate_binding(
                            candidate_dir,
                            task_id=trial.task_id,
                            trial=trial.trial,
                            fingerprint=fingerprint,
                        )
                        if any(
                            payload.get(field) != completed_candidate_binding[field]
                            for field in ("candidate_dir", "candidate_sha256")
                        ):
                            raise ValueError(f"Completed worker result has a mismatched candidate for {trial.key}")
                    elif status == "retryable_error":
                        unexpected_candidate = _existing_candidate_binding(
                            candidate_dir,
                            task_id=trial.task_id,
                            trial=trial.trial,
                            fingerprint=fingerprint,
                        )
                        if unexpected_candidate is not None:
                            raise ValueError(f"Policy retry unexpectedly persisted a candidate for {trial.key}")
                    attempt_row = {
                        "schema_version": 1,
                        "worker": worker_index,
                        "attempt": attempt,
                        "task_id": trial.task_id,
                        "trial": trial.trial,
                        "config_fingerprint": fingerprint,
                        "endpoint_session_id": payload.get("endpoint_session_id"),
                        "status": payload.get("status"),
                        "failure_role": payload.get("failure_role"),
                        "error": payload.get("error"),
                        "candidate_dir": payload.get("candidate_dir"),
                        "candidate_sha256": payload.get("candidate_sha256"),
                        "worker_return_code": return_code,
                        "worker_log": str(log_path),
                        "worker_result": str(result_path),
                        "worker_log_sha256": sha256_file(log_path),
                        "time": time.time(),
                    }
                    attempts.append(attempt_row)
                    if status == "retryable_error":
                        infra_used += 1
                    elif status == "judge_retryable":
                        judge_used += 1
                        judge_candidate_binding = {
                            "candidate_dir": str(payload["candidate_dir"]),
                            "candidate_sha256": str(payload["candidate_sha256"]),
                        }
                    elif status == "fatal_error":
                        raise RuntimeError(f"Fatal worker error for {trial.key}: {payload.get('error')}")
                    elif status in SCORED_STATUSES:
                        if return_code != 0:
                            raise RuntimeError(
                                f"Worker returned {return_code} with scored status {status} for {trial.key}"
                            )
                        results.append(payload)
                        with state_lock:
                            completed_count += 1
                            logger.info(
                                "completed %d/%d %s reward=%s status=%s",
                                completed_count,
                                len(trials),
                                trial.key,
                                payload.get("reward"),
                                status,
                            )
                        break
                    else:
                        raise RuntimeError(f"Unknown worker status for {trial.key}: {status!r}")
                    attempt += 1
                    time.sleep(float(config["retry"]["retry_delay_seconds"]) * min(attempt, 5))
            except Exception as error:
                with state_lock:
                    fatal_errors.append(f"worker {worker_index}, trial {trial.key}: {type(error).__name__}: {error}")
                stop.set()
                logger.exception("worker %d failed on %s", worker_index, trial.key)
            finally:
                work.task_done()

    active_workers = min(worker_count, max(1, len(pending)))
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=active_workers,
        thread_name_prefix="gdpval-vmvm",
    ) as executor:
        futures = [executor.submit(worker_loop, index) for index in range(active_workers)]
        for future in concurrent.futures.as_completed(futures):
            future.result()

    summary = _summary(results_path, len(trials), config)
    summary["missing"] = missing
    summary["fatal_errors"] = fatal_errors
    atomic_write_json(output_dir / "summary.json", summary)
    metadata["finished_at"] = time.time()
    metadata["summary"] = summary
    atomic_write_json(output_dir / "run_metadata.json", metadata)
    if fatal_errors:
        return 2
    return 1 if summary["scored"] != len(trials) else 0


if __name__ == "__main__":
    raise SystemExit(main())
