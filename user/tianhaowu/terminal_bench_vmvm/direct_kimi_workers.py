#!/usr/bin/env python3
"""Bind the fixed Kimi deployment to a secret-free direct-router manifest."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

EXPECTED_MODEL = "Kimi-K3"
EXPECTED_ENDPOINTS = 24
EXPECTED_SPEC_SHA256 = "ab00213a43083eba87f8b5999a3046e8d27ebe42b933ee845fd0cf4928b266e2"
EXPECTED_PROXY_CONFIG_SHA256 = "16a2992e90aaeb54396b1501f84eb3182120f7b89d45ededc539eb7a7a4fa34b"
EXPECTED_SOURCE_REQUEST_TIMEOUT_SECONDS = 600
EXPECTED_SOURCE_RETRIES = 2
ROUTER_POLICY = "consistent_hash"
ROUTER_REQUEST_ID_HEADERS = ("x-session-id",)
ROUTER_REQUEST_TIMEOUT_SECONDS = 43_200
ROUTER_RETRIES = 0
ROUTER_PROVIDER_CONCURRENCY = 24
ROUTER_QUEUE_SIZE = 0
ROUTER_QUEUE_TIMEOUT_SECONDS = 43_200
ROUTER_IMPLEMENTATION = "direct-kimi-transparent-v1"
MANIFEST_SCHEMA_VERSION = 1
MAX_CONFIG_BYTES = 4 * 1024 * 1024
MAX_MODELS_BYTES = 1 << 20
SHA256_RE = re.compile(r"[0-9a-f]{64}")


class DirectKimiWorkerError(ValueError):
    """The direct Kimi worker generation does not match the pinned source."""


@dataclass(frozen=True)
class Worker:
    url: str
    backend_sha256: str
    model_sha256: str

    @property
    def public_record(self) -> dict[str, str]:
        return {
            "backend_sha256": self.backend_sha256,
            "model_sha256": self.model_sha256,
        }


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        before = path.stat()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        after = path.stat()
    except OSError as error:
        raise DirectKimiWorkerError("source_unreadable") from error
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise DirectKimiWorkerError("source_changed")
    return digest.hexdigest()


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        resolved = path.resolve(strict=True)
        if path.is_symlink() or resolved.stat().st_size > MAX_CONFIG_BYTES:
            raise DirectKimiWorkerError("source_unreadable")
        value = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
        raise DirectKimiWorkerError("source_invalid") from error
    if not isinstance(value, dict):
        raise DirectKimiWorkerError("source_invalid")
    return value


def _canonical_worker_url(value: Any) -> str:
    if not isinstance(value, str):
        raise DirectKimiWorkerError("worker_url_invalid")
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise DirectKimiWorkerError("worker_url_invalid") from error
    if (
        parsed.scheme != "http"
        or not parsed.hostname
        or port is None
        or not 1 <= port <= 65_535
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path.rstrip("/") != "/v1"
        or parsed.query
        or parsed.fragment
    ):
        raise DirectKimiWorkerError("worker_url_invalid")
    return urllib.parse.urlunsplit(("http", parsed.netloc, "", "", ""))


def load_workers(deployment_root: Path) -> tuple[list[Worker], str, str, str]:
    root = deployment_root.resolve(strict=True)
    spec = root / "spec.yaml"
    proxy_config = root / "proxy_litellm_config.yaml"
    if (
        not spec.is_file()
        or spec.is_symlink()
        or not proxy_config.is_file()
        or proxy_config.is_symlink()
        or _sha256_file(spec) != EXPECTED_SPEC_SHA256
        or _sha256_file(proxy_config) != EXPECTED_PROXY_CONFIG_SHA256
    ):
        raise DirectKimiWorkerError("source_generation_mismatch")
    document = _read_yaml(proxy_config)
    settings = document.get("litellm_settings")
    entries = document.get("model_list")
    if (
        not isinstance(settings, dict)
        or settings.get("request_timeout") != EXPECTED_SOURCE_REQUEST_TIMEOUT_SECONDS
        or settings.get("num_retries") != EXPECTED_SOURCE_RETRIES
        or not isinstance(entries, list)
        or len(entries) != EXPECTED_ENDPOINTS
    ):
        raise DirectKimiWorkerError("source_generation_mismatch")

    workers: list[Worker] = []
    urls: set[str] = set()
    backend_models: set[str] = set()
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or entry.get("model_name") != EXPECTED_MODEL
            or not isinstance(entry.get("litellm_params"), dict)
        ):
            raise DirectKimiWorkerError("worker_record_invalid")
        params = entry["litellm_params"]
        if set(params) != {"api_base", "api_key", "model"} or params.get("api_key") != "EMPTY":
            raise DirectKimiWorkerError("worker_record_invalid")
        model = params.get("model")
        if not isinstance(model, str) or not model or any(character in model for character in "\r\n"):
            raise DirectKimiWorkerError("worker_model_invalid")
        url = _canonical_worker_url(params.get("api_base"))
        if url in urls:
            raise DirectKimiWorkerError("worker_url_duplicate")
        urls.add(url)
        backend_models.add(model)
        workers.append(
            Worker(
                url=url,
                backend_sha256=_sha256_bytes(f"{url}/v1".encode()),
                model_sha256=_sha256_bytes(EXPECTED_MODEL.encode()),
            )
        )
    if len(backend_models) != 1:
        raise DirectKimiWorkerError("worker_model_generation_mismatch")
    workers.sort(key=lambda worker: worker.backend_sha256)
    endpoint_bundle_sha256 = _sha256_bytes(
        "".join(f"{worker.backend_sha256}\n" for worker in workers).encode()
    )
    return workers, EXPECTED_SPEC_SHA256, EXPECTED_PROXY_CONFIG_SHA256, endpoint_bundle_sha256


def derive_ports(output_root: Path) -> tuple[int, int]:
    digest = hashlib.sha256(str(output_root.resolve()).encode()).digest()
    return 20_000 + int.from_bytes(digest[:4], "big") % 10_000, 40_000 + int.from_bytes(digest[4:8], "big") % 10_000


def _manifest(
    deployment_root: Path,
    workers: list[Worker],
    spec_sha256: str,
    proxy_config_sha256: str,
    endpoint_bundle_sha256: str,
    router_port: int,
    metrics_port: int,
) -> dict[str, Any]:
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "kind": "direct-kimi-worker-generation",
        "deployment_root": str(deployment_root.resolve()),
        "model": EXPECTED_MODEL,
        "source_spec_sha256": spec_sha256,
        "source_proxy_config_sha256": proxy_config_sha256,
        "endpoint_bundle_sha256": endpoint_bundle_sha256,
        "workers": [worker.public_record for worker in workers],
        "router": {
            "implementation": ROUTER_IMPLEMENTATION,
            "implementation_sha256": _sha256_file(Path(__file__).with_name("direct_kimi_router.py")),
            "host": "127.0.0.1",
            "port": router_port,
            "metrics_host": "127.0.0.1",
            "metrics_port": metrics_port,
            "policy": ROUTER_POLICY,
            "request_id_headers": list(ROUTER_REQUEST_ID_HEADERS),
            "request_timeout_seconds": ROUTER_REQUEST_TIMEOUT_SECONDS,
            "max_concurrent_requests": ROUTER_PROVIDER_CONCURRENCY,
            "queue_size": ROUTER_QUEUE_SIZE,
            "queue_timeout_seconds": ROUTER_QUEUE_TIMEOUT_SECONDS,
            "retries": ROUTER_RETRIES,
        },
    }


def _atomic_write(path: Path, raw: bytes, *, exclusive: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        if exclusive:
            try:
                os.link(temporary, path)
            except FileExistsError as error:
                raise DirectKimiWorkerError("output_already_exists") from error
        else:
            os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def prepare_generation(
    deployment_root: Path,
    output_root: Path,
    manifest_path: Path,
    urls_path: Path,
    ports_path: Path,
) -> dict[str, Any]:
    workers, spec_sha256, proxy_config_sha256, endpoint_bundle_sha256 = load_workers(deployment_root)
    router_port, metrics_port = derive_ports(output_root)
    manifest = _manifest(
        deployment_root,
        workers,
        spec_sha256,
        proxy_config_sha256,
        endpoint_bundle_sha256,
        router_port,
        metrics_port,
    )
    _atomic_write(
        manifest_path,
        (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode(),
        exclusive=True,
    )
    _atomic_write(urls_path, "".join(f"{worker.url}\n" for worker in workers).encode(), exclusive=True)
    _atomic_write(ports_path, f"{router_port}\n{metrics_port}\n".encode(), exclusive=True)
    return manifest


def validate_saved_manifest(path: Path, *, revalidate_live_source: bool = True) -> dict[str, Any]:
    try:
        manifest = json.loads(path.resolve(strict=True).read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DirectKimiWorkerError("manifest_invalid") from error
    expected_keys = {
        "schema_version",
        "kind",
        "deployment_root",
        "model",
        "source_spec_sha256",
        "source_proxy_config_sha256",
        "endpoint_bundle_sha256",
        "workers",
        "router",
    }
    router = manifest.get("router") if isinstance(manifest, dict) else None
    workers = manifest.get("workers") if isinstance(manifest, dict) else None
    if (
        not isinstance(manifest, dict)
        or set(manifest) != expected_keys
        or manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION
        or manifest.get("kind") != "direct-kimi-worker-generation"
        or manifest.get("model") != EXPECTED_MODEL
        or manifest.get("source_spec_sha256") != EXPECTED_SPEC_SHA256
        or manifest.get("source_proxy_config_sha256") != EXPECTED_PROXY_CONFIG_SHA256
        or SHA256_RE.fullmatch(str(manifest.get("endpoint_bundle_sha256", ""))) is None
        or not isinstance(workers, list)
        or len(workers) != EXPECTED_ENDPOINTS
        or not isinstance(router, dict)
        or router
        != {
            "implementation": ROUTER_IMPLEMENTATION,
            "implementation_sha256": _sha256_file(Path(__file__).with_name("direct_kimi_router.py")),
            "host": "127.0.0.1",
            "port": router.get("port"),
            "metrics_host": "127.0.0.1",
            "metrics_port": router.get("metrics_port"),
            "policy": ROUTER_POLICY,
            "request_id_headers": list(ROUTER_REQUEST_ID_HEADERS),
            "request_timeout_seconds": ROUTER_REQUEST_TIMEOUT_SECONDS,
            "max_concurrent_requests": ROUTER_PROVIDER_CONCURRENCY,
            "queue_size": ROUTER_QUEUE_SIZE,
            "queue_timeout_seconds": ROUTER_QUEUE_TIMEOUT_SECONDS,
            "retries": ROUTER_RETRIES,
        }
        or any(
            not isinstance(router.get(key), int)
            or isinstance(router.get(key), bool)
            or not 1 <= router[key] <= 65_535
            for key in ("port", "metrics_port")
        )
    ):
        raise DirectKimiWorkerError("manifest_invalid")
    if any(
        not isinstance(worker, dict)
        or set(worker) != {"backend_sha256", "model_sha256"}
        or any(SHA256_RE.fullmatch(str(worker.get(key, ""))) is None for key in worker)
        for worker in workers
    ):
        raise DirectKimiWorkerError("manifest_invalid")
    if len({worker["backend_sha256"] for worker in workers}) != EXPECTED_ENDPOINTS:
        raise DirectKimiWorkerError("manifest_invalid")
    if revalidate_live_source:
        observed, spec_sha256, proxy_config_sha256, endpoint_bundle_sha256 = load_workers(
            Path(manifest["deployment_root"])
        )
        if (
            [worker.public_record for worker in observed] != workers
            or spec_sha256 != manifest["source_spec_sha256"]
            or proxy_config_sha256 != manifest["source_proxy_config_sha256"]
            or endpoint_bundle_sha256 != manifest["endpoint_bundle_sha256"]
        ):
            raise DirectKimiWorkerError("source_generation_changed")
    return manifest


def _probe_worker(worker: Worker, timeout: float) -> None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"{worker.url}/health", timeout=timeout) as response:
            if response.status != 200:
                raise DirectKimiWorkerError("worker_health_failed")
            response.read(1)
        with opener.open(f"{worker.url}/v1/models", timeout=timeout) as response:
            if response.status != 200:
                raise DirectKimiWorkerError("worker_models_failed")
            raw = response.read(MAX_MODELS_BYTES + 1)
    except DirectKimiWorkerError:
        raise
    except Exception as error:
        raise DirectKimiWorkerError("worker_unreachable") from error
    if len(raw) > MAX_MODELS_BYTES:
        raise DirectKimiWorkerError("worker_models_invalid")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DirectKimiWorkerError("worker_models_invalid") from error
    data = payload.get("data") if isinstance(payload, dict) else None
    models = (
        [item.get("id") for item in data]
        if isinstance(data, list) and all(isinstance(item, dict) for item in data)
        else []
    )
    if (
        len(models) != 1
        or not isinstance(models[0], str)
        or _sha256_bytes(models[0].encode()) != worker.model_sha256
    ):
        raise DirectKimiWorkerError("worker_models_mismatch")


def probe_workers(workers: list[Worker], *, timeout: float = 30.0) -> None:
    with concurrent.futures.ThreadPoolExecutor(max_workers=EXPECTED_ENDPOINTS) as executor:
        futures = [executor.submit(_probe_worker, worker, timeout) for worker in workers]
        for future in concurrent.futures.as_completed(futures):
            future.result()


def certify_router(
    manifest_path: Path,
    manifest_sha256: str,
    active_workers: int,
    router_stats_path: Path,
    output: Path,
) -> dict[str, Any]:
    if SHA256_RE.fullmatch(manifest_sha256) is None or _sha256_file(manifest_path) != manifest_sha256:
        raise DirectKimiWorkerError("manifest_sha256_mismatch")
    manifest = validate_saved_manifest(manifest_path)
    if active_workers != EXPECTED_ENDPOINTS:
        raise DirectKimiWorkerError("active_worker_count_mismatch")
    try:
        router_stats = json.loads(router_stats_path.resolve(strict=True).read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DirectKimiWorkerError("router_stats_invalid") from error
    expected_stats_keys = {
        "schema_version",
        "kind",
        "implementation",
        "policy",
        "request_id_headers",
        "request_timeout_seconds",
        "retries",
        "worker_count",
        "active_workers",
        "active_requests",
        "max_active_requests",
        "total_requests",
        "chat_requests",
        "missing_session_rejections",
        "upstream_failures",
        "worker_request_counts",
    }
    counts = router_stats.get("worker_request_counts") if isinstance(router_stats, dict) else None
    if (
        not isinstance(router_stats, dict)
        or set(router_stats) != expected_stats_keys
        or router_stats.get("schema_version") != 1
        or router_stats.get("kind") != "direct-kimi-transparent-router"
        or router_stats.get("implementation") != ROUTER_IMPLEMENTATION
        or router_stats.get("policy") != ROUTER_POLICY
        or router_stats.get("request_id_headers") != list(ROUTER_REQUEST_ID_HEADERS)
        or router_stats.get("request_timeout_seconds") != ROUTER_REQUEST_TIMEOUT_SECONDS
        or router_stats.get("retries") != ROUTER_RETRIES
        or router_stats.get("worker_count") != EXPECTED_ENDPOINTS
        or router_stats.get("active_workers") != EXPECTED_ENDPOINTS
        or router_stats.get("active_requests") != 0
        or not isinstance(counts, list)
        or len(counts) != EXPECTED_ENDPOINTS
        or any(type(value) is not int or value < 0 for value in counts)
        or any(
            type(router_stats.get(key)) is not int or router_stats[key] < 0
            for key in (
                "max_active_requests",
                "total_requests",
                "chat_requests",
                "missing_session_rejections",
                "upstream_failures",
            )
        )
        or not 0 <= router_stats["max_active_requests"] <= ROUTER_PROVIDER_CONCURRENCY
        or router_stats["chat_requests"] > router_stats["total_requests"]
        or sum(counts) != router_stats["total_requests"]
        or router_stats["missing_session_rejections"] != 0
        or router_stats["upstream_failures"] != 0
    ):
        raise DirectKimiWorkerError("router_stats_invalid")
    receipt = {
        "schema_version": 1,
        "kind": "direct-kimi-router-final",
        "state": "passed",
        "worker_manifest_sha256": manifest_sha256,
        "endpoint_bundle_sha256": manifest["endpoint_bundle_sha256"],
        "active_workers": active_workers,
        "implementation": ROUTER_IMPLEMENTATION,
        "implementation_sha256": manifest["router"]["implementation_sha256"],
        "policy": ROUTER_POLICY,
        "request_id_headers": list(ROUTER_REQUEST_ID_HEADERS),
        "request_timeout_seconds": ROUTER_REQUEST_TIMEOUT_SECONDS,
        "retries": ROUTER_RETRIES,
        "max_active_requests": router_stats["max_active_requests"],
        "total_requests": router_stats["total_requests"],
        "chat_requests": router_stats["chat_requests"],
        "worker_request_counts_sha256": _sha256_bytes(
            (json.dumps(counts, separators=(",", ":")) + "\n").encode()
        ),
        "source_generation_revalidated": True,
    }
    _atomic_write(
        output,
        (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode(),
        exclusive=True,
    )
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--deployment-root", type=Path, required=True)
    prepare.add_argument("--output-root", type=Path, required=True)
    prepare.add_argument("--manifest", type=Path, required=True)
    prepare.add_argument("--urls-output", type=Path, required=True)
    prepare.add_argument("--ports-output", type=Path, required=True)
    prepare.add_argument("--probe", action="store_true")
    certify = subparsers.add_parser("certify-router")
    certify.add_argument("--manifest", type=Path, required=True)
    certify.add_argument("--manifest-sha256", required=True)
    certify.add_argument("--active-workers", type=int, required=True)
    certify.add_argument("--router-stats", type=Path, required=True)
    certify.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "certify-router":
        receipt = certify_router(
            args.manifest,
            args.manifest_sha256,
            args.active_workers,
            args.router_stats,
            args.output,
        )
        print(json.dumps({"active_workers": receipt["active_workers"], "ok": True}, sort_keys=True))
        return
    manifest = prepare_generation(
        args.deployment_root,
        args.output_root,
        args.manifest,
        args.urls_output,
        args.ports_output,
    )
    if args.probe:
        workers, _, _, _ = load_workers(args.deployment_root)
        probe_workers(workers)
    print(
        json.dumps(
            {
                "endpoint_bundle_sha256": manifest["endpoint_bundle_sha256"],
                "manifest_sha256": _sha256_file(args.manifest),
                "ok": True,
                "worker_count": len(manifest["workers"]),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
