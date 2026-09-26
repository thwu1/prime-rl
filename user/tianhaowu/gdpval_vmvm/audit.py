from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

from asset_fetch import asset_selection_provenance, bind_manifest_to_catalog, load_asset_manifest, mirror_provenance
from common import judge_deployment_identity, load_jsonl, policy_deployment_identity, sha256_file
from judge import _file_manifest as _judge_file_manifest
from judge import _pairwise_messages, _render_directory, _sha256_json
from run_eval import (
    ENDPOINT_SESSION_SCHEMA_VERSION,
    PREFLIGHT_SCHEMA_VERSION,
    RUN_METADATA_SCHEMA_VERSION,
    WEB_FETCH_INVALID_URL,
    WEB_FETCH_PROBE_URL,
    _assigned_reference,
    _required_asset_entries,
)
from run_eval import _summary as _runner_summary
from worker import _expert_deliverable_specs, _reference_input_specs, _safe_component

SCORED_STATUSES = {"completed", "model_error", "model_timeout"}
RETRYABLE_STATUSES = {"retryable_error", "judge_retryable"}
FAILURE_ROLES = {"policy", "judge"}
ENDPOINT_KEYS = {
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
SOURCE_PATH_KEYS = {"catalog_file", "asset_cache_dir", "reference_cache_dir", "expert_cache_dir"}
BOXED_RE = re.compile(r"BOXED\[(A|B|TIE)\]")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
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
DATASET_PARQUET_FILE = "data/train-00000-of-00001.parquet"
EXPECTED_CATALOG_SOURCE_PINS = {
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
}
EXPECTED_CATALOG_SHAPE = {
    "tasks": 220,
    "sectors": 9,
    "occupations": 44,
    "reference_files": 261,
    "deliverable_files": 248,
    "rubric_items": 10_453,
}


def _require_run_path(
    value: Any,
    *,
    output_dir: Path,
    expected: Path,
    context: str,
) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} has no path")
    supplied = Path(value).expanduser()
    if not supplied.is_absolute():
        raise ValueError(f"{context} path is not absolute: {value!r}")
    output_absolute = output_dir.absolute()
    expected_absolute = expected.absolute()
    try:
        expected_relative = expected_absolute.relative_to(output_absolute)
    except ValueError as error:
        raise ValueError(f"{context} expected path is outside the run directory: {expected}") from error
    current = output_absolute
    for part in expected_relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f"{context} expected path contains a symlink: {current}")
    root = output_dir.resolve()
    resolved = supplied.resolve()
    expected_resolved = expected.resolve()
    if not expected_resolved.is_relative_to(root):
        raise ValueError(f"{context} expected path escapes the run directory through a symlink: {expected}")
    if resolved != expected_resolved or not resolved.is_relative_to(root):
        raise ValueError(f"{context} path is outside its expected run location: {resolved}")
    return resolved


def _fingerprint(config: dict[str, Any], implementation: dict[str, str]) -> str:
    semantic = {
        "source": {key: value for key, value in config["source"].items() if key not in SOURCE_PATH_KEYS},
        "benchmark": config["benchmark"],
        "policy": {key: value for key, value in config["policy"].items() if key not in ENDPOINT_KEYS},
        "judge": {key: value for key, value in config["judge"].items() if key not in ENDPOINT_KEYS},
        "scoring": config["scoring"],
        "tools": config.get("tools", {}),
        "references": config.get("references", []),
        "runtime": config["runtime"],
        "retry": config["retry"],
        "official_reference": config["official_reference"],
        "implementation": implementation,
    }
    payload = json.dumps(semantic, sort_keys=True, separators=(",", ":"))
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
    for key, expected in EXPECTED_CATALOG_SOURCE_PINS.items():
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


def _probe_deployment_matches(probe: Any, expected: dict[str, str]) -> bool:
    return isinstance(probe, dict) and all(probe.get(key) == value for key, value in expected.items())


def _validate_generation_preflight(
    payload: dict[str, Any],
    config: dict[str, Any],
    fingerprint: str,
) -> None:
    if not isinstance(payload, dict):
        raise ValueError("Candidate source generation preflight must be an object")
    schema_version = payload.get("schema_version")
    if isinstance(schema_version, bool) or not isinstance(schema_version, int) or schema_version < 1:
        raise ValueError("Candidate source generation preflight has an invalid schema version")
    if config.get("tools", {}).get("web_fetch_trust_env") is not False:
        raise ValueError("Candidate source must disable environment proxies for Stirrup web fetches")
    if payload.get("ok") is not True or "sandbox" not in payload:
        raise ValueError("Candidate source generation preflight has no successful sandbox probe")
    sandbox = payload["sandbox"]
    if (
        not isinstance(sandbox, dict)
        or not sandbox.get("staged_assets")
        or not sandbox.get("render_history")
        or not any(str(path).lower().endswith(".pdf") for path in sandbox.get("rendered_files", []))
        or not isinstance(sandbox.get("vmvm"), dict)
    ):
        raise ValueError("Candidate source generation preflight has incomplete sandbox evidence")
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
        raise ValueError("Candidate source generation preflight has mismatched asset-mirror provenance")
    if (
        Path(str(asset_mirror.get("cache_dir", ""))).expanduser().resolve()
        != Path(config["source"]["asset_cache_dir"]).expanduser().resolve()
    ):
        raise ValueError("Candidate source generation preflight has a mismatched asset-cache path")
    if (
        asset_mirror.get("ready") is not True
        or asset_mirror.get("hashes_verified") is not True
        or int(asset_mirror.get("cached_assets", -1)) != int(asset_mirror.get("selected_assets", -2))
        or int(asset_mirror.get("selected_assets", -1)) != len(sandbox["staged_assets"])
        or int(asset_mirror.get("missing_assets", -1)) != 0
        or int(asset_mirror.get("corrupt_assets", -1)) != 0
    ):
        raise ValueError("Candidate source generation preflight does not prove a verified asset cache")
    if payload.get("config_fingerprint") != fingerprint:
        raise ValueError("Candidate source generation preflight has a mismatched fingerprint")
    policy_deployment = policy_deployment_identity(config["policy"])
    if payload.get("policy_deployment_id") != policy_deployment["deployment_id"]:
        raise ValueError("Candidate source generation preflight has a mismatched policy deployment")
    if payload.get("policy_slurm_job_id") != policy_deployment["slurm_job_id"]:
        raise ValueError("Candidate source generation preflight has a mismatched policy Slurm job")
    if payload.get("sandbox_image") != config["runtime"]["image"]:
        raise ValueError("Candidate source generation preflight has a mismatched sandbox image")
    policy_probe = payload.get("policy")
    if (
        not isinstance(policy_probe, dict)
        or policy_probe.get("model") != config["policy"]["model"]
        or not _probe_deployment_matches(policy_probe, policy_deployment)
    ):
        raise ValueError("Candidate source generation preflight has a mismatched policy probe")
    if policy_probe.get("chat", {}).get("matched_expected_answer") is not True:
        raise ValueError("Candidate source generation preflight has no successful policy text probe")
    if policy_probe.get("tool_call", {}).get("arguments_valid") is not True:
        raise ValueError("Candidate source generation preflight has no successful policy tool-call probe")
    if policy_probe.get("server", {}).get("version") != config["policy"]["server_version"]:
        raise ValueError("Candidate source generation preflight has a mismatched policy server version")
    if not any(
        item.get("id") == config["policy"]["model"]
        and int(item.get("max_model_len", -1)) == int(config["policy"]["context_window"])
        for item in policy_probe.get("advertised_model_metadata", [])
        if isinstance(item, dict)
    ):
        raise ValueError("Candidate source generation preflight does not confirm the policy context window")
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
        raise ValueError("Candidate source generation preflight has no successful web-fetch probe")
    if (
        config.get("tools", {}).get("require_brave_search")
        and payload.get("web_search", {}).get("matched_expected_shape") is not True
    ):
        raise ValueError("Candidate source generation preflight has no successful Brave Search probe")


def _candidate_manifest(path: Path) -> dict[str, Any]:
    for candidate_path in (path.parent.parent, path.parent, path):
        if candidate_path.is_symlink():
            raise ValueError(f"Candidate path contains a symlink: {candidate_path}")
    if not path.is_dir() or path.is_symlink():
        raise ValueError(f"Missing or unsafe candidate directory: {path}")
    marker = path / "candidate.json"
    if not marker.is_file() or marker.is_symlink():
        raise ValueError(f"Missing candidate manifest: {marker}")
    for candidate_file in path.rglob("*"):
        if candidate_file.is_symlink():
            raise ValueError(f"Candidate contains a symlink: {candidate_file}")
    manifest = json.loads(marker.read_text(encoding="utf-8"))
    actual = [
        {
            "path": file.relative_to(path).as_posix(),
            "size": file.stat().st_size,
            "sha256": sha256_file(file),
        }
        for file in sorted(path.rglob("*"))
        if file.is_file() and not (len(file.relative_to(path).parts) == 1 and file.name == "candidate.json")
    ]
    if manifest.get("files") != actual:
        raise ValueError(f"Candidate file manifest mismatch: {path}")
    candidate_sha256 = hashlib.sha256(json.dumps(actual, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if manifest.get("candidate_sha256") != candidate_sha256:
        raise ValueError(f"Candidate aggregate digest mismatch: {path}")
    return manifest


def _attempt_endpoint_role(row: dict[str, Any], *, context: str) -> str:
    status = str(row.get("status"))
    if status == "completed":
        return "judge"
    if status in {"model_error", "model_timeout"}:
        return "policy"
    if status not in RETRYABLE_STATUSES | {"fatal_error"}:
        raise ValueError(f"{context} has unknown status: {status!r}")
    role = row.get("failure_role")
    if role not in FAILURE_ROLES:
        raise ValueError(f"{context} has invalid failure_role: {role!r}")
    if status == "retryable_error" and role != "policy":
        raise ValueError(f"{context} has policy retry status with {role!r} failure_role")
    if status == "judge_retryable" and role != "judge":
        raise ValueError(f"{context} has judge retry status with {role!r} failure_role")
    has_candidate_dir = row.get("candidate_dir") is not None
    has_candidate_sha256 = row.get("candidate_sha256") is not None
    if has_candidate_dir != has_candidate_sha256:
        raise ValueError(f"{context} has an incomplete candidate binding")
    if role == "policy" and has_candidate_dir:
        raise ValueError(f"{context} binds a candidate to a policy-side failure")
    return str(role)


def _file_manifest(
    path: Path,
    *,
    exclude: set[str] | None = None,
    exclude_top_level_dirs: set[str] | None = None,
) -> list[dict[str, Any]]:
    ignored = exclude or set()
    excluded_dirs = exclude_top_level_dirs or set()
    return [
        {
            "path": file.relative_to(path).as_posix(),
            "size": file.stat().st_size,
            "sha256": sha256_file(file),
        }
        for file in sorted(path.rglob("*"))
        if file.is_file()
        and not (len(file.relative_to(path).parts) == 1 and file.name in ignored)
        and not (file.relative_to(path).parts and file.relative_to(path).parts[0] in excluded_dirs)
    ]


def _candidate_import_path(output_dir: Path, value: Any, expected: Path, context: str) -> Path:
    expected_relative = expected.relative_to(output_dir).as_posix()
    if value != expected_relative:
        raise ValueError(f"{context} path mismatch: expected {expected_relative!r}, got {value!r}")
    resolved = expected.resolve()
    if not resolved.is_relative_to(output_dir) or not resolved.is_file() or expected.is_symlink():
        raise ValueError(f"{context} is missing or unsafe: {expected}")
    return resolved


def _audit_candidate_source_bundle(
    output_dir: Path,
    config: dict[str, Any],
    implementation: dict[str, str],
    run_plan: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any] | None:
    plan_source = run_plan.get("candidate_source")
    metadata_source = metadata.get("candidate_source")
    if plan_source is None and metadata_source is None:
        if metadata.get("candidate_imports") or metadata.get("candidate_source_missing"):
            raise ValueError("Run metadata records candidate imports without a candidate source")
        return None
    if not isinstance(plan_source, dict) or not isinstance(metadata_source, dict):
        raise ValueError("Candidate source provenance is incomplete")
    for key in (
        "source_run",
        "source_config_fingerprint",
        "source_generation_fingerprint",
        "source_catalog_provenance_sha256",
        "missing_candidate_policy",
    ):
        if metadata_source.get(key) != plan_source.get(key):
            raise ValueError(f"Candidate source metadata differs from the run plan: {key}")
    if metadata_source.get("missing_candidate_policy") not in {"error", "generate"}:
        raise ValueError("Candidate source has an invalid missing-candidate policy")
    current_generation_fingerprint = _generation_fingerprint(config, implementation)
    if metadata_source.get("target_generation_fingerprint") != current_generation_fingerprint:
        raise ValueError("Candidate source target generation fingerprint is invalid")
    if metadata_source.get("source_generation_fingerprint") != current_generation_fingerprint:
        raise ValueError("Imported candidates were generated by an incompatible configuration or implementation")

    bundle_sha256 = str(metadata_source.get("source_bundle_manifest_sha256", ""))
    if SHA256_RE.fullmatch(bundle_sha256) is None:
        raise ValueError("Candidate source bundle has an invalid manifest digest")
    bundle_manifest_path = output_dir / "candidate_imports" / "sources" / bundle_sha256 / "manifest.json"
    _candidate_import_path(
        output_dir,
        metadata_source.get("source_bundle_manifest"),
        bundle_manifest_path,
        "Candidate source bundle",
    )
    if sha256_file(bundle_manifest_path) != bundle_sha256:
        raise ValueError("Candidate source bundle manifest digest mismatch")
    bundle_root = bundle_manifest_path.parent
    bundle = json.loads(bundle_manifest_path.read_text(encoding="utf-8"))
    if bundle.get("schema_version") != CANDIDATE_IMPORT_SCHEMA_VERSION:
        raise ValueError("Candidate source bundle has an unsupported schema")
    if bundle.get("source_run") != metadata_source.get("source_run"):
        raise ValueError("Candidate source bundle records a different source run")
    for path in bundle_root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Candidate source bundle contains a symlink: {path}")
    actual_bundle_files = _file_manifest(bundle_root, exclude={"manifest.json"})
    if bundle.get("files") != actual_bundle_files:
        raise ValueError("Candidate source bundle file manifest mismatch")

    source_config_path = bundle_root / "config.toml"
    source_catalog_path = bundle_root / "gdpval_benchmark.jsonl"
    source_catalog_provenance_path = bundle_root / "gdpval_benchmark.jsonl.provenance.json"
    source_implementation_path = bundle_root / "implementation.sha256.json"
    source_metadata_path = bundle_root / "run_metadata.json"
    source_plan_path = bundle_root / "run_plan.json"
    source_sessions_path = bundle_root / "endpoint_sessions.jsonl"
    source_preflight_path = bundle_root / "preflight.json"
    for path in (
        source_config_path,
        source_catalog_path,
        source_catalog_provenance_path,
        source_implementation_path,
        source_metadata_path,
        source_plan_path,
        source_sessions_path,
        source_preflight_path,
    ):
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"Candidate source bundle is missing a required file: {path}")

    source_config = tomllib.loads(source_config_path.read_text(encoding="utf-8"))
    source_implementation = json.loads(source_implementation_path.read_text(encoding="utf-8"))
    if not isinstance(source_implementation, dict):
        raise ValueError("Candidate source implementation manifest is not an object")
    source_fingerprint = _fingerprint(source_config, source_implementation)
    source_generation_fingerprint = _generation_fingerprint(source_config, source_implementation)
    if source_fingerprint != metadata_source.get("source_config_fingerprint"):
        raise ValueError("Candidate source config fingerprint mismatch")
    if source_generation_fingerprint != metadata_source.get("source_generation_fingerprint"):
        raise ValueError("Candidate source generation fingerprint mismatch")
    if bundle.get("source_config_fingerprint") != source_fingerprint:
        raise ValueError("Candidate source bundle config fingerprint mismatch")
    if bundle.get("source_generation_fingerprint") != source_generation_fingerprint:
        raise ValueError("Candidate source bundle generation fingerprint mismatch")

    source_catalog_rows = load_jsonl(source_catalog_path)
    source_catalog = {str(row["task_id"]): row for row in source_catalog_rows}
    if len(source_catalog) != len(source_catalog_rows):
        raise ValueError("Candidate source catalog contains duplicate task IDs")
    source_asset_manifest_shape = bind_manifest_to_catalog(load_asset_manifest(source_config), source_catalog_rows)
    source_catalog_provenance = _validate_catalog_provenance(
        source_catalog_path,
        source_config,
        source_catalog_rows,
        source_asset_manifest_shape,
    )
    if bundle.get("source_catalog_provenance_sha256") != source_catalog_provenance["sha256"]:
        raise ValueError("Candidate source bundle catalog provenance digest mismatch")
    if metadata_source.get("source_catalog_provenance_sha256") != source_catalog_provenance["sha256"]:
        raise ValueError("Candidate source metadata catalog provenance digest mismatch")

    for relative, expected_sha256 in _generation_implementation_hashes(source_implementation).items():
        source_path = bundle_root / "implementation" / relative
        if not source_path.is_file() or source_path.is_symlink() or sha256_file(source_path) != expected_sha256:
            raise ValueError(f"Candidate source generation implementation mismatch: {relative}")

    source_metadata = json.loads(source_metadata_path.read_text(encoding="utf-8"))
    source_deployments = {
        "policy": policy_deployment_identity(source_config["policy"]),
        "judge": judge_deployment_identity(source_config["judge"]),
    }
    if source_metadata.get("schema_version") != RUN_METADATA_SCHEMA_VERSION:
        raise ValueError("Candidate source run metadata has an unsupported schema version")
    if source_metadata.get("config_fingerprint") != source_fingerprint:
        raise ValueError("Candidate source run metadata has a mismatched fingerprint")
    if source_metadata.get("deployments") != source_deployments:
        raise ValueError("Candidate source run metadata has mismatched deployment provenance")
    if source_metadata.get("implementation") != source_implementation:
        raise ValueError("Candidate source run metadata has mismatched implementation hashes")
    source_run_path = Path(str(bundle["source_run"]))
    if not source_run_path.is_absolute():
        raise ValueError("Candidate source bundle source_run is not absolute")
    expected_source_catalog_provenance = source_catalog_provenance | {
        "path": str(source_run_path / source_catalog_provenance_path.name)
    }
    if source_metadata.get("catalog_provenance") != expected_source_catalog_provenance:
        raise ValueError("Candidate source run metadata has mismatched catalog provenance")
    if source_metadata.get("catalog_sha256") != source_catalog_provenance["catalog_sha256"]:
        raise ValueError("Candidate source run metadata has a mismatched catalog digest")
    if source_metadata.get("run_plan_sha256") != sha256_file(source_plan_path):
        raise ValueError("Candidate source run metadata has a mismatched run-plan digest")

    source_plan = json.loads(source_plan_path.read_text(encoding="utf-8"))
    if source_plan.get("config_fingerprint") != source_fingerprint:
        raise ValueError("Candidate source run plan has a mismatched fingerprint")
    if source_plan.get("catalog_sha256") != source_catalog_provenance["catalog_sha256"]:
        raise ValueError("Candidate source run plan has a mismatched catalog digest")
    if source_plan.get("catalog_provenance_sha256") != source_catalog_provenance["sha256"]:
        raise ValueError("Candidate source run plan has a mismatched catalog provenance digest")
    source_planned_keys = {(str(row["task_id"]), int(row["trial"])) for row in source_plan.get("trials", [])}
    if len(source_planned_keys) != len(source_plan.get("trials", [])):
        raise ValueError("Candidate source run plan contains duplicate task/trial keys")
    source_sessions: dict[str, dict[str, Any]] = {}
    for row in load_jsonl(source_sessions_path):
        session_id = row.get("endpoint_session_id")
        if not isinstance(session_id, str) or not session_id or session_id in source_sessions:
            raise ValueError("Candidate source has an invalid or duplicate endpoint session")
        _validate_endpoint_session_row(row, source_config, context=f"Candidate source session {session_id}")
        source_sessions[session_id] = row

    source_preflight = json.loads(source_preflight_path.read_text(encoding="utf-8"))
    source_preflight_sha256 = sha256_file(source_preflight_path)
    source_preflight_record = source_metadata.get("preflight")
    if (
        not isinstance(source_preflight_record, dict)
        or source_preflight_record.get("path")
        != str(source_run_path / "preflights" / f"{source_preflight_sha256}.json")
        or source_preflight_record.get("sha256") != source_preflight_sha256
        or bundle.get("source_preflight_sha256") != source_preflight_sha256
    ):
        raise ValueError("Candidate source preflight digest does not match its provenance")
    _validate_generation_preflight(source_preflight, source_config, source_fingerprint)

    candidate_rows = bundle.get("candidate_index", [])
    missing_rows = bundle.get("missing_candidates", [])
    if not isinstance(candidate_rows, list) or not isinstance(missing_rows, list):
        raise ValueError("Candidate source bundle has an invalid candidate index")
    candidate_index: dict[tuple[str, int], dict[str, Any]] = {}
    for row in candidate_rows:
        key = str(row["task_id"]), int(row["trial"])
        if key in candidate_index:
            raise ValueError(f"Candidate source bundle contains a duplicate candidate index: {key}")
        candidate_index[key] = row
    missing_candidates = {(str(row["task_id"]), int(row["trial"])) for row in missing_rows}
    if len(missing_candidates) != len(missing_rows):
        raise ValueError("Candidate source bundle contains duplicate missing candidates")
    if set(candidate_index) & missing_candidates:
        raise ValueError("Candidate source bundle marks the same candidate present and missing")
    current_planned_keys = {(str(row["task_id"]), int(row["trial"])) for row in run_plan.get("trials", [])}
    if set(candidate_index) | missing_candidates != current_planned_keys:
        raise ValueError("Candidate source bundle index differs from the current run plan")
    if any(key not in source_planned_keys for key in candidate_index):
        raise ValueError("Candidate source bundle indexes a candidate outside the source run plan")
    if any(key[0] not in source_catalog for key in current_planned_keys):
        raise ValueError("Candidate source bundle references a task outside the source catalog")
    return {
        "bundle_manifest": bundle_manifest_path,
        "bundle_manifest_sha256": bundle_sha256,
        "source_run": bundle["source_run"],
        "config": source_config,
        "config_fingerprint": source_fingerprint,
        "generation_fingerprint": source_generation_fingerprint,
        "catalog": source_catalog,
        "planned_keys": source_planned_keys,
        "endpoint_sessions": source_sessions,
        "candidate_index": candidate_index,
        "missing_candidates": missing_candidates,
    }


def _audit_imported_candidate(
    *,
    output_dir: Path,
    fingerprint: str,
    key: tuple[str, int],
    task: dict[str, Any],
    candidate_dir: Path,
    candidate_manifest: dict[str, Any],
    source: dict[str, Any],
) -> dict[str, Any]:
    import_metadata = candidate_manifest.get("candidate_import")
    if (
        not isinstance(import_metadata, dict)
        or import_metadata.get("schema_version") != CANDIDATE_IMPORT_SCHEMA_VERSION
    ):
        raise ValueError(f"Imported candidate has invalid import metadata: {candidate_dir}")
    receipt_path = (
        output_dir / "candidate_imports" / "candidates" / f"task_{key[0]}" / f"repeat_{key[1]}" / "receipt.json"
    )
    _candidate_import_path(output_dir, import_metadata.get("receipt"), receipt_path, "Candidate import receipt")
    receipt_sha256 = sha256_file(receipt_path)
    if import_metadata.get("receipt_sha256") != receipt_sha256:
        raise ValueError(f"Candidate import receipt digest mismatch: {receipt_path}")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    original_manifest_path = receipt_path.parent / "source_candidate.json"
    _candidate_import_path(
        output_dir,
        receipt.get("source_candidate_manifest"),
        original_manifest_path,
        "Imported source candidate manifest",
    )
    original_manifest_sha256 = sha256_file(original_manifest_path)
    if receipt.get("source_candidate_manifest_sha256") != original_manifest_sha256:
        raise ValueError(f"Imported source candidate manifest digest mismatch: {original_manifest_path}")
    original_manifest = json.loads(original_manifest_path.read_text(encoding="utf-8"))
    if not isinstance(original_manifest, dict) or original_manifest.get("candidate_import") is not None:
        raise ValueError(f"Imported source candidate manifest is invalid: {original_manifest_path}")
    expected_manifest = original_manifest | {
        "config_fingerprint": fingerprint,
        "candidate_import": import_metadata,
    }
    if candidate_manifest != expected_manifest:
        raise ValueError(f"Imported candidate manifest was modified beyond its import envelope: {candidate_dir}")
    if (
        receipt.get("schema_version") != CANDIDATE_IMPORT_SCHEMA_VERSION
        or receipt.get("task_id") != key[0]
        or int(receipt.get("trial", -1)) != key[1]
        or receipt.get("source_run") != source["source_run"]
        or receipt.get("source_candidate_relative_path") != f"artifacts/task_{key[0]}/repeat_{key[1]}"
        or receipt.get("source_candidate_manifest_sha256") != import_metadata.get("source_candidate_manifest_sha256")
        or receipt.get("source_candidate_sha256") != candidate_manifest.get("candidate_sha256")
        or receipt.get("source_config_fingerprint") != source["config_fingerprint"]
        or receipt.get("source_generation_fingerprint") != source["generation_fingerprint"]
        or receipt.get("scorer_fingerprint") != fingerprint
        or receipt.get("files") != candidate_manifest.get("files")
        or receipt.get("task_record_sha256") != _sha256_json(task)
        or import_metadata.get("source_config_fingerprint") != source["config_fingerprint"]
        or import_metadata.get("source_generation_fingerprint") != source["generation_fingerprint"]
        or import_metadata.get("scorer_fingerprint") != fingerprint
        or receipt.get("source_bundle_manifest_sha256") != source["bundle_manifest_sha256"]
        or receipt.get("source_bundle_manifest") != source["bundle_manifest"].relative_to(output_dir).as_posix()
    ):
        raise ValueError(f"Candidate import receipt identity mismatch: {receipt_path}")
    if original_manifest.get("config_fingerprint") != source["config_fingerprint"]:
        raise ValueError(f"Imported source candidate has a mismatched source fingerprint: {original_manifest_path}")
    if (
        original_manifest.get("task_id") != key[0]
        or int(original_manifest.get("trial", -1)) != key[1]
        or original_manifest.get("candidate_sha256") != candidate_manifest.get("candidate_sha256")
        or original_manifest.get("files") != candidate_manifest.get("files")
    ):
        raise ValueError(f"Imported source candidate identity mismatch: {original_manifest_path}")
    if key not in source["planned_keys"] or source["catalog"].get(key[0]) != task:
        raise ValueError(f"Imported candidate does not match the source run plan and catalog: {key}")
    index = source["candidate_index"].get(key)
    if (
        not isinstance(index, dict)
        or index.get("candidate_sha256") != candidate_manifest.get("candidate_sha256")
        or index.get("candidate_manifest_sha256") != original_manifest_sha256
        or index.get("task_record_sha256") != _sha256_json(task)
    ):
        raise ValueError(f"Imported candidate does not match the source bundle index: {key}")
    source_session_id = original_manifest.get("policy_endpoint_session_id")
    source_session = source["endpoint_sessions"].get(str(source_session_id))
    source_policy = source["config"]["policy"]
    source_policy_deployment = policy_deployment_identity(source_policy)
    if (
        not isinstance(source_session, dict)
        or source_session.get("policy_required") is not True
        or source_session.get("policy_deployment_id") != source_policy_deployment["deployment_id"]
        or source_session.get("policy_slurm_job_id") != source_policy_deployment["slurm_job_id"]
        or source_session.get("policy", {}).get("model") != source_policy["model"]
        or not _probe_deployment_matches(source_session.get("policy"), source_policy_deployment)
        or source_session.get("policy", {}).get("server", {}).get("version") != source_policy["server_version"]
        or receipt.get("source_policy_endpoint_session_id") != source_session_id
    ):
        raise ValueError(f"Imported candidate has invalid source policy-session provenance: {key}")
    return {
        "task_id": key[0],
        "trial": key[1],
        "candidate_sha256": candidate_manifest["candidate_sha256"],
        "receipt": str(receipt_path),
        "receipt_sha256": receipt_sha256,
    }


def _render_manifest(path: Path) -> dict[str, Any]:
    marker = path / ".render_manifest.json"
    if not marker.is_file():
        raise ValueError(f"Missing rendered-bundle manifest: {marker}")
    manifest = json.loads(marker.read_text(encoding="utf-8"))
    actual = _file_manifest(path, exclude={".render_manifest.json"})
    if manifest.get("files") != actual:
        raise ValueError(f"Rendered-bundle file manifest mismatch: {path}")
    if not isinstance(manifest.get("identity"), dict):
        raise ValueError(f"Rendered-bundle identity is missing: {path}")
    return manifest


def _validate_endpoint_session_row(row: dict[str, Any], config: dict[str, Any], *, context: str) -> None:
    if row.get("schema_version") != ENDPOINT_SESSION_SCHEMA_VERSION:
        raise ValueError(f"{context} has an unsupported schema version")
    deployments = {
        "policy": policy_deployment_identity(config["policy"]),
        "judge": judge_deployment_identity(config["judge"]),
    }
    for role in ("policy", "judge"):
        required = row.get(f"{role}_required")
        if not isinstance(required, bool):
            raise ValueError(f"{context} has invalid {role}_required")
        expected_deployment = deployments[role]
        for key, value in expected_deployment.items():
            session_key = f"{role}_{key}" if key != "deployment_id" else f"{role}_deployment_id"
            if row.get(session_key) != value:
                raise ValueError(f"{context} has a mismatched {session_key}")
        probe = row.get(role)
        if required and not isinstance(probe, dict):
            raise ValueError(f"{context} has no {role} probe")
        if isinstance(probe, dict):
            if not _probe_deployment_matches(probe, expected_deployment):
                raise ValueError(f"{context} has mismatched {role} deployment provenance")
            expected_model = str(config[role]["model"])
            if probe.get("model") != expected_model:
                raise ValueError(f"{context} has a mismatched {role} model")
            advertised = probe.get("advertised_models")
            if not isinstance(advertised, list) or expected_model not in advertised:
                raise ValueError(f"{context} did not advertise the configured {role} model")
            if role == "policy" and probe.get("server", {}).get("version") != config[role]["server_version"]:
                raise ValueError(f"{context} has a mismatched policy server version")


def _endpoint_sessions(output_dir: Path, config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sessions: dict[str, dict[str, Any]] = {}
    for row in load_jsonl(output_dir / "endpoint_sessions.jsonl"):
        session_id = row.get("endpoint_session_id")
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("Endpoint session is missing a non-empty endpoint_session_id")
        if session_id in sessions:
            raise ValueError(f"Duplicate endpoint session: {session_id}")
        _validate_endpoint_session_row(row, config, context=f"Endpoint session {session_id}")
        sessions[session_id] = row
    return sessions


def _require_endpoint_session(
    sessions: dict[str, dict[str, Any]],
    session_id: Any,
    *,
    context: str,
    required_role: str | None = None,
) -> dict[str, Any]:
    if not isinstance(session_id, str) or not session_id:
        raise ValueError(f"{context} is missing endpoint_session_id")
    session = sessions.get(session_id)
    if session is None:
        raise ValueError(f"{context} references unknown endpoint session {session_id}")
    if required_role is not None and session.get(f"{required_role}_required") is not True:
        raise ValueError(f"{context} references a session without a required {required_role} endpoint")
    return session


def _audit_preflight(output_dir: Path, metadata: dict[str, Any], config: dict[str, Any]) -> dict[str, str] | None:
    policy_deployment = policy_deployment_identity(config["policy"])
    judge_deployment = judge_deployment_identity(config["judge"])
    if config.get("tools", {}).get("web_fetch_trust_env") is not False:
        raise ValueError("Audited GDPval runs must disable environment proxies for Stirrup web fetches")
    record = metadata.get("preflight")
    if record is None:
        if config["runtime"].get("require_preflight"):
            raise ValueError("Run metadata is missing the required preflight artifact")
        return None
    if not isinstance(record, dict):
        raise ValueError("Run metadata preflight record must be an object")
    expected_sha256 = record.get("sha256")
    if not isinstance(expected_sha256, str) or SHA256_RE.fullmatch(expected_sha256) is None:
        raise ValueError("Run metadata preflight record has an invalid SHA-256")
    recorded_path = record.get("path")
    if not isinstance(recorded_path, str) or not recorded_path:
        raise ValueError("Run metadata preflight record has no path")
    preflight_path = _require_run_path(
        recorded_path,
        output_dir=output_dir,
        expected=output_dir / "preflights" / f"{expected_sha256}.json",
        context="Preflight artifact",
    )
    if not preflight_path.is_file() or sha256_file(preflight_path) != expected_sha256:
        raise ValueError(f"Preflight artifact is missing or corrupt: {preflight_path}")
    payload = json.loads(preflight_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Preflight artifact must be an object")
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
    if payload.get("config_fingerprint") != metadata.get("config_fingerprint"):
        raise ValueError("Preflight artifact has a mismatched config fingerprint")
    if payload.get("policy_deployment_id") != policy_deployment["deployment_id"]:
        raise ValueError("Preflight artifact has a mismatched policy deployment identity")
    if payload.get("policy_slurm_job_id") != policy_deployment["slurm_job_id"]:
        raise ValueError("Preflight artifact has a mismatched policy Slurm job")
    if payload.get("judge_deployment_id") != judge_deployment["deployment_id"]:
        raise ValueError("Preflight artifact has a mismatched judge deployment identity")
    if payload.get("judge_proxy_jobid") != judge_deployment["proxy_jobid"]:
        raise ValueError("Preflight artifact has a mismatched judge proxy job")
    if payload.get("sandbox_image") != config["runtime"]["image"]:
        raise ValueError("Preflight artifact has a mismatched sandbox image")
    for role in ("policy", "judge"):
        probe = payload.get(role)
        if not isinstance(probe, dict):
            raise ValueError(f"Preflight artifact is missing the {role} semantic probe")
        expected_deployment = policy_deployment if role == "policy" else judge_deployment
        if not _probe_deployment_matches(probe, expected_deployment):
            raise ValueError(f"Preflight artifact has mismatched {role} deployment provenance")
        if probe.get("model") != config[role]["model"]:
            raise ValueError(f"Preflight artifact has a mismatched {role} model")
        if probe.get("chat", {}).get("matched_expected_answer") is not True:
            raise ValueError(f"Preflight artifact has no successful {role} text probe")
    if payload["policy"].get("tool_call", {}).get("arguments_valid") is not True:
        raise ValueError("Preflight artifact has no successful policy tool-call probe")
    if payload["policy"].get("server", {}).get("version") != config["policy"]["server_version"]:
        raise ValueError("Preflight artifact has a mismatched policy server version")
    if not any(
        item.get("id") == config["policy"]["model"]
        and int(item.get("max_model_len", -1)) == int(config["policy"]["context_window"])
        for item in payload["policy"].get("advertised_model_metadata", [])
        if isinstance(item, dict)
    ):
        raise ValueError("Preflight artifact does not confirm the configured policy context window")
    if payload["judge"].get("visual_chat", {}).get("matched_expected_answer") is not True:
        raise ValueError("Preflight artifact has no successful judge visual probe")
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
        raise ValueError("Preflight artifact has no successful scoped Stirrup web-fetch probe")
    if (
        config.get("tools", {}).get("require_brave_search")
        and payload.get("web_search", {}).get("matched_expected_shape") is not True
    ):
        raise ValueError("Preflight artifact has no successful Brave Search probe")
    return {"path": str(preflight_path), "sha256": expected_sha256}


def _comparison_outcome(raw_response: str, trial: int) -> str:
    matches = BOXED_RE.findall(raw_response)
    if not matches:
        return "invalid"
    if matches[-1] == "TIE":
        return "tie"
    return "win" if (matches[-1] == "A") == bool(trial % 2) else "loss"


def _audit_matchup(
    matchup: dict[str, Any],
    *,
    output_dir: Path,
    expected_task_id: str,
    expected_trial: int,
    expected_trials: int,
    format_retries: int,
    endpoint_sessions: dict[str, dict[str, Any]],
    candidate_manifest: dict[str, Any],
    reference_source: str,
    expected_input_assets: list[dict[str, str]],
    expected_reference_assets: list[dict[str, str]] | None,
    task_prompt: str,
    candidate_dir: Path,
    judge_config: dict[str, Any],
) -> dict[str, Any]:
    if matchup.get("mode") != "comparison":
        raise ValueError(f"Unexpected matchup mode for task {expected_task_id}: {matchup.get('mode')!r}")
    reference_inputs_dir_value = matchup.get("reference_inputs_dir")
    if reference_inputs_dir_value:
        reference_inputs_dir = _require_run_path(
            reference_inputs_dir_value,
            output_dir=output_dir,
            expected=output_dir / "rendered_inputs" / f"task_{expected_task_id}",
            context=f"Reference-input bundle for task {expected_task_id}",
        )
        if not reference_inputs_dir.is_dir():
            raise ValueError(f"Missing reference-input directory: {reference_inputs_dir}")
        if matchup.get("reference_input_files") != _file_manifest(
            reference_inputs_dir,
            exclude={".render_manifest.json"},
        ):
            raise ValueError(f"Reference-input manifest mismatch: {reference_inputs_dir}")
        input_render_manifest = _render_manifest(reference_inputs_dir)
        input_identity = input_render_manifest["identity"]
        if (
            input_identity.get("task_id") != expected_task_id
            or input_identity.get("source") != "dataset_reference_inputs"
            or input_identity.get("assets") != expected_input_assets
            or candidate_manifest.get("reference_input_assets") != expected_input_assets
            or input_identity.get("expected_assets") != candidate_manifest.get("reference_input_assets")
        ):
            raise ValueError(f"Reference-input render identity mismatch: {reference_inputs_dir}")
    else:
        if matchup.get("reference_input_files") != []:
            raise ValueError(f"Reference-input manifest is present without a directory for task {expected_task_id}")
        if expected_input_assets:
            raise ValueError(f"Reference-input directory is missing for task {expected_task_id}")
    reference_component = _safe_component(str(matchup.get("reference_id")))
    repeat_component = _safe_component(str(matchup.get("reference_repeat")))
    reference_dir = _require_run_path(
        matchup.get("reference_dir"),
        output_dir=output_dir,
        expected=(
            output_dir / "rendered_references" / f"task_{expected_task_id}" / reference_component / repeat_component
        ),
        context=f"Reference bundle for task {expected_task_id}",
    )
    if not reference_dir.is_dir():
        raise ValueError(f"Missing reference directory: {reference_dir}")
    if matchup.get("reference_files") != _file_manifest(
        reference_dir,
        exclude={".render_manifest.json"},
        exclude_top_level_dirs={"reference_files"},
    ):
        raise ValueError(f"Reference manifest mismatch: {reference_dir}")
    reference_render_manifest = _render_manifest(reference_dir)
    reference_identity = reference_render_manifest["identity"]
    if (
        reference_identity.get("task_id") != expected_task_id
        or reference_identity.get("reference_id") != matchup.get("reference_id")
        or reference_identity.get("repeat") != matchup.get("reference_repeat")
        or reference_identity.get("source") != reference_source
    ):
        raise ValueError(f"Reference render identity mismatch: {reference_dir}")
    if expected_reference_assets is not None and reference_identity.get("assets") != expected_reference_assets:
        raise ValueError(f"Reference render assets do not match the pinned catalog: {reference_dir}")
    render_kwargs = {
        "dpi": int(judge_config["pdf_render_dpi"]),
        "max_pages": int(judge_config["pdf_max_pages"]),
        "include_text": bool(judge_config["pdf_include_text"]),
        "max_file_bytes": int(judge_config["max_file_bytes"]),
        "deduplicate_office_pdf_sidecars": bool(judge_config["deduplicate_office_pdf_sidecars"]),
        "max_visual_blocks": int(judge_config["max_visual_blocks_per_section"]),
        "max_text_characters": int(judge_config["max_text_characters_per_section"]),
    }
    reference_inputs = _render_directory(reference_inputs_dir if reference_inputs_dir_value else None, **render_kwargs)
    reference_submission = _render_directory(
        reference_dir,
        exclude_top_level_dirs={"reference_files"},
        **render_kwargs,
    )
    candidate_submission = _render_directory(
        candidate_dir,
        exclude_top_level_dirs={"reference_files"},
        **render_kwargs,
    )
    request_identity = {
        "task_id": expected_task_id,
        "prompt": task_prompt,
        "reference_id": matchup["reference_id"],
        "reference_repeat": matchup["reference_repeat"],
        "reference_elo": float(matchup["reference_elo"]),
        "reference_inputs": _judge_file_manifest(reference_inputs_dir if reference_inputs_dir_value else None),
        "reference_submission": _judge_file_manifest(
            reference_dir,
            exclude_top_level_dirs={"reference_files"},
        ),
        "candidate_submission": _judge_file_manifest(
            candidate_dir,
            exclude_top_level_dirs={"reference_files"},
        ),
        "judge": {key: value for key, value in judge_config.items() if "key" not in key},
    }
    journal_path = _require_run_path(
        matchup.get("judge_journal"),
        output_dir=output_dir,
        expected=(
            output_dir
            / "judgements"
            / f"task_{expected_task_id}"
            / f"repeat_{expected_trial}.{reference_component}.{repeat_component}.jsonl"
        ),
        context=f"Judge journal for task {expected_task_id}",
    )
    calls = load_jsonl(journal_path)
    grouped: dict[int, list[dict[str, Any]]] = {}
    observed_order: list[int] = []
    for call in calls:
        trial = int(call.get("trial", -1))
        grouped.setdefault(trial, []).append(call)
        observed_order.append(trial)
    if set(grouped) != set(range(expected_trials)):
        raise ValueError(f"Judge journal must cover trials 0..{expected_trials - 1}: {journal_path}")
    expected_order = [trial for trial in range(expected_trials) for _ in grouped[trial]]
    if observed_order != expected_order:
        raise ValueError(f"Judge journal trials are out of order: {journal_path}")

    accepted: list[dict[str, Any]] = []
    request_hashes: list[str] = []
    for trial in range(expected_trials):
        trial_rows = grouped[trial]
        if len(trial_rows) > format_retries:
            raise ValueError(f"Judge format retries exceeded for trial {trial}: {journal_path}")
        if [int(row.get("format_attempt", -1)) for row in trial_rows] != list(range(1, len(trial_rows) + 1)):
            raise ValueError(f"Non-contiguous judge format attempts for trial {trial}: {journal_path}")
        swapped = bool(trial % 2)
        submission_a = candidate_submission if swapped else reference_submission
        submission_b = reference_submission if swapped else candidate_submission
        messages = _pairwise_messages(task_prompt, reference_inputs, submission_a, submission_b)
        expected_request_sha256 = _sha256_json(
            request_identity
            | {
                "trial": trial,
                "swapped": swapped,
                "messages_sha256": _sha256_json(messages),
            }
        )
        trial_hashes: set[str] = set()
        for call in trial_rows:
            if call.get("task_id") != expected_task_id or call.get("mode") != "comparison":
                raise ValueError(f"Judge journal identity mismatch: {journal_path}, trial {trial}")
            _require_endpoint_session(
                endpoint_sessions,
                call.get("endpoint_session_id"),
                context=f"Judge journal {journal_path}, trial {trial}",
                required_role="judge",
            )
            raw_response = call.get("raw_response")
            if not isinstance(raw_response, str):
                raise ValueError(f"Judge response is not text: {journal_path}, trial {trial}")
            response_sha256 = hashlib.sha256(raw_response.encode()).hexdigest()
            if call.get("response_sha256") != response_sha256:
                raise ValueError(f"Judge response digest mismatch: {journal_path}, trial {trial}")
            if call.get("swapped") != bool(trial % 2):
                raise ValueError(f"Judge swap bit mismatch: {journal_path}, trial {trial}")
            expected_outcome = _comparison_outcome(raw_response, trial)
            if call.get("outcome") != expected_outcome:
                raise ValueError(f"Judge parsed outcome mismatch: {journal_path}, trial {trial}")
            request_sha256 = call.get("request_sha256")
            if not isinstance(request_sha256, str) or SHA256_RE.fullmatch(request_sha256) is None:
                raise ValueError(f"Judge request fingerprint is missing: {journal_path}, trial {trial}")
            if request_sha256 != expected_request_sha256:
                raise ValueError(f"Judge request fingerprint mismatch: {journal_path}, trial {trial}")
            trial_hashes.add(request_sha256)
        if len(trial_hashes) != 1:
            raise ValueError(f"Judge format retries changed the request: {journal_path}, trial {trial}")
        request_hashes.append(next(iter(trial_hashes)))
        valid = [row for row in trial_rows if row.get("outcome") != "invalid"]
        if valid:
            if len(valid) != 1 or trial_rows[-1] is not valid[0]:
                raise ValueError(f"Judge journal continued after a valid result: {journal_path}, trial {trial}")
            accepted.append(valid[0])
        else:
            if len(trial_rows) != format_retries:
                raise ValueError(f"Incomplete invalid judge retry chain: {journal_path}, trial {trial}")
            accepted.append(trial_rows[-1])
    if len(set(request_hashes)) != expected_trials:
        raise ValueError(f"Judge request fingerprints are duplicated across trials: {journal_path}")
    observed = {
        "wins": sum(call.get("outcome") == "win" for call in accepted),
        "losses": sum(call.get("outcome") == "loss" for call in accepted),
        "ties": sum(call.get("outcome") == "tie" for call in accepted),
        "invalid_trials": sum(call.get("outcome") == "invalid" for call in accepted),
    }
    if any(matchup.get(key) != value for key, value in observed.items()):
        raise ValueError(f"Judge tally mismatch: {journal_path}")
    valid_trials = observed["wins"] + observed["losses"] + observed["ties"]
    if valid_trials == 0:
        raise ValueError(f"Completed matchup has no valid judge trials: {journal_path}")
    reward = 1.0 if observed["wins"] > observed["losses"] else 0.0 if observed["losses"] > observed["wins"] else 0.5
    if matchup.get("reward") != reward:
        raise ValueError(f"Judge reward mismatch: {journal_path}")
    return observed | {
        "reward": reward,
        "reference_id": str(matchup["reference_id"]),
        "reference_repeat": str(matchup["reference_repeat"]),
        "reference_elo": float(matchup["reference_elo"]),
    }


def _audit_comparison_score(
    row: dict[str, Any],
    output_dir: Path,
    config: dict[str, Any],
    expected_trials: int,
    endpoint_sessions: dict[str, dict[str, Any]],
    candidate_manifest: dict[str, Any],
    candidate_dir: Path,
    task: dict[str, Any],
) -> dict[str, Any]:
    task_id = str(row["task_id"])
    score = row.get("score")
    if not isinstance(score, dict) or score.get("mode") != "comparison":
        raise ValueError(f"Completed comparison result has an invalid score for task {task_id}")
    matchups = score.get("matchups")
    if not isinstance(matchups, list) or not matchups:
        raise ValueError(f"Completed comparison result has no matchups for task {task_id}")
    assigned_reference = _assigned_reference(config, task_id)
    if assigned_reference is None:
        raise ValueError(f"No configured reference is assigned to task {task_id}")
    expected_reference_id = str(assigned_reference["id"])
    expected_reference_elo = float(assigned_reference["elo"])
    expected_input_assets = _reference_input_specs(task, config)
    expected_reference_assets = (
        _expert_deliverable_specs(task, config) if assigned_reference.get("source") == "dataset_deliverables" else None
    )
    audited = [
        _audit_matchup(
            matchup,
            output_dir=output_dir,
            expected_task_id=task_id,
            expected_trial=int(row["trial"]),
            expected_trials=expected_trials,
            format_retries=int(config["judge"]["format_retries"]),
            endpoint_sessions=endpoint_sessions,
            candidate_manifest=candidate_manifest,
            reference_source=str(assigned_reference.get("source", "external")),
            expected_input_assets=expected_input_assets,
            expected_reference_assets=expected_reference_assets,
            task_prompt=str(task["prompt"]),
            candidate_dir=candidate_dir,
            judge_config=config["judge"],
        )
        for matchup in matchups
    ]
    identities = [(item["reference_id"], item["reference_repeat"]) for item in audited]
    if len(set(identities)) != len(identities):
        raise ValueError(f"Duplicate reference repeat in result for task {task_id}")
    if any(
        item["reference_id"] != expected_reference_id or item["reference_elo"] != expected_reference_elo
        for item in audited
    ):
        raise ValueError(f"Matchup reference does not match the configured assignment for task {task_id}")
    observed = {
        key: sum(int(matchup[key]) for matchup in audited) for key in ("wins", "losses", "ties", "invalid_trials")
    }
    reward = 1.0 if observed["wins"] > observed["losses"] else 0.0 if observed["losses"] > observed["wins"] else 0.5
    expected_top_level = observed | {
        "reward": reward,
        "reference_id": expected_reference_id,
        "reference_elo": expected_reference_elo,
        "reference_repeats": len(matchups),
    }
    if any(score.get(key) != value for key, value in expected_top_level.items()):
        raise ValueError(f"Comparison aggregate mismatch for task {task_id}")
    if row.get("reward") != reward:
        raise ValueError(f"Result reward mismatch for task {task_id}")
    return expected_top_level


def audit(output_dir: Path) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    metadata_path = output_dir / "run_metadata.json"
    if not metadata_path.is_file():
        raise ValueError(f"Missing run metadata: {metadata_path}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("schema_version") != RUN_METADATA_SCHEMA_VERSION:
        raise ValueError("Run metadata has an unsupported schema version")
    fingerprint = str(metadata["config_fingerprint"])
    config = tomllib.loads((output_dir / "config.toml").read_text(encoding="utf-8"))
    expected_deployments = {
        "policy": policy_deployment_identity(config["policy"]),
        "judge": judge_deployment_identity(config["judge"]),
    }
    if metadata.get("deployments") != expected_deployments:
        raise ValueError("Run metadata has mismatched resolved deployment provenance")
    snapshot_hashes = json.loads((output_dir / "implementation.sha256.json").read_text(encoding="utf-8"))
    if _fingerprint(config, snapshot_hashes) != fingerprint:
        raise ValueError("Config/source fingerprint does not match run metadata")
    catalog_path = output_dir / "gdpval_benchmark.jsonl"
    catalog_rows = load_jsonl(catalog_path)
    catalog = {str(row["task_id"]): row for row in catalog_rows}
    if len(catalog) != len(catalog_rows):
        raise ValueError("Catalog contains duplicate task IDs")
    asset_manifest = load_asset_manifest(config)
    asset_manifest_shape = bind_manifest_to_catalog(asset_manifest, catalog_rows)
    catalog_provenance = _validate_catalog_provenance(
        catalog_path,
        config,
        catalog_rows,
        asset_manifest_shape,
    )
    if metadata.get("catalog_provenance") != catalog_provenance:
        raise ValueError("Catalog provenance does not match run metadata")
    if metadata.get("catalog_sha256") != catalog_provenance["catalog_sha256"]:
        raise ValueError("Catalog digest does not match run metadata")
    run_plan_path = output_dir / "run_plan.json"
    if metadata.get("run_plan_sha256") != sha256_file(run_plan_path):
        raise ValueError("Run-plan digest does not match run metadata")
    run_plan = json.loads(run_plan_path.read_text(encoding="utf-8"))
    if run_plan.get("config_fingerprint") != fingerprint:
        raise ValueError("Run-plan/config fingerprint mismatch")
    if run_plan.get("scorer_fingerprint", fingerprint) != fingerprint:
        raise ValueError("Run-plan/scorer fingerprint mismatch")
    if run_plan.get("catalog_sha256") != catalog_provenance["catalog_sha256"]:
        raise ValueError("Run plan has a mismatched catalog digest")
    if run_plan.get("catalog_provenance_sha256") != catalog_provenance["sha256"]:
        raise ValueError("Run plan has a mismatched catalog provenance digest")
    if metadata.get("scorer_fingerprint", fingerprint) != fingerprint:
        raise ValueError("Run metadata/scorer fingerprint mismatch")
    if run_plan.get("candidate_source") is not None and (
        "scorer_fingerprint" not in run_plan or "scorer_fingerprint" not in metadata
    ):
        raise ValueError("Candidate-import runs must record an explicit scorer fingerprint")
    planned_keys = {(str(row["task_id"]), int(row["trial"])) for row in run_plan["trials"]}
    if len(planned_keys) != len(run_plan["trials"]):
        raise ValueError("Run plan contains duplicate task/trial keys")
    if int(metadata.get("expected_results", -1)) != len(planned_keys):
        raise ValueError("Run metadata expected count does not match the run plan")
    planned_task_count = len({task_id for task_id, _ in planned_keys})
    if int(metadata.get("selected_tasks", -1)) != planned_task_count:
        raise ValueError("Run metadata task count does not match the run plan")
    candidate_source = _audit_candidate_source_bundle(
        output_dir,
        config,
        snapshot_hashes,
        run_plan,
        metadata,
    )
    if metadata.get("asset_manifest") != asset_manifest_shape:
        raise ValueError("Run metadata asset-manifest shape does not match the implementation snapshot")
    planned_task_ids = {task_id for task_id, _ in planned_keys}
    selected_tasks = [row for row in catalog_rows if str(row["task_id"]) in planned_task_ids]
    selected_assets = _required_asset_entries(asset_manifest, selected_tasks, config)
    expected_asset_selection = asset_selection_provenance(config, selected_assets)
    asset_mirror = metadata.get("asset_mirror")
    if not isinstance(asset_mirror, dict) or any(
        asset_mirror.get(key) != value for key, value in expected_asset_selection.items()
    ):
        raise ValueError("Run metadata asset selection does not match the pinned manifest and run plan")
    if (
        Path(str(asset_mirror.get("cache_dir", ""))).expanduser().resolve()
        != Path(config["source"]["asset_cache_dir"]).expanduser().resolve()
    ):
        raise ValueError("Run metadata has a mismatched GDPval asset-cache path")
    if (
        asset_mirror.get("ready") is not True
        or asset_mirror.get("hashes_verified") is not True
        or int(asset_mirror.get("cached_assets", -1)) != int(asset_mirror.get("selected_assets", -2))
        or int(asset_mirror.get("missing_assets", -1)) != 0
        or int(asset_mirror.get("corrupt_assets", -1)) != 0
    ):
        raise ValueError("Run metadata does not prove a complete verified asset cache")
    cache_record = metadata.get("asset_cache_provenance")
    if not isinstance(cache_record, dict):
        raise ValueError("Run metadata is missing the asset-cache provenance snapshot")
    cache_snapshot_path = _require_run_path(
        cache_record.get("path"),
        output_dir=output_dir,
        expected=output_dir / "asset_cache_provenance.json",
        context="Asset-cache provenance snapshot",
    )
    cache_snapshot_sha256 = str(cache_record.get("sha256", ""))
    if SHA256_RE.fullmatch(cache_snapshot_sha256) is None:
        raise ValueError("Asset-cache provenance snapshot has an invalid SHA-256")
    if not cache_snapshot_path.is_file() or sha256_file(cache_snapshot_path) != cache_snapshot_sha256:
        raise ValueError("Asset-cache provenance snapshot is missing or corrupt")
    if json.loads(cache_snapshot_path.read_text(encoding="utf-8")) != asset_mirror:
        raise ValueError("Asset-cache provenance snapshot differs from run metadata")
    if run_plan.get("asset_manifest_sha256") != config["source"]["asset_manifest_sha256"]:
        raise ValueError("Run plan has a mismatched asset manifest SHA-256")
    if run_plan.get("selected_asset_manifest_sha256") != expected_asset_selection["selected_manifest_sha256"]:
        raise ValueError("Run plan has a mismatched selected-asset digest")
    if int(run_plan.get("selected_assets", -1)) != len(selected_assets):
        raise ValueError("Run plan has a mismatched selected-asset count")
    expected_judge_trials = int(config["scoring"]["num_trials"])
    results = load_jsonl(output_dir / "results.jsonl")
    attempts = load_jsonl(output_dir / "attempts.jsonl")
    preflight = _audit_preflight(output_dir, metadata, config)
    tools_metadata = metadata.get("tools")
    if (
        not isinstance(tools_metadata, dict)
        or tools_metadata.get("web_fetch") is not True
        or tools_metadata.get("web_fetch_trust_env") is not config["tools"]["web_fetch_trust_env"]
        or tools_metadata.get("web_search") is not bool(config["tools"]["require_brave_search"])
    ):
        raise ValueError("Run metadata has mismatched Stirrup web-fetch transport provenance")
    endpoint_sessions = _endpoint_sessions(output_dir, config)
    metadata_endpoint_session_id = metadata.get("endpoint_session_id")
    if metadata_endpoint_session_id:
        metadata_endpoint_session = _require_endpoint_session(
            endpoint_sessions,
            metadata_endpoint_session_id,
            context="Run metadata",
        )
        for role in ("policy", "judge"):
            if metadata.get(role) != metadata_endpoint_session.get(role):
                raise ValueError(f"Run metadata {role} probe does not match its endpoint session")
    elif results or attempts:
        raise ValueError("Run metadata is missing endpoint_session_id")

    imported_candidates: dict[tuple[str, int], dict[str, Any]] = {}
    import_rows = metadata.get("candidate_imports") or []
    if not isinstance(import_rows, list):
        raise ValueError("Run metadata candidate_imports is not a list")
    if import_rows and candidate_source is None:
        raise ValueError("Run metadata has imported candidates without source provenance")
    for recorded in import_rows:
        if not isinstance(recorded, dict):
            raise ValueError("Run metadata contains an invalid candidate-import record")
        key = str(recorded.get("task_id")), int(recorded.get("trial", -1))
        if key in imported_candidates or key not in planned_keys:
            raise ValueError(f"Run metadata contains a duplicate or unplanned candidate import: {key}")
        candidate_dir = output_dir / "artifacts" / f"task_{key[0]}" / f"repeat_{key[1]}"
        candidate_manifest = _candidate_manifest(candidate_dir)
        audited = _audit_imported_candidate(
            output_dir=output_dir,
            fingerprint=fingerprint,
            key=key,
            task=catalog[key[0]],
            candidate_dir=candidate_dir,
            candidate_manifest=candidate_manifest,
            source=candidate_source,
        )
        if recorded != audited:
            raise ValueError(f"Run metadata candidate-import record mismatch: {key}")
        imported_candidates[key] = audited
    receipt_paths = {
        path.resolve()
        for path in (output_dir / "candidate_imports" / "candidates").glob("task_*/repeat_*/receipt.json")
        if path.is_file()
    }
    expected_receipts = {Path(row["receipt"]).resolve() for row in imported_candidates.values()}
    if receipt_paths != expected_receipts:
        raise ValueError("Candidate import receipt set differs from run metadata")
    recorded_missing = {
        (str(row["task_id"]), int(row["trial"])) for row in metadata.get("candidate_source_missing") or []
    }
    if candidate_source is not None:
        if recorded_missing != candidate_source["missing_candidates"]:
            raise ValueError("Candidate source missing set differs from its frozen source bundle")
        if metadata["candidate_source"].get("missing_candidate_policy") == "error" and recorded_missing:
            raise ValueError("Candidate source used error policy but recorded missing candidates")
        if set(imported_candidates) != set(candidate_source["candidate_index"]):
            raise ValueError("Imported candidate set differs from the frozen source bundle index")
    elif recorded_missing:
        raise ValueError("Run metadata records source-missing candidates without a source bundle")

    result_keys: set[tuple[str, int]] = set()
    results_by_key: dict[tuple[str, int], dict[str, Any]] = {}
    candidate_count = 0
    comparison_totals: dict[str, dict[str, Any]] = {}
    for row in results:
        if row.get("config_fingerprint") != fingerprint:
            raise ValueError("Result/config fingerprint mismatch")
        if row.get("status") not in SCORED_STATUSES:
            raise ValueError(f"Unscored status in results.jsonl: {row.get('status')!r}")
        key = str(row["task_id"]), int(row["trial"])
        if key in result_keys:
            raise ValueError(f"Duplicate result: {key}")
        if key not in planned_keys:
            raise ValueError(f"Result is outside the run plan: {key}")
        result_keys.add(key)
        results_by_key[key] = row
        required_role = "judge" if row["status"] == "completed" else "policy"
        _require_endpoint_session(
            endpoint_sessions,
            row.get("endpoint_session_id"),
            context=f"Result {key}",
            required_role=required_role,
        )
        if row["status"] == "completed":
            candidate = _require_run_path(
                row.get("candidate_dir"),
                output_dir=output_dir,
                expected=output_dir / "artifacts" / f"task_{key[0]}" / f"repeat_{key[1]}",
                context=f"Candidate for result {key}",
            )
            manifest = _candidate_manifest(candidate)
            if row.get("candidate_sha256") != manifest.get("candidate_sha256"):
                raise ValueError(f"Candidate digest mismatch in result for {key}")
            if (
                manifest.get("task_id") != key[0]
                or int(manifest.get("trial", -1)) != key[1]
                or manifest.get("config_fingerprint") != fingerprint
                or manifest.get("web_fetch_trust_env") is not config["tools"]["web_fetch_trust_env"]
                or manifest.get("web_search_available") is not bool(config["tools"]["require_brave_search"])
            ):
                raise ValueError(f"Candidate identity mismatch in result for {key}")
            if manifest.get("candidate_import") is not None:
                if key not in imported_candidates:
                    raise ValueError(f"Result references an unrecorded imported candidate: {key}")
            else:
                if key in imported_candidates:
                    raise ValueError(f"Imported-candidate record points to a generated candidate: {key}")
                _require_endpoint_session(
                    endpoint_sessions,
                    manifest.get("policy_endpoint_session_id"),
                    context=f"Candidate {candidate}",
                    required_role="policy",
                )
            if config["scoring"]["mode"] == "comparison":
                if key[0] not in catalog:
                    raise ValueError(f"Result task is missing from the catalog: {key[0]}")
                audited_score = _audit_comparison_score(
                    row,
                    output_dir,
                    config,
                    expected_judge_trials,
                    endpoint_sessions,
                    manifest,
                    candidate,
                    catalog[key[0]],
                )
                reference_id = str(audited_score["reference_id"])
                bucket = comparison_totals.setdefault(
                    reference_id,
                    {
                        "reference_elo": float(audited_score["reference_elo"]),
                        "wins": 0,
                        "losses": 0,
                        "ties": 0,
                        "invalid_trials": 0,
                        "result_reward_sum": 0.0,
                        "results": 0,
                    },
                )
                if bucket["reference_elo"] != float(audited_score["reference_elo"]):
                    raise ValueError(f"Reference Elo changed within pooled results for {reference_id}")
                for field in ("wins", "losses", "ties", "invalid_trials"):
                    bucket[field] += int(audited_score[field])
                bucket["result_reward_sum"] += float(audited_score["reward"])
                bucket["results"] += 1
            else:
                score = row.get("score")
                if not isinstance(score, dict) or score.get("mode") != config["scoring"]["mode"]:
                    raise ValueError(f"Completed result has a mismatched scoring mode for {key}")
                if row.get("reward") != score.get("reward"):
                    raise ValueError(f"Result reward mismatch for {key}")
                rubric_journal = _require_run_path(
                    score.get("judge_journal"),
                    output_dir=output_dir,
                    expected=output_dir / "judgements" / f"task_{key[0]}" / f"repeat_{key[1]}.jsonl",
                    context=f"Judge journal for result {key}",
                )
                if not rubric_journal.is_file():
                    raise ValueError(f"Judge journal is missing for result {key}")
            candidate_count += 1
        elif row.get("reward") != 0.0:
            raise ValueError(f"Terminal model failure must have reward 0.0 for {key}")
    for bucket in comparison_totals.values():
        bucket["valid_trials"] = bucket["wins"] + bucket["losses"] + bucket["ties"]
        bucket["mean_result_reward"] = bucket["result_reward_sum"] / bucket["results"]

    histories: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in attempts:
        if row.get("schema_version") != 1:
            raise ValueError("Attempt has an unsupported schema version")
        if row.get("config_fingerprint") != fingerprint:
            raise ValueError("Attempt/config fingerprint mismatch")
        key = str(row["task_id"]), int(row["trial"])
        if key not in planned_keys:
            raise ValueError(f"Attempt is outside the run plan: {key}")
        attempt_status = str(row.get("status"))
        required_role = _attempt_endpoint_role(row, context=f"Attempt {key}:{row['attempt']}")
        _require_endpoint_session(
            endpoint_sessions,
            row.get("endpoint_session_id"),
            context=f"Attempt {key}:{row['attempt']}",
            required_role=required_role,
        )
        histories.setdefault(key, []).append(row)
        attempt_number = int(row["attempt"])
        stem = f"{key[0]}.trial_{key[1]}.attempt_{attempt_number}"
        worker_log = _require_run_path(
            row.get("worker_log"),
            output_dir=output_dir,
            expected=output_dir / "worker_logs" / f"{stem}.log",
            context=f"Worker log for attempt {key}:{attempt_number}",
        )
        if not worker_log.is_file() or row.get("worker_log_sha256") != sha256_file(worker_log):
            raise ValueError(f"Worker log is missing or corrupt for attempt {key}:{attempt_number}")
        worker_result_value = row.get("worker_result")
        worker_result_path = _require_run_path(
            worker_result_value,
            output_dir=output_dir,
            expected=output_dir / "worker_results" / f"{stem}.json",
            context=f"Worker result for attempt {key}:{attempt_number}",
        )
        if not worker_result_path.is_file():
            raise ValueError(f"Worker result is missing for attempt {key}:{row['attempt']}")
        worker_result = json.loads(worker_result_path.read_text(encoding="utf-8"))
        if (
            worker_result.get("schema_version") != 1
            or worker_result.get("task_id") != key[0]
            or int(worker_result.get("trial", -1)) != key[1]
            or int(worker_result.get("attempt", -1)) != int(row["attempt"])
            or worker_result.get("config_fingerprint") != fingerprint
            or worker_result.get("status") != row.get("status")
            or worker_result.get("endpoint_session_id") != row.get("endpoint_session_id")
            or worker_result.get("failure_role") != row.get("failure_role")
            or worker_result.get("candidate_dir") != row.get("candidate_dir")
            or worker_result.get("candidate_sha256") != row.get("candidate_sha256")
        ):
            raise ValueError(f"Worker result identity mismatch for attempt {key}:{row['attempt']}")
        required_role = _attempt_endpoint_role(
            worker_result,
            context=f"Worker result {key}:{row['attempt']}",
        )
        _require_endpoint_session(
            endpoint_sessions,
            worker_result.get("endpoint_session_id"),
            context=f"Worker result for attempt {key}:{row['attempt']}",
            required_role=required_role,
        )
        candidate_dir_value = row.get("candidate_dir")
        candidate_sha256 = row.get("candidate_sha256")
        if not candidate_dir_value and candidate_sha256 is not None:
            raise ValueError(f"Attempt has a candidate digest without a candidate directory: {key}:{attempt_number}")
        if attempt_status == "judge_retryable" or candidate_dir_value:
            candidate_dir = _require_run_path(
                candidate_dir_value,
                output_dir=output_dir,
                expected=output_dir / "artifacts" / f"task_{key[0]}" / f"repeat_{key[1]}",
                context=f"Candidate for attempt {key}:{attempt_number}",
            )
        else:
            candidate_dir = None
        if candidate_dir is not None:
            candidate_manifest = _candidate_manifest(candidate_dir)
            if candidate_sha256 is not None and candidate_sha256 != candidate_manifest.get("candidate_sha256"):
                raise ValueError(f"Attempt candidate digest mismatch for {key}:{attempt_number}")
            if attempt_status == "judge_retryable" and candidate_sha256 is None:
                raise ValueError(f"Judge-retry attempt has no candidate digest: {key}:{attempt_number}")
            if (
                candidate_manifest.get("task_id") != key[0]
                or int(candidate_manifest.get("trial", -1)) != key[1]
                or candidate_manifest.get("config_fingerprint") != fingerprint
                or candidate_manifest.get("web_fetch_trust_env") is not config["tools"]["web_fetch_trust_env"]
                or candidate_manifest.get("web_search_available") is not bool(config["tools"]["require_brave_search"])
            ):
                raise ValueError(f"Candidate identity mismatch for attempt {key}:{row['attempt']}")
            if candidate_manifest.get("candidate_import") is not None:
                if key not in imported_candidates:
                    raise ValueError(f"Attempt references an unrecorded imported candidate: {key}")
            else:
                if key in imported_candidates:
                    raise ValueError(f"Imported-candidate record points to a generated candidate: {key}")
                _require_endpoint_session(
                    endpoint_sessions,
                    candidate_manifest.get("policy_endpoint_session_id"),
                    context=f"Candidate {candidate_dir}",
                    required_role="policy",
                )
    for key, rows in histories.items():
        numbers = [int(row["attempt"]) for row in rows]
        if numbers != list(range(1, len(rows) + 1)):
            raise ValueError(f"Non-contiguous attempt chain for {key}: {numbers}")
        statuses = [str(row["status"]) for row in rows]
        if "judge_retryable" in statuses:
            first_judge_retry = statuses.index("judge_retryable")
            later_rows = rows[first_judge_retry + 1 :]
            if any(
                later["status"] not in {"judge_retryable", "completed"}
                and not (later["status"] == "fatal_error" and later.get("failure_role") == "judge")
                for later in later_rows
            ):
                raise ValueError(f"Attempt chain regressed from judge-only recovery for {key}: {statuses}")
        if key in result_keys:
            if statuses[-1] not in SCORED_STATUSES:
                raise ValueError(f"Result for {key} does not terminate its attempt chain: {statuses}")
            result = results_by_key[key]
            if int(result.get("attempt", -1)) != numbers[-1]:
                raise ValueError(f"Result attempt does not match the terminal attempt for {key}")
            if any(status not in RETRYABLE_STATUSES for status in statuses[:-1]):
                raise ValueError(f"Unsafe retry chain before terminal result for {key}: {statuses}")
        elif any(status not in RETRYABLE_STATUSES for status in statuses):
            raise ValueError(f"Unfinished chain contains a non-retryable status for {key}: {statuses}")
    if missing_histories := result_keys - set(histories):
        raise ValueError(f"Results have no matching attempt history: {sorted(missing_histories)}")

    configured_hashes = metadata.get("implementation") or {}
    if configured_hashes != snapshot_hashes:
        raise ValueError("Implementation hashes differ between metadata and snapshot")
    implementation_root = output_dir / "implementation"
    implementation_files = {
        path.relative_to(implementation_root).as_posix() for path in implementation_root.rglob("*") if path.is_file()
    }
    if implementation_files != set(snapshot_hashes):
        raise ValueError("Implementation snapshot file set does not match its recorded hashes")
    for relative, expected_sha256 in snapshot_hashes.items():
        if sha256_file(implementation_root / relative) != expected_sha256:
            raise ValueError(f"Implementation snapshot digest mismatch: {relative}")

    recomputed_summary = _runner_summary(output_dir / "results.jsonl", len(planned_keys), config)
    summary_path = output_dir / "summary.json"
    if summary_path.is_file():
        run_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        for key, expected_value in recomputed_summary.items():
            if key not in run_summary or run_summary[key] != expected_value:
                raise ValueError(f"Persisted summary field does not match recomputation: {key}")
        metadata_summary = metadata.get("summary")
        if metadata_summary is not None and metadata_summary != run_summary:
            raise ValueError("Run metadata summary does not match summary.json")
    elif metadata.get("summary") is not None:
        raise ValueError("Run metadata contains a summary but summary.json is missing")
    summary = {
        "ok": True,
        "config_fingerprint": fingerprint,
        "results": len(results),
        "candidates": candidate_count,
        "imported_candidates": len(imported_candidates),
        "candidate_source": metadata.get("candidate_source"),
        "attempt_chains": len(histories),
        "endpoint_sessions": len(endpoint_sessions),
        "deployments": expected_deployments,
        "preflight": preflight,
        "asset_manifest": asset_manifest_shape,
        "asset_mirror": expected_asset_selection,
        "planned": len(planned_keys),
        "comparison_totals": comparison_totals,
        "recomputed_summary": recomputed_summary,
        "incomplete": sorted(
            f"{task_id}:{trial}" for task_id, trial in planned_keys if (task_id, trial) not in result_keys
        ),
    }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.output_dir.resolve()), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
