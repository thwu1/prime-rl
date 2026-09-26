#!/usr/bin/env python3
"""Capture a content-blind, low-load gate for the shared Kimi deployment."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import os
import re
import stat
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from direct_kimi_router import C64_W2_CAPACITY_PROFILE
from direct_kimi_workers import (
    EXPECTED_ENDPOINT_IDENTIFIER,
    EXPECTED_ENDPOINTS,
    GENERATION_FILE_NAMES,
    GENERATION_MANIFEST_NAME,
    GENERATION_MARKER_KIND,
    GENERATION_MARKER_NAME,
    GENERATION_URLS_NAME,
    W2_MANIFEST_SCHEMA_VERSION,
    _read_bound_file,
    _read_marked_bundle,
    validate_manifest_value,
)

KIND = "kimi-endpoint-low-load-gate"
SCHEMA_VERSION = 1
MAX_PREEXISTING_RUNNING = 4
MAX_PREEXISTING_RUNNING_PER_WORKER = 1
MAX_KV_CACHE_USAGE = 0.05
DEFAULT_INTERVAL_SECONDS = 5.0
DEFAULT_REQUEST_TIMEOUT_SECONDS = 10.0
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
REQUIRED_METRICS = {
    "vllm:num_requests_running": "running",
    "vllm:num_requests_waiting": "waiting",
    "vllm:num_preemptions_total": "preemptions",
    "vllm:generation_tokens_total": "generation_tokens",
    "vllm:request_success_total": "successful_requests",
}
KV_METRICS = ("vllm:kv_cache_usage_perc", "vllm:gpu_cache_usage_perc")
PREFIX_METRICS = ("vllm:prefix_cache_hits_total", "vllm:prefix_cache_queries_total")


class KimiEndpointLoadGateError(ValueError):
    """The endpoint is not safely below the bounded shared-load threshold."""


Fetcher = Callable[[str, float], tuple[int, bytes]]


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_base_url(value: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise KimiEndpointLoadGateError("worker_urls_invalid") from error
    if (
        parsed.scheme != "http"
        or not parsed.hostname
        or port is None
        or not 1 <= port <= 65_535
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise KimiEndpointLoadGateError("worker_urls_invalid")
    return urllib.parse.urlunsplit(("http", parsed.netloc, "", "", ""))


def _load_bound_generation(
    manifest_path: Path,
    worker_urls_path: Path,
    expected_manifest_sha256: str,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    if (
        manifest_path.name != GENERATION_MANIFEST_NAME
        or worker_urls_path.name != GENERATION_URLS_NAME
        or manifest_path.parent != worker_urls_path.parent
        or SHA256_RE.fullmatch(expected_manifest_sha256) is None
    ):
        raise KimiEndpointLoadGateError("generation_binding_invalid")
    try:
        bodies = _read_marked_bundle(
            manifest_path.parent,
            marker_name=GENERATION_MARKER_NAME,
            kind=GENERATION_MARKER_KIND,
            expected_file_count=len(GENERATION_FILE_NAMES),
            code="generation_binding_invalid",
        )
        if set(bodies) != GENERATION_FILE_NAMES:
            raise KimiEndpointLoadGateError("generation_binding_invalid")
        manifest_body = bodies[GENERATION_MANIFEST_NAME]
        if _sha256(manifest_body) != expected_manifest_sha256:
            raise KimiEndpointLoadGateError("generation_binding_invalid")
        raw_manifest = json.loads(manifest_body)
        manifest = validate_manifest_value(raw_manifest, revalidate_live_source=True)
        urls_body = bodies[GENERATION_URLS_NAME]
        if not urls_body.endswith(b"\n") or b"\r" in urls_body:
            raise KimiEndpointLoadGateError("worker_urls_invalid")
        urls = tuple(_canonical_base_url(value) for value in urls_body.decode("utf-8").splitlines())
    except KimiEndpointLoadGateError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RuntimeError, ValueError) as error:
        raise KimiEndpointLoadGateError("generation_binding_invalid") from error
    router = manifest.get("router")
    workers = manifest.get("workers")
    backend_digests = [_sha256(f"{url}/v1".encode()) for url in urls]
    if (
        manifest.get("schema_version") != W2_MANIFEST_SCHEMA_VERSION
        or not isinstance(router, dict)
        or router.get("capacity_profile") != C64_W2_CAPACITY_PROFILE
        or router.get("endpoint_identifier") != EXPECTED_ENDPOINT_IDENTIFIER
        or not isinstance(workers, list)
        or len(urls) != EXPECTED_ENDPOINTS
        or len(set(urls)) != EXPECTED_ENDPOINTS
        or backend_digests != [worker.get("backend_sha256") for worker in workers]
        or manifest.get("endpoint_bundle_sha256")
        != _sha256("".join(f"{digest}\n" for digest in backend_digests).encode())
    ):
        raise KimiEndpointLoadGateError("generation_binding_invalid")
    return manifest, urls


def _fetch(url: str, timeout: float) -> tuple[int, bytes]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirectHandler())
    with opener.open(url, timeout=timeout) as response:
        if response.geturl() != url:
            raise KimiEndpointLoadGateError("worker_response_invalid")
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise KimiEndpointLoadGateError("worker_response_invalid")
        return response.status, body


def _parse_metrics(body: bytes) -> dict[str, float]:
    wanted = {*REQUIRED_METRICS, *KV_METRICS, *PREFIX_METRICS}
    values: dict[str, float] = {}
    try:
        lines = body.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise KimiEndpointLoadGateError("worker_metrics_invalid") from error
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.rsplit(None, 1)
        if len(fields) != 2:
            continue
        name = fields[0].split("{", 1)[0]
        if name not in wanted:
            continue
        try:
            value = float(fields[1])
        except ValueError as error:
            raise KimiEndpointLoadGateError("worker_metrics_invalid") from error
        if not math.isfinite(value) or value < 0:
            raise KimiEndpointLoadGateError("worker_metrics_invalid")
        values[name] = values.get(name, 0.0) + value
    if any(name not in values for name in REQUIRED_METRICS):
        raise KimiEndpointLoadGateError("worker_metrics_missing")
    if any(values[name] != int(values[name]) for name in REQUIRED_METRICS):
        raise KimiEndpointLoadGateError("worker_metrics_invalid")
    prefix_present = [name in values for name in PREFIX_METRICS]
    if any(prefix_present) and not all(prefix_present):
        raise KimiEndpointLoadGateError("worker_metrics_invalid")
    return values


def _probe_worker(url: str, timeout: float, fetcher: Fetcher) -> dict[str, float]:
    try:
        health_status, _health_body = fetcher(f"{url}/health", timeout)
        metrics_status, metrics_body = fetcher(f"{url}/metrics", timeout)
    except KimiEndpointLoadGateError:
        raise
    except Exception as error:
        raise KimiEndpointLoadGateError("worker_probe_failed") from error
    if health_status != 200 or metrics_status != 200:
        raise KimiEndpointLoadGateError("worker_probe_failed")
    return _parse_metrics(metrics_body)


def _snapshot(
    urls: tuple[str, ...],
    *,
    timeout: float,
    fetcher: Fetcher,
) -> tuple[dict[str, Any], tuple[dict[str, float], ...]]:
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=EXPECTED_ENDPOINTS) as executor:
            samples = tuple(executor.map(lambda url: _probe_worker(url, timeout, fetcher), urls))
    except KimiEndpointLoadGateError:
        raise
    except Exception as error:
        raise KimiEndpointLoadGateError("worker_probe_failed") from error
    if len(samples) != EXPECTED_ENDPOINTS:
        raise KimiEndpointLoadGateError("worker_probe_failed")

    def required(name: str) -> list[int]:
        metric = next(key for key, output in REQUIRED_METRICS.items() if output == name)
        return [int(sample[metric]) for sample in samples]

    running = required("running")
    waiting = required("waiting")
    preemptions = required("preemptions")
    generation_tokens = required("generation_tokens")
    successes = required("successful_requests")
    cache_values: list[float] = []
    cache_exposure = []
    for sample in samples:
        available = [sample[name] for name in KV_METRICS if name in sample]
        cache_exposure.append(bool(available))
        if available:
            cache_values.append(max(available))
    if not all(cache_exposure):
        raise KimiEndpointLoadGateError("worker_metrics_missing")
    prefix_exposure = [all(name in sample for name in PREFIX_METRICS) for sample in samples]
    if any(prefix_exposure) and not all(prefix_exposure):
        raise KimiEndpointLoadGateError("worker_metrics_invalid")
    prefix_exposed = all(prefix_exposure)
    if prefix_exposed:
        prefix_hits = sum(int(sample[PREFIX_METRICS[0]]) for sample in samples)
        prefix_queries = sum(int(sample[PREFIX_METRICS[1]]) for sample in samples)
        prefix_rate = prefix_hits / prefix_queries if prefix_queries else None
    else:
        prefix_hits = None
        prefix_queries = None
        prefix_rate = None
    result = {
        "workers_healthy": len(samples),
        "running": sum(running),
        "waiting": sum(waiting),
        "workers_with_running": sum(value > 0 for value in running),
        "running_per_worker_max": max(running),
        "preemptions": sum(preemptions),
        "generation_tokens": sum(generation_tokens),
        "successful_requests": sum(successes),
        "kv_cache_metric_exposed": bool(cache_values),
        "kv_cache_usage_mean": sum(cache_values) / len(cache_values) if cache_values else None,
        "kv_cache_usage_max": max(cache_values) if cache_values else None,
        "prefix_cache_hits": prefix_hits,
        "prefix_cache_queries": prefix_queries,
        "prefix_cache_hit_rate": prefix_rate,
    }
    if (
        result["running"] > MAX_PREEXISTING_RUNNING
        or result["running_per_worker_max"] > MAX_PREEXISTING_RUNNING_PER_WORKER
        or result["waiting"] != 0
        or (cache_values and result["kv_cache_usage_max"] > MAX_KV_CACHE_USAGE)
    ):
        raise KimiEndpointLoadGateError("endpoint_not_low_load")
    return result, samples


def capture_load_gate(
    *,
    manifest_path: Path,
    worker_urls_path: Path,
    manifest_sha256: str,
    interval_seconds: float,
    request_timeout_seconds: float,
    output: Path,
    fetcher: Fetcher = _fetch,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.time,
) -> dict[str, Any]:
    if not 1 <= interval_seconds <= 60 or not 1 <= request_timeout_seconds <= 30:
        raise KimiEndpointLoadGateError("timing_invalid")
    manifest, urls = _load_bound_generation(manifest_path, worker_urls_path, manifest_sha256)
    first, first_workers = _snapshot(urls, timeout=request_timeout_seconds, fetcher=fetcher)
    started = time.monotonic()
    sleeper(interval_seconds)
    second, second_workers = _snapshot(urls, timeout=request_timeout_seconds, fetcher=fetcher)
    observed_interval = time.monotonic() - started
    for before, after in zip(first_workers, second_workers, strict=True):
        if any((metric in before) != (metric in after) for metric in (*KV_METRICS, *PREFIX_METRICS)):
            raise KimiEndpointLoadGateError("worker_metric_set_changed")
        for metric in (
            "vllm:generation_tokens_total",
            "vllm:request_success_total",
            "vllm:prefix_cache_hits_total",
            "vllm:prefix_cache_queries_total",
        ):
            if metric in before and (metric not in after or after[metric] < before[metric]):
                raise KimiEndpointLoadGateError("worker_counter_regressed")
        if after["vllm:num_preemptions_total"] != before["vllm:num_preemptions_total"]:
            raise KimiEndpointLoadGateError("worker_preemption_changed")
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "state": "passed",
        "captured_at_unix": int(clock()),
        "manifest_sha256": manifest_sha256,
        "endpoint_bundle_sha256": manifest["endpoint_bundle_sha256"],
        "worker_count": EXPECTED_ENDPOINTS,
        "policy": {
            "snapshots": 2,
            "configured_interval_seconds": interval_seconds,
            "maximum_preexisting_running": MAX_PREEXISTING_RUNNING,
            "maximum_preexisting_running_per_worker": MAX_PREEXISTING_RUNNING_PER_WORKER,
            "maximum_kv_cache_usage": MAX_KV_CACHE_USAGE,
            "waiting_must_be_zero": True,
            "preemptions_must_be_stable": True,
        },
        "snapshots": [first, second],
        "deltas": {
            "generation_tokens": second["generation_tokens"] - first["generation_tokens"],
            "successful_requests": second["successful_requests"] - first["successful_requests"],
            "preemptions": second["preemptions"] - first["preemptions"],
        },
        "observed_interval_milliseconds": max(1, round(observed_interval * 1000)),
        "source_generation_revalidated": True,
        "membership_disclosed": False,
    }
    _write_once(output, receipt)
    return receipt


def _write_once(path: Path, value: dict[str, Any]) -> None:
    try:
        parent = path.parent.resolve(strict=True)
        metadata = parent.lstat()
    except OSError as error:
        raise KimiEndpointLoadGateError("output_invalid") from error
    if (
        not path.is_absolute()
        or parent != path.parent
        or path.parent.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or os.path.lexists(path)
    ):
        raise KimiEndpointLoadGateError("output_invalid")
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        body = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(body)
            handle.flush()
            os.fsync(descriptor)
    finally:
        os.close(descriptor)


def validate_load_gate(
    path: Path,
    *,
    expected_sha256: str,
    manifest_sha256: str,
    endpoint_bundle_sha256: str,
    maximum_age_seconds: int | None = None,
    clock: Callable[[], float] = time.time,
) -> dict[str, Any]:
    """Re-open a private aggregate receipt and enforce its exact load contract."""

    try:
        body = _read_bound_file(
            path,
            maximum_bytes=1 << 20,
            private=True,
            code="load_gate_invalid",
        )
        value = json.loads(body)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RuntimeError, ValueError) as error:
        raise KimiEndpointLoadGateError("load_gate_invalid") from error
    if (
        SHA256_RE.fullmatch(expected_sha256) is None
        or _sha256(body) != expected_sha256
        or not isinstance(value, dict)
        or set(value)
        != {
            "schema_version",
            "kind",
            "state",
            "captured_at_unix",
            "manifest_sha256",
            "endpoint_bundle_sha256",
            "worker_count",
            "policy",
            "snapshots",
            "deltas",
            "observed_interval_milliseconds",
            "source_generation_revalidated",
            "membership_disclosed",
        }
        or value.get("schema_version") != SCHEMA_VERSION
        or value.get("kind") != KIND
        or value.get("state") != "passed"
        or value.get("manifest_sha256") != manifest_sha256
        or value.get("endpoint_bundle_sha256") != endpoint_bundle_sha256
        or value.get("worker_count") != EXPECTED_ENDPOINTS
        or value.get("source_generation_revalidated") is not True
        or value.get("membership_disclosed") is not False
        or value.get("policy")
        != {
            "snapshots": 2,
            "configured_interval_seconds": value.get("policy", {}).get("configured_interval_seconds")
            if isinstance(value.get("policy"), dict)
            else None,
            "maximum_preexisting_running": MAX_PREEXISTING_RUNNING,
            "maximum_preexisting_running_per_worker": MAX_PREEXISTING_RUNNING_PER_WORKER,
            "maximum_kv_cache_usage": MAX_KV_CACHE_USAGE,
            "waiting_must_be_zero": True,
            "preemptions_must_be_stable": True,
        }
    ):
        raise KimiEndpointLoadGateError("load_gate_invalid")
    captured_at = value.get("captured_at_unix")
    interval = value["policy"].get("configured_interval_seconds")
    snapshots = value.get("snapshots")
    deltas = value.get("deltas")
    if (
        type(captured_at) is not int
        or captured_at <= 0
        or isinstance(interval, bool)
        or not isinstance(interval, (int, float))
        or not 1 <= interval <= 60
        or type(value.get("observed_interval_milliseconds")) is not int
        or value["observed_interval_milliseconds"] < 1
        or not isinstance(snapshots, list)
        or len(snapshots) != 2
        or not isinstance(deltas, dict)
        or set(deltas) != {"generation_tokens", "successful_requests", "preemptions"}
        or any(type(item) is not int or item < 0 for item in deltas.values())
        or deltas.get("preemptions") != 0
    ):
        raise KimiEndpointLoadGateError("load_gate_invalid")
    snapshot_keys = {
        "workers_healthy",
        "running",
        "waiting",
        "workers_with_running",
        "running_per_worker_max",
        "preemptions",
        "generation_tokens",
        "successful_requests",
        "kv_cache_metric_exposed",
        "kv_cache_usage_mean",
        "kv_cache_usage_max",
        "prefix_cache_hits",
        "prefix_cache_queries",
        "prefix_cache_hit_rate",
    }
    for snapshot in snapshots:
        prefix_hits = snapshot.get("prefix_cache_hits") if isinstance(snapshot, dict) else None
        prefix_queries = snapshot.get("prefix_cache_queries") if isinstance(snapshot, dict) else None
        prefix_rate = snapshot.get("prefix_cache_hit_rate") if isinstance(snapshot, dict) else None
        kv_mean = snapshot.get("kv_cache_usage_mean") if isinstance(snapshot, dict) else None
        if (
            not isinstance(snapshot, dict)
            or set(snapshot) != snapshot_keys
            or snapshot.get("workers_healthy") != EXPECTED_ENDPOINTS
            or type(snapshot.get("running")) is not int
            or not 0 <= snapshot["running"] <= MAX_PREEXISTING_RUNNING
            or type(snapshot.get("running_per_worker_max")) is not int
            or not 0 <= snapshot["running_per_worker_max"] <= MAX_PREEXISTING_RUNNING_PER_WORKER
            or snapshot["running_per_worker_max"] != int(snapshot["running"] > 0)
            or type(snapshot.get("waiting")) is not int
            or snapshot.get("waiting") != 0
            or type(snapshot.get("workers_with_running")) is not int
            or snapshot["workers_with_running"] != snapshot["running"]
            or type(snapshot.get("preemptions")) is not int
            or snapshot["preemptions"] < 0
            or type(snapshot.get("generation_tokens")) is not int
            or snapshot["generation_tokens"] < 0
            or type(snapshot.get("successful_requests")) is not int
            or snapshot["successful_requests"] < 0
            or snapshot.get("kv_cache_metric_exposed") is not True
            or isinstance(kv_mean, bool)
            or not isinstance(kv_mean, (int, float))
            or not math.isfinite(kv_mean)
            or not 0 <= kv_mean <= MAX_KV_CACHE_USAGE
            or isinstance(snapshot.get("kv_cache_usage_max"), bool)
            or not isinstance(snapshot.get("kv_cache_usage_max"), (int, float))
            or not math.isfinite(snapshot["kv_cache_usage_max"])
            or not 0 <= snapshot["kv_cache_usage_max"] <= MAX_KV_CACHE_USAGE
            or kv_mean > snapshot["kv_cache_usage_max"]
            or (prefix_hits is None) != (prefix_queries is None)
            or (
                prefix_hits is not None
                and (
                    type(prefix_hits) is not int
                    or type(prefix_queries) is not int
                    or prefix_hits < 0
                    or prefix_queries < 0
                    or prefix_hits > prefix_queries
                    or (prefix_queries == 0 and (prefix_hits != 0 or prefix_rate is not None))
                    or (
                        prefix_queries > 0
                        and (
                            isinstance(prefix_rate, bool)
                            or not isinstance(prefix_rate, (int, float))
                            or not math.isfinite(prefix_rate)
                            or not 0 <= prefix_rate <= 1
                            or prefix_rate != prefix_hits / prefix_queries
                        )
                    )
                )
            )
            or (prefix_hits is None and prefix_rate is not None)
        ):
            raise KimiEndpointLoadGateError("load_gate_invalid")
    if (
        snapshots[1]["preemptions"] != snapshots[0]["preemptions"]
        or (
            snapshots[0]["prefix_cache_hits"] is not None
            and (
                snapshots[1]["prefix_cache_hits"] < snapshots[0]["prefix_cache_hits"]
                or snapshots[1]["prefix_cache_queries"] < snapshots[0]["prefix_cache_queries"]
            )
        )
        or snapshots[1]["generation_tokens"] - snapshots[0]["generation_tokens"] != deltas["generation_tokens"]
        or snapshots[1]["successful_requests"] - snapshots[0]["successful_requests"] != deltas["successful_requests"]
        or (
            maximum_age_seconds is not None
            and (
                type(maximum_age_seconds) is not int
                or maximum_age_seconds < 1
                or not 0 <= clock() - captured_at <= maximum_age_seconds
            )
        )
    ):
        raise KimiEndpointLoadGateError("load_gate_invalid")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--worker-urls", type=Path, required=True)
    parser.add_argument("--interval-seconds", type=float, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--request-timeout-seconds", type=float, default=DEFAULT_REQUEST_TIMEOUT_SECONDS)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = capture_load_gate(
            manifest_path=args.manifest,
            worker_urls_path=args.worker_urls,
            manifest_sha256=args.manifest_sha256,
            interval_seconds=args.interval_seconds,
            request_timeout_seconds=args.request_timeout_seconds,
            output=args.output,
        )
    except (OSError, RuntimeError, ValueError):
        print('{"code":"kimi_endpoint_load_gate_failed","state":"blocked"}', file=__import__("sys").stderr)
        return 2
    print(
        json.dumps(
            {
                "membership_disclosed": False,
                "running": receipt["snapshots"][-1]["running"],
                "state": "passed",
                "waiting": receipt["snapshots"][-1]["waiting"],
                "workers": receipt["worker_count"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
