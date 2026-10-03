#!/usr/bin/env python3
"""Canonical, secret-free identity for one serving endpoint generation."""

from __future__ import annotations

import hashlib
import re
import urllib.parse
from datetime import datetime
from typing import Any

SLURM_JOB_ID_RE = re.compile(r"[1-9][0-9]{0,19}")
BACKEND_SHA256_RE = re.compile(r"backend-sha256:[0-9a-f]{64}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
HOST_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]*")
STARTED_AT_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
ROUTE_GENERATION_SCHEMA_VERSION = 2


class RouteGenerationError(ValueError):
    """Serving endpoint jobs do not form the required immutable generation."""


def canonical_backend_identifier(raw_backend: Any) -> str:
    """Return the shared, secret-free identifier for one canonical API base."""

    if not isinstance(raw_backend, str):
        raise RouteGenerationError("serving_endpoint_address_invalid")
    parsed = urllib.parse.urlsplit(raw_backend.rstrip("/"))
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise RouteGenerationError("serving_endpoint_address_invalid")
    normalized = urllib.parse.urlunsplit(parsed)
    digest = hashlib.sha256(normalized.encode()).hexdigest()
    return f"backend-sha256:{digest}"


def _canonical_started_at(value: Any) -> str:
    if not isinstance(value, str) or STARTED_AT_RE.fullmatch(value) is None:
        raise RouteGenerationError("serving_started_at_invalid")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise RouteGenerationError("serving_started_at_invalid") from error
    return value


def coordinator_incarnation_from_status(value: Any) -> dict[str, str]:
    """Extract the immutable coordinator process incarnation from status."""

    if not isinstance(value, dict):
        raise RouteGenerationError("serving_coordinator_invalid")
    job_id = value.get("jobid")
    if not isinstance(job_id, str) or SLURM_JOB_ID_RE.fullmatch(job_id) is None:
        raise RouteGenerationError("serving_coordinator_invalid")
    return {
        "slurm_job_id": job_id,
        "started_at": _canonical_started_at(value.get("started_at")),
    }


def proxy_incarnation_from_status(value: Any) -> dict[str, str]:
    """Extract the immutable proxy job and deployment lifetime stamp."""

    if not isinstance(value, dict) or value.get("slurm_state") != "RUNNING":
        raise RouteGenerationError("serving_proxy_invalid")
    job_id = value.get("jobid")
    if not isinstance(job_id, str) or SLURM_JOB_ID_RE.fullmatch(job_id) is None:
        raise RouteGenerationError("serving_proxy_invalid")
    return {
        "slurm_job_id": job_id,
        "first_ready_at": _canonical_started_at(value.get("first_ready_at")),
    }


def route_generation_from_status_endpoints(
    endpoints: Any,
    coordinator: Any,
    proxy: Any,
) -> dict[str, Any]:
    """Build a canonical generation from endpoint records that are all serving."""

    if not isinstance(endpoints, list) or not endpoints:
        raise RouteGenerationError("serving_endpoints_invalid")
    routes: list[dict[str, str]] = []
    for endpoint in endpoints:
        if (
            not isinstance(endpoint, dict)
            or endpoint.get("slurm_state") != "RUNNING"
            or endpoint.get("sub_state") != "ready"
        ):
            raise RouteGenerationError("serving_endpoints_invalid")
        job_id = endpoint.get("jobid")
        if not isinstance(job_id, str) or SLURM_JOB_ID_RE.fullmatch(job_id) is None:
            raise RouteGenerationError("slurm_endpoint_job_id_invalid")
        routes.append(
            {
                "slurm_job_id": job_id,
                "started_at": _canonical_started_at(endpoint.get("started_at")),
                "backend_sha256": canonical_backend_identifier(
                    f"http://{endpoint.get('host')}:{endpoint.get('port')}/v1"
                    if isinstance(endpoint.get("host"), str)
                    and HOST_RE.fullmatch(endpoint["host"]) is not None
                    and isinstance(endpoint.get("port"), int)
                    and not isinstance(endpoint.get("port"), bool)
                    and 1 <= endpoint["port"] <= 65535
                    else None
                ),
            }
        )
    routes.sort(key=lambda route: int(route["slurm_job_id"]))
    if len({route["slurm_job_id"] for route in routes}) != len(routes) or len(
        {route["backend_sha256"] for route in routes}
    ) != len(routes):
        raise RouteGenerationError("serving_routes_not_unique")
    return {
        "schema_version": ROUTE_GENERATION_SCHEMA_VERSION,
        "coordinator": coordinator_incarnation_from_status(coordinator),
        "proxy": proxy_incarnation_from_status(proxy),
        "routes": routes,
    }


def validate_route_generation(value: Any, *, expected_routes: int | None = None) -> dict[str, Any]:
    """Validate and return the exact canonical artifact representation."""

    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "coordinator",
        "proxy",
        "routes",
    }:
        raise RouteGenerationError("serving_route_generation_invalid")
    schema_version = value.get("schema_version")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != ROUTE_GENERATION_SCHEMA_VERSION
    ):
        raise RouteGenerationError("serving_route_generation_invalid")
    raw_routes = value.get("routes")
    if not isinstance(raw_routes, list) or not raw_routes:
        raise RouteGenerationError("serving_route_generation_invalid")
    routes: list[dict[str, str]] = []
    coordinator = value.get("coordinator")
    if (
        not isinstance(coordinator, dict)
        or set(coordinator) != {"slurm_job_id", "started_at"}
        or not isinstance(coordinator.get("slurm_job_id"), str)
        or SLURM_JOB_ID_RE.fullmatch(coordinator["slurm_job_id"]) is None
    ):
        raise RouteGenerationError("serving_route_generation_invalid")
    try:
        coordinator_started_at = _canonical_started_at(coordinator.get("started_at"))
    except RouteGenerationError as error:
        raise RouteGenerationError("serving_route_generation_invalid") from error
    proxy = value.get("proxy")
    if (
        not isinstance(proxy, dict)
        or set(proxy) != {"slurm_job_id", "first_ready_at"}
        or not isinstance(proxy.get("slurm_job_id"), str)
        or SLURM_JOB_ID_RE.fullmatch(proxy["slurm_job_id"]) is None
    ):
        raise RouteGenerationError("serving_route_generation_invalid")
    try:
        proxy_first_ready_at = _canonical_started_at(proxy.get("first_ready_at"))
    except RouteGenerationError as error:
        raise RouteGenerationError("serving_route_generation_invalid") from error
    for route in raw_routes:
        if (
            not isinstance(route, dict)
            or set(route) != {"backend_sha256", "slurm_job_id", "started_at"}
            or not isinstance(route.get("slurm_job_id"), str)
            or SLURM_JOB_ID_RE.fullmatch(route["slurm_job_id"]) is None
            or not isinstance(route.get("backend_sha256"), str)
            or BACKEND_SHA256_RE.fullmatch(route["backend_sha256"]) is None
        ):
            raise RouteGenerationError("serving_route_generation_invalid")
        try:
            started_at = _canonical_started_at(route.get("started_at"))
        except RouteGenerationError as error:
            raise RouteGenerationError("serving_route_generation_invalid") from error
        routes.append({**route, "started_at": started_at})
    canonical = sorted(routes, key=lambda route: int(route["slurm_job_id"]))
    if routes != canonical:
        raise RouteGenerationError("serving_route_generation_not_canonical")
    if len({route["slurm_job_id"] for route in routes}) != len(routes) or len(
        {route["backend_sha256"] for route in routes}
    ) != len(routes):
        raise RouteGenerationError("serving_route_generation_invalid")
    if expected_routes is not None:
        if (
            not isinstance(expected_routes, int)
            or isinstance(expected_routes, bool)
            or expected_routes < 1
            or len(routes) != expected_routes
        ):
            raise RouteGenerationError("serving_route_generation_count_mismatch")
    return {
        "schema_version": ROUTE_GENERATION_SCHEMA_VERSION,
        "coordinator": {
            "slurm_job_id": coordinator["slurm_job_id"],
            "started_at": coordinator_started_at,
        },
        "proxy": {
            "slurm_job_id": proxy["slurm_job_id"],
            "first_ready_at": proxy_first_ready_at,
        },
        "routes": routes,
    }


def validate_readiness_route_generation(
    value: Any,
    *,
    deployment_id: str | None = None,
    deployment_spec_sha256: str | None = None,
) -> dict[str, Any]:
    """Extract a route generation only from a passed, internally linked readiness record."""

    if not isinstance(value, dict):
        raise RouteGenerationError("readiness_route_generation_invalid")
    expected_routes = value.get("expected_routes")
    if (
        not isinstance(value.get("schema_version"), int)
        or isinstance(value.get("schema_version"), bool)
        or value.get("schema_version") != 1
        or value.get("state") != "passed"
        or not isinstance(expected_routes, int)
        or isinstance(expected_routes, bool)
        or expected_routes < 1
        or (deployment_id is not None and value.get("deployment") != deployment_id)
        or (deployment_spec_sha256 is not None and value.get("observed_spec_sha256") != deployment_spec_sha256)
    ):
        raise RouteGenerationError("readiness_route_generation_invalid")
    generation = validate_route_generation(
        value.get("serving_route_generation"),
        expected_routes=expected_routes,
    )
    last_status = value.get("last_status")
    if not isinstance(last_status, dict):
        raise RouteGenerationError("readiness_route_generation_invalid")
    last_generation = validate_route_generation(
        last_status.get("serving_route_generation"),
        expected_routes=expected_routes,
    )
    probe = value.get("probe")
    coverage = probe.get("coverage") if isinstance(probe, dict) else None
    endpoint = value.get("endpoint")
    endpoint_authority_sha256 = endpoint.get("authority_sha256") if isinstance(endpoint, dict) else None
    expected_backends = sorted(route["backend_sha256"] for route in generation["routes"])
    observed_backends = coverage.get("backends") if isinstance(coverage, dict) else None
    coord_ticks_completed = last_status.get("coord_ticks_completed")
    if (
        last_status.get("schema_version") != 4
        or last_status.get("deployment_id") != value.get("deployment")
        or last_status.get("phase") != "serving"
        or last_status.get("desired") != expected_routes
        or last_status.get("ready") != expected_routes
        or last_status.get("running_not_ready") != 0
        or last_status.get("pending") != 0
        or last_status.get("coordinator_incarnation") != generation["coordinator"]
        or not isinstance(coord_ticks_completed, int)
        or isinstance(coord_ticks_completed, bool)
        or coord_ticks_completed < 0
        or last_generation != generation
        or not isinstance(probe, dict)
        or probe.get("ok") is not True
        or not isinstance(endpoint_authority_sha256, str)
        or SHA256_RE.fullmatch(endpoint_authority_sha256) is None
        or probe.get("endpoint_authority_sha256") != endpoint_authority_sha256
        or not isinstance(coverage, dict)
        or coverage.get("ok") is not True
        or coverage.get("expected_routes") != expected_routes
        or coverage.get("discovered_routes") != expected_routes
        or not isinstance(observed_backends, list)
        or observed_backends != expected_backends
        or len(set(observed_backends)) != expected_routes
    ):
        raise RouteGenerationError("readiness_route_generation_mismatch")
    return generation
